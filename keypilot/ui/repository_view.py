"""Kod parcasi deposu penceresi -- `repository.ahk` `showGui()` portu.

Duzen AHK ile AYNI, dort sutun:

    arama (ustte, tam genislik)
    Kategoriler | Sonuclar | Detaylar
    Tagler      |          |

AHK'DEN AYRILAN UC YER, hepsi ayni sebepten (dosya artik elle okunabilir):

  * Kaydetme ANINDA diske yaziyor. AHK'de de oyleydi ama orada JSON tek
    parca yazildigi icin risk buyuktu; simdi metin bicimi ve `save()`
    atomik degilse bile insan gozuyle onarilabilir.
  * `Refresh` dosyayi DISKTEN yeniden okuyor. AHK'de yalnizca listeleri
    tazeliyordu; dosya artik Notepad'den de duzenlenebildigi icin "disarida
    degisti mi" sorusu gercek.
  * Etiketler tek satirda virgullu. AHK her satira bir tag koyuyordu; dosya
    bicimi `tags: a, b` oldugu icin ekranda da oyle duruyor -- ekranda
    gordugun ile dosyada yazan ayni olsun.

Secim UUID ile korunuyor, satir numarasiyla degil: suzgec degisince liste
bastan kuruluyor ve satir numarasi baska kayda kayar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from keypilot import theme
from keypilot.repository import Item, Repository
from keypilot.ui.place import center_on_cursor_screen

TUMU = "(tumu)"


class RepositoryView(QWidget):
    """Tek ornek: app.py saklayip yeniden gosteriyor (ClipImages gibi)."""

    def __init__(self, repo: Repository) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("\U0001f4da Repository")
        self.repo = repo
        self._shown: list[Item] = []
        #: Detay panelinde duran kayit. Bos = yeni kayit.
        self._current_uuid = ""

        # ---- ust: arama ----
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "\U0001f50e ara -- baslik, kategori ve govde icinde"
        )
        self.search.textChanged.connect(self._apply_filters)

        # ---- sol: kategori + etiket ----
        self.categories = QListWidget()
        self.categories.currentItemChanged.connect(lambda *_: self._apply_filters())
        self.tags = QListWidget()
        # AHK'de `Multi`: secili etiketlerin HEPSINI tasiyanlar geliyor.
        self.tags.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tags.itemSelectionChanged.connect(self._apply_filters)

        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        left_box.addWidget(QLabel("Kategoriler"))
        left_box.addWidget(self.categories, 1)
        left_box.addWidget(QLabel("Etiketler (coklu secim)"))
        left_box.addWidget(self.tags, 1)

        # ---- orta: sonuclar ----
        self.results = QListWidget()
        self.results.currentItemChanged.connect(lambda *_: self._load_selected())
        middle = QWidget()
        middle_box = QVBoxLayout(middle)
        middle_box.setContentsMargins(0, 0, 0, 0)
        self.results_label = QLabel("Sonuclar")
        middle_box.addWidget(self.results_label)
        middle_box.addWidget(self.results, 1)

        # ---- sag: detaylar ----
        self.uuid_label = QLabel("(yeni)")
        theme.muted(self.uuid_label)
        self.title_edit = QLineEdit()
        self.category_edit = QLineEdit()
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("virgulle ayir: tuya, zigbee")
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "Govde. Ne yazarsan yaz -- kayit ayraci dosyadaki === satiri."
        )

        form = QGridLayout()
        for row, (label, widget) in enumerate(
            (
                ("UUID", self.uuid_label),
                ("Baslik", self.title_edit),
                ("Kategori", self.category_edit),
                ("Etiketler", self.tags_edit),
            )
        ):
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(widget, row, 1)
        form.setColumnStretch(1, 1)

        right = QWidget()
        right_box = QVBoxLayout(right)
        right_box.setContentsMargins(0, 0, 0, 0)
        right_box.addLayout(form)
        right_box.addWidget(QLabel("Metin"))
        right_box.addWidget(self.text_edit, 1)

        buttons = QHBoxLayout()
        for label, slot in (
            ("\U0001f4be Kaydet", self.save_current),
            ("➕ Yeni", self.new_item),
            ("\U0001f5d1️ Sil", self.delete_current),
            ("↺ Diskten tazele", self.reload_from_disk),
            ("Kapat", self.close),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        right_box.addLayout(buttons)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        for widget in (left, middle, right):
            splitter.addWidget(widget)
        splitter.setSizes([250, 280, 470])
        splitter.setStretchFactor(2, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(splitter, 1)
        self.status = QLabel("")
        theme.muted(self.status)
        layout.addWidget(self.status)
        self.resize(1020, 620)

    # ---- disari ----

    def open(self) -> None:
        self.reload_from_disk()
        center_on_cursor_screen(self)
        self.show()
        self.raise_()
        self.activateWindow()

    def reload_from_disk(self) -> None:
        """Dosyayi yeniden okur. Depo Notepad'den de duzenlenebiliyor."""
        self.repo.load()
        self._refresh_filters()
        self._apply_filters()

    # ---- suzgecler ----

    def _refresh_filters(self) -> None:
        """Kategori ve etiket listelerini depodan tazeler.

        SECIM KORUNUYOR: tazeleme sirasinda sinyaller kapali, yoksa her
        `clear()` bir suzme turu tetikler ve secim ucar.
        """
        for widget, values in (
            (self.categories, [TUMU, *self.repo.categories]),
            (self.tags, self.repo.tags),
        ):
            selected = {item.text() for item in widget.selectedItems()}
            widget.blockSignals(True)
            widget.clear()
            widget.addItems(values)
            for index in range(widget.count()):
                if widget.item(index).text() in selected:
                    widget.item(index).setSelected(True)
            if widget is self.categories and not selected:
                widget.setCurrentRow(0)  # (tumu)
            widget.blockSignals(False)

    def _apply_filters(self) -> None:
        """AHK `_applyFilters`: once arama, sonra kategori, sonra etiketler."""
        items = self.repo.search(self.search.text())
        current = self.categories.currentItem()
        category = current.text() if current else TUMU
        if category and category != TUMU:
            items = self.repo.filter_category(category, items)
        tags = [item.text() for item in self.tags.selectedItems()]
        if tags:
            items = self.repo.filter_tags(tags, items)
        self._shown = items
        self._fill_results()

    def _fill_results(self) -> None:
        keep = self._current_uuid
        self.results.blockSignals(True)
        self.results.clear()
        for item in self._shown:
            row = QListWidgetItem(
                f"{item.title} ({item.category})" if item.category else item.title
            )
            row.setData(Qt.ItemDataRole.UserRole, item.uuid)
            self.results.addItem(row)
        self.results.blockSignals(False)
        self._select_uuid(keep)
        self.status.setText(f"{len(self._shown)} / {len(self.repo.items)} kayit")

    def _select_uuid(self, uuid: str) -> None:
        for index in range(self.results.count()):
            if self.results.item(index).data(Qt.ItemDataRole.UserRole) == uuid:
                self.results.setCurrentRow(index)
                return

    # ---- detay paneli ----

    def _load_selected(self) -> None:
        row = self.results.currentItem()
        if row is None:
            return
        item = self.repo.get(row.data(Qt.ItemDataRole.UserRole))
        if item is None:
            return
        self._current_uuid = item.uuid
        self.uuid_label.setText(item.uuid)
        self.title_edit.setText(item.title)
        self.category_edit.setText(item.category)
        self.tags_edit.setText(", ".join(item.tags))
        self.text_edit.setPlainText(item.text)

    def new_item(self) -> None:
        """Detay panelini bosaltir. Kayit `Kaydet`e basilinca olusuyor --
        bos kayit listeye dusmesin."""
        self._current_uuid = ""
        self.uuid_label.setText("(yeni)")
        for widget in (self.title_edit, self.category_edit, self.tags_edit):
            widget.clear()
        self.text_edit.clear()
        self.results.setCurrentRow(-1)
        self.title_edit.setFocus()

    def save_current(self) -> None:
        """AHK `_saveItem`: baslik zorunlu, sonra ekle ya da guncelle."""
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "Repository", "Baslik zorunlu.")
            self.title_edit.setFocus()
            return
        category = self.category_edit.text().strip()
        tags = [tag.strip() for tag in self.tags_edit.text().split(",") if tag.strip()]
        text = self.text_edit.toPlainText()

        if self._current_uuid and self.repo.update(
            self._current_uuid, title, category, text, tags
        ):
            pass
        else:
            item = self.repo.add(
                Item(title=title, category=category, text=text, tags=tags)
            )
            self._current_uuid = item.uuid
            self.uuid_label.setText(item.uuid)
        self._write()

    def delete_current(self) -> None:
        if not self._current_uuid:
            return
        item = self.repo.get(self._current_uuid)
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "Repository",
            f"Silinsin mi?\n\n{item.title}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.repo.delete(self._current_uuid)
        self._current_uuid = ""
        self._write()
        self.new_item()

    def _write(self) -> None:
        if not self.repo.save():
            QMessageBox.critical(self, "Repository", "Dosya yazilamadi -- log'a bak.")
            return
        self._refresh_filters()
        self._apply_filters()

    # ---- pencere ----

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
