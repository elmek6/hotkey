"""Tepsi rozeti: KIRMIZI pahali bir renktir.

Once her WARNING+ kaydi simgeyi kirmiziya boyuyordu ve en cok goruleni
"cift tiklama yutuldu" idi -- kendi log satiri bile "program hatasi degil"
diyen bir kayit. Simgeye bakan "keypilot coktu mu" diye irkiliyordu.
"""

import pathlib

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


def test_ipucu_UC_SATIR_surum_profil_ve_tiklamalar(qapp):
    """Ilk satir kimlik, altinda tek/cift tiklamanin O ANDAKI karsiligi."""
    t = tray.Tray("1.2.0+0908_0907*", lambda: None, lambda: None, lambda: None,
                  profile="work")
    # tek tik varsayilanda "hicbir sey": ipucunda da yer kaplamiyor
    assert t.toolTip().splitlines() == ["KeyPilot 1.2.0 - work", "dbClick = Pause/Play"]

    tray.SINGLE_CLICK.set("restart")
    try:
        # AYAR DEGISINCE ipucu da degisir -- yoksa yanlis bilgi asili kalir
        tip = t.toolTip()
    finally:
        tray.SINGLE_CLICK.reset()
    assert tip.splitlines() == [
        "KeyPilot 1.2.0 - work",
        "click = Reload",
        "dbClick = Pause/Play",
    ]
    assert len(tip) <= tray.TOOLTIP_LIMIT
    # yapim damgasi ipucuna girmiyor: 16 karakteri tek basina yerdi
    assert "0908_0907" not in tip


def test_ipucu_SINIRI_asmaz_once_durumu_dusurur(qapp):
    """Kabuk fazlasini sessizce kesiyor; kesilecek olan simgenin RENGIYLE
    zaten belli olan durum olsun, tiklamalar degil."""
    t = tray.Tray("1.2.0", lambda: None, lambda: None, lambda: None,
                  profile="cok-uzun-bir-klasor-adi")
    t.set_dev(True)
    t.set_paused(True)
    t.set_error_count(9, severe=4)
    tip = t.toolTip()
    assert len(tip) <= tray.TOOLTIP_LIMIT
    assert "dbClick = " in tip  # tiklama bilgisi hayatta


def test_isaretli_simgede_ipucu_GERCEK_eylemi_yazar(qapp):
    """Simge kirmizi/sariyken tiklama ayardan bagimsiz log penceresini acar."""
    t = tray.Tray("1.2.0", lambda: None, lambda: None, lambda: None)
    t.set_error_count(1, severe=1)
    assert "dbClick = Show log" in t.toolTip()
    t.set_error_count(0)
    assert "dbClick = Pause/Play" in t.toolTip()


def test_tek_tiklama_varsayilanda_hicbir_sey_yapmaz(qapp):
    """Tek tik cift tiklamanin ilk yarisi: varsayilan olarak sessiz."""
    from PySide6.QtWidgets import QSystemTrayIcon

    calls = []
    t = tray.Tray(
        "test",
        lambda: None,
        lambda: None,
        lambda: None,
        on_toggle_pause=lambda: calls.append("pause"),
        on_settings=lambda: calls.append("settings"),
    )
    t._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert calls == []

    tray.SINGLE_CLICK.set("settings")
    try:
        t._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
        assert calls == ["settings"]
        # Cift tiklama kendi ayarindan: iki ayar birbirine karismiyor.
        t._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        assert calls == ["settings", "pause"]
    finally:
        tray.SINGLE_CLICK.reset()


def test_isaretli_simgede_tek_tik_da_hatalari_acar(qapp):
    from PySide6.QtWidgets import QSystemTrayIcon

    calls = []
    t = tray.Tray(
        "test",
        lambda: None,
        lambda: None,
        lambda: None,
        on_toggle_pause=lambda: calls.append("pause"),
        on_show_errors=lambda: calls.append("errors"),
    )
    t.set_error_count(1, severe=1)
    tray.SINGLE_CLICK.set("pause")
    try:
        t._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
        assert calls == ["errors"]
    finally:
        tray.SINGLE_CLICK.reset()


def test_ipucunu_YALNIZ_tepsi_yazar():
    """Regresyon: `app.on_start` ipucunu sonradan yaziyordu.

    `KeyPilot {surum} - {profil}` metni tepsinin kendi ipucunun (surum +
    profil + tiklamalarin karsiligi) UZERINE biniyordu; ekranda hep o eski
    satir kaliyor, tepside yapilan her degisiklik gorunmez oluyordu. Iki
    kez bu tuzaga dusuldu -- ipucunun tek sahibi ui/tray.py.
    """
    paket = pathlib.Path(__file__).resolve().parent.parent / "keypilot"
    yazanlar = [
        path.relative_to(paket).as_posix()
        for path in paket.rglob("*.py")
        if "tray.setToolTip" in path.read_text(encoding="utf-8")
    ]
    assert yazanlar == []
