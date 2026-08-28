"""Kaskad durum makinesi -- key_handler_cascade.ahk + key_handler_hook.ahk.

AHK bu isi bloke eden bir dongude yapiyordu:

    while (GetKeyState(key, "P")) { ... Sleep(30) }

Python'da LL hook callback'i bloke olamaz: 300 ms'yi asarsan Windows hook'u
sessizce dusurur. Bu yuzden dongu bir durum makinesine cevrildi. Zaman
disaridan verilir; ne sleep var ne GetKeyState. Test edilebilir olmasinin
sebebi bu.

Akis (AHK ile ayni):

    IDLE  --ana tus basildi-->  HELD
    HELD  --yanci tus-->        kombo eylemi calisir, HELD'de kalinir
    HELD  --ana tus birakildi-> basim turu hesaplanir, main eylemi calisir
                                 -> exit_on_press_type ise IDLE
                                 -> degilse MENU (kombo menusu acilir)
    MENU  --kombo tusu-->       eylem calisir, IDLE
    MENU  --Escape / zaman asimi-> IDLE
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import IntEnum

from cascade.core.builder import CascadeDef, PressType, press_type
from cascade.core.state import Busy

VK_ESCAPE = 0x1B

MEDIUM_BEEP = (800, 50)
LONG_BEEP = (600, 50)
UNKNOWN_KEY_BEEP = (1000, 100)


class Phase(IntEnum):
    IDLE = 0
    HELD = 1
    MENU = 2


# ---- disari verilen eylemler (veri, callable degil) ----


@dataclass(frozen=True, slots=True)
class Run:
    action: str
    press: PressType | None = None
    key: int | None = None
    desc: str = ""


@dataclass(frozen=True, slots=True)
class Beep:
    freq: int
    ms: int


@dataclass(frozen=True, slots=True)
class OpenMenu:
    title: str
    items: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class CloseMenu:
    pass


Action = Run | Beep | OpenMenu | CloseMenu


@dataclass
class CascadeMachine:
    """Tum kaskad tanimlarini yoneten tek makine.

    Hook thread'i feed_key'i, Qt thread'i tick'i cagirir; ikisi de ayni
    kilidi alir. Kilit alimi ~100 ns, callback butcesi 300 ms -- sorun degil.
    """

    definitions: dict[int, CascadeDef] = field(default_factory=dict)
    busy: Busy = field(default_factory=Busy)

    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _phase: Phase = field(default=Phase.IDLE, init=False)
    _active: CascadeDef | None = field(default=None, init=False)
    _start: float = field(default=0.0, init=False)
    _menu_start: float = field(default=0.0, init=False)
    _medium_beeped: bool = field(default=False, init=False)
    _long_beeped: bool = field(default=False, init=False)
    _combo_used: bool = field(default=False, init=False)
    _swallowed: set[int] = field(default_factory=set, init=False)

    # ---- sorgular ----

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def active_key(self) -> int | None:
        return self._active.key if self._active else None

    def owns(self, vk: int) -> bool:
        return vk in self.definitions

    # ---- besleme ----

    def feed_key(self, vk: int, down: bool, t: float) -> tuple[bool, list[Action]]:
        """(yutulsun mu, calistirilacak eylemler) doner.

        Hook callback'i icinden cagrilir; O(1) calisir, I/O yapmaz.
        """
        with self._lock:
            if not down:
                return self._on_up(vk, t)
            return self._on_down(vk, t)

    def tick(self, t: float) -> list[Action]:
        """Zamanlayici darbesi: bip esikleri ve menu zaman asimi."""
        with self._lock:
            if self._phase == Phase.HELD and self._active is not None:
                return self._tick_held(self._active, t)
            if (
                self._phase == Phase.MENU
                and self._active is not None
                and (t - self._menu_start) * 1000.0 >= self._active.menu_timeout_ms
            ):
                return [CloseMenu(), *self._finish()]
            return []

    def reset(self) -> None:
        """Hook yeniden kuruldugunda / odak kaybinda hayalet durumu temizler."""
        with self._lock:
            self._swallowed.clear()
            self._finish()

    def set_definitions(self, definitions: dict[int, CascadeDef]) -> None:
        """Ayar dosyasi yeniden okundugunda tanimlari degistirir."""
        with self._lock:
            self._swallowed.clear()
            self._finish()
            self.definitions = definitions

    # ---- ic akis ----

    def _on_down(self, vk: int, t: float) -> tuple[bool, list[Action]]:
        if self._phase == Phase.IDLE:
            definition = self.definitions.get(vk)
            if definition is None:
                return False, []
            if not self.busy.claim(definition.key_text):
                return False, []  # baska bir kaskad calisiyor: tusa dokunma
            self._active = definition
            self._phase = Phase.HELD
            self._start = t
            self._medium_beeped = self._long_beeped = self._combo_used = False
            self._swallowed = {vk} if definition.swallow else set()
            return definition.swallow, []

        assert self._active is not None

        if self._phase == Phase.HELD:
            if vk == self._active.key:
                return self._active.swallow, []  # otomatik tekrar
            combo = self._active.combo_for(vk)
            if combo is None:
                return False, []  # kaskadin ilgilenmedigi tus normal aksin
            self.busy.set_combo(self._active.key_text)
            self._combo_used = True
            self._swallowed.add(vk)
            return True, [Run(combo.action, key=vk, desc=combo.desc)]

        # Phase.MENU -- menu acikken butun tuslar bize ait
        self._swallowed.add(vk)
        if vk == VK_ESCAPE:
            return True, [CloseMenu(), *self._finish()]
        combo = self._active.combo_for(vk)
        if combo is not None:
            return True, [
                CloseMenu(),
                Run(combo.action, key=vk, desc=combo.desc),
                *self._finish(),
            ]
        return True, [Beep(*UNKNOWN_KEY_BEEP), CloseMenu(), *self._finish()]

    def _on_up(self, vk: int, t: float) -> tuple[bool, list[Action]]:
        swallow = vk in self._swallowed
        self._swallowed.discard(vk)

        if self._phase != Phase.HELD or self._active is None or vk != self._active.key:
            return swallow, []

        definition = self._active
        duration_ms = (t - self._start) * 1000.0

        if self._combo_used:
            # AHK: yanci tus kullanildiysa ana tusun kendi eylemi calismaz
            return swallow, self._finish()

        actions: list[Action] = []
        press = press_type(duration_ms, definition.short_ms, definition.long_ms)
        action_id = definition.main.get(press)
        if action_id:
            actions.append(Run(action_id, press=press, key=definition.key))

        if press == definition.exit_on_press_type:
            return swallow, [*actions, *self._finish()]

        if definition.show_menu and definition.combos:
            self._phase = Phase.MENU
            self._menu_start = t
            self.busy.set_combo(definition.key_text)
            actions.append(OpenMenu(definition.key_text, definition.tips))
            return swallow, actions

        return swallow, [*actions, *self._finish()]

    def _tick_held(self, definition: CascadeDef, t: float) -> list[Action]:
        if definition.long_ms is None:
            return []
        elapsed = (t - self._start) * 1000.0
        actions: list[Action] = []
        if not self._medium_beeped and elapsed >= definition.short_ms:
            self._medium_beeped = True
            actions.append(Beep(*MEDIUM_BEEP))
        if not self._long_beeped and elapsed >= definition.long_ms:
            self._long_beeped = True
            actions.append(Beep(*LONG_BEEP))
        return actions

    def _finish(self) -> list[Action]:
        self._phase = Phase.IDLE
        self._active = None
        self._combo_used = False
        self._medium_beeped = self._long_beeped = False
        self.busy.set_free()
        return []
