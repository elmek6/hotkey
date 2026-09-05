"""Calisma zamani durumu -- script_state.ahk'nin karsiligi.

Aktif olan: ClipboardState (ClipboardModule).

AHK'nin BusyModule'u port EDILMEDI ve bilerek silindi. AHK'de global bir
kilitti cunku uc ayri handler dosyasi (keypilot/hook/mouse) birbirinden
habersizdi; her handler basindaki `if (!State.Busy.isFree()) return` ve
`#HotIf State.Busy.isCombo()` onlari senkronize ediyordu. Burada tek bir
CascadeMachine var ve ayni isi kendi `_phase` alani + `_lock`'u ile zaten
yapiyor -- Busy bire bir kopya bir bayraktan ibaretti. Ilerde birden fazla
bagimsiz alt sistemin (makro oynatici, incognito, OCR) ayni anda kaskadlari
kilitlemesi gerekirse buraya kilit sahibinin adini tutan atomik bir
`claim(caller) -> bool` / `release()` ciftini geri koymak dogru yer olur.

TODO(AHK): script_state.ahk'nin diger modulleri de port edilmedi --
ScriptModule (calisma suresi, istatistik), MouseState (tekerlek kisitlama),
WindowModule (hep ustte tutma) ve IdleModule. Son ikisi Win32 cagrisi
gerektirir, core'un "Win32 import'u yasak" kurali geregi buraya degil
win32/ altina yazilmalilar.
"""

from __future__ import annotations

from enum import IntEnum


class ClipboardMode(IntEnum):
    """AHK: State.Clipboard -- panonun o an hangi is icin dinlendigi.

    AHK'de bu bayrak sartti cunku `OnClipboardChange` proses basina TEK
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
