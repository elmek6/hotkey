"""Basili gesture tusu icin gecici, odak almayan yon overlay'i."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget


class GestureOverlay(QWidget):
    """F13/F18 gesture durumunu alti hucreli yarim saydam bir panelde cizer."""

    WIDTH = 246
    HEIGHT = 162
    CELL_W = 82
    CELL_H = 54
    BG = QColor(18, 24, 32, 190)
    BORDER = QColor(230, 237, 243, 205)
    TEXT = QColor(230, 237, 243, 245)
    DIM = QColor(139, 148, 158, 220)
    HIGHLIGHT = QColor(31, 111, 235, 220)
    HIGHLIGHT_BORDER = QColor(88, 166, 255, 255)

    def __init__(self) -> None:
        super().__init__(None)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._phase = ""
        self._direction = ""
        self._values: dict[str, str] = {}

    def update_state(
        self,
        phase: str = "",
        direction: str = "",
        values: dict[str, str] | None = None,
    ) -> None:
        self._phase = phase
        self._direction = direction
        if values is not None:
            self._values = values
        self._place()
        self.show()
        self.raise_()
        self.update()

    def clear_state(self) -> None:
        self._phase = ""
        self._direction = ""
        self._values.clear()
        self.hide()

    def _place(self) -> None:
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = cursor.x() - self.WIDTH // 2
        y = cursor.y() - self.HEIGHT // 2
        x = max(area.left() + 4, min(x, area.right() - self.WIDTH - 4))
        y = max(area.top() + 4, min(y, area.bottom() - self.HEIGHT - 4))
        self.move(x, y)

    def _cell(self, column: int, row: int) -> tuple[int, int, int, int]:
        return (
            column * self.CELL_W,
            row * self.CELL_H,
            self.CELL_W,
            self.CELL_H,
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self.BG)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(1, 1, self.WIDTH - 2, self.HEIGHT - 2, 4, 4)

        cells = {
            "U": (self.CELL_W, 0, self.CELL_W, self.CELL_H),
            "L": (0, self.CELL_H, self.CELL_W, self.CELL_H),
            "P": (self.CELL_W, self.CELL_H, self.CELL_W, self.CELL_H // 2),
            "S": (self.CELL_W, self.CELL_H + self.CELL_H // 2, self.CELL_W, self.CELL_H // 2),
            "R": (self.CELL_W * 2, self.CELL_H, self.CELL_W, self.CELL_H),
            "D": (self.CELL_W, self.CELL_H * 2, self.CELL_W, self.CELL_H),
        }
        for name, rect in cells.items():
            x, y, width, height = rect
            active = name in {self._phase, self._direction}
            painter.setBrush(self.HIGHLIGHT if active else QColor(0, 0, 0, 22))
            painter.setPen(QPen(self.HIGHLIGHT_BORDER if active else self.BORDER, 2))
            painter.drawRect(x, y, width, height)
            painter.setPen(self.TEXT if active else self.DIM)
            if name in "ULRD":
                value = self._values.get(name, "")
                font = QFont("Segoe UI")
                font.setPointSize(10 if value else 14)
                painter.setFont(font)
                painter.drawText(x, y + 20, width, 18, Qt.AlignmentFlag.AlignCenter, name)
                if value:
                    painter.setFont(QFont("Segoe UI", 10))
                    painter.drawText(x, y + 35, width, 16, Qt.AlignmentFlag.AlignCenter, value)
            else:
                font = QFont("Segoe UI")
                font.setPointSize(14)
                painter.setFont(font)
                painter.drawText(x, y, width, height, Qt.AlignmentFlag.AlignCenter, name)
        painter.end()
