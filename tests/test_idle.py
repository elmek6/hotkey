"""Ekran koruyucu butcesi ve Outlook simge durumu."""

from keypilot.idle import (
    WORK_MINUTES,
    clock_label,
    minutes_for,
    should_open_outlook,
    startup_minutes,
    ticks_for,
)
from keypilot.win32 import shell


def test_dakika_saate_cevrilir():
    assert clock_label(0) == "0:00"
    assert clock_label(90) == "1:30"
    assert clock_label(480) == "8:00"
    assert clock_label(7 * 60 + 50) == "7:50"


def test_tur_yuvarlamasi():
    assert ticks_for(0) == 0
    assert ticks_for(90) == 18
    assert minutes_for(18) == 90
    assert ticks_for(WORK_MINUTES) == 96
    assert minutes_for(96) == WORK_MINUTES


def test_is_acilisi_8_saat_ve_outlook():
    assert startup_minutes("work") == WORK_MINUTES
    assert startup_minutes("home") == 0
    assert should_open_outlook("work") is True
    assert should_open_outlook("home") is False


def test_outlook_simge_durumunda_shellexecute(monkeypatch):
    calls = []

    def fake(_hwnd, _op, file, _params, _cwd, show):
        calls.append((file, show))
        return 42

    monkeypatch.setattr(shell, "process_exists", lambda _name: False)
    monkeypatch.setattr(shell.shell32, "ShellExecuteW", fake)
    assert shell.open_minimized("outlook.exe") is True
    assert calls == [("outlook.exe", shell.SW_SHOWMINNOACTIVE)]


def test_outlook_basarisiz_kod(monkeypatch):
    monkeypatch.setattr(shell, "process_exists", lambda _name: False)
    monkeypatch.setattr(shell.shell32, "ShellExecuteW", lambda *_a: 2)
    assert shell.open_minimized("outlook.exe") is False


def test_outlook_zaten_aciksa_tekrar_acilmaz(monkeypatch):
    calls = []
    monkeypatch.setattr(shell, "process_exists", lambda name: name.lower() == "outlook.exe")
    monkeypatch.setattr(
        shell.shell32, "ShellExecuteW", lambda *_a: calls.append(_a) or 42
    )
    assert shell.open_minimized("outlook.exe") is True
    assert calls == []


def test_yeni_outlook_aciksa_klasik_tekrar_acilmaz(monkeypatch):
    calls = []
    monkeypatch.setattr(shell, "process_exists", lambda name: name.lower() == "olk.exe")
    monkeypatch.setattr(
        shell.shell32, "ShellExecuteW", lambda *_a: calls.append(_a) or 42
    )
    assert shell.open_minimized("outlook.exe") is True
    assert calls == []


def test_dialog_dakika_etiketi_gunceller(qapp):
    from keypilot.ui.idle import IdleDialog

    dialog = IdleDialog()
    dialog.show_for(470)
    assert "7:50" in dialog._label.text()
    dialog._edit.setText("90")
    assert "1:30" in dialog._label.text()
    got: list[int] = []
    dialog.accepted_minutes.connect(got.append)
    dialog._accept()
    assert got == [90]
