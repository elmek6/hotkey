"""Duraklatma penceresi -- menus.ahk `DialogPauseGui` portu.

AHK'de bu pencere acilir acilmaz `Suspend(1)` cagriliyordu: program
duraklar, pencere kapanınca ya da "Play" ile devam eder. Dort dugme de
aynen korundu; "Kaydetmeden yeniden baslat" AHK'nin
`setShouldSaveOnExit(false) + Reload` ikilisidir -- pano dosyasi bozuk
gorunuyorsa uzerine yazmadan yeniden baslatmaya yarar.

Modeless: `exec()` ile acilmiyor. Modal dialog kendi olay dongusunu
kuruyor ve o dongude bizim `_drain` / `_tick` zamanlayicilarimiz da
donuyor -- duraklatilmis programda tus kuyrugunu isletmek istemiyoruz.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

#: (etiket, sinyal adi) -- sira AHK'deki dugme sirasi.
BUTTONS = (
    ("▶️  Devam et", "resume"),
    ("\U0001f501  Kaydetmeden yeniden baslat", "restart_nosave"),
    ("\U0001f501  Yeniden baslat", "restart"),
    ("\U0001f6d1  Cikis", "exit"),
)


class PauseDialog(QWidget):
    """Duraklatildi penceresi. Kapatilinca (X / Esc) program devam eder."""

    resume = Signal()
    restart_nosave = Signal()
    restart = Signal()
    exit_app = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowTitle("⏸️ cascade durduruldu")
        self._closing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel("Program duraklatildi -- tuslar dokunulmadan geciyor.")
        title.setStyleSheet("color: #8b949e;")
        layout.addWidget(title)

        signals = {
            "resume": self.resume,
            "restart_nosave": self.restart_nosave,
            "restart": self.restart,
            "exit": self.exit_app,
        }
        for label, name in BUTTONS:
            button = QPushButton(label, self)
            button.setMinimumHeight(38)
            # Kapanma SIRASI onemli: once pencere kapanir, sonra sinyal --
            # "Cikis" sinyali programi kapatiyor, once o kosarsa pencere
            # ekranda asili kalıyordu.
            button.clicked.connect(lambda _c=False, s=signals[name]: self._fire(s))
            layout.addWidget(button)

        self._message = QLabel("")
        self._message.setWordWrap(True)
        self._message.setStyleSheet("color: #f85149;")
        self._message.hide()
        layout.addWidget(self._message)

    def show_paused(self, critical: str = "") -> None:
        """AHK `DialogPauseGui(criticalMsg)` -- kritik hata metni istege bagli."""
        self._message.setVisible(bool(critical))
        if critical:
            self._message.setText(f"⚠ KRITIK HATA:\n{critical}")
        self.adjustSize()
        self.show()
        self.raise_()
        self.activateWindow()

    def _fire(self, signal) -> None:
        self._closing = True  # kapanis "devam et" saymasin
        self.close()
        self._closing = False
        signal.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        """X / Esc: AHK'de de pencere kapaninca `Suspend(0)` calisiyordu."""
        if not self._closing:
            self.resume.emit()
        super().closeEvent(event)
