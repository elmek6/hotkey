"""Diske kayit -- AHK'deki `Path` sinifi + `FileIO` + `_load`/`_save` dizisi.

AHK'de her modul kendi dosyasini kendi aciyor, kendi hata mesajini kendi
yaziyordu; ayni try/catch bloklari `clip_hist`, `memory_slots`,
`trace_store`, `repository` icinde tekrar ediyordu. Burada ortak parcalar
tek yerde: `backup_file` (bozuk dosyayi yaninda saklama), `_drop_temp` ve
atomik yazma sirasi.

Uc depo var, ucu de AHK ile AYNI DOSYA BICIMINI kullanir -- ayni makinede
iki surum ayni veriyi paylasabilsin diye:

    ClipStore   Files/clipboards.bin   ikili, surum 2   clip_hist.ahk
    SlotStore   Files/slots.json       duz JSON         clip_slot.ahk
    JsonStore   (bize ozel dosyalar)   surum alanli JSON

Butun dosyalar `Files/` altinda (cascade/paths.py) -- program tasinabilir
kalsin, AppData'ya dagilmasin. AHK'de de oyleydi.

AHK'den aynen tasinan dort davranis:

1. **Bozuk dosya programi durdurmaz.** Okunamazsa dosya YEDEKLENIR
   (`.bozuk-<zaman>` uzantisiyla yaninda kalir), hata log'a yazilir ve
   program elde ne varsa onunla acilir. AHK: `backupOnError` + `handleError`.
2. **Yazma atomik.** Once `.tmp` dosyaya yazilir, sonra `os.replace` ile
   yerine gecer. Yazarken elektrik giderse eldeki dosya bozulmaz -- AHK'de
   olmayan, ucuza gelen bir kazanc.
3. **Veri kaybi korumasi.** Acilista okunan kayit sayisindan AZ kayit
   yazilacaksa yazma yapilmaz, log'a kritik dusulur. AHK'de bu bir
   `DialogCriticalError` idi; burada sessiz ama izi kalan bir red, cunku
   kapanis sirasinda modal pencere acmak kapanisi kilitler.
4. **Surum alani.** Yalniz BIZE ait dosyalarda (`JsonStore`). AHK'nin
   paylastigi iki dosyaya surum alani EKLENMEZ: `clipboards.bin`in kendi
   surumu var, `slots.json`in hic yok ve eklersek AHK'nin yazdigini
   reddetmis oluruz.

Saf Python: Qt yok, Win32 yok -- test edilebilir.
"""

from __future__ import annotations

import contextlib
import logging
import os
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import orjson

from cascade import paths
from cascade.core.clip_history import ClipEntry

log = logging.getLogger("cascade.store")

BOM = b"\xef\xbb\xbf"  # AHK FileIO.writeText(..., "UTF-8") bunu basa koyuyor

# AHK: `singleClipHist.getInstance(1000, 2500)` -- ikinci sayi DISKTEKI
# sinir. Bellekteki sinir ayri (core/clip_history.py MAX_ITEMS) ve daha
# kucuk; ikisi birbirine karismasin diye ayri sabit.
MAX_SAVE_COUNT = 2500


# ---- ortak yardimcilar ----


def backup_file(path: Path, reason: str, copy: bool = False) -> Path | None:
    """Bozuk dosyayi yaninda saklar. AHK: ErrHandler.backupOnError.

    Silmiyoruz: icinde kurtarilabilir pano gecmisi olabilir ve bunu ancak
    insan degerlendirebilir. `copy=True` ise dosya yerinde de kalir --
    yarim okudugumuz ama uzerine yazacagimiz durumda gerekiyor.
    """
    target = path.with_name(f"{path.name}.{reason}-{datetime.now():%Y%m%d-%H%M%S}")
    try:
        if copy:
            target.write_bytes(path.read_bytes())
        else:
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


def _write_atomic(path: Path, data: bytes) -> bool:
    """Once `.tmp`, sonra `os.replace`. Basarisizsa log'a yazar, firlatmaz."""
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(data)
        os.replace(temp, path)
    except OSError:
        log.exception("%s yazilamadi", path.name)
        _drop_temp(temp)
        return False
    return True


class JsonStore:
    """Tek bir JSON dosyasini yoneten taban sinif -- BIZE ait dosyalar icin.

    AHK ile paylasilan dosyalar bunu kullanmaz (surum alani onlarda yok).
    """

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
            backup_file(path, "bozuk")
            return {}

        if not isinstance(data, dict):
            log.error("%s beklenen bicimde degil (%s)", path.name, type(data).__name__)
            backup_file(path, "bicim")
            return {}

        found = data.get("version")
        if found != self.version:
            log.error(
                "%s surumu uyusmuyor (dosya=%r, beklenen=%r); yedeklenip sifirlaniyor",
                path.name,
                found,
                self.version,
            )
            backup_file(path, "surum")
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
        return _write_atomic(self.path, orjson.dumps(payload, option=orjson.OPT_INDENT_2))


# ---- pano gecmisi: clip_hist.ahk ikili bicimi ----


class ClipStore:
    """Pano gecmisi -- clip_hist.ahk `_readRecords` / `_writeAllRecords`.

    **Bicim AHK ile birebir ayni** (`Files/clipboards.bin`, surum 2), cunku
    ayni makinede iki surum ayni dosyayi paylasabilsin istiyoruz: AHK'nin
    yazdigini bu program okur, bunun yazdigini AHK acar.

        baslik  20 bayt : u32  kayit sayisi
                          u64  dosyanin baslangic tarihi (ms)
                          u32  surum (2)
                          u32  ayrilmis (0)
        kayit 15+N bayt : u64  zaman damgasi (ms)
                          u16  kac kez kopyalandi
                          u32  metnin BAYT uzunlugu
                          u8   0x7E (`~`) isaretci
                          N    UTF-8 metin (sonlandirici yok)

    `~` isaretcisi bicimin tek saglamasi: bir kaydin uzunlugu yanlissa
    sonraki kaydin basinda 0x7E cikmaz ve okuma orada durur. AHK de boyle
    yapiyordu -- cop veriyi kayit diye icmektense okumayi kesmek.

    ZAMAN DAMGASI TUZAGI: AHK `DateDiff(A_Now, "19700101000000", "S")`
    yaziyor, yani YEREL saate gore epoch. Python'un `time.time()` degeri
    UTC. Ayni sayiyi yazmak icin cevirirken yerel saate gecmek zorundayiz
    (`_to_ahk_ms` / `_from_ahk_ms`), yoksa dosya AHK'de saatler kayik
    gorunur.
    """

    filename = "clipboards.bin"
    version = 2
    max_bytes = 1_048_576  # AHK: maxByteSize -- daha buyugu bozuk sayilir

    HEADER = struct.Struct("<IQII")
    RECORD = struct.Struct("<QHI")
    MARKER = 0x7E

    def __init__(self, directory: Path | None = None, max_items: int = MAX_SAVE_COUNT) -> None:
        self._directory = directory or paths.FILES
        #: Diskteki sinir -- AHK `getInstance(1000, 2500)`in ikinci sayisi.
        #: BELLEKTEKI sinirdan (ClipHistory.MAX_ITEMS) bagimsiz ve ondan cok
        #: daha buyuk olabilir, cunku `save_entries` diskte olup bellekte
        #: olmayan kayitlari koruyor (bkz. orada).
        self.max_items = max_items
        self.loaded_count = 0  # AHK: State.Script.getLoadedHistoryCount()
        # AHK dosyanin baslangic tarihini KORUYOR: yeniden yazarken ne
        # okuduysa onu geri koyuyor, boylece "bu gecmis ne zaman baslamis"
        # bilgisi kaybolmuyor.
        self._start_ms = 0

    @property
    def path(self) -> Path:
        return self._directory / self.filename

    # ---- okuma ----

    def load_entries(self) -> list[ClipEntry]:
        """Kayitlari okur. Bozuk dosya programi durdurmaz: yedeklenir ve
        okunabilen kadari ile devam edilir (AHK: backupOnError)."""
        path = self.path
        self.loaded_count = 0
        if not path.exists():
            return []
        try:
            raw = path.read_bytes()
        except OSError:
            log.exception("%s okunamadi", path.name)
            return []

        if len(raw) < self.HEADER.size:
            log.error("%s: baslik eksik (%d bayt)", path.name, len(raw))
            backup_file(path, "bozuk")
            return []

        expected, start_ms, version, _reserved = self.HEADER.unpack_from(raw, 0)
        if version != self.version:
            log.error(
                "%s surumu uyusmuyor (dosya=%d, beklenen=%d); yedeklenip sifirlaniyor",
                path.name,
                version,
                self.version,
            )
            backup_file(path, "surum")
            return []
        self._start_ms = start_ms

        entries, offset = self._read_records(raw)
        if len(entries) > self.max_items:
            # AHK `_readRecords(count)` da istenen sayida kayitta duruyordu.
            entries = entries[: self.max_items]
            expected = min(expected, self.max_items)
        if len(entries) < expected:
            # AHK: okunan < beklenen -> dosya bozuk. Yedegi KOPYA olarak
            # aliniyor ama okunanlar atilmiyor: yarim gecmis, hic gecmisten
            # iyidir.
            log.error(
                "%s bozuk: baslik %d kayit diyor, %d okundu (%d/%d bayt)",
                path.name,
                expected,
                len(entries),
                offset,
                len(raw),
            )
            backup_file(path, "bozuk", copy=True)

        self.loaded_count = len(entries)
        return entries

    def _read_records(self, raw: bytes) -> tuple[list[ClipEntry], int]:
        """Baslik sonrasini kayitlara ayirir. (kayitlar, okunan bayt)."""
        entries: list[ClipEntry] = []
        offset = self.HEADER.size
        size = len(raw)
        while offset + self.RECORD.size + 1 <= size:
            ts_ms, count, byte_len = self.RECORD.unpack_from(raw, offset)
            if byte_len == 0 or byte_len > self.max_bytes:
                break  # AHK ile ayni: sacma uzunluk -> burada kes
            offset += self.RECORD.size
            if raw[offset] != self.MARKER:
                break  # hizalama kaymis
            offset += 1
            if offset + byte_len > size:
                break  # metin dosyanin disina tasiyor
            try:
                text = raw[offset : offset + byte_len].decode("utf-8")
            except UnicodeDecodeError:
                break
            offset += byte_len
            seconds = _from_ahk_ms(ts_ms)
            # TODO(AHK): clip_hist.ahk kayit basina TEK zaman damgasi tutuyor
            # (son kopyalama). Bizim ClipEntry'de ayrica first_ts var; bicimi
            # bozmamak icin diske YAZILMIYOR ve okurken last_ts ile ayni
            # degere kuruluyor. Ilk gorulme tarihini saklamak istersek bicim
            # surumu 3 olmak zorunda -- o zaman da AHK okuyamaz.
            entries.append(
                ClipEntry(
                    text=text,
                    first_ts=seconds,
                    last_ts=seconds,
                    count=max(1, count),
                )
            )
        return entries, offset

    # ---- yazma ----

    def save_entries(self, entries: tuple[ClipEntry, ...] | list[ClipEntry]) -> bool:
        """Kayitlari yazar. AHK `_save` ile ayni veri kaybi korumasi:
        acilista okunandan AZ kayit yazilacaksa yazmaz.

        Gecmis sadece buyur; azaldiysa bir yerde is ters gitmistir ve
        ustune yazmak o hatayi kalicilastirir. (AHK burada modal soru
        soruyordu; kapanis sirasinda modal pencere kapanisi kilitler, o
        yuzden bizde sessiz ama log'a dusen bir red.)

        Yazmadan once diskteki kayitlarla BIRLESTIRILIYOR (AHK `_save` ile
        ayni): bellektekiler basa, dosyada olup bellekte olmayanlar arkaya.
        Sart, cunku bellekteki liste diskteki kadar uzun degil
        (ClipHistory.MAX_ITEMS < MAX_SAVE_COUNT); birlestirmezsek her
        kapanista dosya bellekteki boya kirpilirdi.
        """
        rows = _merge_with_disk(list(entries), self._read_current())[: self.max_items]
        if self.loaded_count > len(rows):
            log.critical(
                "%s: yazilacak kayit (%d) acilista okunandan (%d) az; yazma iptal",
                self.filename,
                len(rows),
                self.loaded_count,
            )
            return False

        start_ms = self._start_ms or _to_ahk_ms(datetime.now().timestamp())
        chunks: list[bytes] = [b""]  # baslik en son yazilacak (sayim icin)
        written = 0
        for entry in rows:
            data = entry.text.encode("utf-8")
            if not data or len(data) > self.max_bytes:
                continue  # AHK okurken bunlarda duruyor; hic yazmiyoruz
            chunks.append(
                self.RECORD.pack(
                    _to_ahk_ms(entry.last_ts), min(entry.count, 0xFFFF), len(data)
                )
            )
            chunks.append(bytes((self.MARKER,)))
            chunks.append(data)
            written += 1
        chunks[0] = self.HEADER.pack(written, start_ms, self.version, 0)

        if not _write_atomic(self.path, b"".join(chunks)):
            return False
        self._start_ms = start_ms
        self.loaded_count = written
        return True

    def clear(self) -> bool:
        """Kullanici bilerek temizledi: ne veri kaybi korumasi calisir ne de
        diskle birlestirme -- yoksa sildigimiz kayitlar geri gelirdi."""
        self.loaded_count = 0
        start_ms = self._start_ms or _to_ahk_ms(datetime.now().timestamp())
        return _write_atomic(self.path, self.HEADER.pack(0, start_ms, self.version, 0))

    def _read_current(self) -> list[ClipEntry]:
        """Diskteki kayitlar -- birlestirme icin. Sorun cikarsa bos liste;
        burasi yazma yolunun ortasi, hata verip kapanisi bozamaz."""
        path = self.path
        if not path.exists():
            return []
        try:
            raw = path.read_bytes()
        except OSError:
            return []
        if len(raw) < self.HEADER.size:
            return []
        if self.HEADER.unpack_from(raw, 0)[2] != self.version:
            return []
        return self._read_records(raw)[0]


# ---- slotlar: clip_slot.ahk JSON bicimi ----


@dataclass(slots=True)
class Slot:
    """AHK: Map("name", "Slot 1", "content", "..."). Sira dosyadaki sira."""

    name: str = ""
    content: str = ""


DEFAULT_GROUP = ""  # AHK: adi bos olan grup her zaman ilk sirada yazilir
SLOTS_PER_GROUP = 10  # AHK: Loop 10

#: Sifre slotu. Tuslarda "0" ile cagrilan SON slot (F13 menusunde "Slot 0",
#: dosyada 10. kayit). Icerigi HICBIR listede/menude gosterilmez -- yalnizca
#: yapistirilir. Parolayi slotta tutmak yaygin kullanim; ekranda durmasi
#: omuz ustunden okunmasina aciktir.
PASSWORD_SLOT = SLOTS_PER_GROUP
MASK = "••••••••"


def slot_display(index: int, content: str, shorten=None) -> str:
    """Slot icerigi listede nasil gorunur (1 tabanli indeks).

    Sifre slotunda icerik yerine maske doner; bos slotta bos dizgi. Metni
    kisaltan islev disaridan verilebilir (menu ve pencere ayri kisaltiyor).
    """
    if not content:
        return ""
    if index == PASSWORD_SLOT:
        return MASK
    return shorten(content) if shorten is not None else content


class SlotStore:
    """Hafiza slotlari -- `clip_slot.ahk` (`Files/slots.json`).

    Bicim AHK'nin yazdiginin aynisi, anahtar adlari dahil:

        {"defaultGroupName": "", "groups": [
            {"groupName": "", "values": [{"content": "...", "name": "Slot 1"}]}
        ]}

    Surum alani YOK ve eklemiyoruz: eklersek AHK tarafi dosyayi taniyor ama
    biz onun yazdigini "surumsuz" diye reddederdik. Bu yuzden `JsonStore`
    tabanindan gelmiyor, kendi okuma/yazmasi var.

    Iki AHK ayrintisi korunuyor:
      * BOM: AHK `FileIO.writeText(..., "UTF-8")` dosyanin basina BOM
        koyuyor; biz de koyuyoruz ki dosya elden ele gecince degismesin.
      * Grup sirasi: adi bos olan grup HER ZAMAN once yazilir (AHK
        `saveSlots` acikca boyle yapiyor).

    Grup yonetimi (AHK `addGroup` / `deleteGroup` / `setDefaultGroup` /
    `setName`) asagida; arayuzu F14 menusunun "Side slot" kolonu veriyor.
    Dokunmadigimiz gruplar dosyada aynen kalir.
    """

    filename = "slots.json"

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory or paths.FILES
        self.default_group = DEFAULT_GROUP
        #: grup adi -> slotlar. Okundugu sirada (Python sozlugu sirali).
        self.groups: dict[str, list[Slot]] = {}

    @property
    def path(self) -> Path:
        return self._directory / self.filename

    # ---- okuma ----

    def load(self) -> dict[str, list[Slot]]:
        """Dosyayi okur. Yoksa on bos slotluk varsayilan grup uretir
        (AHK: initializeDefaultGroups)."""
        path = self.path
        if not path.exists():
            return self._reset()
        try:
            data = orjson.loads(path.read_bytes().lstrip(BOM))
        except (OSError, orjson.JSONDecodeError):
            log.exception("%s okunamadi, yedeklenip sifirlaniyor", path.name)
            backup_file(path, "bozuk")
            return self._reset()

        if not isinstance(data, dict):
            log.error("%s beklenen bicimde degil", path.name)
            backup_file(path, "bicim")
            return self._reset()

        default = data.get("defaultGroupName")
        self.default_group = default if isinstance(default, str) else DEFAULT_GROUP

        groups: dict[str, list[Slot]] = {}
        for group in data.get("groups") or []:
            if not isinstance(group, dict):
                continue
            name = group.get("groupName")
            if not isinstance(name, str):
                continue
            groups[name] = [
                Slot(name=str(value.get("name", "")), content=str(value.get("content", "")))
                for value in group.get("values") or []
                if isinstance(value, dict)
            ]
        if DEFAULT_GROUP not in groups:
            groups[DEFAULT_GROUP] = _blank_slots()
        self.groups = groups
        return groups

    def _reset(self) -> dict[str, list[Slot]]:
        self.default_group = DEFAULT_GROUP
        self.groups = {DEFAULT_GROUP: _blank_slots()}
        return self.groups

    def slots(self, group: str = DEFAULT_GROUP) -> list[Slot]:
        """Bir grubun slotlari; her zaman en az on tane (AHK: setContent
        eksik slotlari yolda uretiyordu)."""
        values = self.groups.setdefault(group, [])
        while len(values) < SLOTS_PER_GROUP:
            values.append(Slot(name=f"Slot {len(values) + 1}", content=""))
        return values

    def group_names(self) -> list[str]:
        """Adi olan gruplar (AHK: getGroupsName -- varsayilan grup haric)."""
        return [name for name in self.groups if name != DEFAULT_GROUP]

    # ---- grup yonetimi (AHK: clip_slot.ahk) ----

    def add_group(self, name: str) -> bool:
        """Yeni grup: on bos slotla acilir. Var olan ada dokunmaz."""
        name = name.strip()
        if not name or name in self.groups:
            return False
        self.groups[name] = _blank_slots()
        return self.save()

    def delete_group(self, name: str) -> bool:
        """Grubu siler. Varsayilan grup (adsiz) SILINMEZ -- AHK'de de oyle.

        Silinen grup "yan grup" olarak secilmisse secim bosa duser.
        """
        if name == DEFAULT_GROUP or name not in self.groups:
            return False
        del self.groups[name]
        if self.default_group == name:
            self.default_group = DEFAULT_GROUP
        return self.save()

    def set_default_group(self, name: str) -> bool:
        """AHK `setDefaultGroup`: "yan grup" secimi. Bos ad = yan grup yok."""
        if name and name not in self.groups:
            log.warning("grup bulunamadi: %s", name)
            return False
        self.default_group = name
        return self.save()

    def set_slot_name(self, group: str, index: int, name: str) -> bool:
        """AHK `setName`: slotun ADI (icerik degil). 1 tabanli indeks."""
        values = self.slots(group)
        if not 1 <= index <= len(values):
            return False
        values[index - 1].name = name.strip() or f"Slot {index}"
        return self.save()

    def set_slot_content(self, group: str, index: int, content: str) -> bool:
        """AHK `saveToSlot`: slota icerik yazar."""
        values = self.slots(group)
        if not 1 <= index <= len(values):
            return False
        values[index - 1].content = content
        return self.save()

    # ---- yazma ----

    def save(self) -> bool:
        """Atomik yazar. Dokunmadigimiz gruplar oldugu gibi geri yazilir."""
        names = [DEFAULT_GROUP] + [name for name in self.groups if name != DEFAULT_GROUP]
        ordered = [
            {
                "groupName": name,
                "values": [
                    {"content": slot.content, "name": slot.name} for slot in self.groups[name]
                ],
            }
            for name in names
            if name in self.groups
        ]
        payload = {"defaultGroupName": self.default_group, "groups": ordered}
        return _write_atomic(self.path, BOM + orjson.dumps(payload))


def _merge_with_disk(memory: list[ClipEntry], disk: list[ClipEntry]) -> list[ClipEntry]:
    """AHK `_save`in birlestirmesi: bellektekiler once, dosyada olup
    bellekte olmayanlar arkaya. Ayni metin iki kez girmez.

    AHK'de eskiden ic ice donguyle O(n*m) idi, sonra `seen` Map'iyle
    O(n+m)'e cekilmisti; buradaki kume de ayni isi yapiyor.
    """
    seen = {entry.text for entry in memory}
    merged = list(memory)
    for entry in disk:
        if entry.text in seen:
            continue
        seen.add(entry.text)
        merged.append(entry)
    return merged


def _blank_slots() -> list[Slot]:
    """AHK: initializeDefaultGroups -- "Slot 1".."Slot 10", icerik bos."""
    return [Slot(name=f"Slot {index}", content="") for index in range(1, SLOTS_PER_GROUP + 1)]


# ---- zaman cevrimi ----

_EPOCH = datetime(1970, 1, 1)


def _to_ahk_ms(seconds: float) -> int:
    """POSIX saniye -> AHK'nin yazdigi YEREL epoch milisaniyesi."""
    try:
        local = datetime.fromtimestamp(seconds)
    except (OverflowError, OSError, ValueError):
        local = datetime.now()
    return int((local - _EPOCH).total_seconds() * 1000)


def _from_ahk_ms(ms: int) -> float:
    """AHK'nin yerel epoch milisaniyesi -> POSIX saniye."""
    try:
        return (_EPOCH + timedelta(milliseconds=ms)).timestamp()
    except (OverflowError, OSError, ValueError):
        return 0.0
