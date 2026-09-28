"""Testler icin tek QApplication -- pencereler ekransiz surucude acilir."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _no_real_input(inputs) -> int:
    return len(inputs)


# Testler GERCEK klavye/fare olayi gondermesin -- oturum boyunca, monkeypatch
# degil: `QTimer.singleShot` ile ertelenen gonderimler (clip_ctl yapistirma)
# testin sahtesi geri alindiktan sonra baska bir testin processEvents'inde
# ateslenip on plandaki pencereye Ctrl+A / Ctrl+V / Enter basiyordu.
from keypilot.win32 import send  # noqa: E402

send._send = _no_real_input


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    return app
