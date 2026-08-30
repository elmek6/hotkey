"""Windows Buyuteci -- AHK'deki `Lib/magnifier.ahk` (singleMagnifier).

AHK dosyasindaki tasarim notu aynen gecerli, o yuzden ozeti burada duruyor:

  1. Her acip kapama (`Win+=` / `Win+Esc`) pahali ve ekranda arac cubugu
     birakiyor. ELENDI.
  2. Magnification API ile kendi buyutmemiz: API fareyi IZLEMIYOR; takip,
     kenar davranisi ve cok monitor mantigini elle yazmak gerekti, her
     seferinde yeni bir kenar durumu cikti. ELENDI.
  3. BU: `Magnify.exe` bir kez acilir ve ACIK KALIR; biz yalniz zoom
     kademesini degistiririz. Fare takibi + kenar + cok monitor tamamen
     Windows'un.

Durum icin ayri bayrak TUTMUYORUZ -- tek dogru kaynak registry
(`HKCU\\Software\\Microsoft\\ScreenMagnifier\\Magnification`). AHK'de
olculmus: magnifier calisirken `Win+NumpadAdd` gonderilince deger aninda
guncelleniyor. Boylece kullanici kendi klavyesiyle buyutmeyi degistirse
bile senkron kaliriz.

Zoom adimi kullanicinin Windows ayari ("Yakinlastirma artisi"), o yuzden
hedefe tek gonderimle degil DONGUYLE gidiliyor.

**Cagri Qt thread'ini bloke etmemeli**: `zoom_to` icinde uyku var (ardisik
zoom tuslari arasinda zorunlu bosluk, AHK'de olculmus 180 ms). Bu yuzden
disari acilan butun islemler ayri bir thread'de kosuyor -- `actions.beep`
ile ayni fikir. Ayni anda iki istek girmesin diye tek kilit.

TODO(AHK): `close()` (magnifier'i tamamen kapatma) port edildi ama hicbir
tusa/menuye bagli degil -- AHK'de de "istersen menuden baglarsin" diye
duruyordu.
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import threading
import time
import winreg
from ctypes import wintypes

from cascade.core.keynames import vk_from_name
from cascade.win32 import send
from cascade.win32.structs import kernel32

log = logging.getLogger("cascade.magnifier")

REG_PATH = r"Software\Microsoft\ScreenMagnifier"
PROCESS_NAME = "Magnify.exe"

DEFAULT_LEVEL = 100  # buyutec kapaliyken varsayilan yuzde
TOGGLE_LEVEL = 200  # AHK: zoomLevel -- toggle'in ciktigi seviye
STEP_GAP_MS = 180  # AHK: stepGap. Olculdu: <150 ms'de tuslar yutuluyor
WAIT_CHANGE_MS = 400  # AHK: _waitChange timeout
MAX_STEPS = 12  # AHK: loop 12 -- sonsuz donguye karsi tur siniri
START_WAIT_MS = 3000  # AHK: loop 30 * Sleep 100


class Magnifier:
    """AHK: singleMagnifier. Tek ornek app.py'de tutuluyor."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # ---- durum ----

    def level(self) -> int:
        """Yuzde olarak su anki buyutme; magnifier kapaliyken 100.

        Surec kontrolu SART: `Magnification` degeri magnifier kapandiktan
        sonra da registry'de duruyor, tek basina bakarsak kapali buyutecin
        eski kademesini okuruz.
        """
        if not process_exists(PROCESS_NAME):
            return DEFAULT_LEVEL
        return _read_dword("Magnification", DEFAULT_LEVEL)

    def is_zoomed(self) -> bool:
        return self.level() > DEFAULT_LEVEL

    # ---- disari acilan islemler (hepsi ayri thread'de) ----

    def zoom_in(self) -> None:
        """Bir kademe yakinlastir. `F13 & F14` buraya bagli."""
        self._spawn(lambda: self._step(up=True))

    def zoom_out(self) -> None:
        """Bir kademe uzaklastir. `F14 & F13` buraya bagli."""
        self._spawn(lambda: self._step(up=False))

    def toggle(self) -> None:
        """AHK: toggle() -- buyutulmusse %100'e don, degilse %200'e cik."""
        self._spawn(self._toggle)

    def reset(self) -> None:
        """%100'e don, magnifier acik kalir. Panik tusundan da cagriliyor."""
        self._spawn(self._reset)

    def close(self) -> None:
        """AHK: close() -- once %100, sonra sureci kapat."""
        self._spawn(self._close)

    # ---- ic akis (worker thread) ----

    def _spawn(self, work) -> None:
        threading.Thread(target=lambda: self._guard(work), name="cascade-mag", daemon=True).start()

    def _guard(self, work) -> None:
        # Kilit BEKLEMEDEN alinir: kullanici tekerlegi cevirir gibi hizli
        # basarsa istekleri kuyruga almak yerine dusuruyoruz. Kuyruk
        # olsaydi tus birakildiktan saniyeler sonra zoom devam ederdi.
        if not self._lock.acquire(blocking=False):
            return
        try:
            work()
        except Exception:
            log.exception("buyutec islemi basarisiz")
        finally:
            self._lock.release()

    def _step(self, up: bool) -> None:
        """Tek kademe. AHK'de ayri bir metot degildi (`zoomTo` icindeydi);
        burada var cunku `F13 & F14` dogrudan kademe degistiriyor."""
        if not self._ensure_running():
            return
        before = self.level()
        _send_zoom_key(up)
        self._wait_change(before)

    def _toggle(self) -> None:
        if self.is_zoomed():
            self._reset()
        else:
            self._zoom_to(TOGGLE_LEVEL)

    def _reset(self) -> None:
        if process_exists(PROCESS_NAME):
            self._zoom_to(DEFAULT_LEVEL)

    def _close(self) -> None:
        self._reset()
        try:
            subprocess.run(
                ["taskkill", "/IM", PROCESS_NAME, "/F"],
                check=False,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError:
            log.exception("%s kapatilamadi", PROCESS_NAME)

    def _zoom_to(self, target: int) -> bool:
        """Hedef yuzdeye cik/in. Adim boyutu kullanici ayarina bagli oldugu
        icin kademeleri tek tek gonderip her seferinde registry'den
        dogruluyoruz. AHK: zoomTo."""
        if not self._ensure_running():
            return False
        first = True
        for _ in range(MAX_STEPS):
            current = self.level()
            if current == target:
                return True
            if not first:
                # Ardisik tuslar icin zorunlu bosluk. Yalniz 2. ve sonraki
                # kademeye uygulanir -- tek kademelik toggle etkilenmez.
                time.sleep(STEP_GAP_MS / 1000.0)
            first = False
            _send_zoom_key(up=current < target)
            if not self._wait_change(current):
                return False  # tus islenmedi ya da sinira dayandik
        return False

    def _wait_change(self, before: int, timeout_ms: int = WAIT_CHANGE_MS) -> bool:
        """Registry degeri degisene kadar bekle. SABIT uyku yetmiyor: art
        arda hizli gonderilen tuslarda magnifier ikinciyi ~40 ms icinde
        islemeyebiliyor ve 'degismedi' gorunup dongu erken kesiliyordu."""
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            time.sleep(0.02)
            if self.level() != before:
                return True
        return False

    def _ensure_running(self) -> bool:
        """Magnifier'i ILK KULLANIMDA baslatir, sonra acik birakir. Script
        acilisinda degil: hic kullanmayan oturumda bosuna calismasin.
        Bedeli oturumdaki ilk islemin yavas olmasi."""
        if process_exists(PROCESS_NAME):
            return True
        try:
            subprocess.Popen(  # noqa: S603 -- sabit sistem araci
                [PROCESS_NAME],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError:
            log.exception("buyutec baslatilamadi")
            return False
        # Hazir olmasini bekle -- erken gonderilen tus yutuluyor.
        deadline = time.monotonic() + START_WAIT_MS / 1000.0
        while time.monotonic() < deadline:
            time.sleep(0.1)
            if process_exists(PROCESS_NAME) and _read_dword("RunningState", 0) == 1:
                return True
        return process_exists(PROCESS_NAME)


# ---- yardimcilar ----


def _send_zoom_key(up: bool) -> None:
    """AHK: Send("#{NumpadAdd}") / Send("#{NumpadSub}")."""
    vk = vk_from_name("NumpadAdd" if up else "NumpadSub")
    if vk is not None:
        send.tap(vk, 0x5B)  # LWin


def _read_dword(name: str, default: int) -> int:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
            value, _kind = winreg.QueryValueEx(key, name)
        return int(value)
    except (OSError, ValueError, TypeError):
        return default


# ---- surec kontrolu: AHK ProcessExist ----

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL


def process_exists(name: str) -> bool:
    """AHK: ProcessExist("Magnify.exe"). Adlar buyuk/kucuk harf duyarsiz."""
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return False
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    target = name.lower()
    try:
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.szExeFile.lower() == target:
                return True
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return False
