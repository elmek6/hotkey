"""Parametresiz eylem kimlikleri -- tip guvenli script verisi.

Ayar (`setting`) buraya girmez. keymap / menu / `@command` ayni uyeyi kullanir.

`StrEnum` zaten `str`: `Cmd.Menu.F13 == "menu.f13"`, ekstra `str()` yok.
Parametreli uye `Id.__call__` ile `Cmd.Clip.PASTE(3) == "clip.paste:3"`.
Tus dizileri `Cmd.send_key("^z")` / `Cmd.send_keys("^a", "^v")`.
"""

from __future__ import annotations

from enum import StrEnum, auto


def _prefix(prefix: str):
    """`RESTART -> app.restart`, `PAUSE_DIALOG -> app.pause_dialog`."""

    def next_value(name: str, start: int, count: int, last_values: list[str]) -> str:
        return f"{prefix}.{name.lower()}"

    return staticmethod(next_value)


def _bare():
    """`CLICK_THEN -> click_then` (noktasiz kimlikler)."""

    def next_value(name: str, start: int, count: int, last_values: list[str]) -> str:
        return name.lower()

    return staticmethod(next_value)


class Id(StrEnum):
    """Kimlik + istege bagli arguman: `PASTE_SLOT(3) -> memslots.paste_slot:3`."""

    def __call__(self, arg: object) -> str:
        return f"{self}:{arg}"


class Cmd:
    """Uygulamanin eylem kimlikleri, alana gore."""

    @staticmethod
    def send_key(stroke: str) -> str:
        return Cmd.Run.SEND_KEY(stroke)

    @staticmethod
    def send_keys(*strokes: str) -> str:
        return Cmd.Run.SEND_KEYS(" ".join(strokes))

    @staticmethod
    def send_text(body: str) -> str:
        return Cmd.Run.SEND_TEXT(body)

    class App(Id):
        _generate_next_value_ = _prefix("app")
        RESTART = auto()
        RESTART_DEV_OFF = auto()
        EXIT = auto()
        PAUSE = auto()
        PAUSE_DIALOG = auto()
        SETTINGS = auto()
        MONITOR = auto()

    class Idle(Id):
        _generate_next_value_ = _prefix("idle")
        SHOW = auto()

    class Mbutton(Id):
        _generate_next_value_ = _prefix("mbutton")
        PASTE_ENTER = auto()
        SELECT_PASTE = auto()

    class Menu(Id):
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

    class Clip(Id):
        _generate_next_value_ = _prefix("clip")
        SHOW = auto()
        FILTER = auto()
        PASTE = auto()
        PASTE_PREV = auto()
        IMAGES = auto()

    class Slots(Id):
        _generate_next_value_ = _prefix("slots")
        COPY = auto()
        EDIT = auto()
        GROUP_NEW = auto()
        GROUP_SELECT = auto()
        GROUP_DELETE = auto()
        SEARCH = auto()
        EDIT_FILE = auto()

    class Slot(Id):
        _generate_next_value_ = _prefix("slot")
        PASTE = auto()
        PASTE_GROUP = auto()
        PASTE_SIDE = auto()
        PASTE_ENTER = auto()

    class Macro(Id):
        _generate_next_value_ = _prefix("macro")
        RECORDER = auto()
        PLAY = auto()

    class Magnifier(Id):
        _generate_next_value_ = _prefix("magnifier")
        TOGGLE = auto()
        RESET = auto()
        ZOOM = auto()
        PANIC = auto()

    class Tip(Id):
        _generate_next_value_ = _prefix("tip")
        HIDE = auto()

    class Window(Id):
        _generate_next_value_ = _prefix("window")
        PIN = auto()

    class Qr(Id):
        _generate_next_value_ = _prefix("qr")
        SHOW = auto()

    class Memslots(Id):
        _generate_next_value_ = _prefix("memslots")
        START = auto()
        PASTE = auto()
        PASTE_ENTER = auto()
        PASTE_SLOT = auto()
        PASTE_HIST = auto()
        SAVE_SLOT = auto()

    class Errors(Id):
        _generate_next_value_ = _prefix("errors")
        SHOW = auto()
        COPY = auto()

    class Keys(Id):
        _generate_next_value_ = _prefix("keys")
        MAP = auto()

    class Shorts(Id):
        _generate_next_value_ = _prefix("shorts")
        MANAGE = auto()
        ADD = auto()
        PLAY = auto()
        EDIT = auto()

    class Repository(Id):
        _generate_next_value_ = _prefix("repository")
        OPEN = auto()

    class Incognito(Id):
        _generate_next_value_ = _prefix("incognito")
        OPEN = auto()

    class Turkish(Id):
        _generate_next_value_ = _prefix("turkish")
        TOGGLE = auto()
        LAYOUT = auto()
        SET = auto()

    class Caps(Id):
        _generate_next_value_ = _prefix("caps")
        TOGGLE = auto()

    class Select(Id):
        _generate_next_value_ = _prefix("select")
        START = auto()
        SCREEN = auto()
        OCR = auto()
        OCR_ADV = auto()

    class Area(Id):
        _generate_next_value_ = _prefix("area")
        RUN = auto()

    class State(Id):
        _generate_next_value_ = _prefix("state")
        RESET = auto()

    class Vmouse(Id):
        _generate_next_value_ = _prefix("vmouse")
        TOGGLE = auto()

    class Click(Id):
        _generate_next_value_ = _prefix("click")
        BOUNCE = auto()

    class Mouse(Id):
        _generate_next_value_ = _prefix("mouse")
        MOVE = auto()
        CLICK = auto()

    class Gesture(Id):
        _generate_next_value_ = _prefix("gesture")
        OVERLAY = auto()

    class Run(Id):
        """Noktasiz kosucu adlari (`tip`, `click_then`, `button_down`)."""

        _generate_next_value_ = _bare()
        TIP = auto()
        TIP_HTML = auto()
        NOTIFY = auto()
        YOK = auto()
        CLICK_THEN = auto()
        CLICK3_THEN = auto()
        BUTTON_DOWN = auto()
        BUTTON_UP = auto()
        MOD_DOWN = auto()
        MOD_UP = auto()
        SEND_KEY = auto()
        SEND_KEYS = auto()
        SEND_TEXT = auto()
        BEEP = auto()


__all__ = ["Cmd", "Id"]
