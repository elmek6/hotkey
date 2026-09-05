"""QR penceresi -- AHK'de karsiligi YOK. Tasarim: qr-plani.md.

Pencere acilinca panodakini ALIR ve sablonu tahmin eder: bu isi yaparken
kullanici zaten kopyalamis oluyor, ayrica yapistirmasi gereksiz.

Her tus vurusunda kare yeniden ciziliyor -- olculdu, segno 1 ms altinda,
gecikme hissedilmiyor.

Ham icerik kutusu SART: telefon kareyi okumazsa hatanin bicimde mi veride
mi oldugu ancak orada gorulur.

Parola alani gizli basliyor. QR ekranda ACIK METIN demektir; gizlemek
odadaki gozu engeller, ekrani goren telefonu engellemez. "Panoya kopyala"
karesi gorsel pano gecmisine (Files/clipimg.dat) duser -- wifi parolasi
icin sorun degil, kullanici parolasi icin dugmeye basma.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from keypilot import paths, qr, theme
from keypilot.settings import SETTINGS
from keypilot.store import PASSWORD_SLOT, SlotStore, slot_display
from keypilot.ui.place import center_on_cursor_screen
from keypilot.ui.preview import shorten

#: Ham icerikte parolanin yerine konan karakter.
MASK_CHAR = "•"

#: Icerik bu surumun uzerine cikarsa kare gozle okunamayacak kadar
#: sikilasiyor -- uyari veriliyor, engellenmiyor.
WARN_VERSION = 20


class QrDialog(QWidget):
    """Sablon secimi + alanlar + canli kare. Esc kapatir."""

    def __init__(self, initial_text: str = "", store: SlotStore | None = None) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("QR kod")
        self._fields: dict[str, QWidget] = {}
        self._content = ""
        self._store = store

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # ---- slot secici (grup acilir kutusu + grubun slotlari)
        self._groups = QComboBox(self)
        self._slots = QListWidget(self)
        self._slots.setFixedHeight(96)
        if store is not None:
            slot_row = QHBoxLayout()
            slot_row.addWidget(QLabel("slot grubu", self))
            slot_row.addWidget(self._groups, 1)
            layout.addLayout(slot_row)
            layout.addWidget(self._slots)
            self._groups.currentTextChanged.connect(self._on_group)
            self._slots.itemClicked.connect(self._use_slot)
            self._load_groups()
        else:
            self._groups.hide()
            self._slots.hide()

        # ---- sablon secimi
        self._group = QButtonGroup(self)
        row = QHBoxLayout()
        for index, item in enumerate(qr.TEMPLATES):
            button = QRadioButton(item.label, self)
            self._group.addButton(button, index)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self._group.idClicked.connect(self._on_template)

        # ---- alanlar (sablona gore yeniden kuruluyor)
        self._form_host = QWidget(self)
        self._form = QFormLayout(self._form_host)
        self._form.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._form_host)

        # ---- ham icerik + kare yan yana
        middle = QHBoxLayout()
        left = QVBoxLayout()
        self._raw = QPlainTextEdit(self)
        self._raw.setReadOnly(True)
        self._raw.setFixedWidth(260)
        self._raw.setFixedHeight(qr.PIXEL_SIZE - 24)
        left.addWidget(self._raw)
        raw_label = QLabel("ham icerik", self)
        theme.muted(raw_label)
        left.addWidget(raw_label)
        middle.addLayout(left)

        self._image = QLabel(self)
        self._image.setFixedSize(qr.PIXEL_SIZE, qr.PIXEL_SIZE)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Beyaz zemin sart: koyu temada QR'in beyaz modulleri sayfaya
        # karisiyor ve telefon kareyi bulamiyor.
        self._image.setStyleSheet("background: #ffffff; border-radius: 4px;")
        middle.addWidget(self._image)
        layout.addLayout(middle)

        # ---- alt sira
        bottom = QHBoxLayout()
        save = QPushButton("Kaydet PNG", self)
        save.clicked.connect(self._save_png)
        bottom.addWidget(save)
        copy = QPushButton("Panoya kopyala", self)
        copy.clicked.connect(self._copy_image)
        bottom.addWidget(copy)
        bottom.addStretch(1)
        self._status = QLabel("", self)
        theme.muted(self._status)
        bottom.addWidget(self._status)
        layout.addLayout(bottom)

        start = qr.guess_template(initial_text)
        index = next(i for i, t in enumerate(qr.TEMPLATES) if t.key == start)
        self._group.button(index).setChecked(True)
        self._build_fields(qr.TEMPLATES[index], initial_text)
        center_on_cursor_screen(self)

    # ---- slotlar ----

    def _load_groups(self) -> None:
        """Gruplar diskten TAZE okunuyor: dosyayi aradan baskasi
        degistirmis olabilir."""
        assert self._store is not None
        self._store.load()
        self._groups.blockSignals(True)
        self._groups.clear()
        for name in self._store.groups:
            # Adsiz grup "base" diye gorunur: kutuda bos satir olmasin.
            self._groups.addItem(name or "base", name)
        current = qr.SLOT_GROUP.get()
        index = self._groups.findData(current)
        self._groups.setCurrentIndex(index if index >= 0 else 0)
        self._groups.blockSignals(False)
        self._fill_slots()

    def _on_group(self, *_args) -> None:
        """Grup secimi ayara yaziliyor."""
        qr.SLOT_GROUP.set(self._groups.currentData() or "")
        # Hemen diske: cikista yazmak cokme/oldurulme halinde kayboluyor.
        SETTINGS.save(paths.SETTINGS)
        self._fill_slots()

    def _fill_slots(self, *_args) -> None:
        """Secili grubun dolu slotlari. Sifre slotu YOK (store.py kurali:
        icerigi hicbir listede gorunmez)."""
        assert self._store is not None
        group = self._groups.currentData() or ""
        self._slots.clear()
        for index, slot in enumerate(self._store.slots(group)[:10], start=1):
            text = " ".join(slot.content.split())
            if not text or index == PASSWORD_SLOT:
                continue
            shown = slot_display(index, text, lambda t: shorten(t, 60))
            item = QListWidgetItem(f"{index % 10}  {slot.name or f'Slot {index}'}: {shown}")
            item.setData(Qt.ItemDataRole.UserRole, slot.content)
            self._slots.addItem(item)
        if self._slots.count() == 0:
            self._slots.addItem("(bu grupta dolu slot yok)")

    def _use_slot(self, item: QListWidgetItem) -> None:
        """Tiklanan slotun icerigi: sablon yeniden tahmin edilip alanlara
        cozuluyor."""
        content = item.data(Qt.ItemDataRole.UserRole)
        if not content:
            return
        key = qr.guess_template(content)
        index = next(i for i, t in enumerate(qr.TEMPLATES) if t.key == key)
        self._group.button(index).setChecked(True)
        self._build_fields(qr.TEMPLATES[index], content)

    # ---- sablon / alanlar ----

    def _on_template(self, index: int) -> None:
        self._build_fields(qr.TEMPLATES[index], "")

    def _build_fields(self, item: qr.Template, initial: str) -> None:
        """Alanlari sifirdan kurar. Sablon degisince eski alanlar
        anlamsizlasiyor, tasimaya calismak yaniltici olurdu."""
        while self._form.count():
            row = self._form.takeAt(0)
            if row.widget():
                row.widget().deleteLater()
        self._fields.clear()
        self._template = item

        for spec in item.fields:
            if spec.choices:
                widget: QWidget = QComboBox(self)
                widget.addItems(spec.choices)
                widget.setCurrentText(spec.default or spec.choices[0])
                widget.currentTextChanged.connect(self._refresh)
            else:
                widget = QLineEdit(self)
                if spec.secret:
                    widget.setEchoMode(QLineEdit.EchoMode.Password)
                widget.textChanged.connect(self._refresh)
            self._fields[spec.key] = widget

            if spec.secret:
                # Goz dugmesi: parolayi gormeden dogru yazdigindan emin
                # olmanin baska yolu yok, kare zaten ekranda.
                line = QHBoxLayout()
                line.addWidget(widget)
                eye = QPushButton("\U0001f441", self)
                eye.setCheckable(True)
                eye.setFixedWidth(32)
                eye.toggled.connect(
                    lambda shown, w=widget: w.setEchoMode(
                        QLineEdit.EchoMode.Normal
                        if shown
                        else QLineEdit.EchoMode.Password
                    )
                )
                line.addWidget(eye)
                holder = QWidget(self)
                holder.setLayout(line)
                line.setContentsMargins(0, 0, 0, 0)
                self._form.addRow(spec.label, holder)
            else:
                self._form.addRow(spec.label, widget)

        if item.key == "wifi":
            hidden = QCheckBox("gizli ag", self)
            hidden.toggled.connect(self._refresh)
            self._fields["hidden"] = hidden
            self._form.addRow("", hidden)

        # Gelen metin alanlara COZULUYOR (qr.parse). Hazir bir `WIFI:...;;`
        # dizgisi geldiginde eskiden metnin tamami SSID kutusuna giriyordu:
        # kacis karakterleri ikinci kez kacirilip cop bir kare cikiyordu.
        if initial:
            for key, value in qr.parse(item.key, initial).items():
                widget = self._fields.get(key)
                if widget is None or not value:
                    continue
                if key == "password" and set(value) <= {MASK_CHAR}:
                    # Maskelenmis ham icerik geri geldi: gercek parola
                    # degil, yildizin kendisi. Yazmak yaniltici olurdu.
                    continue
                if isinstance(widget, QLineEdit):
                    widget.setText(value)
                elif isinstance(widget, QComboBox):
                    widget.setCurrentText(value)
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(value == "1")
        self._refresh()

    # ---- cizim ----

    def _values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, widget in self._fields.items():
            if isinstance(widget, QLineEdit):
                values[key] = widget.text()
            elif isinstance(widget, QComboBox):
                values[key] = widget.currentText()
            elif isinstance(widget, QCheckBox):
                values[key] = "1" if widget.isChecked() else "0"
        return values

    def _refresh(self, *_args) -> None:
        content = self._template.build(self._values())
        self._content = content
        # Ham kutuda parola ACIK gorunmuyor: kutu ekranin bir parcasi ve
        # QR'i dogrulamak icin bicimi gormek yetiyor.
        self._raw.setPlainText(_masked(content, self._values().get("password", "")))
        data = qr.png_bytes(content)
        if not data:
            self._image.clear()
            self._status.setText("")
            return
        pixmap = QPixmap()
        pixmap.loadFromData(data, "PNG")
        self._image.setPixmap(
            pixmap.scaled(
                qr.PIXEL_SIZE,
                qr.PIXEL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                # Yumusatma YOK: QR keskin kenar ister, bulanik kare
                # telefonda okunmuyor.
                Qt.TransformationMode.FastTransformation,
            )
        )
        version = qr.version_of(content)
        note = "  ⚠ cok yogun" if version >= WARN_VERSION else ""
        self._status.setText(f"ver{version}  ·  {len(content.encode())} bayt{note}")

    # ---- disari cikaranlar ----

    def _save_png(self) -> None:
        if not self._content:
            return
        path, _filter = QFileDialog.getSaveFileName(self, "QR kaydet", "qr.png", "PNG (*.png)")
        if not path:
            return
        with open(path, "wb") as handle:
            handle.write(qr.png_bytes(self._content, scale=12))

    def _copy_image(self) -> None:
        pixmap = self._image.pixmap()
        if pixmap and not pixmap.isNull():
            QGuiApplication.clipboard().setPixmap(pixmap)

    def keyPressEvent(self, event) -> None:  # noqa: N802  Qt adi
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


def _masked(content: str, password: str) -> str:
    """Ham icerikte parolayi yildizla. Bos parola maskelenmez."""
    if not password:
        return content
    return content.replace(password, MASK_CHAR * len(password))
