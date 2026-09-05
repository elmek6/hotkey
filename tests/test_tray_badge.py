"""Tepsi rozeti: KIRMIZI pahali bir renktir.

Once her WARNING+ kaydi simgeyi kirmiziya boyuyordu ve en cok goruleni
"cift tiklama yutuldu" idi -- kendi log satiri bile "program hatasi degil"
diyen bir kayit. Simgeye bakan "keypilot coktu mu" diye irkiliyordu.
"""

from keypilot.ui import tray


def _zemin(**kw):
    """Simgenin sol ust kosesindeki zemin rengi."""
    image = tray.make_icon(size=64, **kw).pixmap(64, 64).toImage()
    return image.pixelColor(4, 32)


def test_yalniz_uyari_SARI_kalir():
    assert _zemin(warn=True) == tray.WARN_BACKGROUND


def test_gercek_hata_KIRMIZI_yakar():
    assert _zemin(warn=True, error=True) == tray.ERROR_BACKGROUND


def test_duraklatma_hepsinden_oncelikli():
    assert _zemin(paused=True, error=True) == tray.PAUSED_BACKGROUND


def test_set_error_count_uyariyi_kirmizi_saymaz(qapp):
    t = tray.Tray("test", lambda: None, lambda: None, lambda: None)
    t.set_error_count(2, severe=0)
    assert _zemin(warn=True) == tray.WARN_BACKGROUND
    assert t.severe_count == 0
    assert "2 warning" in t.toolTip()

    t.set_error_count(3, severe=1)
    assert t.severe_count == 1
    assert "1 error" in t.toolTip() and "2 warning" in t.toolTip()
