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

log = logging.getLogger("keypilot.shell")

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
