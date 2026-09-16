from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QFont, QGuiApplication
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget


class GestureOverlay(QWidget):
    """Basili gesture tusu icin gecici, odak almayan yon overlay'i."""

    WIDTH = 282
    HEIGHT = 188
    #: Overlay kac saniye sonra kendiliginden kaybolsun. 0 = tus birakilana
    #: kadar (dispatch `_end_gesture` / hide ile kapanir).
    ACTIVE_SECONDS = 0

    BG = "rgba(18, 24, 32, 235)"
    NORMAL_BG = "rgba(32, 40, 50, 210)"
    ACTIVE_BG = "rgba(45, 115, 220, 240)"
    TEXT = "#E6EDF3"
    DIM = "#AAB4C0"

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

        self.setStyleSheet(
            f"""
            QWidget {{
                background: {self.BG};
                border-radius: 12px;
            }}
            """
        )

        self._phase = ""
        self._direction = ""
        self._labels: dict[str, str] = {}
        self._counts: dict[str, str] = {}
        self._expired = False

        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._expire)

        self._tiles: dict[str, QLabel] = {}
        self._grid = QGridLayout(self)
        self._s_span = False
        self._create_tiles()

    def _create_tiles(self) -> None:
        layout = self._grid
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(6)

        for i in range(3):
            layout.setColumnStretch(i, 1)

        for i in range(4):
            layout.setRowStretch(i, 1)

        self._tiles["U"] = self._create_tile()
        self._tiles["L"] = self._create_tile()
        self._tiles["P"] = self._create_tile()
        self._tiles["S"] = self._create_tile()
        self._tiles["R"] = self._create_tile()
        self._tiles["D"] = self._create_tile()

        layout.addWidget(self._tiles["U"], 0, 1)
        layout.addWidget(self._tiles["L"], 1, 0, 2, 1)
        layout.addWidget(self._tiles["P"], 1, 1)
        layout.addWidget(self._tiles["S"], 2, 1)
        layout.addWidget(self._tiles["R"], 1, 2, 2, 1)
        layout.addWidget(self._tiles["D"], 3, 1)

    def _place_center(self, s_only: bool) -> None:
        """S ikinci asamada P+S hucrelerini kaplar."""
        if s_only == self._s_span:
            return
        self._s_span = s_only
        p_tile = self._tiles["P"]
        s_tile = self._tiles["S"]
        self._grid.removeWidget(p_tile)
        self._grid.removeWidget(s_tile)
        if s_only:
            self._grid.addWidget(s_tile, 1, 1, 2, 1)
        else:
            self._grid.addWidget(p_tile, 1, 1)
            self._grid.addWidget(s_tile, 2, 1)

    def _create_tile(self) -> QLabel:
        tile = QLabel()
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        return tile

    def update_state(
        self,
        phase: str = "",
        direction: str = "",
        labels: dict[str, str] | None = None,
        counts: dict[str, str] | None = None,
    ) -> None:
        if self._expired:
            return

        self._phase = phase
        self._direction = direction

        if labels is not None:
            self._labels = labels

        if counts is not None:
            self._counts = counts

        self._refresh()
        self._place()
        self.show()
        self.raise_()

    def begin(
        self,
        phase: str,
        labels: dict[str, str],
    ) -> None:
        self._expired = False
        self._timeout.stop()
        if self.ACTIVE_SECONDS > 0:
            self._timeout.start(int(self.ACTIVE_SECONDS * 1000))
        self.update_state(phase, "", labels, {})

    def clear_state(self) -> None:
        self._phase = ""
        self._direction = ""
        self._labels.clear()
        self._counts.clear()
        self._expired = False
        self._place_center(False)
        self._timeout.stop()
        self.hide()

    def _expire(self) -> None:
        self._expired = True
        self.hide()

    def _refresh(self) -> None:
        locked = self._direction in "UDLR" and bool(self._direction)
        allowed_axes = None
        if self._direction in ("U", "D"):
            allowed_axes = {"U", "D"}
        elif self._direction in ("L", "R"):
            allowed_axes = {"L", "R"}

        s_only = not locked and self._phase == "S"
        self._place_center(s_only)

        for name, tile in self._tiles.items():
            if name in "ULRD":
                visible = name in self._labels and (
                    allowed_axes is None or name in allowed_axes
                )
                is_active = visible and name == self._direction
            elif name == "P":
                visible = not locked and self._phase != "S"
                is_active = visible and self._phase == "P"
            else:
                visible = not locked
                is_active = visible and self._phase == "S"
            tile.setVisible(visible)
            if not visible:
                continue

            label = self._labels.get(name) or name
            value = self._counts.get(name, "")

            if name in "ULRD":
                if is_active and value:
                    text = f"{label}\n{value}"
                else:
                    text = label

                font = QFont(
                    "Segoe UI",
                    11 if value or label != name else 14,
                )
            else:
                text = label
                font = QFont("Segoe UI", 22 if s_only and name == "S" else 14)

            tile.setText(text)
            tile.setFont(font)

            background = self.ACTIVE_BG if is_active else self.NORMAL_BG

            color = self.TEXT if is_active else self.DIM

            tile.setStyleSheet(
                f"""
                QLabel {{
                    background: {background};
                    color: {color};
                    border: none;
                    border-radius: 9px;
                    padding: 2px;
                }}
                """
            )

    def _place(self) -> None:
        cursor = QCursor.pos()

        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()

        if screen is None:
            return

        area = screen.availableGeometry()

        x = cursor.x() - self.WIDTH // 2
        y = cursor.y() - self.HEIGHT // 2

        x = max(
            area.left() + 4,
            min(x, area.right() - self.WIDTH - 4),
        )

        y = max(
            area.top() + 4,
            min(y, area.bottom() - self.HEIGHT - 4),
        )

        self.move(x, y)
