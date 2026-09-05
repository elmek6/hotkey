"""Slot duzenleme kutusu: ad, slotun eski degeri, yeni deger.

Kutu PANODAKIYLE acilir (pano bossa slotun kendi icerigiyle). Sifre
slotunda eski deger MASKELI gosterilir ve pano bossa kutu BOS acilir.

MODAL DEGIL (`show()`, `exec()` degil): uygulama-modal bir kutu acikken
F13/F14 menuleri calismiyor -- menu de bu uygulamanin penceresi.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from keypilot import theme
from keypilot.store import MASK, PASSWORD_SLOT
from keypilot.ui.place import center_on_cursor_screen
from keypilot.ui.preview import shorten

#: Eski deger etiketinde gosterilen en fazla karakter. Amac hatirlatmak,
#: tam metni gostermek degil -- uzun icerik kutuyu ekran boyuna cikariyordu.
OLD_LIMIT = 160
#: Yeni deger kutusunun yuksekligi (piksel): uc satir. Slot icerigi cogu
#: zaman tek satir; daha buyugu bos yer demek.
VALUE_HEIGHT = 66


class SlotEditDialog(QDialog):
    """Ad + eski deger + yeni deger. Kaydedilince `accepted` yayilir."""

    def __init__(self, index: int, name: str, content: str, proposed: str) -> None:
        super().__init__(None)
        self.setWindowTitle(f"Slot {index % 10}")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumWidth(380)
        # Ust sinir SART: sarmalayan etiket uzun icerikte kutuyu ekran
        # genisligine kadar aciyordu (olculdu: 400 karakterde 932 px).
        self.setMaximumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        layout.addLayout(form)

        self._name = QLineEdit(name, self)
        self._name.setPlaceholderText(f"Slot {index}")
        form.addRow("ad", self._name)

        shown = (
            MASK
            if index == PASSWORD_SLOT and content
            else shorten(" ".join(content.split()), OLD_LIMIT)
        )
        old = QLabel(shown or "(bos)", self)
        old.setWordWrap(True)
        old.setMinimumWidth(1)
        old.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        theme.muted(old)
        form.addRow("eski", old)

        self._value = QPlainTextEdit(proposed, self)
        self._value.setFixedHeight(VALUE_HEIGHT)
        form.addRow("yeni", self._value)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Imlec ad kutusunda: en sik degisen alan o, icerik cogu zaman
        # panodan hazir geliyor.
        self._name.setFocus()
        self.adjustSize()
        center_on_cursor_screen(self)

    def values(self) -> tuple[str, str]:
        return self._name.text(), self._value.toPlainText()
