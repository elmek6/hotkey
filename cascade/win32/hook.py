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

# NOBETCI (bkz. HookThread.looks_dead). Windows hook'u SESSIZCE dusurur:
# callback LowLevelHooksTimeout'u (varsayilan 300 ms) asarsa haber
# verilmeden zincirden cikariliyor. Ne bir hata kodu ne bir olay var --
# callback bir daha hic cagrilmiyor ve program AYAKTA gorunmeye devam
# ediyor. Acilista en sik gorulen hali bu: disk ve CPU doluyken ilk
# callback'ler gec kaliyor, hook dusuyor, tepsi simgesi duruyor ama
# hicbir tus calismiyor.
#
# Tek belirti su: SISTEM girdi goruyor, BIZ gormuyoruz. GetLastInputInfo
# sistemin son girdisini verir (enjekte olanlar dahil -- hook ayaktaysa
# onlari da gormus olmamiz gerekir), `last_event` bizimkini.
#: Sistemin gordugu son girdi bizimkinden bu kadar daha yeniyse hook oldu.
WATCHDOG_GAP_MS = 3000.0

# YEDEK PLAN -- UYGULANMADI, bilerek duruyor.
#
# 300 ms'lik sure Windows ayaridir ve degistirilebilir:
#
#     HKCU\Control Panel\Desktop\LowLevelHooksTimeout   (DWORD, ms)
#     deger yoksa 300 sayilir; oturum kapatip acinca gecerli olur
#
# Neden gerekebilir: bu dosyadaki callback OLCULDU, tam karar yolu dahil
# bir tus basimi 0.031 ms suruyor -- butcenin on binde biri. Yani hook
# dusmesi kodun yavasligindan DEGIL, thread'in AC KALMASINDAN oluyor:
# bilgisayar acilirken disk ve CPU doluyken, cop toplayici devredeyken ya
# da GIL baska bir iste takiliyken callback siraya giriyor ve 300 ms'yi
# oyle asiyor. Degeri 1000 yapmak o anlara uc kat pay birakir.
#
# Neden simdilik yapilmadi: makine ayarina dokunmadan once yazilim
# tarafindaki sebepler kapatildi -- hook artik acilis yukunun BITTIGI
# yerde kuruluyor (app.py), GIL devri 1 ms'ye cekildi (main.py) ve
# dusen hook'u nobetci geri kuruyor. Bunlar yetmezse sirada bu var.
#
# Bedeli: bir gun gercekten takilirsak Windows bizi 300 ms yerine 1 sn
# sonra kurtarir, yani o sure boyunca butun klavye bizi bekler.


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def system_idle_ms() -> float:
    """Sistemin son girdisinden bu yana gecen sure (ms).

    Cagri basarisizsa 0 degil COK BUYUK bir sayi doner: "sistem de girdi
    gormedi" demek nobetcinin yanlis alarm vermemesi demektir.
    """
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return float("inf")
    return float(ctypes.c_uint32(kernel32.GetTickCount() - info.dwTime).value)


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
        events: queue.Queue | None = None,
        key_filter: KeyFilter = _no_swallow,
        mouse_filter: MouseFilter = _no_swallow,
        watch_mouse_move: bool = False,
    ) -> None:
        #: Ham olay kuyrugu -- ISTEGE BAGLI (bkz. `_emit`). app.py vermiyor,
        #: probes/*.py veriyor.
        self.events = events
        self.key_filter = key_filter
        self.mouse_filter = mouse_filter
        self.watch_mouse_move = watch_mouse_move

        self.max_callback_ms = 0.0
        self.dropped = 0
        #: Callback'in EN SON calistigi an (perf_counter). Enjekte olaylar
        #: da sayilir: soru "hook ayakta mi", "kullanici ne yapti" degil.
        self.last_event = time.perf_counter()
        #: Nobetcinin kac kez hook'u yeniden kurdugu (tani ekraninda).
        self.reinstalls = 0
        #: Yeniden kurulumda eski callback nesneleri: takilan bir thread
        #: hala onlara bakiyor olabilir, GC'ye yem edilemezler.
        self._retired: list[HOOKPROC] = []

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
        self.last_event = t0
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
        # Nobetci damgasi hareket ELENMEDEN once: GetLastInputInfo fare
        # hareketini de sayiyor, biz saymasak "sistem girdi gordu, biz
        # gormedik" der ve saglam hook'u durup dururken yeniden kurardik.
        self.last_event = time.perf_counter()
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
        """Ham olayi kuyruga birakir -- kuyruk VERILMISSE.

        Kuyruk artik istege bagli, cunku app.py onu OKUMADAN atiyordu:
        gercek tuketicisi `seen` kuyrugu (dispatch.py doldurur), buradaki
        ise `_drain` icinde bosaltilip cope gidiyordu. Bedeli gorunmez
        degildi -- olay basina 4 mikrosaniye ve tam da korumaya
        calistigimiz yerde, hook callback'inin ICINDE. Tuslarda bu, karar
        yolunun sekizde biri; jest sirasinda fare hareketi saniyede
        yuzlerce olay uretirken daha da fazlasi.

        probes/*.py kuyrugu gercekten okuyor, o yuzden silinmedi.
        """
        if self.events is None:
            return
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
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="cascade-hook", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("hook thread zamaninda hazir olmadi")
        if self._error is not None:
            raise self._error
        self.last_event = time.perf_counter()

    # ---- nobetci ----

    def looks_dead(self, now: float) -> bool:
        """Hook sessizce dusuruldu mu?

        Windows haber vermiyor, o yuzden olcut dolayli: SISTEM son girdiyi
        BIZDEN daha yakin zamanda gorduyse aradaki olaylar bize hic
        ulasmamis demektir. Iki sure de "simdiye gore" olculdugu icin iki
        ayri saatin (perf_counter / GetTickCount) birbirine gore kaymasi
        onemli degil.

        Kullanici bosta otururken yanlis alarm vermez: kimse dokunmuyorsa
        iki sure birlikte buyur, fark acilmaz.
        """
        if self._thread is None or not self._thread.is_alive():
            return True
        if not self._kb_hook or not self._ms_hook:
            return True
        gap = (now - self.last_event) * 1000.0 - system_idle_ms()
        return gap > WATCHDOG_GAP_MS

    def ensure_alive(self, now: float) -> bool:
        """Nobetci darbesi: gerekiyorsa hook'u yeniden kurar.

        Donus True ise yeniden kurulum YAPILDI -- cagiran tarafin kendi
        hayalet durumunu da temizlemesi gerekir (dispatcher.reset), cunku
        hook olu gecen surede birakma olaylari kaybolmustur.
        """
        if not self.looks_dead(now):
            return False
        self.reinstall()
        return True

    def reinstall(self) -> None:
        """Hook'u sokup yeniden takar.

        Eski callback nesneleri `_retired`da tutuluyor: `stop` join'i zaman
        asimina ugrarsa eski thread hala ayakta olabilir ve GC'lenen bir
        HOOKPROC'a giren Windows sureci cokertir.
        """
        self._retired.extend(p for p in (self._kb_proc, self._ms_proc) if p is not None)
        del self._retired[:-8]  # sinirli tut: yeniden kurulum nadir olmali
        self.stop()
        self._thread_id = 0
        self._kb_hook = self._ms_hook = None
        self.reinstalls += 1
        self.start()

    def stop(self, timeout: float = 2.0) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, C.WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout)
