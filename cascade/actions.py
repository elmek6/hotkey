"""Eylem kimliklerini calistiran katman -- AHK'deki dogrudan fonksiyon
referanslarinin karsiligi.

CascadeDef icinde eylemler string olarak duruyor ("send_text:selam ").
Boylece tanim JSON'a yazilabiliyor ve core/ test edilirken hicbir callable
kurulmasi gerekmiyor. Kimligi gercek isle eslestirmek burasinin gorevi.

Bicim:  <ad>            parametresiz
        <ad>:<deger>    parametreli
"""

from __future__ import annotations

import contextlib
import logging
import threading
import winsound
from collections.abc import Callable

from cascade.core.hotkey import parse_hotkey
from cascade.win32 import send

log = logging.getLogger("cascade.actions")


def beep(freq: int, ms: int) -> None:
    """Qt dongusunu bloke etmemek icin ayri thread'de. AHK: SoundBeep."""
    threading.Thread(
        target=lambda: _safe_beep(freq, ms), name="cascade-beep", daemon=True
    ).start()


def _safe_beep(freq: int, ms: int) -> None:
    with contextlib.suppress(RuntimeError):
        winsound.Beep(freq, ms)


class ActionRunner:
    """Eylem kimligi -> gercek is."""

    def __init__(self) -> None:
        self._commands: dict[str, Callable[[str], None]] = {}
        self.register("send_key", self._send_key)
        self.register("send_keys", self._send_keys)
        self.register("send_text", send.type_text)
        self.register("beep", lambda _: beep(800, 60))
        # AHK AutoHotkey.ahk: `#a/#s/#d/#w -> MouseMove(...,"R")`,
        # `#q -> Click("Left")`, `#e -> Click("Right")`. Klavyeyle fare.
        self.register("mouse.move", self._mouse_move)
        self.register("mouse.click", send.click)

    @staticmethod
    def _mouse_move(argument: str) -> None:
        """`mouse.move:-10,0` -- imleci GORECELI oynatir (AHK "R" kipi)."""
        dx, _, dy = argument.partition(",")
        send.move_relative(int(dx or 0), int(dy or 0))

    def register(self, name: str, handler: Callable[[str], None]) -> None:
        self._commands[name] = handler

    def run(self, action: str) -> None:
        name, _, argument = action.partition(":")
        handler = self._commands.get(name)
        if handler is None:
            log.warning("bilinmeyen eylem: %s", action)
            return
        try:
            handler(argument)
        except Exception:
            log.exception("eylem hatasi: %s", action)

    def _send_keys(self, argument: str) -> None:
        """send_keys:^a ^c Enter -- bosluklarla ayrilmis dizi.

        AHK `Send("^a^c{Enter}")` diyebiliyordu cunku kendi mini dili vardi.
        Burada tek tus gonderen yol zaten var; dizi onu tekrarlamak. Ayrac
        bosluk: `^a^c` yazimi ayristirilamaz, `^` hem modifier hem de
        Turkce klavyede bir tus.
        """
        for part in argument.split():
            self._send_key(part)

    @staticmethod
    def _send_key(argument: str) -> None:
        """send_key:^z  /  send_key:Ctrl+C  /  send_key:Tab

        AHK caret sozdizimi (bkz. core/hotkey.py). Kullanicinin o an zaten
        basili tuttugu modifier tekrar gonderilmez -- fare kisayolu
        `^XButton1` gibi bir tanimda Ctrl elde tutuluyorken bizim ayrica
        Ctrl basip birakmamiz onun basimini bozardi.
        """
        try:
            hotkey = parse_hotkey(argument)
        except ValueError:
            log.warning("cozulemeyen tus dizgisi: %s", argument)
            return
        if not hotkey.mods and hotkey.vk in send.MOUSE_VK_NAMES:
            # `send_key:RButton` -- yuttugumuz sag tusu geri vermek icin.
            # Scancode yolu fare dugmesi uretmez.
            send.tap_vk(hotkey.vk)
            return
        modifiers = [
            group[0] for group in hotkey.mods if not any(send.is_down(vk) for vk in group)
        ]
        send.tap(hotkey.vk, *modifiers)
