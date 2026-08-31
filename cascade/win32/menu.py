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

from cascade.win32.screen import BITMAPINFOHEADER, gdi32
from cascade.win32.structs import kernel32, user32

shell32 = ctypes.WinDLL("shell32", use_last_error=True)

#: Menu tanimlarinda "buradan sonrasi YENI KOLON" isareti (AHK: MENU_COL).
COLUMN = "|"

MF_STRING = 0x0000
MF_POPUP = 0x0010
MF_SEPARATOR = 0x0800
MF_GRAYED = 0x0001
MF_DISABLED = 0x0002
MF_BYPOSITION = 0x0400
#: Bayragi TASIYAN oge yeni bir kolonun ILK ogesi olur (AHK: MENU_COL).
#: Win32 menusu dikeyde ekrana sigmayinca kendiliginden kolon acmaz,
#: kaydirma oku koyar -- kolonu elle istemek gerekiyor.
MF_MENUBARBREAK = 0x0020  # yeni kolon + dikey ayrac cizgisi
MF_MENUBREAK = 0x0040  # yeni kolon, cizgisiz

MIIM_BITMAP = 0x00000080
DI_NORMAL = 0x0003

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
shell32.SHDefExtractIconW.argtypes = [
    wintypes.LPCWSTR, ctypes.c_int, wintypes.UINT,
    ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.HICON), wintypes.UINT,
]
shell32.SHDefExtractIconW.restype = ctypes.c_long
user32.DrawIconEx.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON,
    ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT,
]
user32.DrawIconEx.restype = wintypes.BOOL
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP


class MENUITEMINFOW(ctypes.Structure):
    """`SetMenuItemInfoW` icin -- yalniz `hbmpItem` alanini kullaniyoruz."""

    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("fMask", wintypes.UINT),
        ("fType", wintypes.UINT),
        ("fState", wintypes.UINT),
        ("wID", wintypes.UINT),
        ("hSubMenu", wintypes.HMENU),
        ("hbmpChecked", wintypes.HBITMAP),
        ("hbmpUnchecked", wintypes.HBITMAP),
        ("dwItemData", ctypes.c_void_p),
        ("dwTypeData", wintypes.LPWSTR),
        ("cch", wintypes.UINT),
        ("hbmpItem", wintypes.HBITMAP),
    ]


user32.SetMenuItemInfoW.argtypes = [
    wintypes.HMENU, wintypes.UINT, wintypes.BOOL, ctypes.POINTER(MENUITEMINFOW)
]
user32.SetMenuItemInfoW.restype = wintypes.BOOL

#: Menu ikonlarinin geldigi DLL'ler -- AHK: ICO_SHELL / ICO_RES.
ICON_FILES = {
    "shell": "shell32.dll",
    "res": "imageres.dll",
}

#: `"res:243"` -> HBITMAP. Menu her acilisinda yeniden uretmemek icin.
_icon_cache: dict[str, int] = {}

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


def _icon_bitmap(name: str) -> int:
    """`"res:243"` gibi bir ikon adini menuye konabilir HBITMAP'e cevirir.

    AHK `menuIcon(menu, item, ICO_RES, 243)` ile ayni numaralar: sayi
    DLL icindeki 1-TABANLI ikon sirasi. Menu 32 bit ARGB bitmap kabul
    ediyor, o yuzden ikon bir DIB section'a `DrawIconEx` ile ciziliyor --
    saydam kose ve golge korunuyor (klasik menu metni GDI ile cizildigi
    icin emoji hep tek renk cikiyordu; ikon yolu renkli olanin tek yolu).

    Ikon bulunamazsa 0 doner: menu ikonsuz acilir, hata vermez.
    """
    if name in _icon_cache:
        return _icon_cache[name]
    kind, _, number = name.partition(":")
    path = ICON_FILES.get(kind)
    if path is None or not number.isdigit():
        return 0
    bitmap = 0
    icon = wintypes.HICON()
    # SHDefExtractIcon: kucuk ikonu ISTENEN boyutta verir (ExtractIconEx
    # yalniz 32/16 sistem boyutunu verir ve yuksek DPI'da bulaniklasir).
    # Indeks 0 tabanli, AHK'nin numarasi 1 tabanli.
    result = shell32.SHDefExtractIconW(
        ctypes.c_wchar_p(path), int(number) - 1, 0, ctypes.byref(icon), None, 16
    )
    if result == 0 and icon:
        bitmap = _icon_to_bitmap(icon.value, 16)
        user32.DestroyIcon(icon)
    _icon_cache[name] = bitmap
    return bitmap


def _icon_to_bitmap(icon: int, size: int) -> int:
    """HICON -> 32 bit ARGB HBITMAP (menu `hbmpItem` bunu bekler)."""
    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = size
    header.biHeight = -size  # yukaridan asagi
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0  # BI_RGB
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(
        memory, ctypes.byref(header), 0, ctypes.byref(bits), None, 0
    )
    if bitmap:
        old = gdi32.SelectObject(memory, bitmap)
        user32.DrawIconEx(memory, 0, 0, icon, size, size, 0, None, DI_NORMAL)
        gdi32.SelectObject(memory, old)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(None, screen)
    return bitmap or 0


def _set_icon(handle: int, position: int, name: str) -> None:
    """Ogeye ikon koyar. Ikon yoksa sessizce gecer -- menu yine acilmali."""
    bitmap = _icon_bitmap(name)
    if not bitmap:
        return
    info = MENUITEMINFOW()
    info.cbSize = ctypes.sizeof(MENUITEMINFOW)
    info.fMask = MIIM_BITMAP
    info.hbmpItem = bitmap
    user32.SetMenuItemInfoW(handle, position, True, ctypes.byref(info))


def _build(spec, actions: list[str], default: tuple[str, ...]) -> int:
    """Spec'i HMENU'ye cevirir. Alt menuler ozyinelemeli kurulur.

    Komut kimlikleri 1'den baslar (0 = "secim yapilmadi") ve `actions`
    listesindeki sirayla eslesir.
    """
    handle = user32.CreatePopupMenu()
    position = 0  # ikon koymak icin gereken oge sirasi (ayraclar dahil)
    column = 0  # bir sonraki ogeye eklenecek kolon bayragi
    for entry in spec:
        if entry is None:
            user32.AppendMenuW(handle, MF_SEPARATOR, None, None)
            position += 1
            continue
        if entry == COLUMN:
            # Kolon bayragi ogenin KENDISINDE tasinir: bir sonraki oge
            # yeni kolonun ilkidir (AHK'de de Add'in 3. argumaniydi).
            column = MF_MENUBARBREAK
            continue
        label, target, *rest = entry
        icon = rest[0] if rest else ""
        if isinstance(target, tuple):
            sub = _build(target, actions, default)
            user32.AppendMenuW(
                handle, MF_STRING | MF_POPUP | column, ctypes.c_void_p(sub), label
            )
            # Alt menunun eylem kimligi yok; kalin isteniyorsa ETIKETIYLE
            # eslesiyor (AHK: `m.Default := name`) ve sirasiyla veriliyor.
            if label in default:
                user32.SetMenuDefaultItem(handle, position, True)
        else:
            actions.append(target)
            command = len(actions)
            user32.AppendMenuW(handle, MF_STRING | column, ctypes.c_void_p(command), label)
            if target in default:
                user32.SetMenuDefaultItem(handle, command, False)
        if icon:
            _set_icon(handle, position, icon)
        column = 0
        position += 1
    # Alt menuler koke bagli: DestroyMenu(kok) hepsini birlikte yok eder.
    return handle


def track(spec, title: str = "", default: str | tuple[str, ...] = "") -> str | None:
    """Menuyu imlecin yaninda gosterir; secilen eylem kimligini dondurur.

    Secim yapilmadan kapatildiysa (Esc / disari tiklama) `None` doner.
    """
    actions: list[str] = []
    # Kalin oge birden fazla olabilir -- her ALT MENUNUN kendi kalin ogesi
    # var (Win32'de "default item" menu basina tektir): koke sabitlenen
    # pencere, "Profiller" icinde aktif profil.
    marks = (default,) if isinstance(default, str) else tuple(default)
    handle = _build(spec, actions, tuple(m for m in marks if m))
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
