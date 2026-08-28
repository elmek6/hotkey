"""cascade -- giris noktasi.

Su an sadece istenen kadari:
  Qt -> tepsi (reload / exit / surum) -> hook thread -> kaskad makinesi

Ornek kaskad ScrollLock uzerinde ve dogrudan bu dosyada tanimli. AHK'nin 63
kisayolunu tarayinca kullanmadigin tek uygun tus buydu, yani mevcut AHK
scriptinle cakismiyor.

Mimari kural: hook callback'i (ayri thread) yalnizca yut/birak karari verir ve
eylemleri kuyruga atar. Butun is ana thread'de, Qt zamanlayicisinda yapilir.

Calistir:  baslat.vbs          cift tiklama, konsol yok, normal kullanim
           hata-ayikla.cmd    konsol acik kalir, hatalari gorursun
           VSCode F5          "cascade (ana program)"
"""

from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cascade.actions import ActionRunner, beep
from cascade.core.builder import CascadeDef, KeyBuilder, PressType
from cascade.core.cascade import Beep, CascadeMachine, CloseMenu, OpenMenu, Run
from cascade.core.combo import ComboTracker
from cascade.core.hotkey import HotkeyTable
from cascade.core.mouse import mouse_key
from cascade.core.state import Busy
from cascade.ui.monitor import EventMonitor
from cascade.ui.tip import Tip
from cascade.ui.tray import Tray
from cascade.win32.hook import HookThread, KeyEvent, MouseEvent

VERSION = "0.1.0"


def demo_cascade() -> CascadeDef:
    """AHK'deki cascadeTab()/cascadeCaps() ile ayni sekil, zararsiz eylemlerle."""
    return (
        KeyBuilder("ScrollLock", short=350)
        .main_key(PressType.SHORT, "tip_html:<b>ScrollLock</b> kisa basim 👌")
        .main_key(PressType.MEDIUM, "beep")
        .set_exit_on_press_type(PressType.SHORT)
        .combo("1", "📝 Ornek metin yaz", "send_text:cascade calisiyor ")
        .combo("9", "🔁 Yeniden baslat", "app.restart")
        .combo("0", "🛑 Cikis", "app.exit")
        .named("ScrollLock")
        .build()
    )


def demo_hotkeys() -> HotkeyTable:
    """AHK'nin statik `^!k::` satirlarinin karsiligi -- caret sozdizimi.

    Ikisi de YUTULUYOR: alttaki uygulama bu kombolari hic gormez. Yutmayi
    gormek icin Ctrl+Alt+K'yi bir metin kutusunda dene, hicbir sey olmaz.
    """
    return (
        HotkeyTable()
        .add(
            "^!k",
            "tip_html:<b>Ctrl+Alt+K</b> yakalandi \U0001f642<br>"
            "<span style='color:#8b949e;'>bu kombo alttaki uygulamaya gitmedi</span>",
            "zengin ipucu ornegi",
        )
        .add("^!j", "send_text:cascade \U0001f680 ", "metin yaz")
    )


def demo_mouse() -> HotkeyTable:
    """Fare kisayollari klavyeyle ayni tabloda; tek fark tusun VK'si.

    Ctrl'li secildiler cunku ciplak XButton1/2 hala AHK scriptinin:
    haritadaki "bir tusun tek sahibi olur" kurali. Ctrl basili degilken yan
    tuslar dokunulmadan geciyor.
    """
    return (
        HotkeyTable()
        .add("^XButton1", "send_key:^z", "geri al")
        .add("^XButton2", "send_key:^y", "yinele")
        .add("^+XButton1", "send_key:^x", "kes")
    )


class Cascade:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.tip = Tip()
        self.monitor = EventMonitor()
        self.runner = ActionRunner()

        definition = demo_cascade()
        self.machine = CascadeMachine({definition.key: definition}, Busy())

        # Kaskad disi kisayollar. tracker hangi modifier'in basili oldugunu
        # bilir, tablolar "bu kombo bize mi ait" sorusunu cevaplar.
        self.tracker = ComboTracker()
        self.hotkeys = demo_hotkeys()
        self.mouse_keys = demo_mouse()
        self.paused = False
        self._hk_swallowed: set[int] = set()  # yuttugumuz keydown'in keyup'i
        self._mouse_swallowed: set[int] = set()

        self.events: queue.Queue = queue.Queue(maxsize=4096)
        self.actions: queue.Queue = queue.Queue(maxsize=4096)
        self.seen: queue.Queue = queue.Queue(maxsize=4096)  # (olay, yutuldu mu) -> izleyici
        self.hook = HookThread(
            self.events,
            key_filter=self._key_filter,
            mouse_filter=self._mouse_filter,
        )

        # tip: imlecin yaninda 2 sn gorunup kaybolur.  notify: kalici tepsi balonu.
        self.runner.register("tip", lambda text: self.tip.show_text(text, 2000))
        self.runner.register("tip_html", lambda body: self.tip.show_html(body, 2000))
        self.runner.register("notify", lambda text: self.tray.notify("cascade", text))
        self.runner.register("app.restart", lambda _: self.restart())
        self.runner.register("app.exit", lambda _: self.quit())

        self.tray = Tray(
            VERSION,
            on_monitor=self.show_monitor,
            on_restart=self.restart,
            on_exit=self.quit,
            on_toggle_pause=self.toggle_pause,
        )
        self.tray.show()

        self.hook.start()
        # AHK'deki baslangic TrayTip'i. Tepsi balonu KULLANILMIYOR: Windows onu
        # bildirim merkezinde tutuyor, kalici oluyor. Ipucu 2 sn sonra kendi kapanir.
        self.tip.show_menu(
            f"cascade {VERSION} basladi",
            (
                ("ScrollLock", "kaskad menusu \U0001f5c2\ufe0f"),
                *self.hotkeys.tips,
                *self.mouse_keys.tips,
            ),
            footer="tepsi menusunden duraklatilir",
            ms=3000,
        )

        self._drain_timer = QTimer(app)
        self._drain_timer.timeout.connect(self._drain)
        self._drain_timer.start(16)

        self._tick_timer = QTimer(app)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(20)

    # ---- hook thread ----

    def _key_filter(self, event: KeyEvent) -> bool:
        """Hook thread'inde calisir. O(1): karar ver, kuyruga at, don."""
        if event.ours or self.paused:
            return False

        if event.down:
            chord = self.tracker.key_down(event.vk, event.t)
        else:
            self.tracker.key_up(event.vk, event.t)
            chord = None

        swallow, actions = self.machine.feed_key(event.vk, event.down, event.t)
        if not swallow:
            swallow, extra = self._hotkey_key(event, chord)
            actions += extra

        for action in actions:
            with contextlib.suppress(queue.Full):
                self.actions.put_nowait(action)
        with contextlib.suppress(queue.Full):
            self.seen.put_nowait((event, swallow))
        return swallow

    def _hotkey_key(self, event: KeyEvent, chord) -> tuple[bool, list]:
        """Kaskadin ilgilenmedigi tus: caret tablosuna bakilir.

        Yutma karari keydown'da verilir; ayni tusun keyup'i da yutulmali,
        yoksa alttaki uygulama basilmamis bir tusun birakildigini gorur.
        """
        if not event.down:
            was_ours = event.vk in self._hk_swallowed
            self._hk_swallowed.discard(event.vk)
            return was_ours, []
        if chord is None:  # modifier'in kendisi: dokunma
            return False, []
        binding = self.hotkeys.match(event.vk, chord.modifiers)
        if binding is None:
            return False, []
        self._hk_swallowed.add(event.vk)
        if chord.repeat:  # basili tutmada eylem tekrarlanmaz, yutma surer
            return True, []
        return True, [Run(binding.action, key=event.vk, desc=binding.desc)]

    def _mouse_filter(self, event: MouseEvent) -> bool:
        """Fare ayni kisayol tablosunu kullanir; modifier durumunu klavye
        tarafindaki tracker'dan okur. Tekerlegin birakma olayi yoktur."""
        if event.ours or self.paused:
            return False
        key = mouse_key(event.message, event.data)
        if key is None:
            return False
        vk, down = key

        if not down:
            if vk in self._mouse_swallowed:
                self._mouse_swallowed.discard(vk)
                return True
            return False

        binding = self.mouse_keys.match(vk, self.tracker.held)
        if binding is None:
            return False
        if vk < 0x100:  # gercek dugme: birakmasi da bize ait (tekerlekte yok)
            self._mouse_swallowed.add(vk)
        with contextlib.suppress(queue.Full):
            self.actions.put_nowait(Run(binding.action, key=vk, desc=binding.desc))
        return True

    # ---- ana thread ----

    def _drain(self) -> None:
        while not self.events.empty():
            with contextlib.suppress(queue.Empty):
                self.events.get_nowait()  # HookThread'in kendi kuyrugu; kullanmiyoruz

        showing = self.monitor.isVisible()
        for _ in range(200):
            try:
                event, swallowed = self.seen.get_nowait()
            except queue.Empty:
                break
            if showing:
                self.monitor.add(event, swallowed)

        for _ in range(200):
            try:
                action = self.actions.get_nowait()
            except queue.Empty:
                break
            self._apply(action)

    def _tick(self) -> None:
        if self.paused:
            return
        for action in self.machine.tick(time.perf_counter()):
            self._apply(action)

    def _apply(self, action) -> None:
        if isinstance(action, Run):
            self.runner.run(action.action)
        elif isinstance(action, Beep):
            beep(action.freq, action.ms)
        elif isinstance(action, OpenMenu):
            self.tip.show_menu(action.title, action.items)
        elif isinstance(action, CloseMenu):
            self.tip.hide()

    # ---- tepsi menusu ----

    def show_monitor(self) -> None:
        self.monitor.show()
        self.monitor.raise_()
        self.monitor.activateWindow()

    def toggle_pause(self) -> None:
        """AHK: Suspend. Hook yerinde kalir, sadece kararlar devre disi.

        Hook'u sokup takmak yerine bayrak kullaniliyor: yeniden kurulan hook
        zincirin sonuna duser, baska programlarla sira garantisi kaybolur.
        """
        self.paused = not self.paused
        self.machine.reset()
        self.tracker.reset()
        self._hk_swallowed.clear()
        self._mouse_swallowed.clear()
        self.tray.set_paused(self.paused)
        if self.paused:
            self.tip.show_html(
                "\u23f8\ufe0f <b>duraklatildi</b><br>"
                "<span style='color:#8b949e;'>tuslar dokunulmadan geciyor</span>",
                1600,
            )
        else:
            self.tip.show_html("\u25b6\ufe0f <b>devam</b>", 1200)

    def restart(self) -> None:
        """AHK: Pause+Home -> reloadScript()"""
        self._shutdown()
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__)],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            close_fds=True,
        )
        self.app.quit()

    def quit(self) -> None:
        """AHK: Pause+End -> ExitApp()"""
        self._shutdown()
        self.app.quit()

    def _shutdown(self) -> None:
        self._drain_timer.stop()
        self._tick_timer.stop()
        self.machine.reset()
        self.hook.stop()
        self.tip.hide()
        self.monitor.close()
        self.tray.hide()


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("cascade")
    Cascade(app)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())


# ======================================================================
# ASAGIDAKILER DEVRE DISI -- istenmedi, gerekince yorumdan cikar.
#   * tek ornek kilidi (cascade/win32/instance.py, AHK #SingleInstance)
#   * loglama (cascade/logs.py)
#   * Files/hotkeys.json ayar dosyasindan kisayol okuma
#   * Durum penceresi (surum, calisma suresi, tus sayaci)
# ======================================================================
#
# import logging
# import orjson
# from PySide6.QtWidgets import QMessageBox
# from cascade import logs, paths
# from cascade.core.builder import def_from_dict
# from cascade.core.state import AppState
# from cascade.win32.instance import SingleInstance
#
# DEFAULT_HOTKEYS = {
#     "cascades": [
#         {
#             "name": "ScrollLock",
#             "key": "ScrollLock",
#             "short_ms": 350,
#             "long_ms": None,
#             "exit_on_press_type": 1,
#             "main": {"1": "notify:ScrollLock kisa basim", "2": "beep"},
#             "combos": [
#                 {"key": "1", "desc": "Ornek metin yaz", "action": "send_text:cascade calisiyor "},
#                 {"key": "9", "desc": "Yeniden baslat", "action": "app.restart"},
#                 {"key": "0", "desc": "Cikis", "action": "app.exit"},
#             ],
#         }
#     ]
# }
#
#
# def load_definitions() -> dict[int, CascadeDef]:
#     """Files/hotkeys.json okur; yoksa varsayilani yazar."""
#     paths.ensure_files_dir()
#     if not paths.HOTKEYS.exists():
#         paths.HOTKEYS.write_bytes(orjson.dumps(DEFAULT_HOTKEYS, option=orjson.OPT_INDENT_2))
#     data = orjson.loads(paths.HOTKEYS.read_bytes())
#     definitions: dict[int, CascadeDef] = {}
#     for entry in data.get("cascades", []):
#         try:
#             definition = def_from_dict(entry)
#         except (KeyError, ValueError):
#             logging.getLogger("cascade").exception("kisayol tanimi okunamadi: %r", entry)
#             continue
#         definitions[definition.key] = definition
#     return definitions
#
#
# def reload_hotkeys(self) -> None:
#     definitions = load_definitions()
#     self.machine.set_definitions(definitions)
#     self.tray.notify("cascade", f"{len(definitions)} kisayol yeniden yuklendi")
#
#
# def show_status(self) -> None:
#     keys = "\n".join(f"    {n:<12} {c}" for n, c in self.state.top_keys(8))
#     QMessageBox.information(
#         None,
#         f"cascade {VERSION}",
#         f"Surum          : {VERSION}\n"
#         f"Calisma suresi : {self.state.script.uptime_text()}\n"
#         f"Hook callback  : en uzun {self.hook.max_callback_ms:.3f} ms (sinir 300)\n"
#         f"Dusen olay     : {self.hook.dropped}\n\n"
#         f"En cok basilan tuslar:\n{keys or '    henuz yok'}",
#     )
#
#
# def main_with_lock() -> int:
#     lock = SingleInstance("cascade")
#     app = QApplication(sys.argv)
#     app.setQuitOnLastWindowClosed(False)
#     if not lock.acquired:
#         QMessageBox.warning(None, "cascade", "cascade zaten calisiyor.")
#         return 1
#     logs.setup()
#     cascade = Cascade(app)
#     try:
#         return app.exec()
#     finally:
#         lock.release()
