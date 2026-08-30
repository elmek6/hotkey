"""Gorsel deposu -- clip_image_store.ahk bicimi.

Bicim AHK ile paylasildigi icin testlerin cogu BAYT DUZEYINDE: header ve
slot alanlarinin tam olarak dogru offsetlerde oldugu dogrulaniyor. AHK'de
bu dosya hic test edilemiyordu.
"""

import struct
import zlib

import pytest
from PIL import Image

from cascade.imgstore import (
    BLOB_HDR,
    HDR_BYTES,
    MAGIC,
    MAX_SLOTS,
    META_BYTES,
    SLOT_BYTES,
    THUMB_BYTES,
    THUMB_SIZE,
    VERSION,
    ClipImageStore,
    thumb_to_image,
)


@pytest.fixture
def store(tmp_path):
    instance = ClipImageStore(tmp_path)
    yield instance
    instance.close()


def make_image(width=120, height=80, color=(200, 30, 40)) -> Image.Image:
    return Image.new("RGBA", (width, height), (*color, 255))


# ---- dosya bicimi (AHK ile paylasilan) ----


def test_yeni_depo_ahk_headerini_yazar(store, tmp_path):
    raw = (tmp_path / "clipimg.idx").read_bytes()
    magic, version, slots, next_id, head, tail, used = struct.unpack_from("<7I", raw, 0)
    assert magic == MAGIC  # 'CIMG'
    assert version == VERSION
    assert slots == MAX_SLOTS
    assert (next_id, head, tail, used) == (1, 0, 0, 0)


def test_idx_dosyasi_sabit_boyutlu(store, tmp_path):
    """Slot dizisi hic buyumez: 32 + 500 * 16448."""
    assert (tmp_path / "clipimg.idx").stat().st_size == HDR_BYTES + MAX_SLOTS * SLOT_BYTES


def test_slot_boyutlari_ahk_ile_ayni():
    assert META_BYTES == 64
    assert THUMB_BYTES == THUMB_SIZE * THUMB_SIZE * 4 == 16384
    assert SLOT_BYTES == 16448


def test_kayit_metadata_dogru_offsetlere_yazilir(store, tmp_path):
    slot = store.save_image(make_image(120, 80))
    assert slot == 0
    raw = (tmp_path / "clipimg.idx").read_bytes()
    base = HDR_BYTES + slot * SLOT_BYTES
    assert raw[base] == 1  # state = dolu
    assert raw[base + 1] == 1  # type = PNG
    assert struct.unpack_from("<H", raw, base + 2)[0] == 1  # count
    assert struct.unpack_from("<I", raw, base + 4)[0] == 1  # id
    assert struct.unpack_from("<I", raw, base + 28)[0] == 120  # w
    assert struct.unpack_from("<I", raw, base + 32)[0] == 80  # h
    assert struct.unpack_from("<H", raw, base + 36)[0] == 32  # bpp


def test_blob_header_uzunluk_ve_slot_etiketi_tasir(store, tmp_path):
    slot = store.save_image(make_image())
    record = store.slots[slot]
    raw = (tmp_path / "clipimg.dat").read_bytes()
    total, tag = struct.unpack_from("<II", raw, record.dat_offset)
    assert tag == slot  # blob kendi slotunu tarif eder
    assert total % BLOB_HDR == 0  # 8'in katina yuvarlanmis
    assert total >= record.dat_size + BLOB_HDR


def test_png_baytlari_blob_headerindan_sonra_gelir(store):
    slot = store.save_image(make_image())
    png = store.read_png(slot)
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


# ---- kayit ve okuma ----


def test_kaydedilen_gorsel_geri_okunur(store):
    slot = store.save_image(make_image(60, 40, (10, 200, 90)))
    png = store.read_png(slot)
    import io

    with Image.open(io.BytesIO(png)) as image:
        assert image.size == (60, 40)
        assert image.convert("RGBA").getpixel((0, 0)) == (10, 200, 90, 255)


def test_ayni_gorsel_ikinci_kez_yeni_slot_acmaz(store):
    """Dedupe: sayac artar, blob'a hic dokunulmaz."""
    first = store.save_image(make_image())
    used_before = store.dat_used
    second = store.save_image(make_image())
    assert first == second
    assert store.slots[first].count == 2
    assert store.dat_used == used_before  # yeni blob yazilmadi


def test_farkli_gorsel_yeni_slot_alir(store):
    first = store.save_image(make_image(color=(1, 2, 3)))
    second = store.save_image(make_image(color=(9, 9, 9)))
    assert first != second
    assert len(store.records()) == 2


def test_kayitlar_en_yeni_onde_siralanir(store):
    old = store.save_image(make_image(color=(1, 1, 1)))
    new = store.save_image(make_image(color=(2, 2, 2)))
    store.slots[old].ts = 1000
    store.slots[new].ts = 2000
    assert [record.slot for record in store.records()] == [new, old]


def test_silinen_kayit_listeden_ve_diskten_duser(store, tmp_path):
    slot = store.save_image(make_image())
    assert store.delete_many([slot]) == 1
    assert store.records() == []
    raw = (tmp_path / "clipimg.idx").read_bytes()
    assert raw[HDR_BYTES + slot * SLOT_BYTES] == 0  # state = bos


def test_silinen_slot_yeniden_kullanilir(store):
    first = store.save_image(make_image(color=(1, 1, 1)))
    store.delete_many([first])
    second = store.save_image(make_image(color=(2, 2, 2)))
    assert second == first


def test_silinen_blob_pad_olarak_isaretlenir(store, tmp_path):
    """Blob header'inin tag'i TAG_PAD olur; ring o alani olu sayar."""
    slot = store.save_image(make_image())
    offset = store.slots[slot].dat_offset
    store.delete_many([slot])
    raw = (tmp_path / "clipimg.dat").read_bytes()
    assert struct.unpack_from("<I", raw, offset + 4)[0] == 0xFFFFFFFF


# ---- thumb ----


def test_thumb_sabit_boyutta_ve_orani_korur(store):
    slot = store.save_image(make_image(200, 100))
    thumb = store.read_thumb(slot)
    assert len(thumb) == THUMB_BYTES
    image = thumb_to_image(thumb)
    assert image.size == (THUMB_SIZE, THUMB_SIZE)
    # 2:1 gorsel 64x32 olarak ortalanir: ust satirlar saydam kalir
    assert image.getpixel((32, 0))[3] == 0
    assert image.getpixel((32, 32))[3] == 255


def test_thumb_bgra_sirasinda_yazilir(store):
    """AHK 32ARGB scan0 yaziyor; bellekte bayt sirasi BGRA."""
    slot = store.save_image(make_image(64, 64, (255, 0, 0)))  # saf kirmizi
    thumb = store.read_thumb(slot)
    # ortadaki pikselin ilk bayti mavi kanali olmali (kirmizida 0)
    middle = (32 * THUMB_SIZE + 32) * 4
    assert thumb[middle] == 0  # B
    assert thumb[middle + 2] == 255  # R


# ---- kalicilik ----


def test_depo_yeniden_acilinca_kayitlar_geri_gelir(tmp_path):
    first = ClipImageStore(tmp_path)
    slot = first.save_image(make_image(70, 50))
    png = first.read_png(slot)
    first.close()

    second = ClipImageStore(tmp_path)
    try:
        assert len(second.records()) == 1
        record = second.records()[0]
        assert (record.w, record.h) == (70, 50)
        assert second.read_png(record.slot) == png
    finally:
        second.close()


def test_ring_imlecleri_kalici(tmp_path):
    first = ClipImageStore(tmp_path)
    first.save_image(make_image(color=(3, 3, 3)))
    head, used = first.dat_head, first.dat_used
    first.close()

    second = ClipImageStore(tmp_path)
    try:
        assert (second.dat_head, second.dat_used) == (head, used)
    finally:
        second.close()


def test_bozuk_surum_yedeklenip_sifirlanir(tmp_path):
    (tmp_path / "clipimg.idx").write_bytes(struct.pack("<II", MAGIC, 99) + b"\0" * 100)
    (tmp_path / "clipimg.dat").write_bytes(b"")
    store = ClipImageStore(tmp_path)
    try:
        assert store.records() == []
        assert list(tmp_path.glob("clipimg.idx.surum-*"))  # eski dosya duruyor
    finally:
        store.close()


def test_rev_degisiklikte_artar(store):
    """Dialog bunu yoklayip listeyi tazeliyor."""
    before = store.rev
    store.save_image(make_image())
    assert store.rev > before


# ---- hash: AHK ile ayni algoritma mi ----


def test_crc32_ntdll_ile_ayni():
    """AHK `ntdll RtlComputeCrc32` kullaniyor, biz `zlib.crc32`.

    Ikisi de standart CRC-32 (IEEE) olmali; degilse AHK'nin yazdigi
    kayitlarda dedupe sessizce bozulurdu.
    """
    import ctypes

    data = b"cascade gorsel deposu testi 0123456789"
    buffer = ctypes.create_string_buffer(data, len(data))
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.RtlComputeCrc32.restype = ctypes.c_uint32
    expected = ntdll.RtlComputeCrc32(0, buffer, len(data))
    assert zlib.crc32(data) & 0xFFFFFFFF == expected
