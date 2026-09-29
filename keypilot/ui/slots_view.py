"""Slot penceresi -- `Files/slots.json`in butun gruplari tek yerde.

F14 menusu slotlari TEK TEK duzenliyor (`SlotEditDialog`). Burasi hepsini
birden gosteriyor: her grup bir sekme, sekmede grubun on slotu bir tabloda.

    @ | is | ● qrCodes
    No | Baslik  | Icerik
    1  | mail    | ornek@firma.de
    ...
    0  | Slot 10 | ••••••••          <- sifre slotu (store.PASSWORD_SLOT)

Ilk sekme ana grup (adi bos grup, `DEFAULT_GROUP`), etiketi "@". Secili yan
grup F14 menusundeki gibi "● " ile isaretli.

Tablo log penceresiyle AYNI gorunumde (ui/log_view.py: Consolas, satir
secimi, sarmalama yok, alternatif renk yok): satirlar tek satir, tam icerik
hucrenin uzerine gelince ipucunda. Deger hucresi duzenlenirken hucrenin
USTUNE cok satirli bir kutu acilir -- satir satir icerik tek satirlik
editorde duzlesip bozulmasin. Sifre slotunun degeri tabloda da, editorde de
maskeli.

Pencere her acilista dosyayi DISKTEN okur (`store.load()`): F14 akisi ve
Notepad ayni dosyayi degistirebiliyor.

KAYDET YALNIZ DEGISEN SLOTLARI YAZAR. Bazi iceriklerde `\\r\\n` var ve
QPlainTextEdit onu `\\n`e ceviriyor; dokunulmamis slot geri yazilsa dosya
sessizce degisirdi. Karsilastirma satir sonlari normallestirilmis metinle
yapiliyor; editor acilip degismeden kapanirsa hucreye hic yazilmiyor.
Kaydetmeden hemen once `store.load()`: F14'ten bu arada yazilanlar ezilmesin.

Kaydedilmemis degisiklik varken Kaydet dugmesi kirmizi cerceveyle bekler.
Kapatirken soru YOK (kullanicinin karari): degisiklik duser, pencere bir
sonraki acilista diskten okunur. Grup islemleri (yeni / sil) de oyle:
store'a yazip sekmeleri diskten kurar, kaydedilmemis duzenleme duser.

Yeni grup F14'teki gibi HEMEN yan grup olarak secilir ve sekmesi acilir.
Ana grup silinemez (store da reddediyor); o sekmede "Grubu sil" pasif.

AYNI ANDA EN FAZLA IKI PENCERE (`SlotsWindows`). Ikisi ayni SlotStore'u
paylasiyor ama her pencere kendi okudugu hali (`GroupPage._original`) tutuyor;
Kaydet diskten okuyup yalniz kendi degisenlerini yazdigi icin biri digerinin
slotunu ezmez. Biri yazinca (kaydet / grup islemi) oteki, kaydedilmemis
degisikligi YOKSA diskten tazelenir; varsa dokunulmaz -- duzenleme ucmasin.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from keypilot import theme
from keypilot.store import DEFAULT_GROUP, MASK, PASSWORD_SLOT, Slot, SlotStore
from keypilot.ui.place import center_on_cursor_screen
from keypilot.ui.preview import preview_html
from keypilot.ui.slot_edit import VALUE_HEIGHT

#: Ana grubun (adi bos grup) sekme etiketi.
MAIN_TAB = "@"
#: Secili yan grubun isareti -- F14 "Side slot" menusundekiyle ayni.
SIDE_MARK = "● "

KEY_COLUMN, NAME_COLUMN, VALUE_COLUMN = range(3)
COLUMNS = ["No", "Baslik", "Icerik"]

#: Deger editorunun yuksekligi: iki `SlotEditDialog` kutusu kadar (6 satir).
EDITOR_HEIGHT = VALUE_HEIGHT * 2
#: Ipucunda gosterilen en fazla satir / satir basina karakter.
TIP_LINES = 20
TIP_WIDTH = 120
#: Ayni anda acik kalabilecek Slotlar penceresi sayisi.
MAX_WINDOWS = 2
#: Ikinci pencere birincinin tam ustune dusmesin diye kaydirma (piksel).
CASCADE = 40


def tab_label(group: str, side: str) -> str:
    """Sekme etiketi: ana grup "@", secili yan grup "● ad"."""
    if group == DEFAULT_GROUP:
        return MAIN_TAB
    return f"{SIDE_MARK}{group}" if group == side else group


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


class ValueDelegate(QStyledItemDelegate):
    """Deger hucresinin editoru: cok satirli kutu, sifre slotunda maskeli satir."""

    def __init__(self, page: GroupPage) -> None:
        super().__init__(page)
        self.page = page

    def createEditor(self, parent, option, index):
        if index.column() != VALUE_COLUMN:
            return super().createEditor(parent, option, index)
        if index.row() + 1 == PASSWORD_SLOT:
            editor = QLineEdit(parent)
            editor.setEchoMode(QLineEdit.EchoMode.Password)
            return editor
        editor = QPlainTextEdit(parent)
        editor.setTabChangesFocus(True)
        # The editor overlaps the rows below; a palette-based border keeps its edge visible.
        editor.setStyleSheet("QPlainTextEdit { border: 1px solid palette(highlight); }")
        return editor

    def setEditorData(self, editor, index) -> None:
        if index.column() != VALUE_COLUMN:
            super().setEditorData(editor, index)
            return
        content = self.page.value(index.row() + 1)
        if isinstance(editor, QLineEdit):
            editor.setText(content)
        else:
            editor.setPlainText(content)

    def setModelData(self, editor, model, index) -> None:
        if index.column() != VALUE_COLUMN:
            super().setModelData(editor, model, index)
            return
        text = editor.text() if isinstance(editor, QLineEdit) else editor.toPlainText()
        # Degismeden kapanan editor hucreye yazmaz: `\r\n` oldugu gibi kalir.
        if _norm(text) != _norm(self.page.value(index.row() + 1)):
            self.page.set_value(index.row() + 1, text)

    def updateEditorGeometry(self, editor, option, index) -> None:
        if not isinstance(editor, QPlainTextEdit):
            super().updateEditorGeometry(editor, option, index)
            return
        rect = option.rect
        height = max(rect.height(), EDITOR_HEIGHT)
        bottom = editor.parentWidget().height()
        top = max(0, min(rect.top(), bottom - height))
        editor.setGeometry(rect.left(), top, rect.width(), height)


class GroupPage(QTableWidget):
    """Bir grubun sekmesi: on slot, satir basina tus | ad | deger."""

    def __init__(self, group: str, slots: list[Slot], on_edit: Callable[[], None]) -> None:
        super().__init__(0, len(COLUMNS))
        self.group = group
        #: Diskten okunan hal (ad, icerik) -- degisiklik buna gore olculur.
        self._original = [(slot.name, slot.content) for slot in slots[:10]]
        self._values = [content for _name, content in self._original]

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(mono)
        self.setHorizontalHeaderLabels(COLUMNS)
        self.verticalHeader().setVisible(False)
        self.setWordWrap(False)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setItemDelegate(ValueDelegate(self))
        header = self.horizontalHeader()
        header.setSectionResizeMode(KEY_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(VALUE_COLUMN, QHeaderView.ResizeMode.Stretch)

        self.setRowCount(len(self._original))
        for row, (name, _content) in enumerate(self._original):
            key = QTableWidgetItem(str((row + 1) % 10))
            key.setFlags(key.flags() & ~Qt.ItemFlag.ItemIsEditable)
            key.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, KEY_COLUMN, key)
            self.setItem(row, NAME_COLUMN, QTableWidgetItem(name))
            self.setItem(row, VALUE_COLUMN, QTableWidgetItem())
            self._show_value(row + 1)
        self.setColumnWidth(NAME_COLUMN, 180)
        self.itemChanged.connect(lambda _item: on_edit())

    # ---- slotlar (1 tabanli) ----

    def key(self, index: int) -> str:
        return self.item(index - 1, KEY_COLUMN).text()

    def name(self, index: int) -> str:
        return self.item(index - 1, NAME_COLUMN).text()

    def set_name(self, index: int, name: str) -> None:
        self.item(index - 1, NAME_COLUMN).setText(name)

    def value(self, index: int) -> str:
        return self._values[index - 1]

    def set_value(self, index: int, content: str) -> None:
        self._values[index - 1] = content
        self._show_value(index)

    def changes(self) -> list[tuple[int, str | None, str | None]]:
        """Degisen slotlar: (indeks, yeni ad ya da None, yeni icerik ya da None)."""
        result = []
        for index, (name, content) in enumerate(self._original, start=1):
            new_name = self.name(index)
            new_content = self.value(index)
            name_changed = new_name != name
            value_changed = _norm(new_content) != _norm(content)
            if name_changed or value_changed:
                result.append(
                    (
                        index,
                        new_name if name_changed else None,
                        new_content if value_changed else None,
                    )
                )
        return result

    def _show_value(self, index: int) -> None:
        """Hucrede tek satir, ipucunda tam icerik. Sifre slotu maskeli."""
        item = self.item(index - 1, VALUE_COLUMN)
        content = self._values[index - 1]
        if index == PASSWORD_SLOT:
            item.setText(MASK if content else "")
            item.setToolTip("")
        else:
            item.setText(" ".join(content.split()))
            item.setToolTip(preview_html(content, TIP_LINES, TIP_WIDTH) if content else "")


class SlotsView(QWidget):
    """Bir Slotlar penceresi. Ornekleri `SlotsWindows` tutuyor."""

    #: Diske yazildi (kaydet, yeni grup, grup silme).
    changed = Signal()

    def __init__(self, store: SlotStore, number: int = 1) -> None:
        super().__init__(None, Qt.WindowType.Window)
        title = "\U0001f9f0 Slotlar"
        self.setWindowTitle(title if number == 1 else f"{title} ({number})")
        self.store = store

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(lambda _index: self._sync_buttons())

        self.save_button = QPushButton("\U0001f4be Kaydet")
        self.save_button.clicked.connect(self.save)
        self.new_button = QPushButton("➕ Yeni grup")
        self.new_button.clicked.connect(self.new_group)
        self.delete_button = QPushButton("\U0001f5d1️ Grubu sil")
        self.delete_button.clicked.connect(self.delete_group)
        self.close_button = QPushButton("Kapat")
        self.close_button.clicked.connect(self.close)
        self.status = QLabel("")
        theme.muted(self.status)

        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.status, 1)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(buttons)
        self.resize(820, 420)

    # ---- disari ----

    def open(self) -> None:
        self.reload()
        center_on_cursor_screen(self)
        self.show()
        self.raise_()
        self.activateWindow()

    def reload(self) -> None:
        """Dosyayi diskten okur, sekmeleri bastan kurar."""
        self.store.load()
        self._build_tabs()

    def sync_from_disk(self) -> None:
        """Baska pencere yazdiginda: acik ve kaydedilmemis degisikligi yoksa tazeler."""
        if self.isVisible() and not self.is_dirty():
            self.reload()

    def pages(self) -> list[GroupPage]:
        return [self.tabs.widget(index) for index in range(self.tabs.count())]

    def current_group(self) -> str:
        page = self.tabs.currentWidget()
        return page.group if isinstance(page, GroupPage) else DEFAULT_GROUP

    def is_dirty(self) -> bool:
        return any(page.changes() for page in self.pages())

    def save(self) -> None:
        """Yalniz degisen slotlari yazar; once diski tazeler (F14 ezilmesin)."""
        changes = [(page.group, *change) for page in self.pages() for change in page.changes()]
        if not changes:
            return
        self.store.load()
        written = 0
        failed = False
        missing: list[str] = []
        for group, index, name, content in changes:
            if group != DEFAULT_GROUP and group not in self.store.groups:
                if group not in missing:
                    missing.append(group)
                continue
            if content is not None:
                failed |= not self.store.set_slot_content(group, index, content)
            if name is not None:
                failed |= not self.store.set_slot_name(group, index, name)
            written += 1
        if failed:
            QMessageBox.critical(self, "Slotlar", "Dosya yazilamadi -- log'a bak.")
            return
        self._build_tabs()
        self.status.setText(f"{written} slot kaydedildi")
        self.changed.emit()
        if missing:
            QMessageBox.warning(
                self,
                "Slotlar",
                "Bu gruplar bu arada silinmis, degisiklikleri yazilmadi:\n\n" + "\n".join(missing),
            )

    # ---- gruplar ----

    def new_group(self) -> None:
        """F14 `new_group` ile ayni: grup acilir ve yan grup olarak secilir."""
        name, ok = QInputDialog.getText(self, "Yeni grup", "Grup adi:")
        name = name.strip()
        if not ok or not name:
            return
        self.store.load()
        if not self.store.add_group(name):
            QMessageBox.warning(self, "Yeni grup", "Grup zaten var.")
            self._build_tabs()
            return
        self.store.set_default_group(name)
        self._build_tabs(current=name)
        self.status.setText(f"{name} olusturuldu")
        self.changed.emit()

    def delete_group(self) -> None:
        """Secili sekmenin grubunu siler -- once sorar. Ana grup silinmez."""
        name = self.current_group()
        if name == DEFAULT_GROUP:
            return
        answer = QMessageBox.question(
            self,
            "Grup sil",
            f"'{name}' grubunu silmek istiyor musun?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.load()
        self.store.delete_group(name)
        self._build_tabs(current=DEFAULT_GROUP)
        self.status.setText(f"{name} silindi")
        self.changed.emit()

    # ---- ic ----

    def _build_tabs(self, current: str | None = None) -> None:
        """Sekmeleri store'dan kurar. `current` verilirse o gruba gecer,
        yoksa acik olan grup korunur."""
        page = self.tabs.currentWidget()
        if current is None and isinstance(page, GroupPage):
            current = page.group
        while self.tabs.count():
            old = self.tabs.widget(0)
            self.tabs.removeTab(0)
            old.deleteLater()
        side = self.store.default_group
        for group in [DEFAULT_GROUP, *self.store.group_names()]:
            self.tabs.addTab(
                GroupPage(group, self.store.slots(group), self._on_edit),
                tab_label(group, side),
            )
        for index, built in enumerate(self.pages()):
            if built.group == current:
                self.tabs.setCurrentIndex(index)
                break
        self._on_edit()
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.delete_button.setEnabled(self.current_group() != DEFAULT_GROUP)

    def _on_edit(self) -> None:
        """Kaydet dugmesi degisiklik bekledigi surece kirmizi cercevede."""
        dirty = self.is_dirty()
        self.save_button.setStyleSheet(
            f"QPushButton {{ border: 2px solid {theme.DANGER}; padding: 3px 10px; }}"
            if dirty
            else ""
        )
        if dirty:
            self.status.setText("")

    # ---- pencere ----

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


class SlotsWindows:
    """En fazla `MAX_WINDOWS` Slotlar penceresi. app.py tek nesne olarak tutuyor."""

    def __init__(self, store: SlotStore) -> None:
        self.views = [SlotsView(store, number) for number in range(1, MAX_WINDOWS + 1)]
        for view in self.views:
            view.changed.connect(partial(self._sync_others, view))

    def open(self) -> None:
        """Kapali bir pencere varsa onu acar; hepsi aciksa sonuncuyu one getirir."""
        shown = [view for view in self.views if view.isVisible()]
        idle = next((view for view in self.views if not view.isVisible()), None)
        if idle is None:
            last = self.views[-1]
            last.raise_()
            last.activateWindow()
            return
        idle.open()
        if shown:
            idle.move(shown[-1].pos() + QPoint(CASCADE, CASCADE))

    def close(self) -> None:
        for view in self.views:
            view.close()

    def _sync_others(self, source: SlotsView) -> None:
        for view in self.views:
            if view is not source:
                view.sync_from_disk()
