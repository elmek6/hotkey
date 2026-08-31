"""Fare vektorleri -- AHK `Lib/hot_vectors.ahk` portu (eski adi: gesture.py).

AHK'deki mantik birebir: bir YON kaydedilir (tek yonlu `up` ya da cift
yonlu `upDown`), altina bir eylem baglanir; onek tusu basiliyken fare o
eksende yeterince giderse eylem tetiklenir.

    onek tusu basilir            -> sayaclar sifirlanir, baslangic not edilir
    fare `lock_px` kadar gider   -> baskin EKSEN kilitlenir ve JEST BASLAR
    her `step_px` kadar daha     -> bir adim (tetikleme) daha uretilir

Sayaclar tusun BASILI TUTULMASI boyunca yasar: basili tutma tekrari
(Windows'un saniyede ~30 keydown'i) jesti yeniden baslatmaz -- dispatch.py
zaten izlenen bir tusa `start()` demiyor.

Algilama, istenen sirayla iki soru:

1. **Hangi eksenler kayitli?** Yalniz onlar yarisir. Bu onek icin hic yatay
   yon kaydedilmemisse yatay hareket hesaba HIC girmez -- kullanici dikeye
   cikana kadar beklenir.
2. **Hareket hangisine daha yakin?** Duz piksel karsilastirmasi: "yukari 12,
   sola 2" ise hareket dikeydir. Oran, ivme, hiz carpani YOK (AHK 3.0 da
   ivmeyi kaldirmisti).

Kilitlenen sey YON DEGIL EKSENDIR (AHK `bDir.upDown`: tek jest, callback'e
`pos` +1/-1 gider). Dikey kilitlendiginde yukari itmek yakinlastirir, geri
cekmek uzaklastirir; eksen yeni bir jeste kadar degismez ve dik eksendeki
hareket sessizce atilir -- yukari giderken elin saga kaymasi sesi
degistirmesin.

Iki esik var, AHK'deki gibi (`DIRECTION_THRESHOLD` / `STEP_SIZE`):

* **`lock_px`** eksen kilidi. Asildigi anda jest BASLAMIS sayilir: onek tusu
  artik "kullanildi", birakilinca menu ACILMAZ. Once yalniz adim
  uretildiginde jest baslamis sayiliyordu; azicik oynatip birakinca menu
  aciliyor ve "jest basladi ama menuye dondu" hissi veriyordu.
* **`step_px`** tetikleme araligi. Her `step_px` piksel bir adim demek.

Girdi mutlak konum degil **delta**: dispatch.py her hareket olayinda bir
oncekine gore farki verir (hareket olayi yutuluyor, imlec jest bitince
basladigi noktaya donuyor).

Saf Python: Win32 yok, Qt yok, zaman bile gerekmiyor -- yalniz koordinat.
Esikler disaridan veriliyor (keymap.py, `hotVector.*` ayarlari).

TODO(AHK): hot_vectors.ahk'nin `once` / `unlock` bayraklari port edilmedi
    (bir kez tetikle; dik harekette ekseni degistirmeye izin ver). Kayitli
    jestlerimizin hicbiri onlari kullanmiyor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

#: AHK: STEP_SIZE -- bir tetiklenme icin gereken piksel. AHK ile ayni deger:
#: 60 px'te yavas hareket neredeyse hic kademe uretmiyordu.
DEFAULT_STEP_PX = 14.0
#: AHK: DIRECTION_THRESHOLD -- eksenin kilitlenmesi icin gereken piksel.
DEFAULT_LOCK_PX = 8.0

#: Kilit kipleri (`hotVector.lockMode`).
LOCK_AXIS = "eksen"  # eksen kilitlenir, iki yon de canli (AHK bDir.upDown)
LOCK_DIRECTION = "yon"  # ilk yon kilitlenir, ters yon jest boyunca olu
LOCK_MODES = (LOCK_AXIS, LOCK_DIRECTION)


class Axis(IntEnum):
    """Kilitlenen eksen. AHK'de `bDir.upDown` / `bDir.leftRight` cifti."""

    VERTICAL = 1
    HORIZONTAL = 2

    @property
    def label(self) -> str:
        return "dikey" if self is Axis.VERTICAL else "yatay"


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

    @property
    def vertical(self) -> bool:
        return self in (Direction.UP, Direction.DOWN)

    @property
    def axis(self) -> Axis:
        return Axis.VERTICAL if self.vertical else Axis.HORIZONTAL


@dataclass(frozen=True, slots=True)
class VectorDef:
    """`onek tusu + yon -> eylem`. AHK: HotVectors.Register(dir, callback)."""

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
    #: Kilitli eksen. Eksen kilitli ama henuz adim uretilmemis olabilir.
    axis: Axis | None = None

    @property
    def text(self) -> str:
        """AHK'nin jest ipucuyla ayni bicim: `<--> RT +3`.

        Eksen sembolu + yon kodu + O YONDE atilan adim sayisi. Yon
        degistirilince sayac sifirlanir (`LT +1`), cunku sayi "kac kademe
        uygulandi" demek -- ses kac tik acildi, buyutec kac kademe gitti.
        """
        if self.axis is None:
            return f"...  {self.distance:.0f} px"
        symbol = "<-->" if self.axis is Axis.HORIZONTAL else "^--v"
        if self.direction is None:
            return f"{symbol}  {self.distance:.0f} px"
        code = {
            Direction.UP: "UP",
            Direction.DOWN: "DN",
            Direction.LEFT: "LT",
            Direction.RIGHT: "RT",
        }[self.direction]
        label = f"{symbol} {code} +{self.steps}"
        return f"{label}  {self.desc}" if self.desc else label


@dataclass(frozen=True, slots=True)
class VectorEvent:
    """Uretilen tetikleme. `steps` o darbede kac adim ilerlendigi."""

    prefix: int
    direction: Direction
    steps: int
    action: str
    desc: str = ""


@dataclass
class _Active:
    """Basili duran bir onek tusunun jest durumu.

    `dx`/`dy` HENUZ ADIMA DONUSMEMIS mesafe: adim uretildikce tuketilir,
    kalani bir sonraki adima sayilir. Boylece yavas hareket de adim uretir.
    `total` geri bildirim icin: kilitli eksende toplam ne kadar gidildi.
    """

    dx: float = 0.0
    dy: float = 0.0
    #: Kilitli EKSEN -- yon degil. Dikey kilitliyse hem yukari hem asagi
    #: okunur; eksen jest bitene kadar degismez.
    axis: Axis | None = None
    #: En son tetiklenen yon -- yalniz geri bildirim icin.
    direction: Direction | None = None
    #: `LOCK_DIRECTION` kipinde kilitlenen yon; eksen kipinde None.
    locked_dir: Direction | None = None
    #: Jest BASLADI mi -- eksen kilitlendigi anda True. Onek tusu birakilinca
    #: menu acilmasin diye dispatch.py buna bakiyor.
    fired: bool = False
    total: float = 0.0
    steps: int = 0


@dataclass
class HotVectors:
    """Basili onek tuslarini ve altlarindaki fare hareketini izler.

    `start`/`stop` hook thread'inde, `move` de oyle. Sozluk islemi disinda
    is yapmaz; hareket basina birkac cikarma ve karsilastirma.
    """

    defs: dict[tuple[int, Direction], VectorDef] = field(default_factory=dict)
    step_px: float = DEFAULT_STEP_PX
    lock_px: float = DEFAULT_LOCK_PX
    #: `LOCK_AXIS` -- eksen kilitlenir, iki yon de canli kalir (AHK
    #: `bDir.upDown`). `LOCK_DIRECTION` -- ilk yon kilitlenir, ters yon
    #: jest bitene kadar hicbir sey yapmaz. Ayardan secilir
    #: (`hotVector.lockMode`): hangisinin dogru his verdigi kullanima bagli.
    lock_mode: str = LOCK_AXIS
    _active: dict[int, _Active] = field(default_factory=dict, init=False)

    # ---- tanim ----

    def register(
        self, prefix: int, direction: Direction, action: str, desc: str = ""
    ) -> HotVectors:
        self.defs[(prefix, direction)] = VectorDef(prefix, direction, action, desc)
        return self

    def has(self, prefix: int) -> bool:
        """Bu onek tusunun tanimli jesti var mi -- callback'in hizli elemesi."""
        return any(key[0] == prefix for key in self.defs)

    def axes(self, prefix: int) -> set[Axis]:
        """Bu onek icin KAYITLI eksenler. AHK: `__FilterGesturesByDirection`.

        Eksen kilidi yalniz bunlarin arasindan secilir: hic yatay yon
        kayitli degilse yatay hareket yonu belirlemez.
        """
        return {key[1].axis for key in self.defs if key[0] == prefix}

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

    def move(self, dx: float, dy: float) -> list[VectorEvent]:
        """Fare kimildadi (delta). Uretilen adimlari doner.

        Eksen kilitlenene kadar iki eksen de birikir; kilitten SONRA yalniz
        kilitli eksen okunur. Kilitli eksen icinde IKI YON de canli.
        """
        if not self._active:
            return []
        events: list[VectorEvent] = []
        for prefix, state in self._active.items():
            if state.axis is None:
                # Eksen henuz belli degil: ikisini de biriktir.
                state.dx += dx
                state.dy += dy
                if not self._lock(prefix, state):
                    continue
            elif state.axis is Axis.VERTICAL:
                state.dy += dy  # KILITLI: dik eksen HIC okunmaz
            else:
                state.dx += dx

            moved = state.dy if state.axis is Axis.VERTICAL else state.dx
            if state.locked_dir is not None:
                # YON KIPI: yalniz kilitli yonde ilerleme sayilir; geri
                # cekmek adim uretmez (birikim negatife duser ve orada bekler).
                forward = moved if state.locked_dir in (Direction.DOWN, Direction.RIGHT) else -moved
                if forward < 0:
                    # Geri cekildi: birikim SIFIRLANIR. Yoksa geri gidilen
                    # mesafeyi once geri kazanmak gerekirdi ("bir sure hicbir
                    # sey olmuyor" hissi).
                    state.dx = state.dy = 0.0
                    continue
                steps = int(forward // self.step_px)
                if steps <= 0:
                    continue
                direction = state.locked_dir
                moved = forward if direction in (Direction.DOWN, Direction.RIGHT) else -forward
            else:
                steps = int(abs(moved) // self.step_px)
                if steps <= 0:
                    continue  # esigin altinda: birikim durur
                # Isaret o darbenin YONU. Ekran koordinatinda y ASAGI buyur.
                if state.axis is Axis.VERTICAL:
                    direction = Direction.DOWN if moved > 0 else Direction.UP
                else:
                    direction = Direction.RIGHT if moved > 0 else Direction.LEFT

            # Tuketileni birikimden dus: kalan mesafe bir sonraki adima
            # sayilsin, yoksa yavas hareket hic adim uretmezdi.
            consumed = steps * self.step_px * (1 if moved > 0 else -1)
            if state.axis is Axis.VERTICAL:
                state.dy -= consumed
            else:
                state.dx -= consumed
            state.total += steps * self.step_px
            # Sayac YON BASINA: saga gidip sonra sola donunce "RT +3" degil
            # "LT +1" gorunmeli -- sayi o yonde kac kademe uygulandigidir.
            state.steps = steps if direction is not state.direction else state.steps + steps
            state.direction = direction

            definition = self.defs.get((prefix, direction))
            if definition is None:
                continue  # eksen kayitli ama bu yon degil: sayilir, tetiklemez

            events.append(
                VectorEvent(
                    prefix=prefix,
                    direction=direction,
                    steps=steps,
                    action=definition.action,
                    desc=definition.desc,
                )
            )
        return events

    def _lock(self, prefix: int, state: _Active) -> bool:
        """Baskin EKSENI kilitlemeyi dener. Kilitlendiyse True.

        Kayitli eksenler arasinda hangisinde daha cok gidildiyse o kazanir;
        biriken mesafe `lock_px` esigini gecmis olmali. Kilit ayni zamanda
        JESTIN BASLADIGI andir (`fired`): esik asildiktan sonra tusu birakmak
        menuyu acmaz.
        """
        allowed = self.axes(prefix)
        vertical = abs(state.dy) if Axis.VERTICAL in allowed else -1.0
        horizontal = abs(state.dx) if Axis.HORIZONTAL in allowed else -1.0
        if max(vertical, horizontal) < self.lock_px:
            return False
        state.axis = Axis.VERTICAL if vertical >= horizontal else Axis.HORIZONTAL
        if self.lock_mode == LOCK_DIRECTION:
            if state.axis is Axis.VERTICAL:
                state.locked_dir = Direction.DOWN if state.dy > 0 else Direction.UP
            else:
                state.locked_dir = Direction.RIGHT if state.dx > 0 else Direction.LEFT
            state.direction = state.locked_dir
        state.fired = True
        # Dik eksendeki birikim silinir: kilitten sonra islevi yok ve
        # status() icinde yanlis mesafe gosterirdi.
        if state.axis is Axis.VERTICAL:
            state.dx = 0.0
        else:
            state.dy = 0.0
        return True

    def status(self, prefix: int) -> Status | None:
        """Geri bildirim icin: hangi eksen/yon, ne kadar gidildi, kac kademe.

        AHK jest sirasinda bunu ekrana yaziyordu; kullanicinin "ne kadar
        daha itmem lazim" sorusunun cevabi. Kilitlenmeden once eksen de yon
        de None, mesafe o ana kadarki en buyuk sapma.
        """
        state = self._active.get(prefix)
        if state is None:
            return None
        if state.axis is None:
            return Status(None, max(abs(state.dx), abs(state.dy)), 0, "")
        pending = abs(state.dy if state.axis is Axis.VERTICAL else state.dx)
        definition = self.defs.get((prefix, state.direction)) if state.direction else None
        return Status(
            state.direction,
            state.total + pending,
            state.steps,
            definition.desc if definition else "",
            axis=state.axis,
        )

    def stop(self, prefix: int) -> bool:
        """Onek birakildi. Jest BASLADIYSA True -- cagiran o zaman ne menu
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
