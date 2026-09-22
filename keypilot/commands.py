"""Parametresiz eylem kimlikleri.

Ayar (`setting`) buraya girmez. Burasi script verisi: bir kez yaz,
keymap / menu / `@command` ayni kimligi kullansin.

Tel formati degismez -- `str(Cmd.Menu.F13) == "menu.f13"`.
Parametreli eylemler (`send_key:^z`, `clip.paste:3`) enum DEGIL:
kisa factory (`Send.key`, `Cmd.Clip.paste(n)`) ayni dizgiyi uretir.
"""

from __future__ import annotations

from enum import StrEnum, auto


def _prefix(prefix: str):
    """`RESTART -> app.restart`, `PAUSE_DIALOG -> app.pause_dialog`."""

    def next_value(name: str, start: int, count: int, last_values: list[str]) -> str:
        return f"{prefix}.{name.lower()}"

    return staticmethod(next_value)


class Cmd:
    """Uygulamanin parametresiz eylem kimlikleri, alana gore."""

    class App(StrEnum):
        _generate_next_value_ = _prefix("app")
        RESTART = auto()
        RESTART_DEV_OFF = auto()
        EXIT = auto()
        PAUSE = auto()
        PAUSE_DIALOG = auto()
        SETTINGS = auto()
        MONITOR = auto()

    class Menu(StrEnum):
        _generate_next_value_ = _prefix("menu")
        F13 = auto()
        SYS = auto()
        QUICK = auto()
        SLOTS = auto()
        SCROLLLOCK = auto()
        CLOSE = auto()
        CLIP = auto()
        BASE_SLOTS = auto()
        SIDE_SLOTS = auto()

    class Clip(StrEnum):
        _generate_next_value_ = _prefix("clip")
        SHOW = auto()
        FILTER = auto()
        PASTE = auto()
        IMAGES = auto()

    class Slots(StrEnum):
        _generate_next_value_ = _prefix("slots")
        COPY = auto()
        EDIT = auto()
        GROUP_NEW = auto()
        GROUP_SELECT = auto()
        GROUP_DELETE = auto()
        SEARCH = auto()
        EDIT_FILE = auto()

    class Slot(StrEnum):
        _generate_next_value_ = _prefix("slot")
        PASTE = auto()
        PASTE_GROUP = auto()
        PASTE_SIDE = auto()
        PASTE_ENTER = auto()

    class Macro(StrEnum):
        _generate_next_value_ = _prefix("macro")
        RECORDER = auto()

    class Magnifier(StrEnum):
        _generate_next_value_ = _prefix("magnifier")
        TOGGLE = auto()
        RESET = auto()
        PANIC = auto()

    class Tip(StrEnum):
        _generate_next_value_ = _prefix("tip")
        HIDE = auto()

    class Window(StrEnum):
        _generate_next_value_ = _prefix("window")
        PIN = auto()

    class Qr(StrEnum):
        _generate_next_value_ = _prefix("qr")
        SHOW = auto()

    class Memslots(StrEnum):
        _generate_next_value_ = _prefix("memslots")
        START = auto()
        PASTE = auto()
        PASTE_ENTER = auto()

    class Errors(StrEnum):
        _generate_next_value_ = _prefix("errors")
        SHOW = auto()
        COPY = auto()

    class Keys(StrEnum):
        _generate_next_value_ = _prefix("keys")
        MAP = auto()

    class Shorts(StrEnum):
        _generate_next_value_ = _prefix("shorts")
        MANAGE = auto()

    class Repository(StrEnum):
        _generate_next_value_ = _prefix("repository")
        OPEN = auto()

    class Incognito(StrEnum):
        _generate_next_value_ = _prefix("incognito")
        OPEN = auto()

    class Turkish(StrEnum):
        _generate_next_value_ = _prefix("turkish")
        TOGGLE = auto()
        LAYOUT = auto()
        SET = auto()

    class Caps(StrEnum):
        _generate_next_value_ = _prefix("caps")
        TOGGLE = auto()


__all__ = ["Cmd"]
