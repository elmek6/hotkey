"""Tek ornek kilidi -- AHK'deki `#SingleInstance Force` karsiligi.

Adlandirilmis mutex. Iki cascade ornegi ayni anda LL hook kurarsa hangisinin
tusu once gordugu zincirin kurulum sirasina baglidir ve garanti edilemez;
ayni tusu ikisi birden yutmaya calisir. Bu yuzden ikinci ornek acilmaz.

`wait_seconds`: yeniden baslatmada eski ornek daha kapanmamis olabilir.
Cocuk surec kisa bir sure kilidi bekler, hemen "zaten calisiyor" demez.

DEVRALMA (AHK `#SingleInstance Force`): yeni ornek eskisini DUSURUR. Kilit
alinamazsa adlandirilmis bir olay kuruluyor; calisan ornek o olayi bir
thread'de bekliyor ve tetiklendiginde duzgunce kapaniyor (hook sokuluyor,
pano diske yaziliyor). Sonra kilit yeni orneğe geciyor. Eskiden ikinci
ornek "cascade zaten calisiyor" deyip cikiyordu; F5'ten yeniden
baslatildiginda hafizadaki eski surec ayakta kaliyor ve tuslari o yiyordu.
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

from cascade.win32.structs import kernel32

ERROR_ALREADY_EXISTS = 183

kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
kernel32.ReleaseMutex.restype = wintypes.BOOL
kernel32.CreateEventW.argtypes = [
    wintypes.LPVOID,
    wintypes.BOOL,
    wintypes.BOOL,
    wintypes.LPCWSTR,
]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.SetEvent.restype = wintypes.BOOL
kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
kernel32.ResetEvent.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD

WAIT_OBJECT_0 = 0
#: Devralmada eski ornegin kapanmasi icin beklenen sure. Kapanis pano
#: yazma + hook sokme kadar surer; 5 sn fazlasiyla yeter.
TAKEOVER_SECONDS = 5.0


class SingleInstance:
    """`with` ya da elle release ile kullanilir.

    acquired False ise bu oturumda zaten bir cascade calisiyor demektir.
    """

    def __init__(
        self,
        name: str = "cascade",
        wait_seconds: float = 0.0,
        takeover: bool = True,
    ) -> None:
        self.name = f"Local\\{name}-single-instance"
        self._handle = None
        self.acquired = False
        # Devralma olayi MUTEX'TEN AYRI ve her zaman aciliyor: tetikleyen de
        # bekleyen de ayni adi acar, CreateEventW var olani dondurur.
        self._quit_event = kernel32.CreateEventW(None, True, False, f"Local\\{name}-quit")
        self._stop = threading.Event()

        if self._try_acquire():
            self._arm()
            return
        if takeover:
            # Calisan ornege "kapan" de, sonra kilidi bekle. wait_seconds
            # yeniden baslatmadan gelmis olabilir; devralmada en az
            # TAKEOVER_SECONDS bekleniyor.
            kernel32.SetEvent(self._quit_event)
            wait_seconds = max(wait_seconds, TAKEOVER_SECONDS)

        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            time.sleep(0.1)
            if self._try_acquire():
                self._arm()
                return

    def _arm(self) -> None:
        """Kilit bizde: devralma olayini temizle ki bizi oldurmesin."""
        kernel32.ResetEvent(self._quit_event)

    def watch_quit(self, callback: Callable[[], None]) -> None:
        """Yeni bir ornek acilirsa `callback` cagrilir -- BASKA THREAD'DE.

        Cagrilan taraf Qt'ye dokunmamali; app.py bir bayrak kaldirip isi
        ana thread'deki zamanlayiciya birakiyor.
        """
        if not self.acquired or not self._quit_event:
            return

        def wait() -> None:
            while not self._stop.is_set():
                if kernel32.WaitForSingleObject(self._quit_event, 250) == WAIT_OBJECT_0:
                    callback()
                    return

        threading.Thread(target=wait, name="cascade-takeover", daemon=True).start()


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
        # Olay tutamaci BILEREK kapatilmiyor: bekleyen thread daemon ve
        # 250 ms'lik dilimlerle donuyor, kapatilmis tutamac uzerinde
        # uyanirsa gecersiz tutamaca bakardi. Surec zaten bitiyor.
        self._stop.set()
        if self._handle:
            kernel32.ReleaseMutex(self._handle)
            kernel32.CloseHandle(self._handle)
            self._handle = None
            self.acquired = False

    def __enter__(self) -> SingleInstance:
        return self

    def __exit__(self, *_) -> None:
        self.release()
