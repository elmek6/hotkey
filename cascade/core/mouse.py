"""Fare olayini kisayol tablosunun anlayacagi tus koduna cevirir.

dispatch.py mouse_filter icinde kullaniliyor. Bu senin AHK scriptinde var:

    ~F13 & WheelUp::   Send("#{NumpadAdd}")     ; zoom
    ~F14 & WheelUp::   Send("{Volume_Up}")      ; ses

Yani tekerlek, fare yan tusu (F13/F14 -- faren onlari klavye tusu olarak
gonderiyor) basiliyken anlam kazaniyor. Klavye modifier'i (Ctrl/Alt) ile
fare kombosu KURULMUYOR; fare kendi arasinda kombo yapiyor.

Bu dosyanin isi sadece cevirme: WM_MOUSEWHEEL (+delta) -> takma kod
VK_WHEEL_UP. Boylece tekerlek de `hotkey.HotkeyTable` icinde normal bir
tus gibi yazilabiliyor.

Saf Python: ctypes yok, sadece sayi cevirisi. Mesaj sabitleri burada
tekrar yaziliyor cunku core/ icinde win32 import'u yasak; degerler
Windows API'sinin degismeyen sabitleri.
"""

from __future__ import annotations

from dataclasses import dataclass

from cascade.core.keynames import (
    VK_WHEEL_DOWN,
    VK_WHEEL_LEFT,
    VK_WHEEL_RIGHT,
    VK_WHEEL_UP,
)

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEHWHEEL = 0x020E

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_MBUTTON = 0x04
VK_XBUTTON1 = 0x05
VK_XBUTTON2 = 0x06

_BUTTONS: dict[int, tuple[int, bool]] = {
    WM_LBUTTONDOWN: (VK_LBUTTON, True),
    WM_LBUTTONUP: (VK_LBUTTON, False),
    WM_RBUTTONDOWN: (VK_RBUTTON, True),
    WM_RBUTTONUP: (VK_RBUTTON, False),
    WM_MBUTTONDOWN: (VK_MBUTTON, True),
    WM_MBUTTONUP: (VK_MBUTTON, False),
}


def mouse_key(message: int, data: int) -> tuple[int, bool] | None:
    """(vk, basildi mi) doner; ilgilenmedigimiz mesajda None.

    `data`: hook'un cozdugu yuksek word -- XButton numarasi ya da isaretli
    tekerlek delta'si. Tekerlegin "birakma" olayi yoktur, her cevrim tek bir
    basim gibi gelir (AHK'deki WheelUp:: davranisi).
    """
    button = _BUTTONS.get(message)
    if button is not None:
        return button
    if message == WM_XBUTTONDOWN:
        return (VK_XBUTTON1 if data == 1 else VK_XBUTTON2, True)
    if message == WM_XBUTTONUP:
        return (VK_XBUTTON1 if data == 1 else VK_XBUTTON2, False)
    if message == WM_MOUSEWHEEL:
        if data == 0:
            return None
        return (VK_WHEEL_UP if data > 0 else VK_WHEEL_DOWN, True)
    if message == WM_MOUSEHWHEEL:
        if data == 0:
            return None
        return (VK_WHEEL_RIGHT if data > 0 else VK_WHEEL_LEFT, True)
    return None


@dataclass(frozen=True, slots=True)
class MouseSeen:
    """Olay izleyicisine giden fare olayi -- KeyEvent ile ayni alanlar.

    Izleyici (ui/monitor.py) klavye olayini bekliyor; fare dugmeleri de
    ayni tabloya dusebilsin diye cevrilmis bicimi burada duruyor. `scan`
    yerine imlecin konumu tasiniyor: fare olayinda tarama kodu yok.
    """

    vk: int
    down: bool
    t: float
    x: int = 0
    y: int = 0
    scan: int = 0
    extended: bool = False
    mouse: bool = True
