"""Gelismis OCR sonucu penceresi -- F14 secimi + "OCR+".

Basit OCR metni dogrudan panoya koyar; bu pencere ise metni GOSTERIR:
kullanici okur, gerekirse duzeltir, istedigi parcayi ya da tumunu kopyalar.

TODO(AHK): screen_ocr.ahk'nin kelime kelime secilebilen overlay'i port
edilmedi -- oradaki 1300 satirin cogu o overlay'di. Gerekirse buraya gelir.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class OcrView(QWidget):
    """Tek ornek app.py'de tutulur; her sonucta ayni pencere yenilenir."""

    #: "Kopyala" -- panoya yazmayi app.py yapar (pano gecmisine de dussun)
    copy_text = Signal(str)

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowTitle("\U0001f9e0 OCR sonucu")

        self._info = QLabel("")
        self._edit = QPlainTextEdit()
        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._edit.setFont(mono)

        copy_button = QPushButton("\U0001f4cb Tumunu kopyala")
        copy_button.clicked.connect(lambda: self.copy_text.emit(self._edit.toPlainText()))
        close_button = QPushButton("Kapat")
        close_button.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addWidget(self._info, 1)
        buttons.addWidget(copy_button)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._edit, 1)
        layout.addLayout(buttons)
        self.resize(520, 380)

    def show_text(self, text: str) -> None:
        self._edit.setPlainText(text)
        lines = text.count("\n") + 1 if text else 0
        self._info.setText(f"{len(text)} karakter, {lines} satir")
        self.show()
        self.raise_()
        self.activateWindow()
