"""Filtreli liste penceresi -- array_filter.ahk'nin GUI bolumu.

AHK'deki duzen aynen korundu, cunku kas hafizasi orada:

    [ arama kutusu ] [Case] [ mod v ]
    +--------------------------------+
    | F#  Isim   Icerik              |   12 satir
    +--------------------------------+
    [x] Fare ile onizleme
    +--------------------------------+
    | onizleme (salt okunur)         |
    +--------------------------------+

Eslestirme burada DEGIL, core/filter.py'de. Bu dosya yalnizca sorguyu kurar
ve sonucu cizer.

AHK'de zor olup Qt'de bedava gelen uc sey -- bilerek AHK'yi taklit etmedik:

* **Yon tuslari.** AHK global `Hotkey("Up", ...)` kuruyor ve pencere
  kapaninca kapatmayi unutursa tum sistemde Up tusu kaciriliyordu. Burada
  arama kutusuna bir olay suzgeci: Up/Down/PageUp/PageDown listeye
  iletilir, odak kutuda kalir. Pencere kapaninca suzgec de gider.
* **Odak bekcisi.** AHK 50 ms'de bir `WinActive` yokluyordu (`WatchDog`).
  Qt bunu olay olarak veriyor: pencere odagi kaybedince kapanir.
* **F# etiketleri.** AHK `LVM_GETTOPINDEX` mesajini elle gonderiyordu;
  Qt'de `rowAt(0)` ayni seyi soyluyor.

Secim `chosen` sinyaliyle disari verilir; panoya yazma ve yapistirma isi
cagirana ait (app.py) -- bu pencere pano nedir bilmez, sadece liste
gosterir. AHK'de `sendText` sinifin icindeydi ve dolayisiyla pencere yalniz
pano icin kullanilabiliyordu.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cascade.core.filter import FilterItem, FilterMode, Query, apply

VISIBLE_ROWS = 12  # AHK: r12
PREVIEW_LIMIT = 120  # AHK: SubStr(content, 1, 120)
FKEY_COUNT = 12  # F1..F12 -> gorunen satirlar


class ArrayFilter(QWidget):
    """Filtreli liste. `chosen` secilen kaydin tam metnini verir."""

    chosen = Signal(str)
    closed = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._items: tuple[FilterItem, ...] = ()
        self._results: tuple[FilterItem, ...] = ()
        self._title = "Liste"
        self._top_row = -1

        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)

        self.search = QLineEdit()
        self.search.setPlaceholderText("ara...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refresh)
        self.search.installEventFilter(self)

        self.case = QCheckBox("Case")
        self.case.toggled.connect(self._refresh)

        self.mode = QComboBox()
        self.mode.addItems(["Metin", "Joker *?", "RegExp"])
        self.mode.currentIndexChanged.connect(self._refresh)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["F#", "Isim", "Icerik"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(True)
        self.table.setFont(mono)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 44)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.doubleClicked.connect(lambda _index: self._accept())
        self.table.verticalScrollBar().valueChanged.connect(self._update_fkeys)

        self.hover = QCheckBox("Fare ile onizleme")
        self.hover.setChecked(True)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(mono)
        self.preview.setMinimumHeight(150)

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.case)
        top.addWidget(self.mode)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.hover)
        layout.addWidget(self.preview)

        # AHK: SelectByFKey -- F1..F12 GORUNEN satirlari secer, mutlak
        # satiri degil. Liste kaydiginda etiketler de kayar.
        for index in range(1, FKEY_COUNT + 1):
            shortcut = QShortcut(QKeySequence(f"F{index}"), self)
            shortcut.activated.connect(lambda n=index: self._select_visible(n))

        for sequence in ("Return", "Enter"):
            QShortcut(QKeySequence(sequence), self).activated.connect(self._accept)

        self.resize(900, 560)

    # ---- disari ----

    def show_items(self, items: tuple[FilterItem, ...], title: str) -> None:
        """AHK: Show(arrayData, title). Arama kutusu her acilista temizlenir,
        mod ve Case kutusu korunur (AHK'de de `static lastMode` boyleydi)."""
        self._items = items
        self._title = title
        self.search.clear()  # _refresh'i kendisi tetikler
        self._refresh()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

    # ---- filtreleme ----

    def _query(self) -> Query:
        return Query(
            text=self.search.text(),
            mode=FilterMode(self.mode.currentIndex() + 1),
            case_sensitive=self.case.isChecked(),
        )

    def _refresh(self) -> None:
        result = apply(self._items, self._query())
        self._results = result.items
        self._top_row = -1

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(self._results))
        for row, item in enumerate(self._results):
            self.table.setItem(row, 0, QTableWidgetItem(""))
            self.table.setItem(row, 1, QTableWidgetItem(item.name))
            self.table.setItem(row, 2, QTableWidgetItem(_one_line(item.content)))
        self.table.setUpdatesEnabled(True)

        if self._results:
            # selectRow tek basina yetmez: satir 0 zaten seciliyse
            # itemSelectionChanged atmaz ve onizleme onceki kayitta kalir.
            # AHK'de de Modify(1, "Select Focus")'un hemen ardindan
            # UpdatePreviewContent(1) cagriliyordu.
            self.table.selectRow(0)
            self._preview_row(0)
        else:
            self.preview.setPlainText("")
        self._update_fkeys()

        suffix = " (desen?)" if result.pattern_error else f" ({len(self._results)})"
        self.setWindowTitle(self._title + suffix)

    def _update_fkeys(self) -> None:
        """Gorunen ilk 12 satira F1..F12 yazar. AHK: UpdateVisibleLabels."""
        top = self.table.rowAt(0)
        if top < 0:
            top = 0
        if top == self._top_row:
            return
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 0)
            if cell is None:
                continue
            offset = row - top
            cell.setText(f"F{offset + 1}" if 0 <= offset < FKEY_COUNT else "")
        self._top_row = top

    # ---- secim ----

    def _on_selection(self) -> None:
        self._preview_row(self.table.currentRow())

    def _preview_row(self, row: int) -> None:
        if 0 <= row < len(self._results):
            self.preview.setPlainText(self._results[row].content)

    def _select_visible(self, number: int) -> None:
        """F1..F12: ust satirdan sayarak. AHK: topIndex + fKeyIndex."""
        top = max(self.table.rowAt(0), 0)
        row = top + number - 1
        if 0 <= row < len(self._results):
            self.table.selectRow(row)
            self._accept()

    def _accept(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self._results)):
            return
        text = self._results[row].content
        self.close()
        self.chosen.emit(text)

    # ---- olaylar ----

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Arama kutusundaki yon tuslarini listeye iletir; fare gezinmesinde
        onizlemeyi tazeler."""
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (
                Qt.Key.Key_Up,
                Qt.Key.Key_Down,
                Qt.Key.Key_PageUp,
                Qt.Key.Key_PageDown,
            ):
                self.table.keyPressEvent(event)
                return True
        elif watched is self.table.viewport() and event.type() == QEvent.Type.MouseMove:
            if self.hover.isChecked():
                row = self.table.rowAt(int(event.position().y()))
                if row >= 0:
                    self._preview_row(row)
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Esc: once aramayi temizler, ikinci basista kapatir (AHK ile ayni)."""
        if event.key() == Qt.Key.Key_Escape:
            if self.search.text():
                self.search.clear()
            else:
                self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        """Kapanisi app.py'ye bildir: pencere acikken kisayollar susmali,
        yoksa arama kutusuna yazarken `Caret & 1` tetiklenirdi."""
        super().closeEvent(event)
        self.closed.emit()

    def changeEvent(self, event: QEvent) -> None:
        """AHK'nin WatchDog'u: odak baska pencereye gecince kapan.

        AHK 50 ms'de bir yokluyordu; Qt olayi dogrudan veriyor."""
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self.close()
        super().changeEvent(event)


def _one_line(text: str, limit: int = PREVIEW_LIMIT) -> str:
    """Listedeki tek satirlik ozet. AHK: SubStr(..., 1, 120) + '...'"""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
