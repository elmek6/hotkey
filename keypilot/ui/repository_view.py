"""Kod parcasi deposu penceresi -- `repository.ahk` `showGui()` portu.

Duzen AHK ile AYNI, dort sutun:

    arama (ustte, tam genislik)
    Kategoriler | Sonuclar | Detaylar
    Tagler      |          |

AHK'DEN AYRILAN DORT YER. Ilk ucu ayni sebepten (dosya artik elle
okunabilir), dorduncusu suzgec mantiginin kendisi:

  * Kaydetme ANINDA diske yaziyor. AHK'de de oyleydi ama orada JSON tek
    parca yazildigi icin risk buyuktu; simdi metin bicimi ve `save()`
    atomik degilse bile insan gozuyle onarilabilir.
  * `Refresh` dosyayi DISKTEN yeniden okuyor. AHK'de yalnizca listeleri
    tazeliyordu; dosya artik Notepad'den de duzenlenebildigi icin "disarida
    degisti mi" sorusu gercek.
  * Etiketler tek satirda virgullu. AHK her satira bir tag koyuyordu; dosya
    bicimi `tags: a, b` oldugu icin ekranda da oyle duruyor -- ekranda
    gordugun ile dosyada yazan ayni olsun.
  * `(tumu)` SATIRI ETIKETLERDE, KATEGORILERDE DEGIL. AHK'de tersiydi ve
    ters olan da oydu: kategori TEK secim, "hicbiri" hali zaten bos secimle
    anlatilabiliyor (bkz. `ToggleList`); etiket ise COKLU secim ve Qt coklu
    listede secimi bosaltmak icin Ctrl+tik istiyor -- ogrenilmesi gereken,
    ekranda gorunmeyen bir hareket. Suzgeci kaldirmak icin tiklanacak bir
    satir ASIL orada lazimdi.
  * ETIKET LISTESI BAGLAMLA DARALIYOR. AHK tum depodaki etiketleri hep
    gosteriyordu: `git` kategorisini secince bile `zebra`, `ocr`, `tuya`
    listede duruyor ve tiklayinca sonuc BOSALIYORDU -- yani listenin yarisi
    calismayan secenekti. Simdi etiketler arama + kategori suzgecinden GECEN
    kayitlardan toplaniyor; listede ne varsa sonucu daraltir, hicbiri sifira
    dusurmez. Bkz. `_sync_tags`.

Secim UUID ile korunuyor, satir numarasiyla degil: suzgec degisince liste
bastan kuruluyor ve satir numarasi baska kayda kayar.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt
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


class ToggleList(QListWidget):
    """Secili satira tekrar tiklayinca secimi KALDIRAN tek-secim listesi.

    Kategori suzgecinde `(tumu)` satiri yok; "hicbiri" hali bos secim
    demek. Qt'nin tek-secim listesinde bos secime donmenin baska yolu yok --
    tiklamak hep secer, bir kez sectikten sonra kullanici tum kategorilere
    geri donemezdi.
    """

    def mousePressEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and self.selectionModel().isSelected(index):
            self.clearSelection()
            self.setCurrentIndex(QModelIndex())
            return
        super().mousePressEvent(event)


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
        self.categories = ToggleList()
        # `currentItemChanged` DEGIL: secim kalkarken (bkz. `ToggleList`)
        # gecerli satir yerinde kaliyor ve o sinyal hic gelmiyordu.
        self.categories.itemSelectionChanged.connect(self._apply_filters)
        self.tags = QListWidget()
        # AHK'de `Multi`: secili etiketlerin HEPSINI tasiyanlar geliyor.
        self.tags.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tags.itemSelectionChanged.connect(self._on_tags_changed)

        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        left_box.addWidget(QLabel("Kategoriler (tekrar tiklayinca kalkar)"))
        left_box.addWidget(self.categories, 1)
        left_box.addWidget(QLabel("Etiketler (secili kategoriden, coklu secim)"))
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
        """Kategori listesini depodan tazeler.

        Etiketler burada DEGIL, `_apply_filters` icinde kuruluyor: onlar
        depodan degil, o anki suzgecten gecen kayitlardan geliyor.

        SECIM KORUNUYOR: tazeleme sirasinda sinyaller kapali, yoksa her
        `clear()` bir suzme turu tetikler ve secim ucar.
        """
        widget = self.categories
        selected = {item.text() for item in widget.selectedItems()}
        widget.blockSignals(True)
        widget.clear()
        widget.addItems(self.repo.categories)
        for index in range(widget.count()):
            if widget.item(index).text() in selected:
                widget.item(index).setSelected(True)
        widget.blockSignals(False)

    def _apply_filters(self) -> None:
        """AHK `_applyFilters`: once arama, sonra kategori, sonra etiketler."""
        items = self.repo.search(self.search.text())
        # Bos secim = kategori suzgeci yok. `currentItem` degil `selectedItems`:
        # `ToggleList` secimi kaldirdiginda "gecerli" satir bir sure daha
        # duruyor ve suzgec kalkmis gorunmuyordu.
        chosen = self.categories.selectedItems()
        if chosen:
            items = self.repo.filter_category(chosen[0].text(), items)
        # Etiket listesi TAM BURADAN besleniyor: arama + kategori sonucundan.
        # Etiketin kendi suzgeci daha uygulanmadi, yoksa bir etiket secince
        # liste onunla birlikte gorunenlere inip secimi geri almak
        # imkansizlasirdi.
        tags = self._sync_tags(items)
        if tags:
            items = self.repo.filter_tags(tags, items)
        self._shown = items
        self._fill_results()

    def _sync_tags(self, items: list[Item]) -> list[str]:
        """Etiket listesini baglama gore kurar, AYAKTA KALAN secimleri dondurur.

        Baglam degisince (kategori/arama) bir etiket listeden dusebilir --
        o zaman secimi de dusuyor. Alternatifi, gorunmeyen bir etiketin
        sonucu sessizce sifirda tutmasiydi: kullanici ekranda suzgeci
        goremedigi icin depoyu bos sanardi.

        Liste ayni kaldiginda widget'a DOKUNULMUYOR; her tus vurusunda
        `clear()` + `addItems()` kaydirma cubugunu basa atardi.
        """
        available = [TUMU, *sorted({tag for item in items for tag in item.tags})]
        selected = {row.text() for row in self.tags.selectedItems()}
        if available != [
            self.tags.item(index).text() for index in range(self.tags.count())
        ]:
            self.tags.blockSignals(True)
            self.tags.clear()
            self.tags.addItems(available)
            for index in range(self.tags.count()):
                if self.tags.item(index).text() in selected:
                    self.tags.item(index).setSelected(True)
            self.tags.blockSignals(False)
            selected &= set(available)
        if not selected:
            self._select_all_tags()
        return [tag for tag in available if tag in selected and tag != TUMU]

    def _select_all_tags(self) -> None:
        """`(tumu)` satirini isaretler -- suzgecsiz hal de GORUNSUN.

        Hicbir satir secili degilken de suzgec yok, ama ekranda bunu soyleyen
        bir sey olmuyor; liste bos secimle "bir sey mi unuttum" dedirtiyordu.
        """
        self.tags.blockSignals(True)
        self.tags.clearSelection()
        if self.tags.count():
            self.tags.item(0).setSelected(True)
        self.tags.blockSignals(False)

    def _on_tags_changed(self) -> None:
        """`(tumu)` ile tek tek etiketler BIRLIKTE secili kalamaz.

        Hangisinin az once tiklandigini `currentItem` soyluyor: `(tumu)`
        tiklandiysa digerleri kalkiyor, bir etiket tiklandiysa `(tumu)`.
        """
        selected = [row.text() for row in self.tags.selectedItems()]
        if TUMU in selected and len(selected) > 1:
            current = self.tags.currentItem()
            self.tags.blockSignals(True)
            if current is not None and current.text() == TUMU:
                for index in range(1, self.tags.count()):
                    self.tags.item(index).setSelected(False)
            else:
                self.tags.item(0).setSelected(False)
            self.tags.blockSignals(False)
        self._apply_filters()

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
