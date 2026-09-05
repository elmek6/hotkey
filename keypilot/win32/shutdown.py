"""Disaridan gelen kapanis sebebini yakalar -- AHK'de karsiligi YOKTU.

Sorun su: `KeyPilot.on_exit` bizim kendi cikisimizdan da calisiyor,
Windows'un kapatmasindan da. Log'da ikisi ayni satiri biraktigi surece
"program neden kapandi" sorusunun cevabi yoktu -- bir hiber uykusundan
donuldugunde geriye HICBIR iz kalmiyordu.

Uc ayri kanal var; ucu de ayni `note` cagrisina baglaniyor:

    WM_QUERYENDSESSION / WM_ENDSESSION   oturum kapanmasi, kapatma, logoff
    SetConsoleCtrlHandler                gizli konsolun kapatilmasi
                                         (hotkey.vbs bizi `cmd /c` ile
                                         calistiriyor, yani BIR konsolumuz
                                         var; o konsol olurse surec de olur
                                         ve Python'un cikis kodu KOSMAZ)
    signal SIGTERM/SIGINT/SIGBREAK       taskkill (bayraksiz), Ctrl+C

Yakalanamayan tek yol `TerminateProcess` (taskkill /F, job kapanmasi,
elektrigin kesilmesi): surec haber almadan olur, geriye tek satir kalmaz.
Bunu telafi etmek icin duzenli bir "hala ayaktayim" damgasi YAZILMIYOR --
surekli diske yazan bir sey istenmedi. Zaman capasi asagidaki uyku/uyanma
satirlari: kapanis onlarin arasinda bir yerde olmus demektir.

Uyku/uyanma da BURADAN log'a dusuyor. Kapanis sebebi degil ama kapanisin
ZAMANINI okunur kiliyor: "uykuya girildi ... uyandi ... " satirlarindan
sonra bir daha hicbir sey yoksa surec uykuda ya da uyanirken olmus
demektir.

Konsol denetleyicisi KENDI THREAD'inde kosuyor (Windows enjekte ediyor) ve
elinde yaklasik 5 saniye var. Bu yuzden geri cagrilan sey yalnizca log
yazmali: Qt'ye dokunmak oradan kilitlenme demek.
"""

from __future__ import annotations

import ctypes
import logging
import signal
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

from keypilot import logs
from keypilot.win32.structs import kernel32

log = logging.getLogger("keypilot.shutdown")

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_POWERBROADCAST = 0x0218

ENDSESSION_CLOSEAPP = 0x00000001
ENDSESSION_CRITICAL = 0x40000000
ENDSESSION_LOGOFF = 0x80000000

PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_APMRESUMECRITICAL = 0x0006

_POWER = {
    PBT_APMSUSPEND: "sistem uykuya/hibernate'e giriyor",
    PBT_APMRESUMESUSPEND: "sistem uykudan dondu (kullanici)",
    PBT_APMRESUMEAUTOMATIC: "sistem uykudan dondu (otomatik)",
    PBT_APMRESUMECRITICAL: "sistem KRITIK uykudan dondu (elektrik kesilmis olabilir)",
}

CTRL_C_EVENT = 0
CTRL_BREAK_EVENT = 1
CTRL_CLOSE_EVENT = 2
CTRL_LOGOFF_EVENT = 5
CTRL_SHUTDOWN_EVENT = 6

_CONSOLE = {
    CTRL_C_EVENT: "konsolda Ctrl+C",
    CTRL_BREAK_EVENT: "konsolda Ctrl+Break",
    CTRL_CLOSE_EVENT: "konsol penceresi kapatildi (gozetmenin cmd'si oldu)",
    CTRL_LOGOFF_EVENT: "oturum kapatiliyor (konsol)",
    CTRL_SHUTDOWN_EVENT: "bilgisayar kapatiliyor (konsol)",
}

_SIGNALS = {
    "SIGTERM": "taskkill / disaridan sonlandirma (SIGTERM)",
    "SIGINT": "kesme (SIGINT)",
    "SIGBREAK": "kesme (SIGBREAK)",
}

#: `BOOL WINAPI HandlerRoutine(DWORD)`. Referansi SAKLANMALI: cop toplayici
#: alirsa Windows olmayan bir adrese atlar.
_HANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

kernel32.SetConsoleCtrlHandler.argtypes = [_HANDLER, wintypes.BOOL]
kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL


def _endsession_reason(flags: int) -> str:
    if flags & ENDSESSION_LOGOFF:
        text = "oturum kapatiliyor (logoff)"
    elif flags & ENDSESSION_CLOSEAPP:
        text = "Windows uygulamayi kapatmamizi istedi (guncelleme/yeniden baslatma)"
    else:
        text = "bilgisayar kapatiliyor/yeniden baslatiliyor"
    if flags & ENDSESSION_CRITICAL:
        text += " -- KRITIK (reddedilemez)"
    return text


class _SessionFilter(QAbstractNativeEventFilter):
    """Oturum sonu ve guc olaylarini ana thread'in mesaj dongusunden okur.

    Filtre UYGULAMA duzeyinde kurulu: WM_ENDSESSION ve WM_POWERBROADCAST
    butun ust duzey pencerelere yayin yapilir, Qt'nin kendi gizli
    pencereleri de dahil -- gorunur bir pencereye ihtiyac yok.
    """

    def __init__(self, note: Callable[[str], None]) -> None:
        super().__init__()
        self._note = note

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt adi)
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):  # tanimadigimiz platform/bicim
            return False, 0
        if msg.message == WM_QUERYENDSESSION:
            self._note("Windows kapanis izni istedi: " + _endsession_reason(msg.lParam))
        elif msg.message == WM_ENDSESSION:
            if msg.wParam:
                self._note("oturum kapaniyor: " + _endsession_reason(msg.lParam))
        elif msg.message == WM_POWERBROADCAST:
            text = _POWER.get(msg.wParam)
            if text:
                logs.lifecycle("guc olayi: %s", text)
        # Mesaji ASLA yutmuyoruz: kapanis pazarligini Qt yapsin.
        return False, 0


class ExitWatch:
    """Kapanis sebebini toplayan uc kanal. Bkz. dosya basi.

    `note` BASKA THREAD'den cagrilabilir (konsol denetleyicisi) -- Qt'ye
    dokunmamali, yalnizca log yazmali.
    """

    def __init__(self, note: Callable[[str], None]) -> None:
        self._note = note
        self._filter: _SessionFilter | None = None
        #: ctypes geri cagirmasi -- referans burada TUTULUYOR (bkz. _HANDLER).
        self._console = _HANDLER(self._on_console)

    def install(self, app) -> None:
        self._filter = _SessionFilter(self._note)
        app.installNativeEventFilter(self._filter)

        if not kernel32.SetConsoleCtrlHandler(self._console, True):
            # Konsolsuz calisiyoruz (pythonw): kanal yok, digerleri duruyor.
            log.debug("konsol denetleyicisi kurulamadi (konsol yok)")

        for name, text in _SIGNALS.items():
            number = getattr(signal, name, None)
            if number is None:
                continue
            try:
                signal.signal(number, self._make_signal_handler(text))
            except (ValueError, OSError):
                # Ana thread degilsek ya da sinyal desteklenmiyorsa gec.
                log.debug("sinyal kurulamadi: %s", name)

    def _make_signal_handler(self, text: str):
        def handler(_number, _frame) -> None:
            self._note(text)

        return handler

    def _on_console(self, event: int) -> bool:
        self._note(_CONSOLE.get(event, f"konsol olayi {event}"))
        # False: varsayilan davranis kalsin. CTRL_CLOSE'da Windows bizi
        # zaten olduruyor; yapabildigimiz tek sey sebebi yazmakti.
        return False
