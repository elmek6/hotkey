"""Gercek Windows menusu -- AHK `Menu()` nesnesinin birebir karsiligi.

Neden QMenu degil: tepsi uygulamasinin aktif penceresi yok. QMenu bir Qt
penceresidir ve acildiginda uygulama foreground olmadigi icin ILK tiklama
pencereyi aktive etmeye harcaniyordu -- "bazen tiklama gitmiyor" sikayetinin
sebebi buydu. `TrackPopupMenu` ise Windows'un kendi modal menu dongusudur:
fare yakalamasini, klavye gezinmeyi, Esc'i, alt menu acilislarini ve ekran
kenarina sigdirmayi isletim sistemi yapar. AHK de menuyu bu API ile
gosteriyordu.

**Sahip pencere sart.** TrackPopupMenu bir HWND ister ve o pencere
foreground DEGILSE menu, disina tiklandiginda kapanmaz (bilinen Win32
davranisi; `PostMessage(WM_NULL)` reçetesi de bunun icin). Bu yuzden 1x1
piksel, saydam, gorev cubugunda gorunmeyen bir sahip pencere aciliyor,
foreground yapiliyor ve menu kapaninca odak eski pencereye GERI VERILIYOR --
menuden secilen eylem tus gonderiyorsa dogru pencereye gitmeli.

**Cagri BLOKLAR.** Menu kapanana kadar TrackPopupMenu donmez; Qt olay
dongusu o sure boyunca durur. Kasitli: menu acikken hook'tan gelen eylemi
islemek zaten istemedigimiz sey. Cagiran taraf (ui/menu.py) bu sirada
dispatcher'i `ui_open` ile susturur, boylece tuslar menuye gider.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from cascade.win32.structs import kernel32, user32

MF_STRING = 0x0000
MF_POPUP = 0x0010
MF_SEPARATOR = 0x0800
MF_GRAYED = 0x0001
MF_DISABLED = 0x0002
MF_BYPOSITION = 0x0400

TPM_LEFTALIGN = 0x0000
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
TPM_NONOTIFY = 0x0080

WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
SW_SHOWNOACTIVATE = 4
SW_HIDE = 0
LWA_ALPHA = 0x00000002
WM_NULL = 0x0000

user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_void_p, wintypes.LPCWSTR
]
user32.AppendMenuW.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, wintypes.HWND, ctypes.c_void_p,
]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
user32.InsertMenuW.argtypes = [
    wintypes.HMENU, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.LPCWSTR
]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.PostMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD
]
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]

_owner: int = 0


def _owner_window() -> int:
    """Menunun sahibi olacak 1x1 saydam pencere -- bir kez acilir, saklanir."""
    global _owner
    if _owner:
        return _owner
    _owner = user32.CreateWindowExW(
        WS_EX_TOOLWINDOW | WS_EX_LAYERED,
        "STATIC", "cascade-menu", WS_POPUP,
        0, 0, 1, 1,
        None, None, kernel32.GetModuleHandleW(None), None,
    ) or 0
    if _owner:
        user32.SetLayeredWindowAttributes(_owner, 0, 1, LWA_ALPHA)
    return _owner


def _force_foreground(hwnd: int) -> None:
    """SetForegroundWindow'u calistir.

    Windows, arka plandaki bir surecin odak calmasini engeller; standart
    kacamak, o an odaktaki pencerenin girdi kuyruguna baglanip cagriyi
    yapmak. Baglanti hemen kaldiriliyor -- kalirsa iki thread'in klavye
    durumu birlesik kalir.
    """
    if user32.SetForegroundWindow(hwnd):
        return
    other = user32.GetForegroundWindow()
    if not other:
        return
    target = user32.GetWindowThreadProcessId(other, None)
    mine = kernel32.GetCurrentThreadId()
    if target == mine:
        return
    user32.AttachThreadInput(mine, target, True)
    try:
        user32.SetForegroundWindow(hwnd)
    finally:
        user32.AttachThreadInput(mine, target, False)


def _build(spec, actions: list[str], default: str) -> int:
    """Spec'i HMENU'ye cevirir. Alt menuler ozyinelemeli kurulur.

    Komut kimlikleri 1'den baslar (0 = "secim yapilmadi") ve `actions`
    listesindeki sirayla eslesir.
    """
    handle = user32.CreatePopupMenu()
    for entry in spec:
        if entry is None:
            user32.AppendMenuW(handle, MF_SEPARATOR, None, None)
            continue
        label, target = entry
        if isinstance(target, tuple):
            sub = _build(target, actions, default)
            user32.AppendMenuW(handle, MF_STRING | MF_POPUP, ctypes.c_void_p(sub), label)
            continue
        actions.append(target)
        command = len(actions)
        user32.AppendMenuW(handle, MF_STRING, ctypes.c_void_p(command), label)
        if default and target == default:
            user32.SetMenuDefaultItem(handle, command, False)
    # Alt menuler koke bagli: DestroyMenu(kok) hepsini birlikte yok eder.
    return handle


def track(spec, title: str = "", default: str = "") -> str | None:
    """Menuyu imlecin yaninda gosterir; secilen eylem kimligini dondurur.

    Secim yapilmadan kapatildiysa (Esc / disari tiklama) `None` doner.
    """
    actions: list[str] = []
    handle = _build(spec, actions, default)
    if title:
        # Baslik satiri: menunun EN USTUNE, pasif oge olarak. AHK'de de
        # basliklar boyle veriliyordu (Win32 menude ayri baslik alani yok).
        user32.InsertMenuW(handle, 0, MF_BYPOSITION | MF_SEPARATOR, None, None)
        user32.InsertMenuW(
            handle, 0, MF_BYPOSITION | MF_STRING | MF_GRAYED | MF_DISABLED, None, title
        )

    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))

    owner = _owner_window()
    previous = user32.GetForegroundWindow()
    try:
        if owner:
            user32.ShowWindow(owner, SW_SHOWNOACTIVATE)
            _force_foreground(owner)
        command = user32.TrackPopupMenu(
            handle,
            TPM_LEFTALIGN | TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY,
            point.x, point.y, 0, owner, None,
        )
        if owner:
            # Menu kapandiktan sonra sahip pencerenin kuyruguna bos bir mesaj
            # atmak sart: yoksa Windows menuyu "hala acik" sayip sonraki
            # menu acilisini yiyor (belgelenmis TrackPopupMenu tuzagi).
            user32.PostMessageW(owner, WM_NULL, 0, 0)
            user32.ShowWindow(owner, SW_HIDE)
        # Odagi geri ver: secilen eylem tus gonderecekse hedef pencereye
        # gitmeli, bizim gorunmez penceremize degil.
        if previous:
            user32.SetForegroundWindow(previous)
    finally:
        user32.DestroyMenu(handle)

    if 1 <= command <= len(actions):
        return actions[command - 1]
    return None


def cancel() -> None:
    """Acik menuyu disaridan kapat -- Win32 menusunu WM_CANCELMODE bitirir."""
    if _owner:
        user32.PostMessageW(_owner, 0x001F, 0, 0)  # WM_CANCELMODE
