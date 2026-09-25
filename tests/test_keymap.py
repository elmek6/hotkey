"""Tus haritasinin KURULABILDIGI -- keymap.py bir veri dosyasi, ama
icindeki her dizgi `parse_hotkey`den geciyor.

Bu testler olmadan `~MButton` gibi bir yazim hatasi ancak PROGRAM ACILIRKEN
patliyordu: tablolar yalnizca app.py kurulurken kuruluyor, testler ise kendi
kucuk tablolarini yaziyordu.
"""

from keypilot import keymap
from keypilot.commands import Cmd
from keypilot.win32.menu import COLUMN


def test_kisayol_tablosu_kurulur():
    table = keymap.build_hotkeys()
    assert table.bindings
    assert table.prefixes  # F13/F14, Tab, CapsLock, ScrollLock...


def test_kaskadlar_ve_jestler_kurulur():
    from keypilot.core.hot_vectors import Direction

    cascades = keymap.build_cascades()
    assert cascades
    assert 0x7C in cascades and cascades[0x7C].run_cascade is False
    gestures = keymap.build_gestures()
    assert gestures.defs
    assert (keymap.KEY_F13, Direction.UP) in gestures.defs
    assert (0x80, Direction.LEFT) in gestures.defs  # F17
    assert (0x81, Direction.LEFT) in gestures.defs  # F18
    assert gestures.labels(0x81)["P"] == "Back"
    assert gestures.labels(0x81)["S"] == "Home"
    assert keymap.memslots_defs()
    f19 = cascades[0x82]
    combo = f19.combo_for(0x04)
    assert combo is not None
    assert combo.action == Cmd.Clip.PASTE_PREV


def test_turkce_harf_haritasi_vk_dondurur():
    keys = keymap.turkish_keys()
    assert keys  # bu duzende en az birkac tus bulunmali
    assert all(isinstance(vk, int) and len(char) == 1 for vk, char in keys.items())


def _check_menu(spec, seen: list[str]) -> None:
    for entry in spec:
        if entry is None or entry == COLUMN:
            continue
        label, target, *rest = entry
        assert label, "etiketsiz menu ogesi"
        assert len(rest) <= 1
        if isinstance(target, tuple):
            _check_menu(target, seen)
        else:
            assert target
            seen.append(target)


def test_menu_tablolari_bicimli():
    seen: list[str] = []
    for spec in (
        keymap.F13_MENU,
        keymap.F13_MENU_TAIL,
        keymap.SYS_COMMANDS_MENU,
        keymap.SPECIAL_KEYS_MENU,
        keymap.SYSTEM_MENU,
    ):
        _check_menu(spec, seen)
    assert "clip.filter" in seen
    assert Cmd.Idle.SHOW in seen
