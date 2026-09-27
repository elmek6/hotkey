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
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
import winreg
from ctypes import wintypes

from keypilot.core.keynames import vk_from_name
from keypilot.settings import Category, setting
from keypilot.win32 import send
from keypilot.win32.shell import process_exists
from keypilot.win32.structs import user32

log = logging.getLogger("keypilot.magnifier")

REG_PATH = r"Software\Microsoft\ScreenMagnifier"
PROCESS_NAME = "Magnify.exe"

DEFAULT_LEVEL = 100  # buyutec kapaliyken varsayilan yuzde
TOGGLE_LEVEL = 200  # AHK: zoomLevel -- toggle'in ciktigi seviye
STEP_GAP_MS = 180  # AHK: stepGap. Olculdu: <150 ms'de tuslar yutuluyor
WAIT_CHANGE_MS = 400  # AHK: _waitChange timeout
MAX_STEPS = 12  # AHK: loop 12 -- sonsuz donguye karsi tur siniri
START_WAIT_MS = 3000  # AHK: loop 30 * Sleep 100

WINDOW_CLASS = "MagUIClass"  # buyutecin kendi denetim penceresi

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND

HIDE_TASKBAR = setting(
    "magnifier.hide_taskbar",
    "Buyutec gorev cubugunda gorunmesin",
    default=True,
    # Autostart ile ayni sutunda: ikisi de "program acikken sistemde ne
    # gorunsun" sorusunun cevabi.
    category=Category.GENERAL,
    tags="buyutec magnifier gorev cubugu taskbar",
    desc=(
        "Magnify.exe surekli acik kaldigi icin gorev cubugunda bir dugme "
        "isgal ediyor; buyutec zaten tuslarla yonetiliyor."
    ),
)


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
        return _read_level()

    def is_zoomed(self) -> bool:
        return self.level() > DEFAULT_LEVEL

    # ---- disari acilan islemler (hepsi ayri thread'de) ----

    def toggle(self) -> None:
        """AHK: toggle() -- buyutulmusse %100'e don, degilse %200'e cik.
        `F13 & F14` / `F14 & F13` buraya bagli."""
        self._spawn(self._toggle)

    def reset(self) -> None:
        """%100'e don, magnifier acik kalir. Panik tusundan da cagriliyor."""
        self._spawn(self._reset)

    # ---- ic akis (worker thread) ----

    def _spawn(self, work) -> None:
        threading.Thread(target=lambda: self._guard(work), name="keypilot-mag", daemon=True).start()

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

    def _toggle(self) -> None:
        if self.is_zoomed():
            self._reset()
        else:
            self._zoom_to(TOGGLE_LEVEL)

    def _reset(self) -> None:
        if process_exists(PROCESS_NAME):
            self._zoom_to(DEFAULT_LEVEL)

    def _zoom_to(self, target: int) -> bool:
        """Hedef yuzdeye cik/in. Adim boyutu kullanici ayarina bagli oldugu
        icin kademeleri tek tek gonderip her seferinde registry'den
        dogruluyoruz. AHK: zoomTo.

        Dongu icinde kademe REGISTRY'den okunuyor, `level()` degil: surecin
        ayakta oldugu `_ensure_running` ile bir kez dogrulandi, her
        yoklamada (20 ms'de bir) butun surec listesini taramanin anlami yok.
        """
        if not self._ensure_running():
            return False
        first = True
        for _ in range(MAX_STEPS):
            current = _read_level()
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
            if _read_level() != before:
                return True
        return False

    def _ensure_running(self) -> bool:
        """Magnifier'i ILK KULLANIMDA baslatir, sonra acik birakir. Script
        acilisinda degil: hic kullanmayan oturumda bosuna calismasin.
        Bedeli oturumdaki ilk islemin yavas olmasi."""
        if process_exists(PROCESS_NAME):
            _apply_taskbar_visibility()
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
                _apply_taskbar_visibility()
                return True
        running = process_exists(PROCESS_NAME)
        if running:
            _apply_taskbar_visibility()
        return running


# ---- yardimcilar ----


def _send_zoom_key(up: bool) -> None:
    """AHK: Send("#{NumpadAdd}") / Send("#{NumpadSub}")."""
    vk = vk_from_name("NumpadAdd" if up else "NumpadSub")
    if vk is not None:
        send.tap(vk, 0x5B)  # LWin


def _apply_taskbar_visibility() -> None:
    """Ayar aciksa buyutecin gorev cubugu dugmesini kaldirir.

    `WS_EX_TOOLWINDOW` yolu DENENDI ve calismiyor: Magnify.exe baska bir
    surec (ve UIAccess'li), `SetWindowLongW` sessizce basarisiz oluyor,
    exstyle degismeden kaliyor. Calisan yol kabuga sormak: `ITaskbarList
    ::DeleteTab` surec sinirini asabiliyor.

    Etki KALICI DEGIL -- buyutec kapanip acilirsa dugme geri gelir, o
    yuzden her `_ensure_running` cagrisinda tekrar uygulaniyor. Ayar
    kapatilinca dugmeyi geri koymuyoruz; ayar bir SONRAKI acilista
    gecerli olur (`AddTab` calisan pencereyi kabuga yeniden tanitmak icin
    guvenilir degil).
    """
    if not HIDE_TASKBAR.get():
        return
    hwnd = user32.FindWindowW(WINDOW_CLASS, None)
    if not hwnd:
        return
    try:
        _taskbar_delete_tab(hwnd)
    except OSError:
        log.exception("buyutec gorev cubugundan gizlenemedi")


def _taskbar_delete_tab(hwnd: int) -> None:
    """`ITaskbarList::DeleteTab`. comtypes ile: arayuz uc metotluk, elle
    tanimlamak vtable'i ctypes'la sokmekten kisa."""
    import comtypes
    import comtypes.client
    from comtypes import COMMETHOD, GUID, IUnknown

    class ITaskbarList(IUnknown):
        _iid_ = GUID("{56FDF342-FD6D-11D0-958A-006097C9A090}")
        _methods_ = [
            COMMETHOD([], comtypes.HRESULT, "HrInit"),
            COMMETHOD([], comtypes.HRESULT, "AddTab", (["in"], wintypes.HWND, "hwnd")),
            COMMETHOD([], comtypes.HRESULT, "DeleteTab", (["in"], wintypes.HWND, "hwnd")),
        ]

    # Cagri buyutec thread'inden geliyor, COM orada kurulu olmayabilir.
    comtypes.CoInitialize()
    try:
        taskbar = comtypes.client.CreateObject(
            GUID("{56FDF344-FD6D-11D0-958A-006097C9A090}"), interface=ITaskbarList
        )
        taskbar.HrInit()
        taskbar.DeleteTab(hwnd)
    finally:
        comtypes.CoUninitialize()


def _read_dword(name: str, default: int) -> int:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
            value, _kind = winreg.QueryValueEx(key, name)
        return int(value)
    except (OSError, ValueError, TypeError):
        return default


def _read_level() -> int:
    """Registry'deki kademe -- surec ayakta mi diye BAKMAZ (bkz. `level`)."""
    return _read_dword("Magnification", DEFAULT_LEVEL)
