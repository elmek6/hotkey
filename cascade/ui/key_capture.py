"""Kisayol yakalama kutusu -- "tusa bas" alani.

Programda buna kadar KISAYOL SORAN bir arayuz yoktu: tuslar keymap.py'de
yaziliydi, kullanicinin gordugu tek tus yuzeyi ise key history penceresiydi
(ne olup bittigini izler, tus atamaz). Windows'un kisayol kutularinin
yaptigi is burada: kutuya odaklanirsin, tusa basarsin, kutu o tusun ADINI
alir.

Neden dogrudan Qt olayi: kutu acikken dispatcher susturuluyor
(`ui_open`), yani dusuk seviye hook araya girmiyor ve tus normal bir Qt
`keyPressEvent` olarak geliyor. Tus adini `nativeVirtualKey` uzerinden
cozuyoruz -- Qt'nin kendi tus sabitleri degil VK numarasi, cunku programin
geri kalani (keynames, hotkey, dispatch) VK ile konusuyor. F13/F14 gibi
klavyede olmayan ama farenin urettigi tuslar da boylece dogru adlaniyor.

Uretilen metin `parse_hotkey`in anladigi bicimde: `F4`, `Ctrl+Shift+K`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton

from cascade.core.keynames import key_name

#: Tek baslarina kisayol OLMAYAN tuslar: basili tutulurken oteki tusu
#: bekliyoruz, yakalama bunlarda bitmemeli.
_MODIFIER_VKS = frozenset({0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5})

_MOD_WORDS = (
    (Qt.KeyboardModifier.ControlModifier, "Ctrl"),
    (Qt.KeyboardModifier.AltModifier, "Alt"),
    (Qt.KeyboardModifier.ShiftModifier, "Shift"),
    (Qt.KeyboardModifier.MetaModifier, "Win"),
)


class KeyCapture(QPushButton):
    """Tiklaninca tus bekleyen dugme. Secilen kisayolu metin olarak tutar.

    Esc yakalamayi iptal eder (kutu eski degerinde kalir), Backspace/Delete
    kisayolu SILER -- "bu kurala tus atamak istemiyorum" da bir cevap.
    """

    changed = Signal(str)

    def __init__(self, spec: str = "", parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self._armed = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setCheckable(True)
        self.clicked.connect(self._arm)
        self._refresh()

    @property
    def spec(self) -> str:
        return self._spec

    def set_spec(self, spec: str) -> None:
        self._spec = spec
        self._refresh()

    def _refresh(self) -> None:
        if self._armed:
            self.setText("tusa bas...")
        else:
            self.setText(self._spec or "kisayol yok")
        self.setChecked(self._armed)

    def _arm(self) -> None:
        self._armed = True
        self._refresh()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        # Klavye kaydi: yakalama sirasinda tus BASKA widget'a gitmesin --
        # Tab odagi degistirir, bosluk dugmeye basardi.
        self.grabKeyboard()

    def _disarm(self) -> None:
        if self._armed:
            self._armed = False
            self.releaseKeyboard()
            self._refresh()

    def keyPressEvent(self, event) -> None:
        if not self._armed:
            super().keyPressEvent(event)
            return
        vk = event.nativeVirtualKey()
        if vk in _MODIFIER_VKS:
            return  # modifier tek basina kisayol degil: oteki tusu bekle
        if event.key() == Qt.Key.Key_Escape:
            self._disarm()
            return
        if event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self._spec = ""
            self._disarm()
            self.changed.emit(self._spec)
            return
        name = key_name(vk)
        if not name:
            return  # tanimadigimiz tus: yakalamayi bozma, bekle
        mods = [word for flag, word in _MOD_WORDS if event.modifiers() & flag]
        self._spec = "+".join([*mods, name])
        self._disarm()
        self.changed.emit(self._spec)

    def focusOutEvent(self, event) -> None:
        # Odak giderse yakalama asili kalmasin: klavye kaydi birakilmazsa
        # pencerenin geri kalani tus almaz.
        self._disarm()
        super().focusOutEvent(event)
