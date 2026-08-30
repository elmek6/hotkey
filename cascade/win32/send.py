"""SendInput sarmalayicisi.

Tuslar scancode ile gonderilir (KEYEVENTF_SCANCODE). VK ile gonderim
DirectInput kullanan oyunlarda ve bazi RDP/uzak masaustu istemcilerinde
goz ardi ediliyor; scancode her yerde calisiyor.

Bu fonksiyonlar hook callback'i icinden CAGRILMAZ. Callback yalnizca
kuyruga yazar; gonderim tuketici thread'de yapilir.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from cascade.win32 import consts as C
from cascade.win32.structs import INPUT, KEYBDINPUT, MOUSEINPUT, user32

# Extended (E0 onekli) scancode gerektiren tuslar.
_EXTENDED_VKS = frozenset(
    {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E,
     0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5, 0x0D}
)


def scancode_for(vk: int) -> tuple[int, bool]:
    """VK -> (scancode, extended). MAPVK_VK_TO_VSC_EX E0 onekini geri verir."""
    raw = user32.MapVirtualKeyW(vk, C.MAPVK_VK_TO_VSC_EX)
    extended = bool(raw & 0xE000) or vk in _EXTENDED_VKS
    return raw & 0xFF, extended


def vk_for_char(ch: str) -> int | None:
    """Karakteri o anki klavye duzeninde ureten tusun VK'si.

    Turkce Q'da `^` VK 0xDC'de, US duzeninde Shift+6'da. Sabit yazmak
    yerine duzene sormak tek dogru yol. Duzende yoksa None.
    """
    raw = user32.VkKeyScanW(ch)
    if raw == -1:
        return None
    return raw & 0xFF


def caps_on() -> bool:
    """Buyuk harf kilidi acik mi (AHK: `GetKeyState("CapsLock", "T")`)."""
    return bool(user32.GetKeyState(0x14) & 1)


def shift_down() -> bool:
    """Iki Shift'ten biri basili mi -- Turkce dizilimi buna bakiyor."""
    return is_down(0xA0) or is_down(0xA1)


def hard_modifier_down() -> bool:
    """Ctrl / Alt / Win basili mi.

    Turkce eklentisi bunlara DOKUNMAZ: AHK'de de `$c::` yalnizca sade ve
    Shift'li basimi yakaliyordu, Ctrl+C kisayolu bozulmasin diye.
    """
    return any(is_down(vk) for vk in (0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C))


def is_down(vk: int) -> bool:
    """Tus su an fiziksel olarak basili mi. Gonderim oncesi modifier
    tekrarini onlemek icin: kullanici zaten Ctrl'yi tutuyorsa bizim Ctrl'yi
    basip birakmamiz onun basimini mantiksal olarak iptal ederdi."""
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _send(inputs: list[INPUT]) -> int:
    if not inputs:
        return 0
    array = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise ctypes.WinError(ctypes.get_last_error())
    return sent


def _key_input(scan: int, extended: bool, up: bool) -> INPUT:
    flags = C.KEYEVENTF_SCANCODE
    if extended:
        flags |= C.KEYEVENTF_EXTENDEDKEY
    if up:
        flags |= C.KEYEVENTF_KEYUP
    item = INPUT(type=C.INPUT_KEYBOARD)
    item.ki = KEYBDINPUT(
        wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=C.CASCADE_SIGNATURE
    )
    return item


def key_down(vk: int) -> None:
    scan, ext = scancode_for(vk)
    _send([_key_input(scan, ext, up=False)])


def key_up(vk: int) -> None:
    scan, ext = scancode_for(vk)
    _send([_key_input(scan, ext, up=True)])


def tap(vk: int, *modifiers: int) -> None:
    """Modifier'lari basili tutarak tek tus. tap(0x43, 0xA2) -> Ctrl+C."""
    seq: list[INPUT] = []
    for mod in modifiers:
        scan, ext = scancode_for(mod)
        seq.append(_key_input(scan, ext, up=False))
    scan, ext = scancode_for(vk)
    seq.append(_key_input(scan, ext, up=False))
    seq.append(_key_input(scan, ext, up=True))
    for mod in reversed(modifiers):
        scan, ext = scancode_for(mod)
        seq.append(_key_input(scan, ext, up=True))
    _send(seq)


def type_text(text: str) -> None:
    """Unicode karakter akisi. Klavye duzeninden bagimsiz (KEYEVENTF_UNICODE).

    Turkce Q/F ayrimi ve AltGr'li karakterler icin scancode degil bu yol
    kullanilir; AHK'deki SendText'in karsiligi.
    """
    seq: list[INPUT] = []
    for ch in text:
        for code in (ord(ch),) if ord(ch) <= 0xFFFF else _surrogates(ch):
            for up in (False, True):
                flags = C.KEYEVENTF_UNICODE | (C.KEYEVENTF_KEYUP if up else 0)
                item = INPUT(type=C.INPUT_KEYBOARD)
                item.ki = KEYBDINPUT(
                    wVk=0, wScan=code, dwFlags=flags, time=0,
                    dwExtraInfo=C.CASCADE_SIGNATURE,
                )
                seq.append(item)
    _send(seq)


def _surrogates(ch: str) -> tuple[int, int]:
    cp = ord(ch) - 0x10000
    return 0xD800 + (cp >> 10), 0xDC00 + (cp & 0x3FF)


def _mouse_input(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    item = INPUT(type=C.INPUT_MOUSE)
    item.mi = MOUSEINPUT(
        dx=dx, dy=dy, mouseData=data & 0xFFFFFFFF, dwFlags=flags, time=0,
        dwExtraInfo=C.CASCADE_SIGNATURE,
    )
    return item


#: VK -> click() adi. `send_key:RButton` gibi bir eylem geldiginde
#: scancode yoluna degil fare yoluna gitmesi icin.
MOUSE_VK_NAMES = {0x01: "left", 0x02: "right", 0x04: "middle", 0x05: "x1", 0x06: "x2"}


def tap_vk(vk: int) -> bool:
    """Tusu gonderir. Fare dugmesiyse tiklama olarak, degilse scancode.

    `True` doner: fare yoluyla gonderildi. Onek olarak yuttugumuz sag tusu
    geri vermek icin gerekiyor -- klavye scancode'u sag tik uretmez.
    """
    name = MOUSE_VK_NAMES.get(vk)
    if name is None:
        tap(vk)
        return False
    click(name)
    return True


_BUTTON_FLAGS = {
    "left": (C.MOUSEEVENTF_LEFTDOWN, C.MOUSEEVENTF_LEFTUP),
    "right": (C.MOUSEEVENTF_RIGHTDOWN, C.MOUSEEVENTF_RIGHTUP),
    "middle": (C.MOUSEEVENTF_MIDDLEDOWN, C.MOUSEEVENTF_MIDDLEUP),
    "x1": (C.MOUSEEVENTF_XDOWN, C.MOUSEEVENTF_XUP),
    "x2": (C.MOUSEEVENTF_XDOWN, C.MOUSEEVENTF_XUP),
}
# XButton'da hangi dugme oldugu mouseData'da tasiniyor.
_BUTTON_DATA = {"x1": 1, "x2": 2}


def click(button: str = "left") -> None:
    down, up = _BUTTON_FLAGS[button]
    data = _BUTTON_DATA.get(button, 0)
    _send([_mouse_input(down, data=data), _mouse_input(up, data=data)])


def wheel(delta: int = 120, horizontal: bool = False) -> None:
    flag = C.MOUSEEVENTF_HWHEEL if horizontal else C.MOUSEEVENTF_WHEEL
    _send([_mouse_input(flag, data=delta)])


def cursor_pos() -> tuple[int, int]:
    """Imlecin ekran koordinati. Jest capasini atmak icin gerekiyor: onek
    tusu KLAVYEDEN gelince elimizde fare konumu olmuyor.

    Hook callback'inden cagriliyor; tek bir okuma, mikrosaniye mertebesinde.
    """
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return (0, 0)
    return (point.x, point.y)


def set_cursor_pos(x: int, y: int) -> None:
    """Imleci zorla oraya koyar. Jest sirasinda imleci dondurmak icin.

    Hareket olayini yutmak cogu durumda imleci zaten dondurur, ama surucusu
    kendi konumunu yazan fareler (bazi oyun fareleri, uzak masaustu) buna
    uymuyor. Bu ikinci kemer: yutma tutmazsa imlec yine yerine cekilir.
    """
    user32.SetCursorPos(int(x), int(y))


def button_down(vk: int) -> None:
    """Fare dugmesini basili birakir -- birakma AYRI cagrilir.

    Sag tus jesti icin: tusu once yutup bekletiyoruz, kullanici fareyi
    surumeye baslayinca "aslinda bu bir surukleme" deyip gercek basimi
    o anda enjekte ediyoruz. tap_vk bunu yapamaz, o bas-birak gonderir.
    """
    flag, _ = _BUTTON_FLAGS[MOUSE_VK_NAMES[vk]]
    _send([_mouse_input(flag, data=_BUTTON_DATA.get(MOUSE_VK_NAMES[vk], 0))])


def button_up(vk: int) -> None:
    _, flag = _BUTTON_FLAGS[MOUSE_VK_NAMES[vk]]
    _send([_mouse_input(flag, data=_BUTTON_DATA.get(MOUSE_VK_NAMES[vk], 0))])


def move_relative(dx: int, dy: int) -> None:
    _send([_mouse_input(C.MOUSEEVENTF_MOVE, dx=dx, dy=dy)])
