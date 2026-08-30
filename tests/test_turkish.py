"""Turkce eklentisi -- turkish_layout_addon.ahk kurallari (saf katman)."""

from cascade.core.turkish import TurkishLayout


def _tr(layout: int = 1) -> TurkishLayout:
    box = TurkishLayout()
    box.toggle()
    box.layout = layout
    return box


def test_kapaliyken_hicbir_tusa_dokunulmaz():
    box = TurkishLayout()
    assert box.feed("c", True, 0.0, False) == (False, [])


def test_dizilim1_kisa_basim_harfin_kendisi():
    """AHK: once harf gonderilir; 400 ms'den kisa basimda oylece kalir."""
    box = _tr(1)
    assert box.feed("c", True, 0.0, False) == (True, ["send_text:c"])
    assert box.feed("c", False, 0.10, False) == (True, [])


def test_dizilim1_uzun_basim_geri_alip_turkce_yazar():
    box = _tr(1)
    box.feed("s", True, 0.0, False)
    swallow, actions = box.feed("s", False, 0.5, False)
    assert swallow is True
    assert actions == ["send_key:Backspace", "send_text:ş"]


def test_dizilim1_buyuk_harf_basim_anindaki_duruma_gore():
    """Shift basim aninda okunur; birakirken birakilmis olabilir."""
    box = _tr(1)
    assert box.feed("g", True, 0.0, True) == (True, ["send_text:G"])
    assert box.feed("g", False, 0.5, False)[1][1] == "send_text:Ğ"


def test_dizilim1_tus_tekrari_harfi_bir_kez_yazar():
    """Windows basili tusu tekrar tekrar gonderir; harf cogalmamali."""
    box = _tr(1)
    box.feed("c", True, 0.0, False)
    assert box.feed("c", True, 0.05, False) == (True, [])
    assert box.feed("c", True, 0.10, False) == (True, [])


def test_dizilim1_haritada_olmayan_tus_serbest():
    box = _tr(1)
    assert box.feed("k", True, 0.0, False) == (False, [])


def test_dizilim2_dogrudan_remap():
    box = _tr(2)
    assert box.feed(".", True, 0.0, False) == (True, ["send_text:ç"])
    assert box.feed(".", True, 0.0, True) == (True, ["send_text:Ç"])
    assert box.feed(".", False, 0.1, False) == (True, [])  # birakma da yutulur
    assert box.feed("y", True, 0.2, False) == (True, ["send_text:z"])


def test_dizilim_degistirmek_bekleyen_basimi_temizler():
    box = _tr(1)
    box.feed("c", True, 0.0, False)
    assert box.switch_layout() == 2
    assert box.feed("c", False, 0.9, False) == (False, [])
