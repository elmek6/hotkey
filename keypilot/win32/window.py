"""Pencere islemleri -- script_state.ahk `WindowModule` + menus.ahk
`menuAlwaysOnTop` portu.

AHK'de bu is `WinGetID("A")` / `WinSetAlwaysOnTop` ile tek satirdi; burada
karsiliklari `GetForegroundWindow` ve `SetWindowPos(HWND_TOPMOST)`.

Iki ayri kaynak var, ikisi de gerekli:

  `topmost_windows()`  Windows'a sorar -- ekranda su an ustte duran her
                       pencere. Ucuz (olculdu: ~0.5 ms), ama KIMIN
                       sabitledigini soylemez.
  `WindowPins`         BIZIM sabitlediklerimiz (AHK: `onTopWindows` Map).
                       Ayrimi yalnizca bu saglar; menude 📌 (biz) ile
                       📌 ... (win) (yabanci) bundan ayriliyor.

Cikista `clearAllOnTop` ile bizimkiler birakiliyor ki program kapaninca
ekranda asili pencere kalmasin -- yabancilara dokunulmuyor, onlari biz
asmadik.

Kapanmis pencereler listede olu kayit birakir; `prune` her menu acilisinda
onlari temizliyor (AHK'de bu yoktu, olu hwnd menude gorunmeye devam ederdi).
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

from keypilot.win32.structs import kernel32, user32

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
GWL_EXSTYLE = -20

#: DwmGetWindowAttribute: DWMWA_CLOAKED. "Gizlenmis" pencere -- kapatilmis
#: UWP uygulamalari acik gorunur ama ekranda yoktur, listeye girmemeli.
DWMWA_CLOAKED = 14

#: Taramada gizlenen pencere siniflari. Buyutec BIZIM yonettigimiz bir
#: arac (win32/magnifier.py): listede yer kaplamasinin anlami yok, ustelik
#: birakilmasi da ise yaramiyor -- Windows onu kendisi tekrar uste aliyor.
HIDDEN_CLASSES = frozenset({"MagUIClass"})

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
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL

SW_RESTORE = 9
SW_MINIMIZE = 6

#: EnumWindows geri cagrimi. Modul duzeyinde: ctypes tipi her cagride
#: yeniden uretilirse cop toplayici sarmalayiciyi cagri sirasinda
#: toplayabiliyor.
_ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [_ENUM_PROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL

#: Pencerenin DWM'de gizli olup olmadigini yalniz bu DLL biliyor.
_dwmapi = ctypes.WinDLL("dwmapi")


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


def is_topmost(hwnd: int) -> bool:
    """Pencere su an ustte mi. KIMIN astigini soylemez (bkz. WindowPins)."""
    if not is_window(hwnd):
        return False
    return bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


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


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """(sol, ust, sag, alt) ekran koordinati; pencere yoksa hepsi 0.

    Makro kaydinda "pencereye goreli" koordinat bunun sol-ust kosesine
    gore hesaplaniyor -- AHK `CoordMode("Mouse", "Window")` ile ayni nokta
    (istemci alani DEGIL, pencere cercevesi).
    """
    if not is_window(hwnd):
        return (0, 0, 0, 0)
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (0, 0, 0, 0)
    return (rect.left, rect.top, rect.right, rect.bottom)


def minimize(hwnd: int = 0) -> bool:
    """AHK: WinMinimize("A"). hwnd verilmezse one cikan pencereyi kucultur.

    Win+Down tusu yerine dogrudan ShowWindow: Win+Down buyutulmus pencerede
    once "restore" yapar, kucultmez.
    """
    hwnd = hwnd or foreground_window()
    if not is_window(hwnd):
        return False
    return bool(user32.ShowWindow(hwnd, SW_MINIMIZE))


def activate(hwnd: int) -> bool:
    """AHK: WinActivate. Kucultulmusse once geri acar.

    `SetForegroundWindow` her cagirana izin vermiyor (Windows odak calmayi
    kisitliyor): baska bir uygulama etkinken cagrildiginda pencere yalnizca
    gorev cubugunda yanip soner. Makro oynatirken one cikan pencere BIZIM
    tepsi uygulamamiz oldugu icin cogu durumda izin cikiyor.
    """
    if not is_window(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    return bool(user32.SetForegroundWindow(hwnd))


#: `force_focus` denemeler arasinda ne kadar bekler. Bu cagri QT'NIN ANA
#: THREAD'inde kosuyor: en kotu durumda `tries * SETTLE` kadar tepsi,
#: ipucu ve tus kuyrugu bekler. Odagi zaten alabilen bir pencerede hic
#: beklenmiyor (ilk deneme dogrulaniyor ve doniliyor); bekleme yalnizca
#: Windows'un odak vermeyi reddettigi durumda odeniyor.
FOCUS_SETTLE = 0.25


def force_foreground(hwnd: int) -> bool:
    """`SetForegroundWindow`u ZORLA calistir. TEK ATIS, dogrulama yok.

    Windows arka plandaki bir surecin odak calmasini engelliyor: izin
    yalnizca "son girdiyi alan" surecte. Standart kacamak, o an odaktaki
    pencerenin girdi kuyruguna baglanip cagriyi oradan yapmak. Baglanti
    hemen kaldiriliyor -- kalirsa iki thread'in klavye durumu birlesik
    kalir.

    `win32/menu.py` `force_foreground` bu isi menu ve `ui/snip.py` icin
    yapiyordu; adim 14'te Flet penceresi ucuncu kullanici oldu ve is ortak
    yere alindi. Menudeki ad korunuyor (`ui/snip.py` onu cagiriyor), govde
    buraya delege ediyor.
    """
    if user32.SetForegroundWindow(hwnd):
        return True
    other = user32.GetForegroundWindow()
    if not other:
        return False
    target = user32.GetWindowThreadProcessId(other, None)
    mine = kernel32.GetCurrentThreadId()
    if target == mine:
        return False
    user32.AttachThreadInput(mine, target, True)
    try:
        return bool(user32.SetForegroundWindow(hwnd))
    finally:
        user32.AttachThreadInput(mine, target, False)


def force_focus(hwnd: int, tries: int = 3, settle: float = FOCUS_SETTLE) -> bool:
    """Pencereyi one getir ve GERCEKTEN geldigini dogrula.

    ODAK KOPRUSU -- adim 14'un olcumunden cikan yardimci (senaryo H).
    Flet penceresi odagi kendisi ALAMIYOR: `flet.exe` ayri bir surec ve
    kullanicinin son tusu ona gitmedi, yani `window.focused = True` da
    `to_front()` de ise yaramiyor (senaryo G). BIZIM surecimiz
    getirebiliyor; `array_filter` ve `quick_panel` bunu kullanacak
    (ikisinde de arama kutusuna YAZILIYOR, yani odagi almalilar).

    `activate`den farki: sonucu DOGRULUYOR. `SetForegroundWindow` izin
    verilmeyince `False` donmuyor, pencereyi gorev cubugunda yanip soner
    halde birakip `True` donebiliyor. Tek olcut `GetForegroundWindow`.

    Tekrar neden: olcumde tek atis her seferinde yetmedi -- odak bir kez
    alinip hemen kaybedilebiliyor (araya odak calan baska bir uygulama
    giriyor). `tries=1, settle=0` verilirse hic beklemez.

    IPUCU VE ROZET ICIN CAGIRILMAMALI (`tip.py`, `incognito_badge.py`):
    onlar odak ALMAMALI ve Flet'in varsayilan davranisi zaten oyle.
    """
    for _ in range(max(1, tries)):
        if not is_window(hwnd):
            return False
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        force_foreground(hwnd)
        user32.BringWindowToTop(hwnd)
        if foreground_window() == hwnd:
            return True
        if not settle:
            continue
        # Odak degisimi cagri donerken bitmis olmayabilir: pencere baska
        # bir surecte ve haber onun mesaj kuyrugundan geciyor.
        time.sleep(settle)
        if foreground_window() == hwnd:
            return True
    return False


def find_window(cls: str = "", title: str = "") -> int:
    """Sinifi TAM, basligi PARCA eslesen ilk gorunur pencere; yoksa 0.

    AHK'nin `SetTitleMatchMode(2)` davranisi: baslik icerik olarak aranir,
    cunku baslik uygulamaya gore degisiyor ("Adsiz - Not Defteri" bir
    kaydetmeden sonra baska turlu yaziliyor).
    """
    if not cls and not title:
        return 0
    found = 0

    @_ENUM_PROC
    def _visit(hwnd, _lparam):
        nonlocal found
        if not user32.IsWindowVisible(hwnd):
            return True
        if cls and window_class(hwnd) != cls:
            return True
        if title and title.lower() not in window_title(hwnd).lower():
            return True
        found = int(hwnd)
        return False  # bulundu, taramayi bitir

    user32.EnumWindows(_visit, 0)
    return found


@dataclass(frozen=True, slots=True)
class Pin:
    hwnd: int
    title: str


def topmost_windows() -> tuple[Pin, ...]:
    """Su anda WS_EX_TOPMOST isaretli, KULLANICIYA GORUNEN pencereler.

    Kaynak Windows'un kendisi, bizim sozlugumuz degil: bir program cokup
    pencereyi asili biraktiysa ya da kullanici uygulamanin kendi "hep
    ustte"sini actiysa (VLC, Gorev Yoneticisi) burada gorunur -- bizim
    listemizde ise gorunmez.

    Ham liste kirli, olculdu: 253 pencerenin 52'si topmost, 51'i cop
    (ipucu pencereleri, gorev cubugu, IME, cloaked UWP, bizim kendi tip
    pencerelerimiz). Dort suzgec temizliyor: gorunur + basligi var +
    DWM'de gizli degil + tool window degil.

    Maliyet olculdu: tam tarama ~0.5 ms. Menu her acilista tarayabilir,
    onbellege gerek yok.
    """
    found: list[Pin] = []

    def visit(hwnd, _lparam):
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if not style & WS_EX_TOPMOST or style & WS_EX_TOOLWINDOW:
            return True
        if not user32.IsWindowVisible(hwnd) or _is_cloaked(hwnd):
            return True
        if window_class(hwnd) in HIDDEN_CLASSES:
            return True
        title = window_title(hwnd)
        if title:
            found.append(Pin(int(hwnd), title))
        return True

    user32.EnumWindows(_ENUM_PROC(visit), 0)
    return tuple(found)


def _is_cloaked(hwnd) -> bool:
    """DWM'ye gore pencere gizli mi. Cagri basarisizsa "gizli degil" --
    dwmapi bu ozelligi bilmek zorunda degil, bilmiyorsa suzgec bir eleman
    eksik calisir, patlamaz."""
    value = ctypes.c_int(0)
    try:
        result = _dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_CLOAKED,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except OSError:
        return False
    return result == 0 and value.value != 0


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
        if is_topmost(hwnd):
            # Baskasinin astigi pencere (menude "(win)"): dogru davranis onu
            # BIRAKMAK. Yoksa "zaten ustte olani tekrar uste al" olur ve
            # tiklama hicbir sey yapmamis gibi gorunur.
            set_always_on_top(hwnd, False)
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
