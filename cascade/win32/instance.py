"""Tek ornek kilidi -- AHK'deki `#SingleInstance Force` karsiligi.

Adlandirilmis mutex. Iki cascade ornegi ayni anda LL hook kurarsa hangisinin
tusu once gordugu zincirin kurulum sirasina baglidir ve garanti edilemez;
ayni tusu ikisi birden yutmaya calisir. Bu yuzden ikinci ornek acilmaz.

`wait_seconds`: yeniden baslatmada eski ornek daha kapanmamis olabilir.
Cocuk surec kisa bir sure kilidi bekler, hemen "zaten calisiyor" demez.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from cascade.win32.structs import kernel32

ERROR_ALREADY_EXISTS = 183

kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
kernel32.ReleaseMutex.restype = wintypes.BOOL


class SingleInstance:
    """`with` ya da elle release ile kullanilir.

    acquired False ise bu oturumda zaten bir cascade calisiyor demektir.
    """

    def __init__(self, name: str = "cascade", wait_seconds: float = 0.0) -> None:
        self.name = f"Local\\{name}-single-instance"
        self._handle = None
        self.acquired = False

        deadline = time.monotonic() + wait_seconds
        while True:
            if self._try_acquire():
                return
            if time.monotonic() >= deadline:
                return
            time.sleep(0.1)

    def _try_acquire(self) -> bool:
        handle = kernel32.CreateMutexW(None, True, self.name)
        last_error = ctypes.get_last_error()
        if handle and last_error != ERROR_ALREADY_EXISTS:
            self._handle = handle
            self.acquired = True
            return True
        if handle:
            kernel32.CloseHandle(handle)
        return False

    def release(self) -> None:
        if self._handle:
            kernel32.ReleaseMutex(self._handle)
            kernel32.CloseHandle(self._handle)
            self._handle = None
            self.acquired = False

    def __enter__(self) -> SingleInstance:
        return self

    def __exit__(self, *_) -> None:
        self.release()
