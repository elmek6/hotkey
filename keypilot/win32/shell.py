"""Kabuk isleri: bildirim (incognito.ahk `_refreshShell` portu) ve harici
uygulama acma.

Explorer son-dosya listesini bellekte tutuyor: registry geri yuklendikten
sonra kabugu tazelemezsek eski liste ekranda kalmaya devam ediyor, yani
"geri yukledim" dedigimiz sey kullanicinin gozunde olmamis gibi gorunuyor.
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger("keypilot.shell")

#: Klasik Outlook + yeni Outlook (olk.exe). Acilista ikincisini de gor;
#: yoksa `outlook.exe` tekrar baslatilip ikinci kopya aciliyor.
OUTLOOK_EXES = ("outlook.exe", "olk.exe")

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PATH = 260

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


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
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

shell32 = ctypes.WinDLL("shell32", use_last_error=True)

SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000

shell32.SHChangeNotify.argtypes = [
    wintypes.LONG,
    wintypes.UINT,
    wintypes.LPVOID,
    wintypes.LPVOID,
]
shell32.SHChangeNotify.restype = None

SW_SHOWMINNOACTIVE = 7

shell32.ShellExecuteW.argtypes = [
    wintypes.HWND,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    ctypes.c_int,
]
shell32.ShellExecuteW.restype = wintypes.HINSTANCE


def process_exists(name: str) -> bool:
    """Calisan surec listesinde exe adi var mi (buyuk/kucuk harf duyarsiz)."""
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


def open_minimized(program: str, params: str = "") -> bool:
    """Programi simge durumunda acar; odak calinmaz.

    `outlook.exe` gibi PATH / App Paths kaydindaki adlar yeter: tam yol yok.
    Donus > 32 basari (ShellExecute sozlesmesi).

    Ayni exe zaten calisiyorsa ShellExecute CIFT ornek acar (Outlook).
    O yuzden once surece bakilir; Outlook icin `olk.exe` de ayni uygulama.
    """
    exe = Path(program).name.lower()
    aliases = OUTLOOK_EXES if exe in OUTLOOK_EXES else (exe,)
    if any(process_exists(name) for name in aliases):
        log.info("zaten calisiyor, tekrar acilmadi: %s", exe)
        return True
    result = int(
        shell32.ShellExecuteW(None, "open", program, params or None, None, SW_SHOWMINNOACTIVE)
    )
    if result <= 32:
        log.warning("simge durumunda acilamadi: %s (kod %s)", program, result)
        return False
    return True


def refresh_shell() -> None:
    shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)


def open_in_paint(png_path) -> bool:
    """Verilen PNG'yi Paint'te acar. Basarisizsa False.

    Neden dosya, neden Ctrl+V degil: `mspaint.exe` panodan resim alan bir
    parametre tanimiyor. "Paint'i ac, penceresi gelene kadar bekle, Ctrl+V
    gonder" zinciri ise Windows surumune bagli -- Win11'de Paint bir MSIX
    uygulamasi, acilisi saniyeler suruyor ve pencere sinifi degisebiliyor;
    ustelik varsayilan tuvalden buyuk bir resim yapistirilinca "tuval
    buyutulsun mu?" diyalogu cikiyor. Dosya yolunda bunlarin hicbiri yok:
    Paint resmi tam boyutta, dogru tuvalle acar.
    """
    try:
        subprocess.Popen(["mspaint.exe", str(png_path)])
    except OSError:
        log.warning("Paint acilamadi: %s", png_path, exc_info=True)
        return False
    return True
