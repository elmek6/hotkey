"""Diske kayit -- AHK'deki `Path` sinifi + `FileIO` + `_load`/`_save` dizisi.

AHK'de her modul kendi dosyasini kendi aciyor, kendi hata mesajini kendi
yaziyordu; ayni try/catch bloklari `clip_hist`, `memory_slots`,
`trace_store`, `repository` icinde tekrar ediyordu. Burada tek bir taban
sinif var: dosya adini ve surumu alt sinif soyler, geri kalan ortak.

    class ClipStore(JsonStore):
        filename = "clip_history.json"
        version = 1

Butun dosyalar `Files/` altinda (cascade/paths.py) -- program tasinabilir
kalsin, AppData'ya dagilmasin. AHK'de de oyleydi.

AHK'den aynen tasinan dort davranis:

1. **Bozuk dosya programi durdurmaz.** Okunamazsa dosya YEDEKLENIR
   (`.bozuk-<zaman>` uzantisiyla yaninda kalir), hata log'a yazilir ve
   program bos listeyle acilir. AHK: `backupOnError` + `handleError`.
2. **Yazma atomik.** Once `.tmp` dosyaya yazilir, sonra `os.replace` ile
   yerine gecer. Yazarken elektrik giderse eldeki dosya bozulmaz -- AHK'de
   olmayan, ucuza gelen bir kazanc.
3. **Veri kaybi korumasi.** Acilista okunan kayit sayisindan AZ kayit
   yazilacaksa yazma yapilmaz, log'a kritik dusulur. AHK'de bu bir
   `DialogCriticalError` idi; burada sessiz ama izi kalan bir red, cunku
   kapanis sirasinda modal pencere acmak kapanisi kilitler.
4. **Surum alani.** Dosya bicimi degisince eski dosyayi tanimak icin.
   Farkli surum bozuk sayilir: yedeklenir, sifirdan baslanir.

Saf Python: Qt yok, Win32 yok -- test edilebilir.
"""

from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

import orjson

from cascade import paths
from cascade.core.clip_history import ClipEntry

log = logging.getLogger("cascade.store")


class JsonStore:
    """Tek bir JSON dosyasini yoneten taban sinif."""

    filename: ClassVar[str] = "store.json"
    version: ClassVar[int] = 1

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory or paths.FILES

    @property
    def path(self) -> Path:
        return self._directory / self.filename

    # ---- okuma ----

    def load(self) -> dict[str, Any]:
        """Dosyayi okur. Yoksa bos sozluk; bozuksa yedekleyip bos sozluk.

        Hicbir durumda exception firlatmaz: acilista tek bir bozuk dosya
        programin hic acilmamasina yol acmamali.
        """
        path = self.path
        if not path.exists():
            return {}
        try:
            data = orjson.loads(path.read_bytes())
        except (OSError, orjson.JSONDecodeError):
            log.exception("%s okunamadi, yedeklenip sifirlaniyor", path.name)
            self._backup("bozuk")
            return {}

        if not isinstance(data, dict):
            log.error("%s beklenen bicimde degil (%s)", path.name, type(data).__name__)
            self._backup("bicim")
            return {}

        found = data.get("version")
        if found != self.version:
            log.error(
                "%s surumu uyusmuyor (dosya=%r, beklenen=%r); yedeklenip sifirlaniyor",
                path.name,
                found,
                self.version,
            )
            self._backup("surum")
            return {}
        return data

    # ---- yazma ----

    def save(self, data: dict[str, Any]) -> bool:
        """Atomik yazar. Basarisizsa log'a yazip False doner, firlatmaz."""
        payload: dict[str, Any] = {
            "version": self.version,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        payload.update(data)

        path = self.path
        temp = path.with_suffix(path.suffix + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
            os.replace(temp, path)
        except OSError:
            log.exception("%s yazilamadi", path.name)
            _drop_temp(temp)
            return False
        return True

    # ---- yardimci ----

    def _backup(self, reason: str) -> Path | None:
        """Bozuk dosyayi yaninda saklar. AHK: ErrHandler.backupOnError.

        Silmiyoruz: icinde kurtarilabilir pano gecmisi olabilir ve bunu
        ancak insan degerlendirebilir.
        """
        path = self.path
        target = path.with_name(f"{path.name}.{reason}-{datetime.now():%Y%m%d-%H%M%S}")
        try:
            os.replace(path, target)
        except OSError:
            log.exception("%s yedeklenemedi", path.name)
            return None
        log.warning("%s -> %s olarak yedeklendi", path.name, target.name)
        return target


def _drop_temp(path: Path) -> None:
    """Yarim kalmis .tmp dosyasini temizler; silinemezse sorun degil."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


class ClipStore(JsonStore):
    """Pano gecmisi dosyasi -- clip_hist.ahk'nin `_load` / `_save` bolumu.

    AHK ikili (binary) bir bicim kullaniyordu: 20 baytlik baslik, sonra
    `~` isaretcisiyle ayrilan kayitlar. Sebebi AHK'de duzgun bir JSON
    kutuphanesinin olmamasiydi (`jsongo.v2.ahk` 410 satir el yazmasi).
    Burada JSON: okunabilir, elle duzeltilebilir, kutuphane bedava.
    """

    filename = "clip_history.json"
    version = 1

    def __init__(self, directory: Path | None = None, max_items: int = 200) -> None:
        super().__init__(directory)
        self.max_items = max_items
        self.loaded_count = 0  # AHK: State.Script.getLoadedHistoryCount()

    def load_entries(self) -> list[ClipEntry]:
        """Kayitlari okur. Tek bir bozuk kayit dosyanin tamamini dusurmez --
        atlanir ve log'a yazilir."""
        data = self.load()
        rows = data.get("entries")
        if not isinstance(rows, list):
            self.loaded_count = 0
            return []

        entries: list[ClipEntry] = []
        skipped = 0
        for row in rows:
            entry = _entry_from_row(row)
            if entry is None:
                skipped += 1
                continue
            entries.append(entry)
        if skipped:
            log.warning("%s: %d bozuk kayit atlandi", self.filename, skipped)

        self.loaded_count = len(entries)
        return entries

    def save_entries(self, entries: tuple[ClipEntry, ...] | list[ClipEntry]) -> bool:
        """Kayitlari yazar.

        AHK'deki veri kaybi korumasi: acilista okunandan az kayit
        yazilacaksa yazma. Gecmis sadece buyur -- azaldiysa bir yerde is
        ters gitmistir ve dosyanin ustune yazmak o hatayi kalicilastirir.
        Kullanici bilerek temizlediyse `clear` yolundan gecer.
        """
        rows = [_row_from_entry(entry) for entry in entries[: self.max_items]]
        if self.loaded_count > len(rows):
            log.critical(
                "%s: yazilacak kayit (%d) acilista okunandan (%d) az; yazma iptal",
                self.filename,
                len(rows),
                self.loaded_count,
            )
            return False
        if self.save({"entries": rows}):
            self.loaded_count = len(rows)
            return True
        return False

    def clear(self) -> bool:
        """Kullanici bilerek temizledi: koruma devre disi."""
        self.loaded_count = 0
        return self.save({"entries": []})


def _row_from_entry(entry: ClipEntry) -> dict[str, Any]:
    return {
        "text": entry.text,
        "first_ts": entry.first_ts,
        "last_ts": entry.last_ts,
        "count": entry.count,
    }


def _entry_from_row(row: Any) -> ClipEntry | None:
    """Tek kaydi cevirir; bicim tutmuyorsa None (cagiran atlar)."""
    if not isinstance(row, dict):
        return None
    text = row.get("text")
    if not isinstance(text, str) or not text:
        return None
    try:
        entry = ClipEntry(
            text=text,
            first_ts=float(row.get("first_ts", 0.0)),
            last_ts=float(row.get("last_ts", 0.0)),
            count=int(row.get("count", 1)),
        )
    except (TypeError, ValueError):
        return None
    return entry if entry.count >= 1 else replace(entry, count=1)
