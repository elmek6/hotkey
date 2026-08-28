"""WH_KEYBOARD_LL / WH_MOUSE_LL katmani.

Kural: callback O(1). Karar ver (yut / birak), olayi kuyruga at, don.
Icinde I/O, kilit, SendInput, print YOK. Windows'un LowLevelHooksTimeout
degeri varsayilan 300 ms; asilirsa hook sessizce devre disi birakilir.
"""

from __future__ import annotations

import ctypes
import queue
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass

from cascade.win32 import consts as C
from cascade.win32.structs import (
    HOOKPROC,
    KBDLLHOOKSTRUCT,
    MSLLHOOKSTRUCT,
    kernel32,
    user32,
)

SWALLOW = True
PASS = False


@dataclass(frozen=True, slots=True)
class KeyEvent:
    vk: int
    scan: int
    down: bool
    extended: bool
    injected: bool
    ours: bool
    time_ms: int
    t: float  # perf_counter, kaskad sureleri icin


@dataclass(frozen=True, slots=True)
class MouseEvent:
    message: int
    x: int
    y: int
    data: int  # tekerlek delta'si veya XButton numarasi
    injected: bool
    ours: bool
    time_ms: int
    t: float


# Karar fonksiyonlari: olayi alir, yutulacaksa True doner.
KeyFilter = Callable[[KeyEvent], bool]
MouseFilter = Callable[[MouseEvent], bool]


def _no_swallow(_event) -> bool:
    return PASS


class HookThread:
    """Kendi mesaj dongusune sahip ayri thread.

    SetWindowsHookEx, hook'u kuran thread'in mesaj pompasina baglanir; bu
    yuzden Qt event loop'undan ayri bir thread'de kurulur ve orada
    GetMessage donguse girer.
    """

    def __init__(
        self,
        events: queue.Queue,
        key_filter: KeyFilter = _no_swallow,
        mouse_filter: MouseFilter = _no_swallow,
        watch_mouse_move: bool = False,
    ) -> None:
        self.events = events
        self.key_filter = key_filter
        self.mouse_filter = mouse_filter
        self.watch_mouse_move = watch_mouse_move

        self.max_callback_ms = 0.0
        self.dropped = 0

        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._error: BaseException | None = None

        # GC'ye yem olmamalari icin ornek uzerinde tutuluyor.
        self._kb_proc: HOOKPROC | None = None
        self._ms_proc: HOOKPROC | None = None
        self._kb_hook = None
        self._ms_hook = None

    # ---- hook callback'leri (hook thread'inde calisir) ----

    def _on_key(self, ncode: int, wparam: int, lparam: int) -> int:
        if ncode != C.HC_ACTION:
            return user32.CallNextHookEx(None, ncode, wparam, lparam)
        t0 = time.perf_counter()
        swallow = PASS
        try:
            kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            direction = C.KEY_MESSAGES.get(wparam)
            if direction is not None:
                event = KeyEvent(
                    vk=kb.vkCode,
                    scan=kb.scanCode,
                    down=direction == "down",
                    extended=bool(kb.flags & C.LLKHF_EXTENDED),
                    injected=bool(kb.flags & C.LLKHF_INJECTED),
                    ours=kb.dwExtraInfo == C.CASCADE_SIGNATURE,
                    time_ms=kb.time,
                    t=t0,
                )
                swallow = self.key_filter(event)
                self._emit(event)
        except Exception:
            swallow = PASS
        finally:
            elapsed = (time.perf_counter() - t0) * 1000.0
            if elapsed > self.max_callback_ms:
                self.max_callback_ms = elapsed
        if swallow:
            return 1
        return user32.CallNextHookEx(None, ncode, wparam, lparam)

    def _on_mouse(self, ncode: int, wparam: int, lparam: int) -> int:
        if ncode != C.HC_ACTION:
            return user32.CallNextHookEx(None, ncode, wparam, lparam)
        if wparam == C.WM_MOUSEMOVE and not self.watch_mouse_move:
            return user32.CallNextHookEx(None, ncode, wparam, lparam)
        t0 = time.perf_counter()
        swallow = PASS
        try:
            ms = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            raw = ms.mouseData
            # yuksek word: tekerlek delta'si (isaretli) veya XButton numarasi
            high = (raw >> 16) & 0xFFFF
            if wparam in (C.WM_MOUSEWHEEL, C.WM_MOUSEHWHEEL) and high > 0x7FFF:
                high -= 0x10000
            event = MouseEvent(
                message=wparam,
                x=ms.pt.x,
                y=ms.pt.y,
                data=high,
                injected=bool(ms.flags & C.LLMHF_INJECTED),
                ours=ms.dwExtraInfo == C.CASCADE_SIGNATURE,
                time_ms=ms.time,
                t=t0,
            )
            swallow = self.mouse_filter(event)
            self._emit(event)
        except Exception:
            swallow = PASS
        finally:
            elapsed = (time.perf_counter() - t0) * 1000.0
            if elapsed > self.max_callback_ms:
                self.max_callback_ms = elapsed
        if swallow:
            return 1
        return user32.CallNextHookEx(None, ncode, wparam, lparam)

    def _emit(self, event) -> None:
        try:
            self.events.put_nowait(event)
        except queue.Full:
            self.dropped += 1

    # ---- yasam dongusu ----

    def _run(self) -> None:
        try:
            self._thread_id = kernel32.GetCurrentThreadId()
            hmod = kernel32.GetModuleHandleW(None)

            self._kb_proc = HOOKPROC(self._on_key)
            self._ms_proc = HOOKPROC(self._on_mouse)

            self._kb_hook = user32.SetWindowsHookExW(C.WH_KEYBOARD_LL, self._kb_proc, hmod, 0)
            if not self._kb_hook:
                raise ctypes.WinError(ctypes.get_last_error())
            self._ms_hook = user32.SetWindowsHookExW(C.WH_MOUSE_LL, self._ms_proc, hmod, 0)
            if not self._ms_hook:
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException as exc:  # kurulum hatasi
            self._error = exc
            self._ready.set()
            return

        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._ms_hook:
            user32.UnhookWindowsHookEx(self._ms_hook)
        if self._kb_hook:
            user32.UnhookWindowsHookEx(self._kb_hook)
        self._kb_hook = self._ms_hook = None

    def start(self, timeout: float = 5.0) -> None:
        self._thread = threading.Thread(target=self._run, name="cascade-hook", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("hook thread zamaninda hazir olmadi")
        if self._error is not None:
            raise self._error

    def stop(self, timeout: float = 2.0) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, C.WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout)
