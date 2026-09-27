from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QFont, QGuiApplication
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from keypilot.core.hot_vectors import Cell


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

        self._phase: Cell | None = None
        self._direction: Cell | None = None
        self._labels: dict[Cell, str] = {}
        self._counts: dict[Cell, str] = {}
        self._expired = False

        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._expire)

        self._tiles: dict[Cell, QLabel] = {}
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

        for cell in (Cell.UP, Cell.LEFT, Cell.P, Cell.S, Cell.RIGHT, Cell.DOWN):
            self._tiles[cell] = self._create_tile()

        layout.addWidget(self._tiles[Cell.UP], 0, 1)
        layout.addWidget(self._tiles[Cell.LEFT], 1, 0, 2, 1)
        layout.addWidget(self._tiles[Cell.P], 1, 1)
        layout.addWidget(self._tiles[Cell.S], 2, 1)
        layout.addWidget(self._tiles[Cell.RIGHT], 1, 2, 2, 1)
        layout.addWidget(self._tiles[Cell.DOWN], 3, 1)

    def _place_center(self, s_only: bool) -> None:
        """S ikinci asamada P+S hucrelerini kaplar."""
        if s_only == self._s_span:
            return
        self._s_span = s_only
        p_tile = self._tiles[Cell.P]
        s_tile = self._tiles[Cell.S]
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
        phase: Cell | None = None,
        direction: Cell | None = None,
        labels: dict[Cell, str] | None = None,
        counts: dict[Cell, str] | None = None,
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
        phase: Cell | None,
        labels: dict[Cell, str],
    ) -> None:
        self._expired = False
        self._timeout.stop()
        if self.ACTIVE_SECONDS > 0:
            self._timeout.start(int(self.ACTIVE_SECONDS * 1000))
        self.update_state(phase, None, labels, {})

    def clear_state(self) -> None:
        self._phase = None
        self._direction = None
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
        direction = self._direction
        axis = direction if direction is not None and direction.is_direction else None
        locked = axis is not None

        s_only = not locked and self._phase == Cell.S
        self._place_center(s_only)

        for name, tile in self._tiles.items():
            if name.is_direction:
                # Kilitli yon varsa yalniz onun ekseni gorunur.
                visible = name in self._labels and (
                    axis is None or name.vertical == axis.vertical
                )
                is_active = visible and name == direction
            elif name == Cell.P:
                visible = not locked and self._phase != Cell.S
                is_active = visible and self._phase == Cell.P
            else:
                visible = not locked
                is_active = visible and self._phase == Cell.S
            tile.setVisible(visible)
            if not visible:
                continue

            label = self._labels.get(name) or name
            value = self._counts.get(name, "")

            if name.is_direction:
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
                font = QFont("Segoe UI", 22 if s_only and name == Cell.S else 14)

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
