"""cascade -- giris noktasi.

Mimari kural: hook callback'i (ayri thread) yalnizca yut/birak karari verir ve
eylemleri kuyruga atar. Butun is ana thread'de, Qt zamanlayicisinda yapilir.
Callback icinden SendInput cagrilmaz -- yeniden giris ve kilitlenme olur.

Deneme icin bagli tuslar (build_hotkeys):
    F13              acilir menu (ui/menu.py) -- icinden filtreli liste acilir
    F14              ipucu
    F13 & F14        onek kombosu: F13 basiliyken F14
    ^ & 1 .. 9       `^` basiliyken rakam -> pano gecmisinin o kaydini yapistirir
    ScrollLock       kaskad menusu (demo_cascade); 2 -> filtreli liste

Pano kopyalandigi anda gecmise dusuyor (ui/clipboard.py + core/clip_history.py).
Gorunur yuzu iki tane: kisa ipucu (tip) ve filtreli liste penceresi
(ui/array_filter.py -- arama + onizleme). Liste bellekte; diske yazma Faz 5.

Calistir:  baslat.vbs          cift tiklama, konsol yok, normal kullanim
           hata-ayikla.cmd    konsol acik kalir, hatalari gorursun
           VSCode F5          "cascade (ana program)"
"""

from __future__ import annotations

import contextlib
import html
import os
import queue
import subprocess
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from cascade.actions import ActionRunner, beep
from cascade.core.builder import CascadeDef, KeyBuilder, PressType
from cascade.core.cascade import Beep, CascadeMachine, CloseMenu, OpenMenu, Run
from cascade.core.clip_history import ClipHistory
from cascade.core.combo import ComboTracker
from cascade.core.filter import FilterItem
from cascade.core.hotkey import HotkeyTable
from cascade.core.keynames import key_name, register_name
from cascade.core.state import Busy, ClipboardState
from cascade.ui.array_filter import ArrayFilter
from cascade.ui.clipboard import ClipboardWatcher
from cascade.ui.menu import PopupMenu
from cascade.ui.monitor import EventMonitor
from cascade.ui.tip import Tip
from cascade.ui.tray import Tray
from cascade.win32 import send
from cascade.win32.hook import HookThread, KeyEvent
from cascade.win32.instance import SingleInstance

VERSION = "0.1.0"

# restart() cocuk surece bunu gecer: eski ornek kilidi birakana kadar bekle.
RESTART_FLAG = "--restart"


def demo_cascade() -> CascadeDef:
    """AHK'deki cascadeTab()/cascadeCaps() ile ayni sekil, zararsiz eylemlerle."""
    return (
        KeyBuilder("ScrollLock", short=350)
        .main_key(PressType.SHORT, "tip_html:<b>ScrollLock</b> kisa basim \U0001f44c")
        .main_key(PressType.MEDIUM, "beep")
        .set_exit_on_press_type(PressType.SHORT)
        .combo("1", "\U0001f4dd Ornek metin yaz", "send_text:cascade calisiyor ")
        .combo("2", "\U0001f4cb Pano gecmisi", "clip.filter")
        .combo("9", "\U0001f501 Yeniden baslat", "app.restart")
        .combo("0", "\U0001f6d1 Cikis", "app.exit")
        .named("ScrollLock")
        .build()
    )


F13_MENU = (
    ("\U0001f4cb Pano gecmisi...", "clip.filter"),
    ("\U0001f5c2\ufe0f Windows pano gecmisi", "send_key:#v"),
    None,
    ("\U0001f5bc\ufe0f Ekran alintisi", "send_key:#+s"),
    None,
    ("\U0001f440 Olay izleyici...", "app.monitor"),
    ("\u23f8\ufe0f Duraklat / Devam", "app.pause"),
    None,
    ("\U0001f501 Yeniden baslat", "app.restart"),
    ("\U0001f6d1 Cikis", "app.exit"),
)
"""AHK: showF13menu(). Oge basina bir kod satiri degil, tek veri tablosu --
ileride JSON'a tasinacak yer burasi."""


def build_hotkeys() -> HotkeyTable:
    """Denemek icin istenen tuslar. AHK'deki statik `::` satirlarinin karsiligi.

    F13/F14 klavyede yok, faren onlari gonderiyor (AHK'de de `F13::` ile
    yakalaniyorlar, SC064/SC065). Bu yuzden "fare tuslari kendi arasinda
    kombo olur" demek, F13 & F14 demek -- klavye modifier'i karismiyor.

    `^` tusunun VK'si klavye duzenine bagli; sabit yazmak yerine duzene
    soruluyor (Turkce Q'da 0xDC, US'de Shift+6). Bulunduktan sonra "Caret"
    adiyla kaydediliyor ki dizgide okunur dursun.
    """
    table = HotkeyTable()

    table.add("F13", "menu.f13", "acilir menu")
    table.add(
        "F14",
        "tip_html:<b>F14</b> \U0001f5b1️ fare yan tusu",
        "ipucu goster",
    )
    table.add(
        "F13 & F14",
        "tip_html:<b>F13 &amp; F14</b> \U0001f389 onek kombosu calisti",
        "fare tuslari kendi arasinda",
    )

    # `^` basiliyken rakam: pano gecmisinin o sirasindaki kaydi yapistirir.
    # 1 en yeni kopya, 2 bir onceki... AHK'deki `clip_slot` mantiginin
    # gecmis listesi uzerinde calisan hali.
    caret = send.vk_for_char("^")
    if caret is not None:
        register_name(caret, "Caret")
        for index in range(1, 10):
            table.add(
                f"Caret & {index}",
                f"clip.paste:{index}",
                "pano gecmisi 1-9" if index == 1 else "",
            )

    return table


def _shorten(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Cascade:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.tip = Tip()
        self.monitor = EventMonitor()
        self.runner = ActionRunner()

        definition = demo_cascade()
        self.machine = CascadeMachine({definition.key: definition}, Busy())

        # Pano. Durum (hangi mod) ile liste (ne saklandi) ayri duruyor;
        # dinleme tek yerde, ui/clipboard.py icinde. AHK'de de boyleydi.
        self.clip_state = ClipboardState()
        self.clip_history = ClipHistory()
        self.clip_watcher = ClipboardWatcher()
        self.clip_watcher.text_copied.connect(self._on_clip_text)
        self.clip_watcher.other_copied.connect(self._on_clip_other)

        # Filtreli liste ve acilir menu. Liste penceresi acikken kisayollar
        # susar (_ui_open): arama kutusuna yazarken `Caret & 1` tetiklenmesin.
        self.filter_window = ArrayFilter()
        self.filter_window.chosen.connect(self.paste_text)
        self.filter_window.closed.connect(lambda: setattr(self, "_ui_open", False))
        self.menu = PopupMenu(self.runner.run)
        self._ui_open = False

        # Kaskad disi kisayollar. tracker basili tuslari bilir (hangi modifier,
        # hangi onek); tablo "bu kombo bize mi ait" sorusunu cevaplar.
        self.tracker = ComboTracker()
        self.hotkeys = build_hotkeys()
        self.paused = False
        self._hk_swallowed: set[int] = set()  # yuttugumuz keydown'in keyup'i
        self._prefix_used: dict[int, bool] = {}  # onek tusu komboya donustu mu

        self.events: queue.Queue = queue.Queue(maxsize=4096)
        self.actions: queue.Queue = queue.Queue(maxsize=4096)
        self.seen: queue.Queue = queue.Queue(maxsize=4096)  # (olay, yutuldu mu) -> izleyici
        self.hook = HookThread(self.events, key_filter=self._key_filter)

        # tip: imlecin yaninda 2 sn gorunup kaybolur.  notify: kalici tepsi balonu.
        self.runner.register("tip", lambda text: self.tip.show_text(text, 2000))
        self.runner.register("tip_html", lambda body: self.tip.show_html(body, 2000))
        self.runner.register("notify", lambda text: self.tray.notify("cascade", text))
        self.runner.register("app.restart", lambda _: self.restart())
        self.runner.register("app.exit", lambda _: self.quit())
        self.runner.register("clip.show", lambda _: self.show_clip_history())
        self.runner.register("clip.filter", lambda _: self.show_clip_filter())
        self.runner.register("clip.paste", self.paste_history)
        self.runner.register("menu.f13", lambda _: self.show_f13_menu())
        self.runner.register("app.monitor", lambda _: self.show_monitor())
        self.runner.register("app.pause", lambda _: self.toggle_pause())

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
        # bildirim merkezinde tutuyor, kalici oluyor. Ipucu kendi kapanir.
        self.tip.show_menu(
            f"cascade {VERSION} basladi",
            (("ScrollLock", "kaskad menusu \U0001f5c2️"), *self.hotkeys.tips),
            footer="tepsi menusunden duraklatilir",
            ms=3000,
        )

        self._drain_timer = QTimer(app)
        self._drain_timer.timeout.connect(self._drain)
        self._drain_timer.start(8)

        self._tick_timer = QTimer(app)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(20)

    # ---- hook thread ----

    def _key_filter(self, event: KeyEvent) -> bool:
        """Hook thread'inde calisir. O(1): karar ver, kuyruga at, don."""
        if event.ours or self.paused or self._ui_open:
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
        """Kaskadin ilgilenmedigi tus: kisayol tablosuna bakilir.

        Onek tusu (F13, `^`) basildigi anda yutulur, cunku komboya donusup
        donusmeyecegi o an bilinmiyor -- LL hook keydown'da cevap vermek
        zorunda, AHK gibi bekleyemeyiz. Karar birakildiginda veriliyor:

          kombo yapildi   -> hicbir sey, kombo eylemi zaten calisti
          kendi tanimi var-> o eylem calisir (F13 -> ipucu)
          ikisi de yok    -> orijinal tus geri gonderilir (`^` yazilir)
        """
        if not event.down:
            return self._hotkey_up(event)

        if chord is None:  # modifier'in kendisi: dokunma
            return False, []

        # Onek tusu: kendi tanimi olsa bile karar birakmaya ertelenir, cunku
        # F13'un tek basina mi yoksa F13 & F14 mi oldugu daha belli degil.
        if event.vk in self.hotkeys.prefixes and chord.prefix is None:
            self._prefix_used.setdefault(event.vk, False)
            self._hk_swallowed.add(event.vk)
            return True, []

        binding = self.hotkeys.match(event.vk, chord.modifiers, chord.prefix)
        if binding is None:
            return False, []
        if chord.prefix is not None:
            self._prefix_used[chord.prefix] = True
        self._hk_swallowed.add(event.vk)
        if chord.repeat:  # basili tutmada eylem tekrarlanmaz, yutma surer
            return True, []
        return True, [Run(binding.action, key=event.vk, desc=binding.desc)]

    def _hotkey_up(self, event: KeyEvent) -> tuple[bool, list]:
        was_ours = event.vk in self._hk_swallowed
        self._hk_swallowed.discard(event.vk)
        if event.vk not in self._prefix_used:
            return was_ours, []

        used = self._prefix_used.pop(event.vk)
        if used:
            return was_ours, []

        binding = self.hotkeys.match(event.vk)  # oneki n kendi tanimi var mi
        if binding is not None:
            return was_ours, [Run(binding.action, key=event.vk, desc=binding.desc)]
        # Hicbir sey olmadi: yuttugumuz tusu geri ver, kullanici `^` yazabilsin.
        return was_ours, [Run(f"send_key:{key_name(event.vk)}", key=event.vk)]

    # ---- pano (ana thread) ----

    def _on_clip_text(self, text: str) -> None:
        """AHK: processClipboard'in gecmise ekleyen kismi.

        Mod kontrolu AHK'deki `if (!State.Clipboard.isHistory()) return`
        ile ayni yerde: dinleyici her zaman dinler, kaydi durum belirler.
        """
        if not self.clip_state.is_history():
            return
        entry = self.clip_history.add(text, time.time())
        if entry is None:
            return  # bos, cok buyuk ya da zaten en ustteki kayit
        self.tip.show_html(
            f"📋 <b>{len(self.clip_history)}.</b> "
            f"{html.escape(_shorten(entry.preview))}",
            1200,
        )

    def _on_clip_other(self) -> None:
        """Metin olmayan icerik. Gorsel pano Faz 7; simdilik AHK'deki gibi
        sadece 'gordum' demek yeterli."""
        self.tip.show_html("⛵ <span style='color:#8b949e;'>metin disi kopya</span>", 900)

    def paste_text(self, text: str) -> None:
        """AHK: ArrayFilter.sendText -- panoya yaz, kisa bekle, Ctrl+V.

        Bekleme sus payi degil: panoya yazmak asenkron bitiyor ve hedef
        uygulama Ctrl+V'yi ayni anda alirsa eski icerigi yapistiriyor.
        AHK'de de Sleep(50) vardi. Kendi yazdigimiz metin gecmise ikinci kez
        girmiyor -- ClipboardWatcher.set_text bunu biliyor.
        """
        if not text:
            return
        self.clip_watcher.set_text(text)
        QTimer.singleShot(60, lambda: self.runner.run("send_key:^v"))

    def paste_history(self, argument: str) -> None:
        """`^ & 1` -> gecmisin 1. kaydi. 1 tabanli, AHK ile ayni."""
        try:
            index = int(argument)
        except ValueError:
            return
        entry = self.clip_history.get(index)
        if entry is None:
            self.tip.show_html(
                f"\U0001f4cb <b>{index}.</b> "
                "<span style='color:#8b949e;'>kayit yok</span>",
                1200,
            )
            return
        self.tip.show_html(
            f"\U0001f4cb <b>{index}.</b> {html.escape(_shorten(entry.preview, 40))}",
            1200,
        )
        self.paste_text(entry.text)

    def show_clip_filter(self) -> None:
        """Pano gecmisini filtreli listede acar -- array_filter.ahk'nin
        pano icin kullanildigi yer. Liste veriye cevrilir; pencere panoyu
        bilmez, sadece FilterItem gosterir."""
        entries = self.clip_history.entries
        if not entries:
            self.tip.show_html("\U0001f4cb <b>pano gecmisi bos</b>", 1500)
            return
        items = tuple(
            FilterItem(
                name=f"{index}" + (f" x{entry.count}" if entry.count > 1 else ""),
                content=entry.text,
                key=index,
            )
            for index, entry in enumerate(entries, start=1)
        )
        self._ui_open = True
        self.filter_window.show_items(items, "Pano gecmisi")  # sayiyi pencere ekler

    def show_f13_menu(self) -> None:
        """AHK: showF13menu()"""
        self.menu.show(F13_MENU, title=f"cascade {VERSION}", default="clip.filter")

    def show_clip_history(self) -> None:
        entries = self.clip_history.entries[:9]
        if not entries:
            self.tip.show_html("📋 <b>pano gecmisi bos</b>", 1500)
            return
        items = tuple(
            (
                str(index),
                html.escape(_shorten(entry.preview))
                + (
                    f" <span style='color:#8b949e;'>x{entry.count}</span>"
                    if entry.count > 1
                    else ""
                ),
            )
            for index, entry in enumerate(entries, start=1)
        )
        self.tip.show_menu(
            f"📋 Pano gecmisi ({len(self.clip_history)})",
            items,
            footer="",
            ms=4000,
        )

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
        self._prefix_used.clear()
        self.tray.set_paused(self.paused)
        if self.paused:
            self.tip.show_html(
                "⏸️ <b>duraklatildi</b><br>"
                "<span style='color:#8b949e;'>tuslar dokunulmadan geciyor</span>",
                1600,
            )
        else:
            self.tip.show_html("▶️ <b>devam</b>", 1200)

    def restart(self) -> None:
        """AHK: Pause+Home -> reloadScript()

        Cocuk surec AYRIK baslatilir. Boyle olmazsa VSCode/konsoldan
        baslatildiginda ebeveynle ayni surec grubunda kalir ve ebeveyn
        olunce o da olur -- "yeniden baslat deyince cikti" bunun yuzunden.
        Yeni ornek --restart ile aciliyor: tek ornek kilidini eskisi
        birakana kadar bekliyor.
        """
        script = os.path.abspath(__file__)
        try:
            subprocess.Popen(
                [sys.executable, script, RESTART_FLAG],
                cwd=os.path.dirname(script),
                close_fds=True,
                creationflags=(
                    subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                ),
            )
        except OSError as exc:
            # Sessizce cikmaktansa soyle: eskiden "yeniden baslat" cikis gibi
            # gorunuyordu, cunku hata kimseye ulasmiyordu.
            QMessageBox.critical(None, "cascade", f"Yeniden baslatilamadi: {exc}")
            return
        self._shutdown()
        self.app.quit()

    def quit(self) -> None:
        """AHK: Pause+End -> ExitApp()"""
        self._shutdown()
        self.app.quit()

    def _shutdown(self) -> None:
        self._drain_timer.stop()
        self._tick_timer.stop()
        self.clip_watcher.stop()
        self.filter_window.close()
        self.machine.reset()
        self.hook.stop()
        self.tip.hide()
        self.monitor.close()
        self.tray.hide()


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("cascade")

    # AHK: #SingleInstance Force. Iki ornek ayni anda hook kurarsa hangisinin
    # tusu once gordugu garanti edilemez; ikinci ornek acilmaz.
    restarting = RESTART_FLAG in sys.argv
    lock = SingleInstance("cascade", wait_seconds=5.0 if restarting else 0.0)
    if not lock.acquired:
        QMessageBox.warning(None, "cascade", "cascade zaten calisiyor.")
        return 1

    Cascade(app)
    try:
        return app.exec()
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
