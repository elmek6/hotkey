"""Olay izleyici penceresi -- tepsi menusunden acilir.

probes/gui.py'deki sondajin uygulama icindeki hali. Fark: kendi hook'unu
KURMAZ. Uygulamada zaten calisan tek hook'un olaylari app.py tarafindan
buraya beslenir -- iki hook birden kurmak gereksiz ve kafa karistirici olurdu.

Pencere kapaliyken app.py besleme yapmaz, yani acik degilken maliyeti sifir.

Kullanim:

    * **Cift tiklama**: satirin TAMAMINI panoya kopyalar (sekmeyle ayrilmis).
    * **Sag tiklama**: menuden hucreyi, satiri ya da butun listeyi kopyala.
    * **"Yeni ustte"**: yeni olaylar en uste dusar, liste asagi kaymaz --
      son basilan tusa bakarken listenin pesinden kosmak gerekmiyor.
    * **Duraklat**: listeye yeni olay eklenmez (hook calismaya devam eder,
      yalniz bu pencere yazmayi birakir) -- akan listeyi okumak icin.
    * Alt siradaki dugmeler sag tik menusuyle ayni kopyalama secenekleri.

Fare dugmeleri de listede: dispatch.py fare olayini `MouseSeen` olarak
buraya veriyor (hareket haric). `sc` sutununda fare olayinda imlec konumu
yazar -- fare olayinda tarama kodu yok.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
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

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(lambda _index: self._copy_row())

        # AHK'de liste hep eskiden yeniye akiyordu; son olaya bakarken
        # listenin dibini kovalamak gerekiyordu. Kutu isaretliyken yeni olay
        # EN USTE giriyor ve liste hic kaymiyor.
        self.newest_first = QCheckBox("Yeni ustte")
        self.newest_first.setToolTip("Yeni olaylar listenin basina eklensin")

        self.stats = QLabel()
        self.stats.setFont(mono)

        clear = QPushButton("Temizle")
        clear.clicked.connect(self._clear)

        # AHK'de liste akarken durdurmanin yolu yoktu; olayi okumak icin
        # pencereyi kapatmak gerekiyordu. Kutu isaretliyken hook calismaya
        # devam eder, yalniz bu tablo yazmayi birakir.
        self.paused = QCheckBox("Duraklat")
        self.paused.setToolTip("Listeye yeni olay eklenmesin")

        copy_row = QPushButton("Satiri kopyala")
        copy_row.clicked.connect(self._copy_row)
        copy_all = QPushButton("Tumunu kopyala")
        copy_all.clicked.connect(self._copy_all)

        bar = QHBoxLayout()
        bar.addWidget(self.stats, 1)
        bar.addWidget(self.paused)
        bar.addWidget(self.newest_first)
        bar.addWidget(copy_row)
        bar.addWidget(copy_all)
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
        """app.py her klavye/fare olayinda cagirir (pencere acikken)."""
        if self.paused.isChecked():
            return
        if self._t0 is None:
            self._t0 = event.t
        self._count += 1
        if swallowed:
            self._swallowed += 1

        cells = [
            f"{event.t - self._t0:7.2f}",
            key_name(event.vk, event.scan, event.extended),
            f"0x{event.vk:02X}",
            (
                f"{event.x},{event.y}"
                if getattr(event, "mouse", False)
                else f"0x{event.scan:02X}"
            ),
            "down" if event.down else "up",
            "YUTULDU" if swallowed else "",
        ]
        top = self.newest_first.isChecked()
        if self.table.rowCount() >= MAX_ROWS:
            self.table.removeRow(self.table.rowCount() - 1 if top else 0)
        row = 0 if top else self.table.rowCount()
        self.table.insertRow(row)
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if swallowed:
                item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, col, item)
        if not top:
            self.table.scrollToBottom()
        self._update_stats()

    # ---- kopyalama ----

    def _row_text(self, row: int) -> str:
        cells = [self.table.item(row, col) for col in range(self.table.columnCount())]
        return "\t".join(item.text().strip() if item else "" for item in cells)

    def _copy(self, text: str) -> None:
        if text:
            QGuiApplication.clipboard().setText(text)

    def _copy_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self._copy(self._row_text(row))

    def _copy_cell(self) -> None:
        item = self.table.currentItem()
        if item is not None:
            self._copy(item.text().strip())

    def _copy_all(self) -> None:
        rows = (self._row_text(row) for row in range(self.table.rowCount()))
        self._copy("\n".join(rows))

    def _context_menu(self, point) -> None:
        index = self.table.indexAt(point)
        if index.isValid():
            self.table.setCurrentCell(index.row(), index.column())
        menu = QMenu(self)
        menu.addAction("Hucreyi kopyala", self._copy_cell)
        menu.addAction("Satiri kopyala", self._copy_row)
        menu.addSeparator()
        menu.addAction("Tumunu kopyala", self._copy_all)
        menu.exec(self.table.viewport().mapToGlobal(point))

    def _update_stats(self) -> None:
        self.stats.setText(f"olay {self._count}    yutulan {self._swallowed}")
