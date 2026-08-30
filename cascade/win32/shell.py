"""Kabuk bildirimi -- incognito.ahk `_refreshShell` portu.

Explorer son-dosya listesini bellekte tutuyor: registry geri yuklendikten
sonra kabugu tazelemezsek eski liste ekranda kalmaya devam ediyor, yani
"geri yukledim" dedigimiz sey kullanicinin gozunde olmamis gibi gorunuyor.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

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
