"""Radyal menu modeli -- halka geometrisi, isabet hesabi, yon kilidi.

Qt yok, Win32 yok: pencere (ui/radial_menu.py) yalnizca cizer ve fare
konumunu buraya sorar. Boylece "imlec su noktadayken hangi dilim" ve "kilitte
kac adim sayildi" sorulari ekransiz test edilebiliyor.

Halkalar merkezden disa:

    delik    (HOLE_R)          bos, uzerine gelinen ogenin adi yazar
    ic halka (INNER_R)         4 yon: UP / RIGHT / DOWN / LEFT, 90'ar derece
    dis halka (OUTER_R)        12 dilim, saat gibi: 1 ustte, saat yonunde
    bosluk   (CLOSE_R)         beyaz aralik, isabet yok
    pembe    (EDGE_R)          degince menu kapanir

Acilar ekran koordinatinda: 0 derece yukari, saat yonunde artar (dy asagi
pozitif).

YON KILIDI: kilitli yonun sektorune girince imlec o eksende sabitlenir
(pencere geri tasir), eksen boyunca hareket `AxisLock` ile adima cevrilir:
her `STEP_PX` piksel bir adim, yukari/sola +1. Diger eksen serbest; o eksende
sektorden cikinca kilit biter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from keypilot.core.hot_vectors import Direction

HOLE_R = 34
INNER_R = 132
OUTER_R = 200
CLOSE_R = 212
EDGE_R = 232

OUTER_COUNT = 12
OUTER_SPAN = 360 / OUTER_COUNT

#: Kilitte bir adim icin gereken hareket (piksel).
STEP_PX = 12

#: Yon sektorleri: (baslangic, bitis) derece, saat yonunde.
DIRECTION_SPANS: dict[Direction, tuple[float, float]] = {
    Direction.UP: (-45, 45),
    Direction.RIGHT: (45, 135),
    Direction.DOWN: (135, 225),
    Direction.LEFT: (225, 315),
}


class Axis(Enum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"


@dataclass(frozen=True)
class RadialItem:
    """Bir dilim. Uc turden biri: eylem, alt menu ya da kilitli yon.

    `label` dilimin ustunde, `hint` (bossa `label`) ortadaki delikte yazar.
    Kilitli yonde `step_up` +1, `step_down` -1 adimda calisir.
    """

    label: str
    action: str = ""
    menu: tuple | None = None
    lock: Axis | None = None
    step_up: str = ""
    step_down: str = ""
    hint: str = ""

    @property
    def caption(self) -> str:
        return self.hint or self.label


@dataclass(frozen=True)
class RadialSpec:
    directions: dict[Direction, RadialItem] = field(default_factory=dict)
    #: Saat yonunde, 1. dilim ustte. En fazla `OUTER_COUNT`.
    outer: tuple[RadialItem, ...] = ()


class Zone(Enum):
    HOLE = "hole"
    DIRECTION = "direction"
    OUTER = "outer"
    GAP = "gap"
    CLOSE = "close"


@dataclass(frozen=True)
class Hit:
    zone: Zone
    direction: Direction | None = None
    #: Dis halkada 0 tabanli dilim (0 = ustteki "1").
    index: int = -1


def angle_of(dx: float, dy: float) -> float:
    """0 = yukari, saat yonunde; [0, 360)."""
    return math.degrees(math.atan2(dx, -dy)) % 360


def hit(dx: float, dy: float) -> Hit:
    """Merkeze gore (dx, dy) noktasi hangi bolgede."""
    radius = math.hypot(dx, dy)
    if radius < HOLE_R:
        return Hit(Zone.HOLE)
    if radius >= CLOSE_R:
        return Hit(Zone.CLOSE)
    if radius >= OUTER_R:
        return Hit(Zone.GAP)
    angle = angle_of(dx, dy)
    if radius < INNER_R:
        return Hit(Zone.DIRECTION, direction=direction_at(angle))
    return Hit(Zone.OUTER, index=int(((angle + OUTER_SPAN / 2) % 360) // OUTER_SPAN))


def direction_at(angle: float) -> Direction:
    for direction, (start, end) in DIRECTION_SPANS.items():
        if start <= angle < end or start <= angle - 360 < end:
            return direction
    return Direction.UP


def item_at(spec: RadialSpec, where: Hit) -> RadialItem | None:
    if where.zone is Zone.DIRECTION and where.direction is not None:
        return spec.directions.get(where.direction)
    if where.zone is Zone.OUTER and 0 <= where.index < len(spec.outer):
        return spec.outer[where.index]
    return None


class AxisLock:
    """Kilitli eksendeki hareketi adima cevirir. Artan kalan birikir.

    `feed` imlecin eksendeki o anki konumunu alir (sabitlenen noktaya gore
    fark buradan cikiyor); pencere her cagridan sonra imleci `anchor`a geri
    tasir. Yukari/sola hareket +1.
    """

    def __init__(self, axis: Axis, anchor: float, step_px: int = STEP_PX) -> None:
        self.axis = axis
        self.anchor = anchor
        self.step_px = step_px
        self._rest = 0.0

    def feed(self, position: float) -> int:
        self._rest += self.anchor - position
        steps = int(self._rest / self.step_px)
        self._rest -= steps * self.step_px
        return steps


def fit_center(
    x: int, y: int, area: tuple[int, int, int, int], radius: int = EDGE_R
) -> tuple[int, int]:
    """Menu merkezi: imlec noktasi, menu ekrana sigmiyorsa iceri kaydirilmis."""
    left, top, width, height = area
    cx = min(max(x, left + radius), left + width - radius)
    cy = min(max(y, top + radius), top + height - radius)
    return cx, cy
