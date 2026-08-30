"""Olay izleyici penceresi -- tepsi menusunden acilir.

probes/gui.py'deki sondajin uygulama icindeki hali. Fark: kendi hook'unu
KURMAZ. Uygulamada zaten calisan tek hook'un olaylari app.py tarafindan
buraya beslenir -- iki hook birden kurmak gereksiz ve kafa karistirici olurdu.

Pencere kapaliyken app.py besleme yapmaz, yani acik degilken maliyeti sifir.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cascade.core.keynames import key_name

MAX_ROWS = 400


class EventMonitor(QWidget):
    COLUMNS = ["t", "tus", "vk", "sc", "yon", "durum"]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("cascade - olay izleyici")
        self.resize(660, 460)
        self._t0: float | None = None
        self._count = 0
        self._swallowed = 0

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setFont(mono)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        self.stats = QLabel()
        self.stats.setFont(mono)

        clear = QPushButton("Temizle")
        clear.clicked.connect(self._clear)

        bar = QHBoxLayout()
        bar.addWidget(self.stats, 1)
        bar.addWidget(clear)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        layout.addLayout(bar)
        self._update_stats()

    def _clear(self) -> None:
        self.table.setRowCount(0)
        self._count = self._swallowed = 0
        self._t0 = None
        self._update_stats()

    def add(self, event, swallowed: bool) -> None:
        """app.py her klavye olayinda cagirir (pencere acikken)."""
        if self._t0 is None:
            self._t0 = event.t
        self._count += 1
        if swallowed:
            self._swallowed += 1

        cells = [
            f"{event.t - self._t0:7.2f}",
            key_name(event.vk, event.scan, event.extended),
            f"0x{event.vk:02X}",
            f"0x{event.scan:02X}",
            "down" if event.down else "up",
            "YUTULDU" if swallowed else "",
        ]
        if self.table.rowCount() >= MAX_ROWS:
            self.table.removeRow(0)
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if swallowed:
                item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, col, item)
        self.table.scrollToBottom()
        self._update_stats()

    def _update_stats(self) -> None:
        self.stats.setText(f"olay {self._count}    yutulan {self._swallowed}")
