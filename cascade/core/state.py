"""Calisma zamani durumu -- script_state.ahk'nin karsiligi.

Aktif olanlar: Busy (BusyModule) ve ClipboardState (ClipboardModule).
ScriptModule ve MouseModule dosyanin altinda yorumda duruyor.

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


class ClipboardMode(IntEnum):
    """AHK: State.Clipboard -- panonun o an hangi is icin dinlendigi.

    AHK'de bu bayrak sarttti cunku `OnClipboardChange` proses basina TEK
    kez kaydedilebiliyor: pano geçmisi ile hafiza slotlari ayni callback'i
    paylasip modla ayrisiyorlardi. Python'da o kisitlama yok -- birden cok
    dinleyici kurulabilirdi -- ama bayrak yine de dogru sey, cunku asil
    soru "kim dinliyor" degil, "kopyalanan sey NEREYE yazilsin".
    Tek dinleyici + mod, iki dinleyicinin ayni kopyayi iki yere yazma
    yarisindan daha ongorulebilir.
    """

    NONE = 0
    HISTORY = 1
    MEM_SLOTS = 2


class ClipboardState:
    """AHK: State.Clipboard -- metot adlari da ayni birakildi."""

    __slots__ = ("_mode",)

    def __init__(self, mode: ClipboardMode = ClipboardMode.HISTORY) -> None:
        self._mode = mode

    @property
    def mode(self) -> ClipboardMode:
        return self._mode

    def set_mode(self, mode: ClipboardMode) -> None:
        self._mode = mode

    def is_none(self) -> bool:
        return self._mode is ClipboardMode.NONE

    def is_history(self) -> bool:
        return self._mode is ClipboardMode.HISTORY

    def is_mem_slots(self) -> bool:
        return self._mode is ClipboardMode.MEM_SLOTS

    def set_none(self) -> None:
        self._mode = ClipboardMode.NONE

    def set_history(self) -> None:
        self._mode = ClipboardMode.HISTORY

    def set_mem_slots(self) -> None:
        self._mode = ClipboardMode.MEM_SLOTS


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
# @dataclass
# class AppState:
#     """AHK'deki `global State` nesnesinin karsiligi."""
#
#     version: str
#     script: ScriptInfo = field(init=False)
#     busy: Busy = field(default_factory=Busy)
#     mouse: MouseState = field(default_factory=MouseState)
#     clipboard: ClipboardState = field(default_factory=ClipboardState)
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
