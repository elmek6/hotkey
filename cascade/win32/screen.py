"""Ekran yakalama -- tum monitorleri TEK karede, FIZIKSEL pikselde.

Neden Qt'nin `QScreen.grabWindow`'u degil: Qt ekran geometrisini "mantiksal"
piksele cevirir ve karisik DPI'da bu cevrim guvenilir degil. Bu makinede
ikinci monitorun konumu fiziksel (-1920) ama boyutu mantiksal (1418)
raporlaniyor; yakalanan pixmap de kendi devicePixelRatio'suyla geliyor ve
oldugu gibi cizilince olcek kadar kuculuyordu.

Buradaki yol o hesabin tamamini atlar:

  * sanal masaustunun sinirlari `GetSystemMetrics` ile FIZIKSEL pikselde
    alinir (SM_XVIRTUALSCREEN ...) -- monitor eklenir/cikarilir, cozunurluk
    ya da olcek degisirse bu degerler kendiliginden degisir, kod sabit
    hicbir sey varsaymaz
  * ekranin tamami tek `BitBlt` ile kopyalanir -- monitor basina dongu yok,
    dolayisiyla monitorler arasi DPI farki diye bir mesele de yok
  * sonuc gercek piksel boyutunda bir QImage

Surec per-monitor DPI aware olmali, yoksa Windows bu olculeri olceklenmis
verir; PySide6 uygulamasi bunu zaten kendisi ayarliyor.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtGui import QImage

from cascade.win32.structs import user32

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000  # katmanli (saydam) pencereler de gelsin
BI_RGB = 0
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL

user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int


def virtual_rect() -> tuple[int, int, int, int]:
    """Sanal masaustu: (x, y, genislik, yukseklik), FIZIKSEL piksel.

    Sol ustteki monitor negatif koordinatta olabilir; x/y bu yuzden var.
    """
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def grab_virtual() -> tuple[QImage, tuple[int, int, int, int]]:
    """Tum ekranlari tek karede yakalar. (goruntu, sanal dikdortgen) doner.

    Goruntu her zaman fiziksel piksel boyutunda ve devicePixelRatio'su 1 --
    yani "ne yakaladiysak o". Olcek hesabi cagirana kalir.
    """
    x, y, width, height = virtual_rect()
    if width <= 0 or height <= 0:
        return QImage(), (x, y, 0, 0)

    screen_dc = user32.GetDC(None)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not gdi32.BitBlt(
            memory_dc, 0, 0, width, height, screen_dc, x, y, SRCCOPY | CAPTUREBLT
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        # Negatif yukseklik: satirlar YUKARIDAN asagi gelsin. Varsayilan DIB
        # duzeni ters cevriktir; boyle isteyince ayrica cevirmek gerekmiyor.
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB

        buffer = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(
            memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), DIB_RGB_COLORS
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        # 32 bit BI_RGB bellekte BGRA sirasindadir; Format_RGB32 tam bu.
        # `copy()` sart: QImage tamponu odunc alir, buffer burada olur.
        image = QImage(buffer, width, height, width * 4, QImage.Format.Format_RGB32).copy()
        return image, (x, y, width, height)
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)
