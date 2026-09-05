"""Win32 menusunun KURULMASI -- kolon bayragi ve ikon (win32/menu.py).

Menu gosterilmiyor (TrackPopupMenu bloklar); yalniz HMENU kuruluyor ve
Windows'a "ne kurdum" diye soruluyor. Boylece kolon/ikon yolu gercek API
uzerinde dogrulaniyor, ekranda pencere acilmadan.
"""

import ctypes
from ctypes import wintypes

import pytest

from keypilot.win32 import menu as win32_menu

pytestmark = pytest.mark.skipif(
    not hasattr(ctypes, "windll"), reason="yalniz Windows"
)

MIIM_FTYPE = 0x00000100
MIIM_BITMAP = 0x00000080
MF_MENUBARBREAK = 0x0020


def _item_info(handle: int, position: int):
    info = win32_menu.MENUITEMINFOW()
    info.cbSize = ctypes.sizeof(win32_menu.MENUITEMINFOW)
    info.fMask = MIIM_FTYPE | MIIM_BITMAP
    ok = ctypes.windll.user32.GetMenuItemInfoW(
        wintypes.HMENU(handle), position, True, ctypes.byref(info)
    )
    assert ok
    return info


def test_kolon_ve_ikon_menuye_islenir():
    actions: list[str] = []
    spec = (
        ("Bir", "a"),
        win32_menu.COLUMN,
        ("Iki", "b", "res:243"),
    )
    handle = win32_menu._build(spec, actions)
    try:
        assert actions == ["a", "b"]
        assert ctypes.windll.user32.GetMenuItemCount(wintypes.HMENU(handle)) == 2
        # COLUMN kendi basina bir oge DEGIL: bayragi SONRAKI ogeye biner.
        assert not _item_info(handle, 0).fType & MF_MENUBARBREAK
        second = _item_info(handle, 1)
        assert second.fType & MF_MENUBARBREAK
        assert second.hbmpItem  # ikon bitmap'i yerinde
    finally:
        ctypes.windll.user32.DestroyMenu(wintypes.HMENU(handle))


def test_bilinmeyen_ikon_menuyu_bozmaz():
    """Ikon bulunamazsa oge ikonsuz eklenir, menu yine kurulur."""
    actions: list[str] = []
    handle = win32_menu._build((("Bir", "a", "yok:5"),), actions)
    try:
        assert ctypes.windll.user32.GetMenuItemCount(wintypes.HMENU(handle)) == 1
        assert not _item_info(handle, 0).hbmpItem
    finally:
        ctypes.windll.user32.DestroyMenu(wintypes.HMENU(handle))


MF_CHECKED = 0x0008
MFS_DEFAULT = 0x1000


def _state(handle: int, position: int) -> int:
    """Ogenin durum bayraklari (tikli mi, kalin mi)."""
    return ctypes.windll.user32.GetMenuState(
        wintypes.HMENU(handle), position, 0x0400  # MF_BYPOSITION
    )


def test_checked_tik_isareti_koyar():
    """`CHECKED` isareti gercekten MF_CHECKED'e donuyor mu (ScrollLock
    menusu bununla hangi Turkce setinin secili oldugunu gosteriyor)."""
    actions: list[str] = []
    spec = (("Secili", "a", win32_menu.CHECKED), ("Bos", "b"))
    handle = win32_menu._build(spec, actions)
    try:
        assert actions == ["a", "b"]
        assert _state(handle, 0) & MF_CHECKED
        assert not _state(handle, 1) & MF_CHECKED
    finally:
        ctypes.windll.user32.DestroyMenu(wintypes.HMENU(handle))


def test_tikli_ogeye_ikon_konmaz():
    """Tik ile ikon Win32'de ayni alani paylasir: ikon konursa tik silinir.
    Ikisi birden verilirse tik kazanmali."""
    actions: list[str] = []
    handle = win32_menu._build((("Secili", "a", win32_menu.CHECKED, "res:243"),), actions)
    try:
        assert _state(handle, 0) & MF_CHECKED
        assert not _item_info(handle, 0).hbmpItem
    finally:
        ctypes.windll.user32.DestroyMenu(wintypes.HMENU(handle))
