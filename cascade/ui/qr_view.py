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
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from cascade import qr, theme
from cascade.ui.place import center_on_cursor_screen

#: Icerik bu surumun uzerine cikarsa kare gozle okunamayacak kadar
#: sikilasiyor -- uyari veriliyor, engellenmiyor.
WARN_VERSION = 20


class QrDialog(QWidget):
    """Sablon secimi + alanlar + canli kare. Esc kapatir."""

    def __init__(self, initial_text: str = "") -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("QR kod")
        self._fields: dict[str, QWidget] = {}
        self._content = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

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

        # Panodan gelen metin ILK alana dusuyor: sablonu ondan tahmin
        # ettik, tahmin dogruysa dogru alana gitmis olur.
        if initial and item.fields:
            first = self._fields[item.fields[0].key]
            if isinstance(first, QLineEdit):
                first.setText(initial)
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
    return content.replace(password, "•" * len(password))
