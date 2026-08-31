"""Ayar ekrani -- AHK `Lib/settings_dialog.ahk` portu.

Ustte arama, solda kategori, sagda liste. Duzeni AHK ile ayni tutuldu:
tanidik gelsin ve ayni kisayol aliskanligi calissin.

    * cift tiklama  bool ise dogrudan cevirir, digerlerinde deger sorar
    * kalin satir   varsayilandan FARKLI olan ayar (AHK'de NM_CUSTOMDRAW ile
                    yapiliyordu; Qt'de hucrenin fontu yetiyor). Ad ve deger
                    kalin, aciklama degil -- aciklama uzun ve kalin bir metin
                    blogu satiri okunmaz yapiyor.
    * varsayilan    ayri sutun DEGIL, deger hucresinin ipucunda -- masayi
                    genisletmeye degmiyordu
    * arama         bosluk ile AND; arama varken kategori suzgeci devre disi

Kaydetme kapanista (`Settings.save`): ekran acikken her degisiklikte diske
yazmak gereksiz, ayar dosyasi kucuk ama degisiklik cok olabiliyor.
"""

from __future__ import annotations

import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cascade import paths
from cascade.settings import SETTINGS, Category, Setting

ALL_LABEL = "Tumu"


class SettingsDialog(QWidget):
    """Ayar penceresi. Tek ornek: app.py bunu saklayip yeniden gosteriyor."""

    COLUMNS = ("Ayar", "Deger", "Aciklama")

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("⚙️ Ayarlar")
        self.resize(860, 520)
        self._rows: list[Setting] = []
        self._category = ""  # "" = Tumu

        self.search = QLineEdit()
        self.search.setPlaceholderText("\U0001f50e ara (bosluk = ve)")
        self.search.textChanged.connect(self._refresh)

        self.categories = QListWidget()
        self.categories.setFixedWidth(180)
        self.categories.currentRowChanged.connect(self._on_category)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(lambda _index: self._edit())
        self.table.setWordWrap(True)
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents  # aciklamalar cok satirli
        )
        header = self.table.horizontalHeader()
        for index, width in enumerate((260, 130)):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(index, width)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.status = QLabel()

        reset = QPushButton("↺ Seciliyi sifirla")
        reset.clicked.connect(self._reset_selected)
        reset_all = QPushButton("↺ Tumu varsayilana")
        reset_all.clicked.connect(self._reset_all)
        open_json = QPushButton("\U0001f4dd settings.json")
        open_json.clicked.connect(self._open_json)

        buttons = QHBoxLayout()
        buttons.addWidget(self.status, 1)
        buttons.addWidget(reset)
        buttons.addWidget(reset_all)
        buttons.addWidget(open_json)

        middle = QHBoxLayout()
        middle.addWidget(self.categories)
        middle.addWidget(self.table, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addLayout(middle, 1)
        layout.addLayout(buttons)

        self._fill_categories()
        self._refresh()

    # ---- liste ----

    def _fill_categories(self) -> None:
        self.categories.blockSignals(True)
        self.categories.clear()
        self.categories.addItem(f"{ALL_LABEL} ({len(SETTINGS.all)})")
        for name in SETTINGS.categories:
            self.categories.addItem(
                f"{Category.label(name)} ({len(SETTINGS.tree[name])})"
            )
        self.categories.setCurrentRow(0)
        self.categories.blockSignals(False)

    def _on_category(self, row: int) -> None:
        self._category = "" if row <= 0 else SETTINGS.categories[row - 1]
        self._refresh()

    def _refresh(self) -> None:
        query = self.search.text()
        items = SETTINGS.search(query)
        if query:  # arama varken kategori suzgeci devre disi (AHK ile ayni)
            self.categories.blockSignals(True)
            self.categories.setCurrentRow(0)
            self.categories.blockSignals(False)
            self._category = ""
        if self._category:
            items = [item for item in items if item.category == self._category]

        self._rows = items
        self.table.setRowCount(len(items))
        changed = 0
        for row, item in enumerate(items):
            cells = (item.name, self._value_text(item), item.desc or item.key)
            hint = f"{item.key}\nvarsayilan: {self._default_text(item)}"
            for column, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if column < 2 and item.is_changed():
                    font = cell.font()
                    font.setBold(True)  # AHK: degismis deger kalin
                    cell.setFont(font)
                cell.setToolTip(hint)
                self.table.setItem(row, column, cell)
            changed += bool(item.is_changed())
        self.status.setText(f"{len(items)} ayar, {changed} degismis")

    @staticmethod
    def _value_text(item: Setting) -> str:
        if item.type_of() == "bool":
            return "✓ acik" if item.get() else "✗ kapali"
        return item.label_for(item.get())

    @staticmethod
    def _default_text(item: Setting) -> str:
        if item.type_of() == "bool":
            return "acik" if item.default else "kapali"
        return item.label_for(item.default)

    def _selected(self) -> Setting | None:
        row = self.table.currentRow()
        return self._rows[row] if 0 <= row < len(self._rows) else None

    # ---- duzenleme ----

    def _edit(self) -> None:
        item = self._selected()
        if item is None:
            return
        if item.type_of() == "bool":
            item.toggle()
            self._refresh()
            return
        if item.type_of() == "enum":
            # Listede ETIKET gosterilir, ayara KIMLIK yazilir.
            ids = list(item.choices)
            current = ids.index(item.get()) if item.get() in ids else 0
            label, ok = QInputDialog.getItem(
                self, item.name, item.desc or item.key,
                [item.label_for(one) for one in ids], current, False
            )
            value = ids[[item.label_for(one) for one in ids].index(label)] if ok else None
        else:
            value, ok = QInputDialog.getText(
                self, item.name, item.desc or item.key, text=str(item.get())
            )
        if not ok:
            return
        message = item.set(value)
        if message:
            QMessageBox.warning(self, "Ayarlar", message)
        self._refresh()

    def _reset_selected(self) -> None:
        item = self._selected()
        if item is not None:
            item.reset()
            self._refresh()

    def _reset_all(self) -> None:
        answer = QMessageBox.question(
            self, "Ayarlar", "Tum ayarlar varsayilana donecek. Devam?"
        )
        if answer == QMessageBox.StandardButton.Yes:
            SETTINGS.reset_all()
            self._refresh()

    def _open_json(self) -> None:
        """AHK ile ayni: once diske yaz, sonra Notepad ile ac."""
        SETTINGS.save_now(paths.SETTINGS)
        subprocess.Popen(["notepad.exe", str(paths.SETTINGS)])  # noqa: S603, S607

    # ---- yasam dongusu ----

    def show_dialog(self) -> None:
        self._fill_categories()
        self._refresh()
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        """Kapanista kaydet -- AHK `SettingsDialog._close`."""
        SETTINGS.save(paths.SETTINGS)
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
