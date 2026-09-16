"""Kaskad tanimi -- AHK'deki key_builder.ahk karsiligi.

AHK'de KeyBuilder akici (fluent) bir kurucu ve icine dogrudan fonksiyon
referanslari konuyordu:

    KeyBuilder(350)
        .mainKey((dt) => ...)
        .setExitOnPressType(1)
        .combo("1", "Slot 1", () => loadSave(1))
    10|        .build()

Burada eylemler fonksiyon degil **eylem kimligi** (string). Sebep: tanim
boylece JSON'a yazilabiliyor, ayar dosyasindan okunabiliyor ve testte
callable kurmadan dogrulanabiliyor. Kimlikleri callable'a cevirmek
dispatcher'in isi (keypilot/actions.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from keypilot.core.hot_vectors import Direction
from keypilot.core.keynames import key_name, vk_from_name


class PressType(IntEnum):
    """AHK: 1 kisa, 2 orta, 3 uzun, 4 cift tiklama.

    Sayilar AHK ile ayni cunku JSON'a bu sekilde yaziliyor. Ekrana yazarken
    `label` kullanilir -- basim turu hicbir yerde string olarak dolasmaz,
    karsilastirma her zaman enum uzerinden yapilir.
    """

    SHORT = 1
    MEDIUM = 2
    LONG = 3
    DOUBLE = 4

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    PressType.SHORT: "kisa",
    PressType.MEDIUM: "orta",
    PressType.LONG: "uzun",
    PressType.DOUBLE: "cift",
}


def press_type(duration_ms: float, short_ms: float, long_ms: float | None) -> PressType:
    """AHK KeyBuilder.getPressType birebir.

    long_ms yoksa iki seviye: <= short_ms kisa, digeri orta.
    long_ms varsa uc seviye. Sinirlar AHK'deki gibi: <= short kisa,
    < long orta, geri kalani uzun.
    """
    if long_ms is None:
        return PressType.SHORT if duration_ms <= short_ms else PressType.MEDIUM
    if duration_ms <= short_ms:
        return PressType.SHORT
    if duration_ms < long_ms:
        return PressType.MEDIUM
    return PressType.LONG


@dataclass(frozen=True, slots=True)
class Combo:
    """Ana tus basiliyken ya da menu acikken basilan yanci tus."""

    key: int
    desc: str
    action: str

    @property
    def key_text(self) -> str:
        return key_name(self.key)


@dataclass(frozen=True, slots=True)
class GestureSpec:
    """Fare jesti: yon + overlay etiketi + eylem + her N adimda bir."""

    direction: Direction
    label: str
    action: str
    every: int = 1


@dataclass(frozen=True, slots=True)
class CascadeDef:
    """Tek bir kaskad tusunun tam tanimi.

    `run_cascade=False`: yalniz jest/etiket kaynagi (ornegin F13). Basim
    turu HotkeyTable / PrefixTracker'da kalir; CascadeMachine'e girmez.
    """

    key: int
    main: dict[PressType, str] = field(default_factory=dict)
    main_labels: dict[PressType, str] = field(default_factory=dict)
    combos: tuple[Combo, ...] = ()
    gestures: tuple[GestureSpec, ...] = ()
    short_ms: float = 350.0
    long_ms: float | None = None
    exit_on_press_type: int = -1
    menu_timeout_ms: float = 30000.0
    show_menu: bool = True
    swallow: bool = True
    gesture_visible: bool = False
    #: Overlay P/S icin gestureVisible(True, "Back", "Home") override.
    gesture_center: tuple[str, str] | None = None
    run_cascade: bool = True
    name: str = ""

    def combo_for(self, vk: int) -> Combo | None:
        for combo in self.combos:
            if combo.key == vk:
                return combo
        return None

    @property
    def key_text(self) -> str:
        return self.name or key_name(self.key)

    @property
    def tips(self) -> tuple[tuple[str, str], ...]:
        """AHK builder.tips -- menude gosterilecek 'tus: aciklama' listesi."""
        return tuple((c.key_text, c.desc) for c in self.combos)

    @property
    def overlay_center(self) -> dict[str, str]:
        """P/S etiketleri: gesture_center override, yoksa MEDIUM/LONG main_labels."""
        if self.gesture_center is not None:
            p_label, s_label = self.gesture_center
            out: dict[str, str] = {}
            if p_label:
                out["P"] = p_label
            if s_label:
                out["S"] = s_label
            return out
        out = {}
        if PressType.MEDIUM in self.main_labels:
            out["P"] = self.main_labels[PressType.MEDIUM]
        if PressType.LONG in self.main_labels:
            out["S"] = self.main_labels[PressType.LONG]
        return out


class KeyBuilder:
    """AHK KeyBuilder'in akici arayuzu, ayni metot adlariyla."""

    def __init__(self, key: int | str, short: float = 350.0, long: float | None = None) -> None:
        self._key = _resolve(key)
        self._short = short
        self._long = long
        self._main: dict[PressType, str] = {}
        self._main_labels: dict[PressType, str] = {}
        self._combos: list[Combo] = []
        self._gestures: list[GestureSpec] = []
        self._exit_on: int = -1
        self._timeout = 30000.0
        self._show_menu = True
        self._swallow = True
        self._gesture_visible = False
        self._gesture_center: tuple[str, str] | None = None
        self._run_cascade = True
        self._name = ""

    def set_press_type(self, short: float = 350.0, long: float | None = None) -> KeyBuilder:
        self._short, self._long = short, long
        return self

    def main_key(self, press: PressType | int, action: str, label: str = "") -> KeyBuilder:
        """`main_key(press, action)` veya `main_key(press, action, "Back")`."""
        kind = PressType(press)
        self._main[kind] = action
        if label:
            self._main_labels[kind] = label
        return self

    def combo(self, key: int | str, desc: str, action: str) -> KeyBuilder:
        self._combos.append(Combo(key=_resolve(key), desc=desc, action=action))
        return self

    def gesture(
        self,
        direction: Direction,
        label: str,
        action: str,
        *,
        every: int = 1,
    ) -> KeyBuilder:
        """Fare jesti. `every=5` = her 5 adimda bir tetikle."""
        self._gestures.append(
            GestureSpec(direction, label, action, every=max(1, int(every)))
        )
        return self

    def gestureVisible(self, on: bool = False, p: str = "", s: str = "") -> KeyBuilder:
        """Overlay acilsin mi (varsayilan kapali); istege bagli P/S override."""
        self._gesture_visible = bool(on)
        if p or s:
            self._gesture_center = (p, s)
        return self

    def gesture_visible(self, on: bool = True, p: str = "", s: str = "") -> KeyBuilder:
        return self.gestureVisible(on, p, s)

    def set_exit_on_press_type(self, press: int) -> KeyBuilder:
        self._exit_on = int(press)
        return self

    def set_timeout(self, ms: float) -> KeyBuilder:
        self._timeout = ms
        return self

    def show_menu(self, on: bool = True) -> KeyBuilder:
        self._show_menu = on
        return self

    def swallow(self, on: bool = True) -> KeyBuilder:
        self._swallow = on
        return self

    def run_cascade(self, on: bool = True) -> KeyBuilder:
        """False: CascadeMachine'e girme (F13: jest-only KeyBuilder)."""
        self._run_cascade = on
        return self

    def named(self, name: str) -> KeyBuilder:
        self._name = name
        return self

    def build(self) -> CascadeDef:
        return CascadeDef(
            key=self._key,
            main=dict(self._main),
            main_labels=dict(self._main_labels),
            combos=tuple(self._combos),
            gestures=tuple(self._gestures),
            short_ms=self._short,
            long_ms=self._long,
            exit_on_press_type=self._exit_on,
            menu_timeout_ms=self._timeout,
            show_menu=self._show_menu,
            swallow=self._swallow,
            gesture_visible=self._gesture_visible,
            gesture_center=self._gesture_center,
            run_cascade=self._run_cascade,
            name=self._name,
        )


def _resolve(key: int | str) -> int:
    if isinstance(key, int):
        return key
    vk = vk_from_name(key)
    if vk is None:
        raise ValueError(f"bilinmeyen tus adi: {key!r}")
    return vk


def def_from_dict(data: dict) -> CascadeDef:
    """JSON ayar dosyasindan CascadeDef uretir."""
    builder = KeyBuilder(
        data["key"],
        short=float(data.get("short_ms", 350)),
        long=None if data.get("long_ms") is None else float(data["long_ms"]),
    )
    for press, action in (data.get("main") or {}).items():
        builder.main_key(int(press), action)
    for entry in data.get("combos") or []:
        builder.combo(entry["key"], entry.get("desc", ""), entry["action"])
    builder.set_exit_on_press_type(int(data.get("exit_on_press_type", -1)))
    builder.set_timeout(float(data.get("menu_timeout_ms", 30000)))
    builder.show_menu(bool(data.get("show_menu", True)))
    builder.swallow(bool(data.get("swallow", True)))
    if data.get("name"):
        builder.named(str(data["name"]))
    return builder.build()
