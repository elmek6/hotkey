"""Pano gorselleri panelinin FLET surumu (fui/clip_images.py).

Flet calistirilmiyor: `_build` cagrilmadan panelin QT TARAFI suruluyor --
depoya dokunan her satir zaten ana thread'de kosuyor (`ask_qt`), Flet
tarafi yalnizca hazir demetleri ciziyor. Adim 9 (`test_fui_repository`)
ve adim 11'de (`test_fui_profiles`) kurulan kalibin ayni.

Qt surumunun davranisi da burada korunuyor: `ui/clip_images.py` ayakta,
ayni depoyu okuyor.
"""

from __future__ import annotations

import pytest
from PIL import Image

from keypilot.fui.clip_images import (
    ClipImagesPanel,
    Row,
    fit_scale,
    format_ts,
    info_text,
    preview_size,
    row_texts,
    stats_text,
    thumb_png,
)
from keypilot.imgstore import THUMB_SIZE, ClipImageStore


def resim(width: int = 120, height: int = 80, color=(200, 30, 40)) -> Image.Image:
    return Image.new("RGBA", (width, height), (*color, 255))


@pytest.fixture
def store(tmp_path):
    instance = ClipImageStore(tmp_path)
    yield instance
    instance.close()


@pytest.fixture
def panel(qapp, store):
    """Uc gorselli bir depo. En son kaydedilen listenin BASINDA olur."""
    for index in range(3):
        store.save_image(resim(100 + 10 * index, 60 + 10 * index, (10 * index, 40, 90)))
    instance = ClipImagesPanel(store)
    instance._reload()
    return instance


def _slotlar(panel: ClipImagesPanel) -> list[int]:
    return [row.slot for row in panel._rows]


# ---- saf metin yardimcilari ----


def test_format_ts_bos_zamani_bos_birakir():
    assert format_ts(0) == ""


def test_format_ts_bozuk_degerde_dusmez():
    """Bozuk zaman damgasi SATIRI dusurmemeli (Qt surumunde de ayni
    savunma var): `store._from_ahk_ms` sifira duser, biz de bir metin
    dondururuz."""
    assert isinstance(format_ts(-(10**18)), str)


def test_row_texts_tek_kayit(store):
    store.save_image(resim(120, 80))
    record = store.records()[0]
    _when, size, _created, repeats = row_texts(record)
    assert size.startswith("120x80")
    assert size.endswith("KB")
    assert repeats == "tek kayit"


def test_row_texts_tekrar_sayisini_yazar(store):
    """Ayni gorseli iki kez kaydetmek yeni kayit ACMAZ, sayaci artirir."""
    store.save_image(resim(120, 80))
    store.save_image(resim(120, 80))
    record = store.records()[0]
    assert record.count == 2
    assert row_texts(record)[3] == "2 kez"


def test_info_text_qt_bicimini_korur(store):
    store.save_image(resim(120, 80))
    record = store.records()[0]
    metin = info_text(record)
    assert metin.startswith("120x80 px")
    assert f"#{record.id}" in metin
    assert "ilk:" in metin
    # Tek kayitta "kopyalandi" YOK (Qt: yalniz count > 1).
    assert "kopyalandi" not in metin


def test_stats_text_qt_ile_ayni():
    assert stats_text(3, 2 * 1024 * 1024, 7) == "3 gorsel   ·   2.0 MB   ·   7 kopyalama"


# ---- sigdirma ve onizleme olcusu ----


def test_fit_scale_kucuk_gorseli_buyutmez():
    """Qt: `min(1.0, ratio)` -- sigan gorsel 1:1 kalir."""
    assert fit_scale(100, 50, 620, 498) == 1.0


def test_fit_scale_buyuk_gorseli_kutuya_sigdirir():
    assert fit_scale(1240, 498, 620, 498) == pytest.approx(0.5)


def test_fit_scale_sifir_olcude_dusmez():
    assert fit_scale(0, 0, 620, 498) == 1.0


def test_preview_size_sigdirilmis():
    assert preview_size(1240, 996, 620, 498, one_to_one=False) == (620, 498)


def test_preview_size_bire_bir():
    assert preview_size(1240, 996, 620, 498, one_to_one=True) == (1240, 996)


def test_preview_size_en_az_bir_piksel():
    """Cok ince bir gorselde yuvarlama sifira dusmemeli."""
    assert preview_size(4000, 1, 620, 498, one_to_one=False)[1] == 1


# ---- kucuk resim ----


def test_thumb_png_png_bayti_uretir(store):
    store.save_image(resim(120, 80))
    slot = store.records()[0].slot
    png = thumb_png(store.read_thumb(slot))
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_thumb_png_okunamayan_thumbda_none():
    assert thumb_png(None) is None


def test_satir_kucuk_resmi_onbellege_alir(panel, store):
    """Ikinci okuma diske DEGIL onbellege gitmeli: liste her tazelemede
    bastan kuruluyor."""
    row = panel._rows[0]
    assert row.thumb is not None
    onbellek = dict(panel._thumbs)
    panel._reload()
    assert panel._thumbs == onbellek
    assert panel._rows[0].thumb is row.thumb


def test_silinen_kaydin_kucuk_resmi_onbellekten_duser(panel, store):
    silinen = panel._rows[0].slot
    panel._delete_now((silinen,))
    assert all(slot != silinen for slot, _ident in panel._thumbs)


# ---- liste ----


def test_liste_en_yeni_onde(panel):
    """Depo son kullanima gore siraliyor; panel o sirayi bozmamali."""
    assert [row.when for row in panel._rows] == [
        format_ts(record.ts) for record in panel.store.records()
    ]
    assert len(panel._rows) == 3


def test_acilista_ilk_satir_secili(panel):
    assert panel._current == panel._rows[0].slot
    assert panel._preview is not None
    assert panel._info.startswith(f"{panel.store.records()[0].w}x")


def test_secim_slot_ile_tasinir(panel, store):
    """Yeni gorsel listenin basina girse de bakilan kayit degismemeli."""
    panel._select_now(panel._rows[2].slot)
    secili = panel._current
    store.save_image(resim(300, 200, (5, 5, 5)))
    panel._poll()
    assert len(panel._rows) == 4
    assert panel._current == secili


def test_poll_degisiklik_yoksa_okumaz(panel):
    onceki = panel._rows
    panel._poll()
    assert panel._rows is onceki


def test_secim_silinirse_ilk_satira_kayar(panel):
    silinen = panel._current
    assert silinen is not None
    panel._delete_now((silinen,))
    assert panel._current == panel._rows[0].slot
    assert panel._current != silinen


# ---- onizleme ----


def test_yeni_secim_sigdirilmis_baslar(panel):
    """Qt: `set_image` -> `reset_view`. Baska kayda gecince zoom sifirlanir."""
    panel._one_to_one = True
    panel._select_now(panel._rows[1].slot)
    assert panel._one_to_one is False


def test_onizleme_olculeri_kayittan_gelir(panel, store):
    slot = store.save_image(resim(640, 400, (9, 9, 9)))
    panel._reload()
    panel._select_now(slot)
    assert panel._preview is not None
    _png, width, height = panel._preview
    assert (width, height) == (640, 400)


# ---- isaretleme ve silme ----


def test_isaretsizken_hedef_secili_satir(panel):
    assert panel._targets() == (panel._current,)


def test_isaretliler_hedef_olur(panel):
    panel._on_mark(panel._rows[1].slot, True)
    panel._on_mark(panel._rows[2].slot, True)
    assert set(panel._targets()) == {panel._rows[1].slot, panel._rows[2].slot}


def test_isaret_kaldirilabilir(panel):
    slot = panel._rows[1].slot
    panel._on_mark(slot, True)
    panel._on_mark(slot, False)
    assert panel._targets() == (panel._current,)


def test_bos_listede_hedef_yok(panel):
    panel._delete_now(tuple(_slotlar(panel)))
    assert panel._rows == ()
    assert panel._targets() == ()


def test_toplu_silme_depodan_siler(panel, store):
    hedefler = (panel._rows[0].slot, panel._rows[1].slot)
    panel._delete_now(hedefler)
    assert len(store.records()) == 1
    assert _slotlar(panel) == [record.slot for record in store.records()]


def test_silme_isaretleri_temizler(panel):
    panel._on_mark(panel._rows[1].slot, True)
    panel._delete_now(panel._targets())
    assert panel._marked == frozenset()


def test_silinen_slot_isaretli_kalmaz(panel):
    """Isaret Flet tarafinda konuyor; kayit aradan giderse dusmeli."""
    panel._on_mark(panel._rows[1].slot, True)
    panel._delete_now((panel._rows[1].slot,))
    panel._reload()
    assert panel._marked == frozenset()


def test_sayac_silme_sonrasi_tazelenir(panel):
    panel._delete_now((panel._rows[0].slot,))
    assert panel._stats.startswith("2 gorsel")


# ---- disari acilan yuz (clip_ctl.py bunlara bakiyor) ----


def test_kopyalama_sinyali_olcuyu_yazar(panel, qapp):
    """`clip_ctl._on_image_copied` bu metni ipucunda gosteriyor."""
    gelen: list[str] = []
    panel.copied.connect(gelen.append)
    row = panel._rows[0]
    record = next(r for r in panel.store.records() if r.slot == row.slot)
    panel._copy_now(row.slot)
    assert gelen == [f"{record.w}x{record.h}"]


def test_kopyalama_son_kullanimi_tazeler(panel):
    """AHK: panoya alinan kayit listenin basina gecer."""
    hedef = panel._rows[2].slot
    panel._copy_now(hedef)
    panel._reload()
    assert panel._rows[0].slot == hedef


def test_okunamayan_kayitta_bos_sinyal(panel):
    gelen: list[str] = []
    panel.copied.connect(gelen.append)
    panel._copy_now(499)  # bos slot
    assert gelen == [""]


def test_disa_aktarma_dosyayi_yazar(panel, tmp_path, monkeypatch):
    hedef = tmp_path / "disari.png"
    monkeypatch.setattr(
        "keypilot.fui.clip_images.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(hedef), "PNG (*.png)"),
    )
    gelen: list[str] = []
    panel.copied.connect(gelen.append)
    panel._export_now(panel._rows[0].slot)
    assert hedef.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert gelen == [f"kaydedildi: {hedef}"]


def test_disa_aktarma_iptal_edilirse_yazmaz(panel, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "keypilot.fui.clip_images.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    gelen: list[str] = []
    panel.copied.connect(gelen.append)
    panel._export_now(panel._rows[0].slot)
    assert gelen == []
    assert not list(tmp_path.glob("*.png"))


def test_uzantisiz_ad_png_olur(panel, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "keypilot.fui.clip_images.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "uzantisiz"), "PNG (*.png)"),
    )
    panel._export_now(panel._rows[0].slot)
    assert (tmp_path / "uzantisiz.png").exists()


# ---- satirin kendisi ----


def test_row_kucuk_resim_olcusu_sabit(panel):
    """Thumb depoda 64x64 -- satir yuksekligi ona gore."""
    row = panel._rows[0]
    assert isinstance(row, Row)
    assert len(panel.store.read_thumb(row.slot)) == THUMB_SIZE * THUMB_SIZE * 4
