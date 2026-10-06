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

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

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
