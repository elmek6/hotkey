from keypilot.core.hotkey import HotkeyTable, parse_hotkey
from keypilot.core.keynames import VK_WHEEL_DOWN, VK_WHEEL_UP, register_name
from keypilot.core.mouse import (
    WM_MBUTTONDOWN,
    WM_MOUSEMOVE,
    WM_MOUSEWHEEL,
    WM_XBUTTONDOWN,
    WM_XBUTTONUP,
    mouse_key,
)

LCTRL, RCTRL, LSHIFT, LALT = 0xA2, 0xA3, 0xA0, 0xA4
F13, F14, CARET = 0x7C, 0x7D, 0xDC
Z, K = 0x5A, 0x4B
XBUTTON1, MBUTTON = 0x05, 0x04


# ---- ayristirma ----


def test_caret_sozdizimi_ahk_ile_ayni():
    hotkey = parse_hotkey("^!k")
    assert hotkey.vk == K
    assert hotkey.text == "Ctrl+Alt+K"
    assert hotkey.matches(K, (LCTRL, LALT))


def test_arti_yazimi_da_kabul_edilir():
    assert parse_hotkey("Ctrl+Alt+K") == parse_hotkey("^!k")


def test_sol_sag_ayrimi():
    """AHK: <^z yalniz sol Ctrl."""
    hotkey = parse_hotkey("<^z")
    assert hotkey.matches(Z, (LCTRL,))
    assert not hotkey.matches(Z, (RCTRL,))
    assert parse_hotkey("^z").matches(Z, (RCTRL,))  # yansiz tanim ikisini de alir


def test_fazladan_modifier_eslesmeyi_bozar():
    assert not parse_hotkey("^z").matches(Z, (LCTRL, LSHIFT))


def test_yildiz_oneki_fazladan_modifiere_izin_verir():
    """AHK: *^z"""
    assert parse_hotkey("*^z").matches(Z, (LCTRL, LSHIFT))


def test_modifiersiz_tanim_modifier_varken_tetiklenmez():
    assert parse_hotkey("z").matches(Z, ())
    assert not parse_hotkey("z").matches(Z, (LCTRL,))


def test_fare_tusu_da_ayni_dizgide_yazilir():
    hotkey = parse_hotkey("XButton1")
    assert hotkey.vk == XBUTTON1
    assert hotkey.matches(XBUTTON1)


# ---- onek (prefix) kombosu: AHK'deki `A & B::` ----


def test_onek_kombosu_ayristirilir():
    """AHK: F13 & F14::  --  fare yan tuslari kendi arasinda."""
    hotkey = parse_hotkey("F13 & F14")
    assert hotkey.vk == F14
    assert hotkey.prefix == F13
    assert hotkey.text == "F13 & F14"


def test_onek_kombosu_yalniz_onek_basiliyken_eslesir():
    hotkey = parse_hotkey("F13 & F14")
    assert hotkey.matches(F14, (), F13)
    assert not hotkey.matches(F14, (), None)
    assert not hotkey.matches(F14, (), F14)


def test_oneksiz_tanim_onek_basiliyken_tetiklenmez():
    """`^ & 1` calisirken sade `1` tanimi patlamamali."""
    assert parse_hotkey("1").matches(0x31, (), None)
    assert not parse_hotkey("1").matches(0x31, (), CARET)


def test_calisma_aninda_ad_kaydi():
    """`^` tusunun VK'si duzene bagli; ogrenilince adlandirilip kullanilir."""
    register_name(CARET, "Caret")
    hotkey = parse_hotkey("Caret & 1")
    assert hotkey.prefix == CARET
    assert hotkey.vk == 0x31
    assert hotkey.text == "Caret & 1"


def test_tekerlek_yonu_onek_kombosunda_kullanilabilir():
    """AHK: ~F13 & WheelUp -- fare yan tusu basiliyken tekerlek."""
    hotkey = parse_hotkey("F13 & WheelUp")
    assert hotkey.vk == VK_WHEEL_UP
    assert hotkey.prefix == F13


# ---- tablo ----


def test_onek_tuslari_listelenir():
    """dispatch.py bu listeye bakip hangi tusu keydown'da yutacagini biliyor."""
    table = HotkeyTable().add("F13 & F14", "a").add("F14", "b")
    assert table.prefixes == frozenset({F13})


def test_onekli_tanim_oneksizden_once_denenir():
    table = HotkeyTable().add("F14", "yalniz").add("F13 & F14", "kombo")
    assert table.match(F14, (), F13).action == "kombo"
    assert table.match(F14, (), None).action == "yalniz"


def test_en_ozgul_tanim_kazanir():
    """^+z tanimi ^z tanimini golgede birakmamali (AHK'deki gibi)."""
    table = HotkeyTable().add("^z", "a").add("^+z", "b")
    assert table.match(Z, (LCTRL, LSHIFT)).action == "b"
    assert table.match(Z, (LCTRL,)).action == "a"


def test_sahip_olmadigi_tusa_dokunmaz():
    table = HotkeyTable().add("^z", "a")
    assert not table.owns(K)
    assert table.match(K, (LCTRL,)) is None
    assert table.match(Z, ()) is None  # modifier yoksa eslesme yok


def test_tips_yalniz_aciklamali_tanimlari_verir():
    table = HotkeyTable().add("^z", "a", "geri al").add("^y", "b")
    assert table.tips == (("Ctrl+Z", "geri al"),)


# ---- fare olayi cevirisi ----


def test_xbutton_numarasi_vkye_cevrilir():
    assert mouse_key(WM_XBUTTONDOWN, 1) == (0x05, True)
    assert mouse_key(WM_XBUTTONDOWN, 2) == (0x06, True)
    assert mouse_key(WM_XBUTTONUP, 2) == (0x06, False)


def test_orta_dugme_ve_tekerlek():
    assert mouse_key(WM_MBUTTONDOWN, 0) == (MBUTTON, True)
    assert mouse_key(WM_MOUSEWHEEL, 120) == (VK_WHEEL_UP, True)
    assert mouse_key(WM_MOUSEWHEEL, -120) == (VK_WHEEL_DOWN, True)


def test_ilgilenmedigimiz_mesaj_none_doner():
    assert mouse_key(WM_MOUSEMOVE, 0) is None


def test_tek_basina_tilde_tusu_yutmaz():
    """AHK `~MButton`: eylem calisir, tus uygulamaya da gider."""
    hotkey = parse_hotkey("~MButton")
    assert hotkey.passthrough is True
    assert hotkey.prefix is None
    assert hotkey.text == "~MButton"
