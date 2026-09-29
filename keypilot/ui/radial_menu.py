"""Radyal menu penceresi -- imlecin cevresinde acilan halkalar (core/radial.py).

Yuzen, odak ALMAYAN pencere: tiklama alttaki uygulamanin odagini
degistirmez, yapistirma oraya gider. Kapanis iki yoldan:

  * bir ogeye tiklamak -- is yapilir, menu kapanir;
  * pembe halkaya (ya da disina) degmek -- hicbir sey yapilmaz.

Kose pikselleri saydam oldugu icin fare oralardan pencereyi terk eder;
`leaveEvent` de kapatir.

Kilitli yon (ornek: sol, dikey): sektore girince imlec o yukseklikte
sabitlenir, dikey hareket `AxisLock` ile +1/-1 adima cevrilip ogenin
`step_up` / `step_down` eylemi calistirilir. Yatay serbest.

Alt menulu yon tiklaninca menu kapanir ve klasik menu (win32) ayni noktada
acilir.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from keypilot.core.radial import (
    CLOSE_R,
    DIRECTION_SPANS,
    EDGE_R,
    HOLE_R,
    INNER_R,
    OUTER_COUNT,
    OUTER_R,
    OUTER_SPAN,
    Axis,
    AxisLock,
    Hit,
    RadialItem,
    RadialSpec,
    Zone,
    fit_center,
    hit,
    item_at,
)

INNER_BG = QColor("#3b7dd8")
OUTER_BG = QColor("#5b94de")
EMPTY_BG = QColor("#c9d9f0")
HOVER_BG = QColor("#9dc1f2")
LOCK_BG = QColor("#2a5fb0")
GAP_BG = QColor("#ffffff")
CLOSE_BG = QColor("#ed6ea7")
TEXT = QColor("#ffffff")
HINT_TEXT = QColor("#1f2228")

#: Dilimler arasindaki beyaz cizgi (piksel).
SEPARATOR = 3
#: Ic halka ile dis halka arasindaki beyaz aralik.
RING_GAP = 6


def _sector(center: float, r0: float, r1: float, start: float, end: float) -> QPainterPath:
    """Halka dilimi. Acilar 0 = yukari, saat yonunde (core/radial.py)."""
    outer = QRectF(center - r1, center - r1, 2 * r1, 2 * r1)
    inner = QRectF(center - r0, center - r0, 2 * r0, 2 * r0)
    sweep = end - start
    path = QPainterPath()
    path.arcMoveTo(outer, 90 - start)
    path.arcTo(outer, 90 - start, -sweep)
    path.arcTo(inner, 90 - end, sweep)
    path.closeSubpath()
    return path


def _point(center: float, radius: float, angle: float) -> QPointF:
    rad = math.radians(angle)
    return QPointF(center + radius * math.sin(rad), center - radius * math.cos(rad))


class RadialMenu(QWidget):
    """Tek ornek: app.py tutuyor, her acilista imlecin cevresine tasiniyor."""

    def __init__(
        self,
        spec: RadialSpec,
        run: Callable[[str], None],
        show_menu: Callable[[tuple], None],
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFixedSize(2 * EDGE_R, 2 * EDGE_R)
        self.spec = spec
        self._run = run
        self._show_menu = show_menu
        self._hit = Hit(Zone.HOLE)
        self._lock: AxisLock | None = None
        self._lock_item: RadialItem | None = None

    # ---- disari ----

    def open_at_cursor(self) -> None:
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        cx, cy = pos.x(), pos.y()
        if screen is not None:
            area = screen.availableGeometry()
            cx, cy = fit_center(cx, cy, (area.x(), area.y(), area.width(), area.height()))
        if (cx, cy) != (pos.x(), pos.y()):
            QCursor.setPos(cx, cy)
        self.move(cx - EDGE_R, cy - EDGE_R)
        self._hit = Hit(Zone.HOLE)
        self._release_lock()
        self.show()
        self.raise_()

    def track(self, dx: float, dy: float) -> None:
        """Merkeze gore imlec konumu. Kilit, hover ve kapanis burada."""
        if self._lock is not None:
            if self._lock.axis is Axis.VERTICAL:
                steps = self._lock.feed(dy)
                dy = self._lock.anchor
            else:
                steps = self._lock.feed(dx)
                dx = self._lock.anchor
            self._pin(dx, dy)
            self._step(steps)
        where = hit(dx, dy)
        if where.zone is Zone.CLOSE:
            self.close()
            return
        item = item_at(self.spec, where)
        if self._lock is not None and item is not self._lock_item:
            self._release_lock()
        if self._lock is None and item is not None and item.lock is not None:
            self._lock_item = item
            anchor = dy if item.lock is Axis.VERTICAL else dx
            self._lock = AxisLock(item.lock, anchor)
        if where != self._hit:
            self._hit = where
            self.update()

    def click(self) -> None:
        """Uzerindeki ogeyi calistirir ve kapanir. Delik/aralik bos."""
        item = item_at(self.spec, self._hit)
        if item is None:
            return
        self.close()
        if item.lock is not None:
            return
        if item.menu is not None:
            menu = item.menu
            QTimer.singleShot(0, lambda: self._show_menu(menu))
        elif item.action:
            action = item.action
            QTimer.singleShot(0, lambda: self._run(action))

    @property
    def locked(self) -> bool:
        return self._lock is not None

    # ---- ic ----

    def _step(self, steps: int) -> None:
        item = self._lock_item
        if item is None or not steps:
            return
        action = item.step_up if steps > 0 else item.step_down
        if not action:
            return
        for _ in range(abs(steps)):
            self._run(action)

    def _pin(self, dx: float, dy: float) -> None:
        """Imleci kilit eksenindeki sabit noktaya geri tasir."""
        target = self.mapToGlobal(QPoint(round(EDGE_R + dx), round(EDGE_R + dy)))
        if QCursor.pos() != target:
            QCursor.setPos(target)

    def _release_lock(self) -> None:
        self._lock = None
        self._lock_item = None

    # ---- olaylar ----

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        self.track(pos.x() - EDGE_R, pos.y() - EDGE_R)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.click()

    def leaveEvent(self, event) -> None:
        self.close()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:
        self._release_lock()
        super().hideEvent(event)

    # ---- cizim ----

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = float(EDGE_R)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(CLOSE_BG)
        painter.drawEllipse(QPointF(center, center), EDGE_R - 2, EDGE_R - 2)
        painter.setBrush(GAP_BG)
        painter.drawEllipse(QPointF(center, center), CLOSE_R, CLOSE_R)

        separator = QPen(GAP_BG, SEPARATOR)
        painter.setPen(separator)
        for index in range(OUTER_COUNT):
            start = index * OUTER_SPAN - OUTER_SPAN / 2
            item = self.spec.outer[index] if index < len(self.spec.outer) else None
            hovered = self._hit.zone is Zone.OUTER and self._hit.index == index
            painter.setBrush(HOVER_BG if hovered else OUTER_BG if item else EMPTY_BG)
            painter.drawPath(
                _sector(center, INNER_R + RING_GAP, OUTER_R, start, start + OUTER_SPAN)
            )

        for direction, (start, end) in DIRECTION_SPANS.items():
            item = self.spec.directions.get(direction)
            hovered = self._hit.zone is Zone.DIRECTION and self._hit.direction == direction
            if hovered and self._lock is not None:
                color = LOCK_BG
            elif hovered:
                color = HOVER_BG
            else:
                color = INNER_BG if item else EMPTY_BG
            painter.setBrush(color)
            painter.drawPath(_sector(center, HOLE_R + RING_GAP, INNER_R, start, end))

        painter.setPen(TEXT)
        bold = QFont(self.font())
        bold.setBold(True)
        bold.setPointSizeF(bold.pointSizeF() + 1)
        painter.setFont(bold)
        for index, item in enumerate(self.spec.outer[:OUTER_COUNT]):
            self._label(
                painter, center, (INNER_R + OUTER_R) / 2, index * OUTER_SPAN, item.label, 52
            )

        painter.setFont(self.font())
        for direction, (start, end) in DIRECTION_SPANS.items():
            item = self.spec.directions.get(direction)
            if item is not None:
                self._label(
                    painter, center, (HOLE_R + INNER_R) / 2 + 6, (start + end) / 2, item.label, 96
                )

        item = item_at(self.spec, self._hit)
        if item is not None:
            small = QFont(self.font())
            small.setPointSizeF(max(6.0, small.pointSizeF() - 2))
            painter.setFont(small)
            painter.setPen(HINT_TEXT)
            box = QRectF(center - HOLE_R, center - HOLE_R, 2 * HOLE_R, 2 * HOLE_R)
            painter.drawText(
                box, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, item.caption
            )
        painter.end()

    @staticmethod
    def _label(
        painter: QPainter, center: float, radius: float, angle: float, text: str, width: int
    ) -> None:
        at = _point(center, radius, angle)
        box = QRectF(at.x() - width / 2, at.y() - 22, width, 44)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
