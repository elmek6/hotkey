"""Pano gorsellerinin kalici deposu -- clip_image_store.ahk portu.

**Dosya bicimi AHK ile BIREBIR AYNI** (surum 2): AHK'nin yazdigi depoyu bu
program acar, bunun yazdigini AHK acar. Bu yuzden asagidaki sayilarin hicbiri
degistirilemez.

Iki dosya:

    clipimg.idx   Sabit boyutlu slot dizisi (~7.84 MB). Metadata + 64x64 ham
                  thumb. Slot no = fiziksel konum, offset = 32 + slot*16448.
                  Hic buyumez, hic sikistirma istemez.
    clipimg.dat   500 MB DAIRESEL log. Yalniz PNG blob'lari, sona ekleme.
                  Dolunca en eski kayitlardan (tail) yer acilana kadar yenir.

Gorsel ASLA ham saklanmaz; tek ham istisna thumb'lar (sabit slot boyutu icin).

Slot duzeni (v2) -- 64 B metadata + 16384 B thumb:

     0 u8  state (0=bos 1=dolu)   1 u8  type (1=PNG)   2 u16 count
     4 u32 id                     8 u64 ts (son kullanim)
    16 u32 hash (ham DIB crc32)  20 u32 datOffset     24 u32 datSize
    28 u32 w                     32 u32 h             36 u16 bpp
    40 u64 createdTs (ilk yakalama)                   48..63 rezerve

Blob duzeni: [u32 toplamUzunluk][u32 tag] + PNG baytlari. Tag slot numarasi,
`TAG_PAD` ise olu alan. Uzunluk 8'in katina yuvarlanir -- yuvarlanmazsa ring
sonunda header'a SIGMAYAN 1..7 baytlik bir bosluk kalabiliyor ve ring
okunamaz hale geliyordu.

**Yazma sirasi (cokme guvenligi):** once blob -> sonra slot -> EN SON header.
Header commit noktasidir; yarida kalan yazimda header eski durumu gosterir,
yazilmis yetim baytlar bir sonraki turda uzerine yazilir.

AHK'den AYRILAN tek yer: hash. AHK `ntdll RtlComputeCrc32` cagiriyordu;
burada `zlib.crc32` var. Ikisi de standart CRC-32 (IEEE) ve ayni sonucu
uretiyor (tests/test_imgstore.py bunu dogruluyor), yani dedupe AHK'nin
yazdigi kayitlarda da calisir.
"""

from __future__ import annotations

import contextlib
import io
import logging
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from cascade import paths
from cascade.store import _to_ahk_ms, backup_file

log = logging.getLogger("cascade.imgstore")

MAGIC = 0x474D4943  # 'CIMG'
VERSION = 2
HDR_BYTES = 32
META_BYTES = 64
THUMB_SIZE = 64
THUMB_BYTES = THUMB_SIZE * THUMB_SIZE * 4  # 16384
SLOT_BYTES = META_BYTES + THUMB_BYTES  # 16448
MAX_SLOTS = 500
MAX_DAT = 500 * 1024 * 1024
MAX_PNG = 8 * 1024 * 1024  # kodlanmis ust sinir
MAX_RAW = 64 * 1024 * 1024  # ham DIB akil sagligi siniri
BLOB_HDR = 8
TAG_PAD = 0xFFFFFFFF

_HEADER = struct.Struct("<7I")  # magic, version, slotCount, nextId, head, tail, used
_META = struct.Struct("<BBHIQIIIIIH2xQ")  # 48 bayt; kalan 16 bayt rezerve
_BLOB = struct.Struct("<II")


@dataclass(slots=True)
class ImageRecord:
    """Tek bir kayit. `slot` fiziksel konum, kullaniciya gosterilmez."""

    slot: int
    state: int = 1
    type: int = 1  # 1 = PNG
    count: int = 1
    id: int = 0
    ts: int = 0  # son kullanim (AHK yerel epoch ms)
    hash: int = 0
    dat_offset: int = 0
    dat_size: int = 0
    w: int = 0
    h: int = 0
    bpp: int = 32
    created_ts: int = 0

    @property
    def valid(self) -> bool:
        """Diskten okunan kayit akla yatkin mi? (idx bozulmasina karsi tek savunma)"""
        return (
            0 < self.dat_size <= MAX_PNG
            and self.dat_offset < MAX_DAT
            and self.w > 0
            and self.h > 0
        )


class ClipImageStore:
    """AHK: singleClipImageStore. Tek ornek app.py'de tutulur.

    Yalniz Qt ana thread'inden kullanilir; AHK'deki `Critical` bloklarinin
    karsiligi bu yuzden gerekmiyor.
    """

    def __init__(self, directory: Path | None = None) -> None:
        directory = directory or paths.FILES
        self.idx_path = directory / "clipimg.idx"
        self.dat_path = directory / "clipimg.dat"
        self.slots: list[ImageRecord | None] = [None] * MAX_SLOTS
        self.by_hash: dict[int, int] = {}
        self.next_id = 1
        self.dat_head = 0
        self.dat_tail = 0
        self.dat_used = 0
        #: Her degisiklikte artar; dialog bunu yoklayip listeyi tazeler.
        self.rev = 0
        self._idx: io.BufferedRandom | None = None
        self._dat: io.BufferedRandom | None = None
        self._open()

    # ---- acilis ----

    def _open(self) -> None:
        try:
            self.idx_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.idx_path.exists() or not self.dat_path.exists():
                self._create_files()
            elif not self._version_ok():
                self._reset_for_new_version()
            # Dosyalar oturum boyunca ACIK kalir: her yazimda acip kapamak
            # 500 slotluk indekste anlamsiz maliyet. `close()` kapatir.
            self._idx = open(self.idx_path, "r+b")  # noqa: SIM115
            self._dat = open(self.dat_path, "r+b")  # noqa: SIM115
            self._load_meta()
            self._align_ring_head()
        except OSError:
            log.exception("gorsel deposu acilamadi")
            self.close()

    def _version_ok(self) -> bool:
        """Header'in ilk 8 bayti (magic + surum) bekledigimizle uyusuyor mu?"""
        try:
            with open(self.idx_path, "rb") as file:
                head = file.read(8)
        except OSError:
            return False
        if len(head) != 8:
            return False
        magic, version = struct.unpack("<II", head)
        return magic == MAGIC and version == VERSION

    def _reset_for_new_version(self) -> None:
        """Slot duzeni degistiyse eski veri okunamaz. Sessizce SILMIYORUZ:
        iki dosya da yedeklenip sifirdan kuruluyor (AHK: backupOnError)."""
        log.error("gorsel deposu surumu degisti, yedeklenip sifirlaniyor")
        backup_file(self.idx_path, "surum")
        backup_file(self.dat_path, "surum")
        self._create_files()

    def _create_files(self) -> None:
        """Bos idx (7.84 MB sifir) + bos dat (ilk yazimda buyur)."""
        with open(self.idx_path, "wb") as file:
            file.write(_HEADER.pack(MAGIC, VERSION, MAX_SLOTS, 1, 0, 0, 0) + b"\0" * 4)
            blank = b"\0" * SLOT_BYTES
            for _ in range(MAX_SLOTS):
                file.write(blank)
        open(self.dat_path, "wb").close()

    def _load_meta(self) -> None:
        """Acilista SADECE metadata okunur (500 x 64 B). Thumb'lar (8 MB)
        dialog acilana kadar diskte kalir."""
        assert self._idx is not None
        self._idx.seek(0)
        head = self._idx.read(HDR_BYTES)
        if len(head) != HDR_BYTES:
            raise OSError("gorsel deposu: header okunamadi")
        magic, version, slot_count, self.next_id, self.dat_head, self.dat_tail, self.dat_used = (
            _HEADER.unpack_from(head, 0)
        )
        if magic != MAGIC or version != VERSION:
            raise OSError("gorsel deposu: gecersiz magic/surum")
        slot_count = min(slot_count, MAX_SLOTS)

        # Header bozuksa ring imleclerine guvenmek felaket olur (devasa
        # okuma, sonsuz tahliye dongusu). Ring'i bosaltiyoruz VE slot'lari da:
        # imlecler olmadan blob'larin nerede yasadigini bilemeyiz.
        ring_lost = (
            self.dat_head >= MAX_DAT or self.dat_tail >= MAX_DAT or self.dat_used > MAX_DAT
        )
        if ring_lost:
            log.error(
                "gorsel deposu: ring imlecleri sinir disi (head=%d tail=%d used=%d), sifirlaniyor",
                self.dat_head, self.dat_tail, self.dat_used,
            )
            self.dat_head = self.dat_tail = self.dat_used = 0

        self.slots = [None] * MAX_SLOTS
        self.by_hash = {}
        for slot in range(slot_count):
            self._idx.seek(self._slot_offset(slot))
            meta = self._idx.read(META_BYTES)
            if len(meta) != META_BYTES:
                break
            if meta[0] == 0:
                continue
            record = self._parse_meta(meta, slot)
            if ring_lost or not record.valid:
                self._clear_meta(slot)  # diskte de kalmasin
                continue
            self.slots[slot] = record
            self.by_hash[record.hash] = slot

    @staticmethod
    def _parse_meta(meta: bytes, slot: int) -> ImageRecord:
        (state, type_, count, id_, ts, hash_, offset, size, w, h, bpp, created) = (
            _META.unpack_from(meta, 0)
        )
        return ImageRecord(
            slot=slot, state=state, type=type_, count=count, id=id_, ts=ts,
            hash=hash_, dat_offset=offset, dat_size=size, w=w, h=h, bpp=bpp,
            created_ts=created,
        )

    @staticmethod
    def _slot_offset(slot: int) -> int:
        return HDR_BYTES + slot * SLOT_BYTES

    # ---- yakalama ----

    def save_png(self, png: bytes, width: int, height: int, raw_hash: int, bpp: int = 32) -> int:
        """Kodlanmis PNG'yi depoya koyar. Slot no doner, basarisizsa -1.

        `raw_hash` HAM piksellerin crc32'si olmali -- PNG kodlamasi
        deterministik degil, ayni gorsel iki kez farkli bayt uretebiliyor.
        """
        if self._idx is None or self._dat is None:
            return -1
        if not png or len(png) > MAX_PNG:
            return -1
        try:
            # Dedupe: ayni gorsel zaten varsa blob'a hic dokunma.
            if raw_hash in self.by_hash:
                duplicate = self._touch_duplicate(raw_hash, width, height, bpp)
                if duplicate >= 0:
                    return duplicate

            thumb = self._make_thumb(png)
            if thumb is None:
                return -1
            offset = self._append_blob(png, TAG_PAD)  # tag sonra damgalanir
            if offset < 0:
                return -1
            slot = self._alloc_slot()
            if slot < 0:
                return -1
            self._stamp_tag(offset, slot)

            now = _to_ahk_ms(datetime.now().timestamp())
            record = ImageRecord(
                slot=slot, state=1, type=1, count=1, id=self.next_id, ts=now,
                created_ts=now, hash=raw_hash, dat_offset=offset, dat_size=len(png),
                w=width, h=height, bpp=bpp,
            )
            self.next_id += 1
            self.slots[slot] = record
            self.by_hash[raw_hash] = slot
            self._write_meta(record, thumb)
            self._write_header()
            return slot
        except (OSError, ValueError):
            log.exception("gorsel kaydedilemedi")
            return -1

    def save_image(self, image: Image.Image) -> int:
        """PIL goruntusunu depoya koyar (F14 secimi ve pano bu yoldan gecer).

        Hash ham RGBA piksellerden: PNG kodlamasi deterministik degil.
        AHK ham DIB baytlarindan hesapliyordu, yani ayni gorsel iki tarafta
        FARKLI hash verir -- dedupe surumler arasi calismaz, dosya bicimi
        yine de uyumlu kalir (bkz. dosya basi).
        """
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        png = buffer.getvalue()
        return self.save_png(
            png, image.width, image.height, zlib.crc32(image.tobytes()) & 0xFFFFFFFF
        )

    def _touch_duplicate(self, hash_: int, width: int, height: int, bpp: int) -> int:
        """Zaten depoda olan gorselin sayac/zaman damgasini tazeler.

        -1 = "bu bir kopya degil" (kayit olmus ya da CRC32 cakismasi) ->
        cagiran yeniden kaydeder.
        """
        slot = self.by_hash.get(hash_, -1)
        record = self.slots[slot] if 0 <= slot < MAX_SLOTS else None
        if record is None or record.state == 0:
            self.by_hash.pop(hash_, None)
            return -1
        # CRC32 cakismasi nadir ama mumkun -- boyutlar tutmuyorsa ayni gorsel degil.
        if record.w != width or record.h != height or record.bpp != bpp:
            return -1
        record.count = min(65535, record.count + 1)
        record.ts = _to_ahk_ms(datetime.now().timestamp())
        self._write_meta(record)
        return slot

    def _make_thumb(self, png: bytes) -> bytes | None:
        """64x64 ham BGRA thumb -- AHK GdipMini._bitmapToThumb ile ayni kural:
        orani koru, kutuya sigdir, ORTALA, arka plan saydam."""
        try:
            with Image.open(io.BytesIO(png)) as source:
                source = source.convert("RGBA")
                image = source.copy()
        except OSError:
            log.exception("thumb uretilemedi")
            return None
        image.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (THUMB_SIZE, THUMB_SIZE), (0, 0, 0, 0))
        canvas.paste(image, ((THUMB_SIZE - image.width) // 2, (THUMB_SIZE - image.height) // 2))
        # AHK 32ARGB scan0 yaziyor; little-endian bellekte bayt sirasi BGRA.
        red, green, blue, alpha = canvas.split()
        return Image.merge("RGBA", (blue, green, red, alpha)).tobytes()

    # ---- ring yonetimi ----

    def _append_blob(self, data: bytes, tag: int) -> int:
        """Blob'u head'e yazar, gerekirse tail'dan yiyerek yer acar.

        Kayit dosya sonunda IKIYE BOLUNMEZ: sigmiyorsa oraya pad birakip basa
        donuluyor. Uzunluk 8'in katina yuvarlaniyor (bkz. dosya basi).
        """
        assert self._dat is not None
        total = _align(len(data) + BLOB_HDR)
        if total > MAX_DAT:
            return -1

        tail_room = MAX_DAT - self.dat_head
        if 0 < tail_room < total:
            if tail_room < BLOB_HDR:
                log.error("gorsel deposu: ring sonunda tarif edilemez %d baytlik bosluk", tail_room)
                return -1
            if not self._ensure_space(tail_room):
                return -1
            self._write_blob_header(self.dat_head, tail_room, TAG_PAD)
            self.dat_used += tail_room
            self.dat_head = 0
        if not self._ensure_space(total):
            return -1

        offset = self.dat_head
        self._write_blob_header(offset, total, tag)
        self._dat.seek(offset + BLOB_HDR)
        self._dat.write(data)
        self._dat.flush()
        self.dat_head = (offset + total) % MAX_DAT
        self.dat_used += total
        return offset

    def _align_ring_head(self) -> None:
        """Hizalama kuralindan once yazilmis dosyalarda datHead 8'in kati
        olmayabilir. Olu bir pad kaydiyla katina getiriyoruz. Veri kaybi yok."""
        if self._dat is None:
            return
        rest = self.dat_head % BLOB_HDR
        if rest == 0:
            return
        pad = 2 * BLOB_HDR - rest
        tail_room = MAX_DAT - self.dat_head
        pad = min(pad, tail_room)
        if pad < BLOB_HDR or not self._ensure_space(pad):
            return
        self._write_blob_header(self.dat_head, pad, TAG_PAD)
        self.dat_used += pad
        self.dat_head = (self.dat_head + pad) % MAX_DAT
        self._write_header()

    def _ensure_space(self, need: int) -> bool:
        """Bos alan yetene kadar tail'daki kaydi yer. Kayit kendini tarif
        ettigi icin index'e bakmaya gerek yok -- 8 baytlik header yeter."""
        assert self._dat is not None
        guard = 0
        while MAX_DAT - self.dat_used < need:
            guard += 1
            if self.dat_used == 0 or guard > MAX_SLOTS * 2:
                return False
            self._dat.seek(self.dat_tail)
            head = self._dat.read(BLOB_HDR)
            if len(head) != BLOB_HDR:
                return False
            length, tag = _BLOB.unpack(head)
            if length == 0 or length > self.dat_used:
                return False  # bozuk ring -- yutmayi durdur
            if tag != TAG_PAD:
                self._free_slot(tag, stamp_pad=False)  # blob oldu -> slot da bosalir
            self.dat_tail = (self.dat_tail + length) % MAX_DAT
            self.dat_used -= length
        return True

    def _evict_one(self) -> bool:
        """Tail'daki tek kaydi yer -- slot dolulugunda yer acmak icin."""
        assert self._dat is not None
        if self.dat_used == 0:
            return False
        self._dat.seek(self.dat_tail)
        head = self._dat.read(BLOB_HDR)
        if len(head) != BLOB_HDR:
            return False
        length, tag = _BLOB.unpack(head)
        if length == 0 or length > self.dat_used:
            return False
        if tag != TAG_PAD:
            self._free_slot(tag, stamp_pad=False)
        self.dat_tail = (self.dat_tail + length) % MAX_DAT
        self.dat_used -= length
        return True

    def _write_blob_header(self, offset: int, total: int, tag: int) -> None:
        assert self._dat is not None
        self._dat.seek(offset)
        self._dat.write(_BLOB.pack(total, tag))
        self._dat.flush()

    def _stamp_tag(self, offset: int, tag: int) -> None:
        """Blob header'inin tag alanina slot numarasini yazar."""
        assert self._dat is not None
        self._dat.seek(offset + 4)
        self._dat.write(struct.pack("<I", tag))
        self._dat.flush()

    def _read_blob(self, record: ImageRecord) -> bytes | None:
        assert self._dat is not None
        self._dat.seek(record.dat_offset + BLOB_HDR)
        data = self._dat.read(record.dat_size)
        return data if len(data) == record.dat_size else None

    # ---- slot yonetimi ----

    def _alloc_slot(self) -> int:
        for slot in range(MAX_SLOTS):
            if self.slots[slot] is None:
                return slot
        # .dat'ta yer var ama 500 slot dolu: en eski blob'u yiyerek slot ac.
        before = self.dat_tail
        if not self._evict_one() or self.dat_tail == before:
            return -1
        for slot in range(MAX_SLOTS):
            if self.slots[slot] is None:
                return slot
        return -1

    def _free_slot(self, slot: int, stamp_pad: bool = True) -> None:
        if not 0 <= slot < MAX_SLOTS:
            return
        record = self.slots[slot]
        if record is None:
            return
        if stamp_pad:
            self._stamp_tag(record.dat_offset, TAG_PAD)
        if self.by_hash.get(record.hash) == slot:
            del self.by_hash[record.hash]
        self.slots[slot] = None
        self._clear_meta(slot)

    def delete_many(self, slots: list[int] | tuple[int, ...]) -> int:
        """Secili kayitlari siler. Silinen sayisi doner."""
        removed = 0
        for slot in slots:
            if 0 <= slot < MAX_SLOTS and self.slots[slot] is not None:
                self._free_slot(slot, stamp_pad=True)
                removed += 1
        if removed:
            self._write_header()
        return removed

    # ---- diske yazma ----

    def _write_meta(self, record: ImageRecord, thumb: bytes | None = None) -> None:
        assert self._idx is not None
        self.rev += 1
        meta = _META.pack(
            record.state, record.type, record.count, record.id, record.ts,
            record.hash, record.dat_offset, record.dat_size, record.w, record.h,
            record.bpp, record.created_ts,
        )
        meta = meta.ljust(META_BYTES, b"\0")  # 48..63 rezerve
        self._idx.seek(self._slot_offset(record.slot))
        self._idx.write(meta)
        if thumb is not None:
            self._idx.write(thumb[:THUMB_BYTES].ljust(THUMB_BYTES, b"\0"))
        self._idx.flush()

    def _clear_meta(self, slot: int) -> None:
        """state=0 yeterli; thumb baytlari yerinde kalir (yeni kayit uzerine yazar)."""
        if self._idx is None:
            return
        self.rev += 1
        self._idx.seek(self._slot_offset(slot))
        self._idx.write(b"\0" * META_BYTES)
        self._idx.flush()

    def _write_header(self) -> None:
        """Commit noktasi -- her zaman EN SON cagrilir."""
        assert self._idx is not None
        self._idx.seek(0)
        self._idx.write(
            _HEADER.pack(
                MAGIC, VERSION, MAX_SLOTS, self.next_id,
                self.dat_head, self.dat_tail, self.dat_used,
            )
            + b"\0" * 4
        )
        self._idx.flush()

    # ---- okuma ----

    def records(self) -> list[ImageRecord]:
        """Yasayan kayitlar, EN YENI ONDE. Fiziksel slot duzeni kullaniciya
        yansimasin diye son kullanim zamanina gore siralanir (AHK ile ayni)."""
        live = [record for record in self.slots if record is not None]
        live.sort(key=lambda record: record.ts, reverse=True)
        return live

    def read_thumb(self, slot: int) -> bytes | None:
        """Slotun 64x64 ham BGRA thumb'i. Decode YOK -- diskten oldugu gibi."""
        if self._idx is None or not 0 <= slot < MAX_SLOTS:
            return None
        self._idx.seek(self._slot_offset(slot) + META_BYTES)
        data = self._idx.read(THUMB_BYTES)
        return data if len(data) == THUMB_BYTES else None

    def read_png(self, slot: int) -> bytes | None:
        """Kaydin PNG baytlari."""
        if not 0 <= slot < MAX_SLOTS:
            return None
        record = self.slots[slot]
        return self._read_blob(record) if record is not None else None

    def export_to(self, slot: int, target: str | Path) -> bool:
        """Kaydi PNG olarak diske yazar."""
        png = self.read_png(slot)
        if png is None:
            return False
        try:
            Path(target).write_bytes(png)
        except OSError:
            log.exception("gorsel disa aktarilamadi")
            return False
        return True

    def touch(self, slot: int) -> None:
        """Kaydin son kullanim zamanini tazeler (panoya alinca)."""
        if not 0 <= slot < MAX_SLOTS:
            return
        record = self.slots[slot]
        if record is None:
            return
        record.ts = _to_ahk_ms(datetime.now().timestamp())
        self._write_meta(record)
        self._write_header()

    def stats(self) -> tuple[int, int, int]:
        """(kayit sayisi, toplam blob bayti, toplam kopya sayisi) -- AHK getStats."""
        live = [record for record in self.slots if record is not None]
        return (
            len(live),
            sum(record.dat_size for record in live),
            sum(record.count for record in live),
        )

    def close(self) -> None:
        for handle in (self._idx, self._dat):
            if handle is not None:
                with contextlib.suppress(OSError):
                    handle.close()
        self._idx = self._dat = None


def _align(value: int) -> int:
    rest = value % BLOB_HDR
    return value + (BLOB_HDR - rest) if rest else value


def thumb_to_image(thumb: bytes) -> Image.Image:
    """Ham BGRA thumb -> PIL goruntusu (liste ikonu icin)."""
    image = Image.frombytes("RGBA", (THUMB_SIZE, THUMB_SIZE), thumb)
    blue, green, red, alpha = image.split()
    return Image.merge("RGBA", (red, green, blue, alpha))


# TODO(AHK): `_isNearTail` / `_relocate` port edilmedi -- AHK sik kullanilan
#     bir gorsel tahliye sirasina yaklasinca onu ring'in basina TASIYORDU
#     (LRU'ya yaklasan davranis). Yalnizca ring %80 dolduktan sonra devreye
#     giriyordu; 500 MB'lik depo pratikte nadiren o noktaya gelir. Eklenirse
#     yeri `_touch_duplicate` icidir.
# TODO(AHK): `saveFromClipboard`in CF_DIB yolu yerine burada PNG/PIL yolu
#     kullaniliyor (win32/clipboard.py). Sonuc ayni ama AHK'nin ham DIB
#     hash'iyle bizimki farkli: dedupe surumler arasi calismaz.
