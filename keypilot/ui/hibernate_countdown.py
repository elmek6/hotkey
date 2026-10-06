"""Hibernate'e kalan sure -- tepsi simgesinin ustunde geri sayim penceresi.

Zamanlayicida "Hibernate" isaretliyse son 5 dakikada cikar. Odak calmaz:
kullanici o an baska bir seyle ugrasiyor olabilir.

  * Sure dolunca `expired` -- hibernate'i app yapar.
  * "Cancel Hibernate" dugmesi `cancelled` yayar: hibernate YAPILMAZ.
  * Pencerenin kapatma dugmesi yok, yalniz kucultme: kapatmak "iptal mi,
    gizle mi?" sorusunu doguruyordu. Kucultulse de sayim surer.
  * `stop()` sessizce gizler (app tarafindan kapatma; sinyal yok).

Fare/klavye hareketi sayaci ETKILEMEZ: geri sayim baslamissa kullanici
onu goruyor, calismaya devam etmesi "iptal" demek degil.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

#: Kenar ile tepsi arasindaki bosluk (piksel).
MARGIN = 8

#: Dikkat cekmek icin her dakika basi pencere zemini beyaz/siyah degisir.
FLASH_STEP_MS = 400
FLASH_STEPS = 10
FLASH_STYLES = (
    "background-color: #ffffff; color: #000000;",
    "background-color: #000000; color: #ffffff;",
)


class HibernateCountdown(QWidget):
    expired = Signal()
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Window
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("Hibernate")
        self._deadline = 0.0
        self._last_minute = 0

        title = QLabel("Hibernate countdown", self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("font-size: 22pt; font-weight: bold;")
        cancel = QPushButton("Cancel Hibernate", self)
        cancel.clicked.connect(self._cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self._label)
        layout.addWidget(cancel)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self._flash_left = 0
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(FLASH_STEP_MS)
        self._flash_timer.timeout.connect(self._flash_step)

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def start(self, seconds: float) -> None:
        self._deadline = time.monotonic() + max(0.0, seconds)
        self._refresh()
        self.adjustSize()
        self.showNormal()
        self._place()
        self._timer.start()
        self._last_minute = self._remaining() // 60
        self._start_flash()

    def stop(self) -> None:
        self._timer.stop()
        self._flash_timer.stop()
        self.setStyleSheet("")
        self.hide()

    def _start_flash(self) -> None:
        self._flash_left = FLASH_STEPS
        self._flash_timer.start()

    def _flash_step(self) -> None:
        self._flash_left -= 1
        if self._flash_left <= 0:
            self._flash_timer.stop()
            self.setStyleSheet("")
            return
        self.setStyleSheet(FLASH_STYLES[self._flash_left % 2])

    def _remaining(self) -> int:
        return max(0, round(self._deadline - time.monotonic()))

    def _refresh(self) -> None:
        minutes, seconds = divmod(self._remaining(), 60)
        self._label.setText(f"{minutes}:{seconds:02d}")
        if self.isMinimized():
            # Gorev cubugu dugmesinde de kalan sure okunsun.
            self.setWindowTitle(f"Hibernate {minutes}:{seconds:02d}")
        else:
            self.setWindowTitle("Hibernate")

    def _tick(self) -> None:
        if self._remaining() <= 0:
            self.stop()
            self.expired.emit()
            return
        self._refresh()
        minute = self._remaining() // 60
        if minute != self._last_minute:
            self._last_minute = minute
            self._start_flash()

    def _cancel(self) -> None:
        self.stop()
        self.cancelled.emit()

    def _place(self) -> None:
        """Ana ekranin sag alt kosesi -- tepsi simgeleri orada."""
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        screen = app.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        self.move(
            area.right() - frame.width() - MARGIN + 1,
            area.bottom() - frame.height() - MARGIN + 1,
        )
