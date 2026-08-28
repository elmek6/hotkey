"""Busy durumu -- AHK'deki script_state.ahk'nin BusyModule karsiligi.

SADECE Busy aktif. script_state.ahk'nin geri kalanini (ScriptModule,
MouseModule, ClipboardModule) da cevirmistim ama istenmemisti; silmedim,
dosyanin altinda yorumda duruyor. Ihtiyac olunca yorumdan cikarilir.

Cevirmediklerim: WindowModule ve IdleModule -- ikisi de Win32 cagrisi
gerektiriyor, core'un "Win32 import'u yasak" kuralini bozarlardi.
"""

from __future__ import annotations

import threading
from enum import IntEnum


class BusyLevel(IntEnum):
    """AHK: State.Busy.current -- 0 serbest, 1 aktif, 2 kombo bekliyor."""

    FREE = 0
    ACTIVE = 1
    COMBO = 2


class Busy:
    """Ayni anda tek bir kaskadin calismasini garanti eder.

    AHK'de her handler basinda `if (!State.Busy.isFree()) return` vardi;
    aynisi burada. Fark: hook thread'i ile Qt thread'i ayni nesneye
    dokundugu icin kilit var.
    """

    __slots__ = ("_level", "_caller", "_lock")

    def __init__(self) -> None:
        self._level = BusyLevel.FREE
        self._caller = ""
        self._lock = threading.Lock()

    @property
    def level(self) -> BusyLevel:
        return self._level

    @property
    def caller(self) -> str:
        return self._caller

    def is_free(self) -> bool:
        return self._level == BusyLevel.FREE

    def is_active(self) -> bool:
        return self._level == BusyLevel.ACTIVE

    def is_combo(self) -> bool:
        return self._level == BusyLevel.COMBO

    def set_free(self) -> None:
        with self._lock:
            self._level = BusyLevel.FREE
            self._caller = ""

    def set_active(self, caller: str = "") -> None:
        with self._lock:
            self._level = BusyLevel.ACTIVE
            self._caller = caller

    def set_combo(self, caller: str = "") -> None:
        with self._lock:
            self._level = BusyLevel.COMBO
            self._caller = caller

    def claim(self, caller: str = "") -> bool:
        """Serbestse kilitle ve True don; degilse dokunma ve False don.

        AHK'de bu iki adimdi (`isFree()` sonra `setActive()`) ve arada
        yaris vardi. Tek adimda ve kilitli.
        """
        with self._lock:
            if self._level != BusyLevel.FREE:
                return False
            self._level = BusyLevel.ACTIVE
            self._caller = caller
            return True


# ======================================================================
# ASAGIDAKILER DEVRE DISI -- istenmedi, gerekince yorumdan cikar.
# script_state.ahk'nin Script / Mouse / Clipboard modulleri.
# Yorumdan cikarirsan su import'lari da ac:
#     from dataclasses import dataclass, field
#     from datetime import datetime
# ======================================================================
#
# @dataclass
# class ScriptInfo:
#     """AHK: State.Script"""
#
#     version: str
#     start_time: datetime = field(default_factory=datetime.now)
#     save_on_exit: bool = True
#
#     @property
#     def uptime_seconds(self) -> float:
#         return (datetime.now() - self.start_time).total_seconds()
#
#     def uptime_text(self) -> str:
#         total = int(self.uptime_seconds)
#         hours, rest = divmod(total, 3600)
#         minutes, seconds = divmod(rest, 60)
#         if hours:
#             return f"{hours} sa {minutes} dk"
#         if minutes:
#             return f"{minutes} dk {seconds} sn"
#         return f"{seconds} sn"
#
#
# @dataclass
# class MouseState:
#     """AHK: State.Mouse -- tekerlek kisitlama ve sag tik durumu."""
#
#     right_click_active: bool = False
#     middle_wheel_used: bool = False
#     _last_wheel_t: float = 0.0
#     _wheel_count: int = 0
#
#     def should_process_wheel(self, now: float, throttle_ms: float = 600.0) -> bool:
#         """AHK shouldProcessWheel: hizli tekerlek cevriminde her ikinci olayi al."""
#         diff_ms = (now - self._last_wheel_t) * 1000.0
#         if diff_ms > throttle_ms:
#             self._last_wheel_t = now
#             self._wheel_count = 0
#             return False
#         self._wheel_count += 1
#         self._last_wheel_t = now
#         return self._wheel_count % 2 == 0
#
#
# class ClipboardMode(IntEnum):
#     """AHK: State.Clipboard"""
#
#     NONE = 0
#     HISTORY = 1
#     MEM_SLOTS = 2
#
#
# @dataclass
# class AppState:
#     """AHK'deki `global State` nesnesinin karsiligi."""
#
#     version: str
#     script: ScriptInfo = field(init=False)
#     busy: Busy = field(default_factory=Busy)
#     mouse: MouseState = field(default_factory=MouseState)
#     clipboard: ClipboardMode = ClipboardMode.NONE
#     key_counts: dict[str, int] = field(default_factory=dict)
#
#     def __post_init__(self) -> None:
#         self.script = ScriptInfo(version=self.version)
#
#     def count_key(self, name: str) -> None:
#         """AHK: App.KeyCounts.inc(key)"""
#         self.key_counts[name] = self.key_counts.get(name, 0) + 1
#
#     def top_keys(self, limit: int = 10) -> list[tuple[str, int]]:
#         return sorted(self.key_counts.items(), key=lambda kv: -kv[1])[:limit]
