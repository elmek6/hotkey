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
import time
import winsound
from collections.abc import Callable

from keypilot.core.hotkey import parse_hotkey
from keypilot.settings import Category, between, setting
from keypilot.win32 import send

log = logging.getLogger("keypilot.actions")

KEY_DELAY = setting(
    "send.keyDelay",
    "Gonderilen tuslar arasi bekleme",
    default=10,
    category=Category.GENERAL,
    tags="gonder tus gecikme kopyala yapistir ctrl vysor emulator flutter",
    desc="Kisayol gonderirken olaylar arasina konan ara (ms). 0 = hepsi tek yiginda",
    info="0=yok 0-200ms",
    validate=between(0, 200, "ms"),
)


def command(*names: str):
    """Metodu eylem kimligiyle isaretler -- kaydi `ActionRunner.adopt` yapar.

    Amac: kimlik, aciklama ve gercek is AYNI yerde dursun. Onceden kimlik
    app.py'nin kurulum blogunda, is ise dosyanin bin satir asagisindaki
    metotta duruyordu.

    Isaretli metot `run()` gibi tek dizgi argumani alir; parametresiz
    komutlar `_argument: str = ""` yazip yok sayar.
    """

    def mark(function):
        function.keypilot_commands = names
        return function

    return mark


def beep(freq: int, ms: int) -> None:
    """Qt dongusunu bloke etmemek icin ayri thread'de. AHK: SoundBeep."""
    threading.Thread(
        target=lambda: _safe_beep(freq, ms), name="keypilot-beep", daemon=True
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

    @property
    def handlers(self) -> dict:
        """Kayitli eylem kimlikleri -- menu/keymap denetimi icin salt okunur."""
        return dict(self._commands)

    @staticmethod
    def _mouse_move(argument: str) -> None:
        """`mouse.move:-10,0` -- imleci GORECELI oynatir (AHK "R" kipi)."""
        dx, _, dy = argument.partition(",")
        send.move_relative(int(dx or 0), int(dy or 0))

    def register(self, name: str, handler: Callable[[str], None]) -> None:
        self._commands[name] = handler

    def adopt(self, *owners: object) -> None:
        """`@command` ile isaretli metotlari sahiplerinden toplayip kaydeder.

        Gezinti SINIF uzerinden: ornek uzerinde `getattr` ile dolasmak
        `handlers` gibi property'leri tetiklerdi. Taban siniflar once
        geliyor ki turemis sinif ayni kimligi ezebilsin.
        """
        for owner in owners:
            for klass in reversed(type(owner).__mro__):
                for attribute, value in vars(klass).items():
                    for name in getattr(value, "keypilot_commands", ()):
                        self.register(name, getattr(owner, attribute))

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

        Kullanicinin basili tuttugu modifier'lar dizinin BASINDA bir kez
        okunuyor ve butun tuslara ayni goruntu uygulaniyor: her tusta
        yeniden sorulursa kendi enjeksiyonumuz okunuyor (bkz.
        `send.held_modifiers`) ve dizinin ikinci tusu modifier'sini
        kaybediyordu.
        """
        held = send.held_modifiers()
        delay = int(KEY_DELAY.get())
        for index, part in enumerate(argument.split()):
            if index and delay:
                time.sleep(delay / 1000.0)
            self._send_key(part, held)

    @staticmethod
    def _send_key(argument: str, held: frozenset[int] | None = None) -> None:
        """send_key:^z  /  send_key:Ctrl+C  /  send_key:Tab

        AHK caret sozdizimi (bkz. core/hotkey.py). Kullanicinin o an zaten
        basili tuttugu modifier tekrar gonderilmez -- fare kisayolu
        `^XButton1` gibi bir tanimda Ctrl elde tutuluyorken bizim ayrica
        Ctrl basip birakmamiz onun basimini bozardi.

        `held` verilmisse basili modifier'lar icin O kullanilir; dizi
        gonderirken tek anlik goruntuyle calisilmasi icin.
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
        if held is None:
            held = send.held_modifiers()
        modifiers = [group[0] for group in hotkey.mods if not held.intersection(group)]
        send.tap(hotkey.vk, *modifiers, delay_ms=int(KEY_DELAY.get()))
