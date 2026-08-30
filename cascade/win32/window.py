"""Pencere islemleri -- script_state.ahk `WindowModule` + menus.ahk
`menuAlwaysOnTop` portu.

AHK'de bu is `WinGetID("A")` / `WinSetAlwaysOnTop` ile tek satirdi; burada
karsiliklari `GetForegroundWindow` ve `SetWindowPos(HWND_TOPMOST)`.

`WindowPins` sabitlenen pencereleri AKILDA TUTAR (AHK: `onTopWindows` Map).
Sebep: Windows "bu pencere ustte mi" sorusunu ucuz cevaplamiyor -- WS_EX_TOPMOST
okunabilir ama bizim mi sabitledigimiz yoksa uygulamanin kendisinin mi oyle
acildigi ayirt edilemez. AHK de bu yuzden kendi listesini tutuyordu; cikista
`clearAllOnTop` ile hepsi birakiliyor ki program kapaninca ekranda asili
pencere kalmasin.

Kapanmis pencereler listede olu kayit birakir; `prune` her menu acilisinda
onlari temizliyor (AHK'de bu yoktu, olu hwnd menude gorunmeye devam ederdi).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from cascade.win32.structs import user32

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

WS_EX_TOPMOST = 0x00000008
GWL_EXSTYLE = -20

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL


def foreground_window() -> int:
    """AHK: WinGetID("A"). One cikan pencerenin hwnd'si; yoksa 0."""
    return int(user32.GetForegroundWindow() or 0)


def window_title(hwnd: int) -> str:
    """AHK: WinGetTitle. Basligi olmayan pencerede bos dizgi."""
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def window_class(hwnd: int) -> str:
    """AHK: WinGetClass. Uygulama profilleri pencereyi bununla taniyor.

    Tampon 256: Win32 sinif adi en fazla 256 karakter (RegisterClass
    siniri), bu yuzden tek atista okumak yeterli.
    """
    if not hwnd:
        return ""
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def is_window(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def set_always_on_top(hwnd: int, on: bool) -> bool:
    """AHK: WinSetAlwaysOnTop(1/0, "ahk_id " hwnd).

    Yalniz Z-duzeni degisir: NOMOVE|NOSIZE ile konum ve boyuta,
    NOACTIVATE ile odaga dokunulmaz.
    """
    if not is_window(hwnd):
        return False
    return bool(
        user32.SetWindowPos(
            hwnd,
            wintypes.HWND(HWND_TOPMOST if on else HWND_NOTOPMOST),
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    )


@dataclass(frozen=True, slots=True)
class Pin:
    hwnd: int
    title: str


class WindowPins:
    """Bizim sabitledigimiz pencereler -- AHK `State.Window.onTopWindows`.

    Tek ornek app.py'de tutulur; yalniz Qt ana thread'inden kullanilir.
    """

    def __init__(self) -> None:
        self._pins: dict[int, str] = {}

    def __len__(self) -> int:
        return len(self._pins)

    def has(self, hwnd: int) -> bool:
        return hwnd in self._pins

    def items(self) -> tuple[Pin, ...]:
        """Sabitli pencereler, eklenme sirasinda."""
        return tuple(Pin(hwnd, title) for hwnd, title in self._pins.items())

    def prune(self) -> None:
        """Kapanmis pencereleri listeden dusur."""
        for hwnd in [h for h in self._pins if not is_window(h)]:
            del self._pins[hwnd]

    def toggle(self, hwnd: int = 0, title: str = "") -> bool | None:
        """AHK: toggleAlwaysOnTop. Yeni durumu doner; pencere yoksa None.

        hwnd verilmezse one cikan pencere kullanilir (AHK: `this.update()`).
        """
        if not hwnd:
            hwnd = foreground_window()
            title = window_title(hwnd)
        if not is_window(hwnd):
            return None
        if hwnd in self._pins:
            set_always_on_top(hwnd, False)
            del self._pins[hwnd]
            return False
        set_always_on_top(hwnd, True)
        self._pins[hwnd] = title or window_title(hwnd)
        return True

    def clear_all(self) -> None:
        """AHK: clearAllOnTop -- cikista cagrilir, hicbir pencere asili kalmaz."""
        for hwnd in self._pins:
            set_always_on_top(hwnd, False)
        self._pins.clear()


# TODO(AHK): menus.ahk `setMenuDefault` sirali kalin-oge secimi port edilmedi.
#     AHK'de menude tek bir kalin oge vardi ve adaylar oncelik siralaniyordu
#     (1 sabitlenmis aktif pencere, 2 profilsiz pencerede "Ekle", 3 bos "Add").
#     Bizde menude sabit bir varsayilan var (PopupMenu `default`).
# TODO(AHK): script_state.ahk WindowModule'un `getClass`/`isClass` kismi
#     port edilmedi -- yalnizca app_shorts profil eslestirmesinde kullaniliyordu.
