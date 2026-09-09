"""ODAK KOPRUSU (adim 15) -- `win32/window.py` `force_focus`.

Adim 14'un olcumu (senaryo H) sunu gosterdi: Flet penceresi odagi
kendisi ALAMIYOR (`flet.exe` ayri bir surec, Windows odak calmayi
kisitliyor) ama BIZIM surecimiz ona verebiliyor. `array_filter` ve
`quick_panel` bunu kullanacak.

Burada olculen sey odagin gercekten degistigi DEGIL -- o `probes/focus.py`nin
isi ve ekran ister. Burada surulen sey KARAR MANTIGI: fonksiyon sonucu
`GetForegroundWindow` ile dogruluyor mu, kucultulmus pencereyi geri
aciyor mu, bosuna bekliyor mu. Win32 cagrilari yamaniyor.
"""

from __future__ import annotations

import pytest

from keypilot.win32 import window as win

HWND = 0x1234


@pytest.fixture
def sahte(monkeypatch):
    """Win32 tarafini yamalar; testin verdigi senaryoyu oynatir."""

    durum = {"onde": 0, "cagri": [], "iconic": False, "uyku": 0.0}

    def foreground():
        return durum["onde"]

    def set_foreground(hwnd):
        durum["cagri"].append("SetForegroundWindow")
        return False

    monkeypatch.setattr(win, "foreground_window", foreground)
    monkeypatch.setattr(win, "is_window", lambda hwnd: bool(hwnd))
    monkeypatch.setattr(win.user32, "SetForegroundWindow", set_foreground)
    monkeypatch.setattr(win.user32, "GetForegroundWindow", lambda: durum["onde"])
    monkeypatch.setattr(win.user32, "GetWindowThreadProcessId", lambda *_: 999)
    monkeypatch.setattr(win.user32, "AttachThreadInput", lambda *_: True)
    monkeypatch.setattr(
        win.user32, "BringWindowToTop",
        lambda hwnd: durum["cagri"].append("BringWindowToTop"),
    )
    monkeypatch.setattr(win.user32, "IsIconic", lambda hwnd: durum["iconic"])
    monkeypatch.setattr(
        win.user32, "ShowWindow",
        lambda hwnd, cmd: durum["cagri"].append(f"ShowWindow({cmd})"),
    )

    def uyu(saniye):
        durum["uyku"] += saniye

    monkeypatch.setattr(win.time, "sleep", uyu)
    return durum


def test_odak_alinirsa_TRUE_ve_HIC_BEKLEMIYOR(sahte):
    """Ilk atis tuttuysa bekleme YOK: bu cagri Qt'nin ana thread'inde
    kosuyor, bosuna beklemek tepsiyi ve tus kuyrugunu durdururdu."""
    sahte["onde"] = HWND
    assert win.force_focus(HWND) is True
    assert sahte["uyku"] == 0.0


def test_odak_ALINAMAZSA_FALSE(sahte):
    """`SetForegroundWindow` izin verilmeyince `True` donup pencereyi
    gorev cubugunda yanip soner birakabiliyor. Tek olcut odagin nerede
    oldugu."""
    sahte["onde"] = 0xBEEF
    assert win.force_focus(HWND, tries=2) is False
    assert sahte["cagri"].count("SetForegroundWindow") == 4  # 2 deneme x 2 atis


def test_beklemeden_denenebiliyor(sahte):
    sahte["onde"] = 0xBEEF
    assert win.force_focus(HWND, tries=3, settle=0) is False
    assert sahte["uyku"] == 0.0


def test_kucultulmus_pencere_GERI_ACILIYOR(sahte):
    sahte["onde"] = HWND
    sahte["iconic"] = True
    assert win.force_focus(HWND) is True
    assert f"ShowWindow({win.SW_RESTORE})" in sahte["cagri"]


def test_olmayan_pencere_FALSE(sahte):
    assert win.force_focus(0) is False
    assert sahte["cagri"] == []
