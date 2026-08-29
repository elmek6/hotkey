"""Kombo ve basim suresi durum makinesi. Saf Python -- Win32 import'u YOK.

AHK karsiliklari:
  Ctrl+Shift+K::        -> modifier komboları
  Pause & Home::        -> prefix kombosu (modifier olmayan bir tus onek olur)
  kisa/orta/uzun basim  -> key_handler_cascade'in sure siniflandirmasi

Zaman disaridan verilir (perf_counter saniye). Boylece testte sentetik
zaman damgalariyla calisir; AHK'de yapilamayan seydi.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cascade.core.builder import PressType, press_type
from cascade.core.keynames import MODIFIER_VKS, key_name


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Basim suresi esikleri, milisaniye. Sinirlar AHK ile ayni.

    Siniflandirma tek yerden gelir: builder.press_type. AHK'nin kurali
    "short_ms dahil kisa sayilir" (<=), yani 350 ms tam sinirda kisa basim.
    """

    short_ms: float = 350.0
    long_ms: float | None = 500.0

    def classify(self, ms: float) -> PressType:
        return press_type(ms, self.short_ms, self.long_ms)


@dataclass(frozen=True, slots=True)
class Chord:
    """Bir tusa basildigi anda olusan kombo."""

    vk: int
    modifiers: tuple[int, ...]
    prefix: int | None
    repeat: bool

    @property
    def text(self) -> str:
        parts = [key_name(m) for m in self.modifiers]
        parts.append(key_name(self.vk))
        combo = "+".join(parts)
        if self.prefix is not None:
            return f"{key_name(self.prefix)} & {combo}"
        return combo


@dataclass(frozen=True, slots=True)
class Press:
    """Bir tus birakildiginda olusan basim ozeti."""

    vk: int
    ms: float
    kind: PressType
    was_prefix: bool

    @property
    def text(self) -> str:
        return key_name(self.vk)


@dataclass
class ComboTracker:
    """Fiziksel tus durumunu izler, kombo ve basim suresi uretir.

    key_down / key_up sirasiyla beslenir. Hook callback'inden cagrilacak
    kadar ucuz: sozluk islemi disinda is yapmaz.
    """

    thresholds: Thresholds = field(default_factory=Thresholds)
    _down: dict[int, float] = field(default_factory=dict, init=False)
    _order: list[int] = field(default_factory=list, init=False)
    _used_as_prefix: set[int] = field(default_factory=set, init=False)

    # ---- sorgular ----

    @property
    def held(self) -> tuple[int, ...]:
        return tuple(self._order)

    def is_down(self, vk: int) -> bool:
        return vk in self._down

    def reset(self) -> None:
        """Odak kaybi / hook yeniden kurulumu sonrasi hayalet tuslari temizler."""
        self._down.clear()
        self._order.clear()
        self._used_as_prefix.clear()

    # ---- besleme ----

    def key_down(self, vk: int, t: float) -> Chord | None:
        repeat = vk in self._down
        if not repeat:
            self._down[vk] = t
            self._order.append(vk)

        if vk in MODIFIER_VKS:
            return None

        modifiers = tuple(sorted(k for k in self._order if k in MODIFIER_VKS))
        prefix = next(
            (k for k in self._order if k != vk and k not in MODIFIER_VKS),
            None,
        )
        if prefix is not None:
            self._used_as_prefix.add(prefix)

        return Chord(vk=vk, modifiers=modifiers, prefix=prefix, repeat=repeat)

    def key_up(self, vk: int, t: float) -> Press | None:
        t0 = self._down.pop(vk, None)
        if vk in self._order:
            self._order.remove(vk)
        was_prefix = vk in self._used_as_prefix
        self._used_as_prefix.discard(vk)
        if t0 is None:
            return None  # basimini gormedigimiz tus (baska proses yutmus olabilir)
        ms = (t - t0) * 1000.0
        return Press(vk=vk, ms=ms, kind=self.thresholds.classify(ms), was_prefix=was_prefix)
