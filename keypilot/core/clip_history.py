"""Pano gecmisi listesi -- clip_hist.ahk'nin `history` dizisinin karsiligi.

Saf Python: Win32 yok, Qt yok, zaman disaridan verilir. Dinleme isi burada
DEGIL (ui/clipboard.py); burasi yalnizca "ne saklanir, nasil siralanir"
sorusunu cevaplar ve tamamen test edilebilir.

AHK'deki kurallar birebir korundu:

  * yeni metin basa girer, liste yeniden -> eskiye dogru siralidir
  * ayni metin tekrar kopyalanirsa yeni kayit acilmaz: mevcut kayit basa
    tasinir, `count` artar, `last_ts` guncellenir
  * ust ust ayni metin (lastClip) hicbir sey yapmaz, sayaci da artirmaz
  * bos metin ve 1 MB ustu metin alinmaz
  * liste dolunca en eski (sondaki) kayit duser

Diske kayit store.ClipStore'da: `entries` acilista oradan yuklenir
(`load`), kapanista oraya yazilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

MAX_ITEMS = 50
MAX_BYTES = 1_048_576  # AHK: maxByteSize


@dataclass(frozen=True, slots=True)
class ClipEntry:
    """AHK: Map("ts", ..., "count", ..., "text", ...) -- artik tipli."""

    text: str
    first_ts: float
    last_ts: float
    count: int = 1

    @property
    def preview(self) -> str:
        """Tek satirlik ozet; ipucunda ve listede gosterilir."""
        return " ".join(self.text.split())


@dataclass
class ClipHistory:
    """Bellekte duran pano gecmisi. Yalnizca ana thread'den kullanilir.

    Kilit yok: pano bildirimi Qt ana thread'inde gelir, gosterim de orada.
    Hook thread'i bu nesneye hic dokunmaz.
    """

    max_items: int = MAX_ITEMS
    max_bytes: int = MAX_BYTES
    _items: list[ClipEntry] = field(default_factory=list, init=False)

    # ---- sorgular ----

    @property
    def entries(self) -> tuple[ClipEntry, ...]:
        return tuple(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def get(self, index: int) -> ClipEntry | None:
        """1 tabanli -- AHK'deki `history[index]` ile ayni numaralandirma."""
        if 1 <= index <= len(self._items):
            return self._items[index - 1]
        return None

    @property
    def last_text(self) -> str:
        """AHK: lastClip"""
        return self._items[0].text if self._items else ""

    # ---- besleme ----

    def add(self, text: str, now: float) -> ClipEntry | None:
        """Metni gecmise koyar. Alinmadiysa None doner (cagiran ipucu basmaz).

        None donen durumlar AHK ile ayni: bos, cok buyuk, ya da zaten en
        ustteki kayit.
        """
        if not text or text == self.last_text:
            return None
        if len(text.encode("utf-8")) > self.max_bytes:
            return None

        for index, item in enumerate(self._items):
            if item.text == text:
                moved = replace(item, last_ts=now, count=item.count + 1)
                del self._items[index]
                self._items.insert(0, moved)
                return moved

        entry = ClipEntry(text=text, first_ts=now, last_ts=now, count=1)
        self._items.insert(0, entry)
        del self._items[self.max_items :]
        return entry

    def load(self, entries: list[ClipEntry] | tuple[ClipEntry, ...]) -> int:
        """Diskten okunan kayitlari yerlestirir (store.ClipStore cagirir).

        Mevcut listenin USTUNE degil, YERINE: acilista bir kez cagriliyor.
        Ayni metin iki kez gelirse ilki kalir -- dosyada olmamasi gereken
        bir durum ama okunan dosyaya guvenmiyoruz.
        """
        seen: set[str] = set()
        items: list[ClipEntry] = []
        for entry in entries:
            if entry.text in seen:
                continue
            seen.add(entry.text)
            items.append(entry)
        self._items = items[: self.max_items]
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()
