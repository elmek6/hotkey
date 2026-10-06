"""Eksen kilidi -- fare hareketini adima ceviren "jest" modeli.

Kilitli alana girince imlec bir eksende sabitlenir (pencere onu her
harekette geri tasir); o eksendeki hareket adima cevrilir: her `STEP_PX`
piksel bir adim, yukari/sola +1, asagi/saga -1. Diger eksen serbest.

Qt yok: pencere yalnizca imlecin eksendeki konumunu verir, adim sayisini
buradan alir. (radial dalindaki core/radial.py'de ayni sinif var; birlesince
oradan buraya baglanmali.)
"""

from __future__ import annotations

from enum import Enum

#: Bir adim icin gereken hareket (piksel).
STEP_PX = 12


class Axis(Enum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"


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
