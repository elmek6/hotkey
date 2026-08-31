"""Onek tusu durum makinesi -- AHK'de `A & B::` yaziminin arkasindaki is.

Bir onek tusu (F13, `^`, LButton) dort sey yapabilir ve hangisi oldugu ancak
SONRADAN belli olur:

    kombo       onek basiliyken baska tusa basildi   -> kombo eylemi
    surukleme   onek basiliyken fare kimildadi       -> drag eylemi
    basili tut  esik gecti, kombo yok                -> hold eylemi
    kisa basim  esikten once birakildi, kombo yok    -> tap eylemi
                                                        (yoksa tus geri gonderilir)

AHK bunu bloke eden `KeyWait` ile yapiyordu. LL hook keydown aninda cevap
vermek zorunda oldugu icin burada durum makinesi: zaman disaridan verilir,
`tick` esigi yoklar. Sinif saf Python -- Win32 yok, Qt yok, test edilebilir.

`~` (passthrough) AHK ile ayni anlamda: onek tusu YUTULMAZ, alttaki
uygulamaya da gider. Fare tuslari icin sart -- LButton'i yutarsak hicbir yere
tiklayamayiz. Yutulmayan onek geri gonderilmez de (zaten gitti).

Yutulan onekte ise geri gonderme sart: `^` tusunu yutup hicbir sey
yapmazsak kullanici `^` yazamaz. Karar birakma aninda veriliyor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

DEFAULT_HOLD_MS = 350.0
#: Cift basim penceresi. AHK key_handler_mouse.ahk: kisa basimdan sonra
#: `KeyWait(key, "D T0.1")` -- 100 ms icinde ikinci basim gelirse basim
#: turu 4 (cift) olur. Bizde de kisa basim eylemi bu kadar BEKLETILIR.
DEFAULT_DOUBLE_MS = 180.0


class Outcome(IntEnum):
    """Onek tusu birakildiginda ne olacagi."""

    NOTHING = 0  # kombo/surukleme yapildi -- tusun kendi isi bitti
    TAP = 1  # tek basina kisa basim -- cagiran tap eylemini calistirir
    HOLD = 2  # esik gecti, kombo yok -- cagiran hold eylemini calistirir


@dataclass(frozen=True, slots=True)
class PrefixDef:
    """Bir onek tusunun ayarlari. `hold_action` bos ise basili tutmanin
    ayri bir anlami yoktur (F13'te oyle, `^`'te var)."""

    vk: int
    passthrough: bool = False  # AHK'deki `~`
    hold_action: str = ""
    hold_ms: float = DEFAULT_HOLD_MS
    #: AHK `EM.enableDoubleClick()`: kisa basim iki kere ust uste yapilirsa
    #: calisir. Tanimliysa TEK basim eylemi `double_ms` kadar bekletilir --
    #: yoksa ilk basimin menusu acilip ikinciyi yerdi (AHK'de de basim
    #: turune ancak bu bekleme bitince karar veriliyor).
    double_action: str = ""
    double_ms: float = DEFAULT_DOUBLE_MS
    #: Onek basiliyken fare kimildarsa calisir (F14: ekran alani secimi).
    #: Bos ise surukleme tusun anlamini degistirmez.
    drag_action: str = ""
    desc: str = ""


@dataclass
class PrefixTracker:
    """Basili duran onek tuslarini izler.

    `key_down` / `key_up` hook thread'inde, `tick` Qt thread'inde cagrilir.
    Ikisi de yalnizca sozluk islemi yapar; kilit yok cunku sozluk islemleri
    GIL altinda atomik ve yaris ciksa bile sonucu tek bir tusun bir kez
    gec/erken tetiklenmesi olur -- kilit almanin bedeline degmez.
    """

    defs: dict[int, PrefixDef] = field(default_factory=dict)
    _down: dict[int, float] = field(default_factory=dict, init=False)
    _used: set[int] = field(default_factory=set, init=False)

    # ---- sorgular ----

    def is_prefix(self, vk: int) -> bool:
        return vk in self.defs

    def is_down(self, vk: int) -> bool:
        return vk in self._down

    def is_used(self, vk: int) -> bool:
        """Bu basimda kombo/surukleme/hold calisti mi -- ikinci kez tetiklenmesin."""
        return vk in self._used

    def definition(self, vk: int) -> PrefixDef | None:
        return self.defs.get(vk)

    @property
    def held(self) -> tuple[int, ...]:
        return tuple(self._down)

    # ---- besleme ----

    def key_down(self, vk: int, t: float) -> bool:
        """Onek basildi. Yutulmasi gerekiyorsa True doner.

        Otomatik tekrar zamani sifirlamaz: basili tutma suresi ilk
        basimdan olculur.
        """
        definition = self.defs.get(vk)
        if definition is None:
            return False
        self._down.setdefault(vk, t)
        return not definition.passthrough

    def combo_used(self, vk: int) -> None:
        """Bu onekle bir kombo calisti: birakildiginda kendi eylemi olmayacak."""
        if vk in self._down:
            self._used.add(vk)

    def key_up(self, vk: int, t: float) -> Outcome:
        """Onek birakildi. Basim turune BURADA karar veriliyor.

        AHK `KeyBuilder.getPressType(totalDuration, ...)` ile ayni: tus
        basiliyken hicbir sey olmaz, esik karsilastirmasi birakma aninda
        yapilir. Once esik `tick` ile basiliyken yoklaniyordu; jest yapmak
        350 ms'yi kolayca gectigi icin pano menusu jestin ortasinda aciliyor
        ve jesti kesiyordu (docs/hot_vectors.md D-5).
        """
        started = self._down.pop(vk, None)
        used = vk in self._used
        self._used.discard(vk)
        if started is None or used:
            return Outcome.NOTHING
        definition = self.defs.get(vk)
        if definition is not None and definition.hold_action:
            elapsed = (t - started) * 1000.0
            if elapsed >= definition.hold_ms:
                return Outcome.HOLD
        return Outcome.TAP

    def reset(self) -> None:
        """Duraklatma / hook yeniden kurulumu sonrasi hayalet durumu temizler."""
        self._down.clear()
        self._used.clear()
