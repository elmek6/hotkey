"""Fare jesti -- AHK'deki HotGestures.ahk'nin bize gereken kadari.

AHK kutuphanesi genel amacli bir sekil tanuyucuydu: vektor dizisi biriktirip
DTW benzeri bir mesafe matrisiyle kayitli sekillere benzetiyordu (`Gesture`,
`DistanceMatrix`, cizim tahtasi). Bize gereken o degil -- dort ana yon ve
"kac kademe" bilgisi. O yuzden sekil tanima degil, **eksen kilitli adim
sayaci** yazildi: cok daha ucuz (hareket basina birkac cikarma) ve
callback'in icinden cagrilacak kadar hizli.

Nasil calisir:

    onek tusu basilir            -> sayaclar sifirlanir, imlec DONDURULUR
    fare `step_px` kadar gider   -> baskin eksen KILITLENIR (up/down/left/right)
    her `step_px` kadar daha     -> bir adim daha uretilir

Girdi mutlak konum degil **delta**: jest sirasinda imleci yerinde tuttugumuz
icin (dispatch.py hareket olayini yutuyor) mutlak konum akmaz, her olay yalniz o
darbenin ne kadar ittigini soyler. AHK de jest sirasinda imleci sabitliyordu;
sebebi hem yanlislikla bir seye tiklanmasin hem de jest bittiginde imlec
baslangictaki yerinde kalsin.

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

TODO(AHK): hot_vectors.ahk'nin SEKIL TANIMA tarafi port edilmedi -- vektor
    dizisi biriktirip DTW benzeri bir mesafe matrisiyle kayitli sekillere
    benzetme (`Gesture`, `DistanceMatrix`, cizim tahtasi, sekil kaydetme).
    Bilerek: bize gereken dort ana yon ve kademe sayisi. Serbest sekil
    (daire, L, zikzak) istenirse o kod buraya gelmek zorunda.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

DEFAULT_STEP_PX = 60.0

# Yon kilitlenmeden once baskin eksenin otekini KAC KAT gecmesi gerektigi.
# 1.0 olsaydi "hafif yukari-sol" hareketinde bir piksellik fark yonu
# belirlerdi ve kullanici yukari giderken ses degisirdi. 1.6 ile capraz
# hareket kilitlenmeyi ERTELER: kullanici birazcik daha ittiginde hangi
# ekseni istedigi belli olur.
DEFAULT_LOCK_RATIO = 1.6


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
class Status:
    """Jestin o anki hali -- ekrana yazilan geri bildirim."""

    direction: Direction | None
    distance: float
    steps: int
    desc: str = ""

    @property
    def text(self) -> str:
        if self.direction is None:
            return f"jest bekliyor  {self.distance:.0f} px"
        arrow = {
            Direction.UP: "\u2191",
            Direction.DOWN: "\u2193",
            Direction.LEFT: "\u2190",
            Direction.RIGHT: "\u2192",
        }[self.direction]
        label = f"{arrow} {self.direction.label}  {self.distance:.0f} px  {self.steps} kademe"
        return f"{label}  --  {self.desc}" if self.desc else label


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
    """Basili duran bir onek tusunun jest durumu.

    `dx`/`dy` HENUZ ADIMA DONUSMEMIS mesafe: adim uretildikce tuketilir,
    kalani bir sonraki adima sayilir. Boylece yavas hareket de adim uretir.
    `total` geri bildirim icin: kilitli yonde toplam ne kadar gidildi.
    """

    dx: float = 0.0
    dy: float = 0.0
    direction: Direction | None = None
    fired: bool = False
    total: float = 0.0
    steps: int = 0


@dataclass
class GestureTracker:
    """Basili onek tuslarini ve altlarindaki fare hareketini izler.

    `start`/`stop` hook thread'inde, `move` de oyle. Sozluk islemi disinda
    is yapmaz; hareket basina birkac cikarma ve karsilastirma.
    """

    defs: dict[tuple[int, Direction], GestureDef] = field(default_factory=dict)
    step_px: float = DEFAULT_STEP_PX
    lock_ratio: float = DEFAULT_LOCK_RATIO
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
    def active(self) -> tuple[int, ...]:
        """Su an jest izlenen onek tuslari -- geri bildirim icin."""
        return tuple(self._active)

    @property
    def watching(self) -> bool:
        """Su an jest izlenen bir tus basili mi. Fare hareketi bu bayrak
        kapaliyken hic islenmez."""
        return bool(self._active)

    # ---- besleme ----

    def start(self, prefix: int) -> None:
        """Onek tusu basildi: sayaclar sifirlanir. AHK: Start()."""
        if self.has(prefix):
            self._active[prefix] = _Active()

    def move(self, dx: float, dy: float) -> list[GestureEvent]:
        """Fare kimildadi (delta). Uretilen adimlari doner."""
        if not self._active:
            return []
        events: list[GestureEvent] = []
        for prefix, state in self._active.items():
            if state.direction is None:
                # Yon henuz belli degil: iki ekseni de biriktir.
                state.dx += dx
                state.dy += dy
                if not self._lock(prefix, state):
                    continue
            else:
                # KILITLI: dik eksen HIC okunmaz. Kullanici yukari giderken
                # elin saga kaymasi sesi/zoom'u degistirmesin -- istenen buydu.
                if state.direction in (Direction.LEFT, Direction.RIGHT):
                    state.dx += dx
                else:
                    state.dy += dy

            moved = _advance(state.direction, state.dx, state.dy)
            steps = int(moved // self.step_px)
            if steps <= 0:
                continue  # geri gidis ya da esigin altinda: birikim durur

            definition = self.defs[(prefix, state.direction)]
            state.fired = True
            # Tuketileni birikimden dus: kalan mesafe bir sonraki adima
            # sayilsin, yoksa yavas hareket hic adim uretmezdi.
            consumed = steps * self.step_px
            if state.direction is Direction.RIGHT:
                state.dx -= consumed
            elif state.direction is Direction.LEFT:
                state.dx += consumed
            elif state.direction is Direction.DOWN:
                state.dy -= consumed
            else:
                state.dy += consumed
            state.total += consumed
            state.steps += steps

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

    def _lock(self, prefix: int, state: _Active) -> bool:
        """Baskin ekseni kilitlemeyi dener. Kilitlendiyse True.

        Iki sart var: baskin eksende en az bir adimlik yol gidilmis olmali
        VE oteki ekseni `lock_ratio` kati gecmis olmali. Ikincisi capraz
        hareketin yanlis ekseni secmesini onler -- eskiden "hafif yukari
        sol" hareketinde sol kazanip yanlis eylem calisiyordu.
        """
        primary = max(abs(state.dx), abs(state.dy))
        if primary < self.step_px:
            return False
        secondary = min(abs(state.dx), abs(state.dy))
        if primary < secondary * self.lock_ratio:
            return False  # capraz: kararsiz, biraz daha bekle
        candidate = _direction(state.dx, state.dy)
        if (prefix, candidate) not in self.defs:
            return False  # bu yon icin tanim yok: kilitleme, beklemeye devam
        state.direction = candidate
        # Dik eksendeki birikim silinir: kilitlendikten sonra hicbir islevi
        # yok ve status() icinde yanlis mesafe gosterirdi.
        if candidate in (Direction.LEFT, Direction.RIGHT):
            state.dy = 0.0
        else:
            state.dx = 0.0
        return True

    def status(self, prefix: int) -> Status | None:
        """Geri bildirim icin: hangi yon, ne kadar gidildi, kac kademe.

        AHK jest sirasinda bunu ekrana yaziyordu; kullanicinin "ne kadar
        daha itmem lazim" sorusunun cevabi. Kilitlenmeden once yon None,
        mesafe o ana kadarki en buyuk sapma.
        """
        state = self._active.get(prefix)
        if state is None:
            return None
        if state.direction is None:
            return Status(None, max(abs(state.dx), abs(state.dy)), 0, "")
        pending = max(_advance(state.direction, state.dx, state.dy), 0.0)
        definition = self.defs[(prefix, state.direction)]
        return Status(state.direction, state.total + pending, state.steps, definition.desc)

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
