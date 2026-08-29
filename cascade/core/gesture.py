"""Fare jesti -- AHK'deki HotGestures.ahk'nin bize gereken kadari.

AHK kutuphanesi genel amacli bir sekil tanuyucuydu: vektor dizisi biriktirip
DTW benzeri bir mesafe matrisiyle kayitli sekillere benzetiyordu (`Gesture`,
`DistanceMatrix`, cizim tahtasi). Bize gereken o degil -- dort ana yon ve
"kac kademe" bilgisi. O yuzden sekil tanima degil, **eksen kilitli adim
sayaci** yazildi: cok daha ucuz (hareket basina birkac cikarma) ve
callback'in icinden cagrilacak kadar hizli.

Nasil calisir:

    onek tusu basilir            -> imlecin o anki yeri capa olur
    fare `step_px` kadar gider   -> baskin eksen KILITLENIR (up/down/left/right)
    her `step_px` kadar daha     -> bir adim daha uretilir

Eksen neden kilitleniyor: kilitlemezsen hafif capraz bir hareket sirayla
"up" ve "left" uretir, ses hem acilip hem kisilir. AHK'de bunun karsiligi
`Excluded` bayragiydi -- bir sekil bir kez elendi mi geri donmuyordu.

Geri sayim degeri **adim sayisi**: cagiran onu "sesi kac kademe artir"
diye kullanir. Cikti bir olay listesi, callable degil -- core'un geri
kalaniyla ayni kural.

Jest bir kez tetiklendiginde onek tusu "kullanildi" sayilir: birakilinca ne
menu acilir ne tusun kendisi geri gonderilir. Istenen davranis buydu.

Saf Python: Win32 yok, Qt yok, zaman disaridan bile gerekmiyor -- yalniz
koordinat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

DEFAULT_STEP_PX = 60.0


class Direction(IntEnum):
    UP = 1
    DOWN = 2
    LEFT = 3
    RIGHT = 4

    @property
    def label(self) -> str:
        return {
            Direction.UP: "yukari",
            Direction.DOWN: "asagi",
            Direction.LEFT: "sola",
            Direction.RIGHT: "saga",
        }[self]


@dataclass(frozen=True, slots=True)
class GestureDef:
    """`onek tusu + yon -> eylem`. AHK: hgs.Register(gesture, comment, cb)."""

    prefix: int
    direction: Direction
    action: str
    desc: str = ""


@dataclass(frozen=True, slots=True)
class GestureEvent:
    """Uretilen jest. `steps` o darbede kac kademe ilerlendigi."""

    prefix: int
    direction: Direction
    steps: int
    action: str
    desc: str = ""


def _direction(dx: float, dy: float) -> Direction:
    """Baskin eksen. Ekran koordinatinda y ASAGI dogru buyur."""
    if abs(dx) >= abs(dy):
        return Direction.RIGHT if dx > 0 else Direction.LEFT
    return Direction.DOWN if dy > 0 else Direction.UP


def _advance(direction: Direction, dx: float, dy: float) -> float:
    """Kilitli yonde ne kadar ilerlendi. Geri gidis negatif."""
    if direction is Direction.RIGHT:
        return dx
    if direction is Direction.LEFT:
        return -dx
    if direction is Direction.DOWN:
        return dy
    return -dy


@dataclass
class _Active:
    """Basili duran bir onek tusunun jest durumu."""

    x: float
    y: float
    direction: Direction | None = None
    fired: bool = False


@dataclass
class GestureTracker:
    """Basili onek tuslarini ve altlarindaki fare hareketini izler.

    `start`/`stop` hook thread'inde, `move` de oyle. Sozluk islemi disinda
    is yapmaz; hareket basina birkac cikarma ve karsilastirma.
    """

    defs: dict[tuple[int, Direction], GestureDef] = field(default_factory=dict)
    step_px: float = DEFAULT_STEP_PX
    _active: dict[int, _Active] = field(default_factory=dict, init=False)

    # ---- tanim ----

    def register(
        self, prefix: int, direction: Direction, action: str, desc: str = ""
    ) -> GestureTracker:
        self.defs[(prefix, direction)] = GestureDef(prefix, direction, action, desc)
        return self

    def has(self, prefix: int) -> bool:
        """Bu onek tusunun tanimli jesti var mi -- callback'in hizli elemesi."""
        return any(key[0] == prefix for key in self.defs)

    @property
    def watching(self) -> bool:
        """Su an jest izlenen bir tus basili mi. Fare hareketi bu bayrak
        kapaliyken hic islenmez."""
        return bool(self._active)

    # ---- besleme ----

    def start(self, prefix: int, x: float, y: float) -> None:
        """Onek tusu basildi: imlecin yeri capa olur. AHK: Start()."""
        if self.has(prefix):
            self._active[prefix] = _Active(x=x, y=y)

    def move(self, x: float, y: float) -> list[GestureEvent]:
        """Fare kimildadi. Basili her onek icin uretilen adimlari doner."""
        if not self._active:
            return []
        events: list[GestureEvent] = []
        for prefix, state in self._active.items():
            dx = x - state.x
            dy = y - state.y

            if state.direction is None:
                if max(abs(dx), abs(dy)) < self.step_px:
                    continue
                candidate = _direction(dx, dy)
                if (prefix, candidate) not in self.defs:
                    continue  # bu yon icin tanim yok: kilitleme, beklemeye devam
                state.direction = candidate

            moved = _advance(state.direction, dx, dy)
            steps = int(moved // self.step_px)
            if steps <= 0:
                continue  # geri gidis ya da esigin altinda: capa yerinde kalir

            definition = self.defs[(prefix, state.direction)]
            state.fired = True
            # Capayi tuketilen kadar ileri tasi: kalan mesafe bir sonraki
            # adima sayilsin, yoksa yavas hareket hic adim uretmezdi.
            consumed = steps * self.step_px
            if state.direction is Direction.RIGHT:
                state.x += consumed
            elif state.direction is Direction.LEFT:
                state.x -= consumed
            elif state.direction is Direction.DOWN:
                state.y += consumed
            else:
                state.y -= consumed

            events.append(
                GestureEvent(
                    prefix=prefix,
                    direction=state.direction,
                    steps=steps,
                    action=definition.action,
                    desc=definition.desc,
                )
            )
        return events

    def stop(self, prefix: int) -> bool:
        """Onek birakildi. Jest tetiklendiyse True -- cagiran o zaman ne menu
        acar ne tusu geri gonderir."""
        state = self._active.pop(prefix, None)
        return bool(state and state.fired)

    def fired(self, prefix: int) -> bool:
        state = self._active.get(prefix)
        return bool(state and state.fired)

    def reset(self) -> None:
        self._active.clear()

    @property
    def tips(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (f"{definition.direction.label}", definition.desc)
            for definition in self.defs.values()
            if definition.desc
        )
