"""Uygulama govdesi -- parcalari birbirine baglayan katman.

AHK karsiligi: AutoHotkey.ahk'nin LoadSettings/ExitSettings/reloadScript
bolumu + App sinifindaki singleton kayitlari.

Gorev dagilimi:

    keymap.py    NE yapilacagi (tablolar, menuler)          -- script
    dispatch.py  tuslarin NASIL calistigi (yutma, onek)     -- cekirdek
    actions.py   eylem kimligi -> gercek is
    app.py       parcalarin kurulumu, pano/slot/buyutec baglantilari,
                 yasam dongusu (baslat / duraklat / yeniden baslat / cikis)

Mimari kural: hook callback'i (ayri thread) yalnizca yut/birak karari verir
ve eylemleri kuyruga atar (dispatch.py). Butun is ana thread'de, Qt
zamanlayicisinda yapilir. Callback icinden SendInput cagrilmaz -- yeniden
giris ve kilitlenme olur.
"""

from __future__ import annotations

import contextlib
import ctypes
import html
import logging
import os
import platform
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from cascade import keymap, logs, paths
from cascade.actions import ActionRunner, beep
from cascade.app_shorts import ShortcutStore, stroke_kind
from cascade.clip_ctl import ClipController
from cascade.core.cascade import Beep, CascadeMachine, CloseMenu, OpenMenu, Run
from cascade.core.keynames import key_name, vk_from_name
from cascade.core.state import Busy, ClipboardMode
from cascade.dispatch import Dispatcher
from cascade.incognito import Incognito
from cascade.settings import SETTINGS
from cascade.slots_ctl import SlotController
from cascade.store import SlotStore
from cascade.ui.array_filter import ArrayFilter
from cascade.ui.incognito_badge import IncognitoBadge
from cascade.ui.mem_slots import MemSlots
from cascade.ui.menu import DEFAULT, PopupMenu
from cascade.ui.monitor import EventMonitor
from cascade.ui.ocr_view import OcrView
from cascade.ui.pause import PauseDialog
from cascade.ui.preview import preview_html, shorten
from cascade.ui.settings_dialog import SettingsDialog
from cascade.ui.snip import SnipOverlay
from cascade.ui.tip import Tip
from cascade.ui.tray import Tray
from cascade.win32 import ocr, send
from cascade.win32.hook import HookThread
from cascade.win32.instance import SingleInstance
from cascade.win32.magnifier import Magnifier
from cascade.win32.window import (
    WindowPins,
    foreground_window,
    window_class,
    window_title,
)

log = logging.getLogger("cascade.app")

VERSION = "0.1.0"

#: Ekran koruyucu engelleyici -- AHK IdleModule: 5 dakikada bir, en cok
#: 60 tur (5 saat) boyunca.
IDLE_INTERVAL_MS = 5 * 60 * 1000
IDLE_TICKS = 60

VK_CAPITAL = 0x14  # buyuk harf kilidi (caps.toggle)
VK_SCROLL = 0x91  # ScrollLock lambasi (turkish.toggle)
user32 = ctypes.windll.user32

# restart() cocuk surece bunu gecer: eski ornek kilidi birakana kadar bekle.
RESTART_FLAG = "--restart"

# VSCode F5 (debugpy) programi KILL_ON_JOB_CLOSE bayrakli bir job'a koyuyor;
# debugger kapaninca job'daki HER surec olduruluyor -- yeniden baslattigimiz
# cocuk dahil. Bu bayrak cocugu job'un disina cikarir (debugpy job'unda
# BREAKAWAY_OK acik, izin var). Job yokken bayragin etkisi yok.
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def press_button(name: str) -> None:
    """`button_down:RButton` -- dugmeyi basili birakir, birakmayi gercek
    fare yapar. Surukleme anlasildiginda cagriliyor."""
    vk = vk_from_name(name)
    if vk is not None:
        send.button_down(vk)


class _ErrorBridge(QObject):
    """Hata kaydini ana thread'e tasiyan kopru (level, text)."""

    raised = Signal(str, str)


class _OcrBridge(QObject):
    """OCR ayri thread'de kosuyor (bloklayici, bkz. win32/ocr.py); sonuc
    Qt sinyaliyle ana thread'e doner -- baska thread'den arayuze dokunulmaz."""

    finished = Signal(str, object)  # mod ("ocr" / "ocr_adv"), ocr.Result
    failed = Signal(str)


def _child_env() -> dict[str, str]:
    """Yeniden baslatilan cocuga TEMIZ ortam.

    Debugger altinda calisirken debugpy/pydevd ortam degiskenleri ve
    PYTHONPATH enjeksiyonu cocuga miras kalirsa cocuk, kapanmakta olan
    debug oturumuna baglanmaya calisip acilamadan oluyordu.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DEBUGPY_", "PYDEVD_"))
    }
    pythonpath = env.get("PYTHONPATH", "")
    if pythonpath:
        parts = [
            part
            for part in pythonpath.split(os.pathsep)
            if part and "debugpy" not in part.lower() and "pydevd" not in part.lower()
        ]
        if parts:
            env["PYTHONPATH"] = os.pathsep.join(parts)
        else:
            env.pop("PYTHONPATH", None)
    return env


class Cascade:
    def __init__(self, app: QApplication, lock: SingleInstance | None = None) -> None:
        self.app = app
        # Tek ornek kilidi. restart() cocuk sureci baslatmadan ONCE birakmak
        # zorunda: birakmazsak cocuk kilidi bekler ve program saniyelerce
        # kapali kalir.
        self.lock = lock
        self.tip = Tip()
        self.monitor = EventMonitor()
        #: Ayar ekrani ilk istendiginde kuruluyor -- acilista maliyeti olmasin.
        self._settings_dialog: SettingsDialog | None = None
        self.runner = ActionRunner()

        # Taban tanimlar ayri duruyor: hafiza slotlari acikken F1..F10
        # bunlarin USTUNE ekleniyor, kapaninca tabana geri donuluyor.
        self._base_defs = dict(keymap.build_cascades())
        self.machine = CascadeMachine(dict(self._base_defs), Busy())

        # Pano: durum + gecmis + gorseller tek denetleyicide (clip_ctl.py).
        # Hafiza bloklari moduna dusen metni buradan alip pencereye veriyoruz.
        self.clip = ClipController(
            tip_html=self.tip.show_html,
            tip_menu=self.tip.show_menu,
            show_menu=lambda spec: self.menu.show(spec),
            show_filter=self.show_filter_items,
            send_key=self.runner.run,
            to_mem_slots=lambda text: self.mem_slots.on_clip(text),
        )
        self.clip.register(self.runner)

        # AHK clip_slot.ahk ile ayni dosya ve bicim: Files/slots.json.
        # Slotlarin butun mantigi slots_ctl.py'de; burasi yalniz baglar.
        self.slot_store = SlotStore()

        # Filtreli liste ve acilir menu. Liste penceresi acikken kisayollar
        # susar (dispatcher.ui_open): arama kutusuna yazarken `Caret & 1`
        # tetiklenmesin.
        self.filter_window = ArrayFilter()
        self.filter_window.chosen.connect(self.clip.paste_text)
        self.filter_window.closed.connect(lambda: setattr(self.dispatcher, "ui_open", False))
        # Menu acikken dispatcher susmali: Win32 menusu kendi modal
        # dongusunu isletir, tuslar hook'a degil MENUYE gitmeli.
        self.menu = PopupMenu(
            self.runner.run,
            set_ui_open=lambda state: setattr(self.dispatcher, "ui_open", state),
        )

        # AHK: App.Magnifier. Magnify.exe bir kez acilir ve acik kalir;
        # biz yalniz zoom kademesini degistiriyoruz (win32/magnifier.py).
        self.magnifier = Magnifier()

        # Hafiza slotlari (AHK memory_slots.ahk). Pencere panoyu kendisi
        # yazmaz; her sey sinyalle buraya gelir. `ui_open` BILEREK
        # kurulmuyor: F1..F10 sistem geneli calismali, pencere onde
        # degilken de.
        self.mem_slots = MemSlots()
        self._clip_mode_before = self.clip.state.mode
        self.mem_slots.paste_text.connect(self.clip.paste_text)
        self.mem_slots.copy_text.connect(self.clip.watcher.set_text)
        self.mem_slots.grab_clip.connect(lambda: self.runner.run("send_key:^c"))
        self.mem_slots.tip.connect(lambda body: self.tip.show_html(body, 1500))
        self.mem_slots.fkeys_toggled.connect(self._on_memslot_fkeys)
        self.mem_slots.closed.connect(self._on_memslots_closed)

        # F14 secim araci (ui/snip.py) + OCR koprusu. Secim acikken
        # kisayollar SUSMAZ: AHK'de de butun tuslar calisiyordu.
        self.snip = SnipOverlay()
        # Yeniden yakalamadan once OCR paneli de gizlenmeli: ustte duran
        # bir pencere ve secimin uzerine denk gelirse OCR kendi metnini
        # okur (bkz. ui/snip.py `_recapture`).
        self.snip.hide_others = self._hide_over_snip
        self.snip.done.connect(self._on_snip_done)
        self.snip.rect_changed.connect(self._on_snip_rect_changed)
        self.snip.closed.connect(self._on_snip_closed)
        self.ocr_view = OcrView()
        self.ocr_view.copy_text.connect(self.clip.copy_to_history)
        self.ocr_view.reocr_requested.connect(self._on_reocr)
        self.ocr_view.closed.connect(self.snip.end_session)

        #: OCR+ oturumundaki son kirpim -- ayar degisince ekran YENIDEN
        #: CEKILMEDEN bunun uzerinden tekrar okunur (AHK: cache'li bitmap).
        self._ocr_image: QImage | None = None
        self._ocr_bridge = _OcrBridge()
        self._ocr_bridge.finished.connect(self._on_ocr_done)
        self._ocr_bridge.failed.connect(self._on_ocr_failed)

        # AHK: State.Window.onTopWindows -- sabitledigimiz pencereler.
        self.pins = WindowPins()

        self.paused = False
        self._idle_count = IDLE_TICKS  # ekran koruyucu engelleyici sayaci
        self._exited = False
        # Yeni bir ornek acildi mi (win32/instance.py devralmasi). Hook
        # disi bir thread kaldiriyor, `_tick` gorup kapatiyor.
        self._quit_requested = False
        # Arizali farenin yutulan basim sayisi (AHK: KeyCounts "DoubleCount").
        self._bounce_count = 0
        #: Tepsi rozetindeki hata sayisi -- son hata okununca sifirlanir.
        self._error_count = 0
        # AHK: State.Script.shouldSaveOnExit. "Kaydetmeden yeniden baslat"
        # bunu indirir; kapanista pano dosyasina DOKUNULMAZ.
        self.save_on_exit = True

        self.events: queue.Queue = queue.Queue(maxsize=4096)
        self.actions: queue.Queue = queue.Queue(maxsize=4096)
        self.seen: queue.Queue = queue.Queue(maxsize=4096)

        # Yut/birak kararlarinin tamami dispatch.py'de; burasi yalniz kurar.
        self.dispatcher = Dispatcher(
            machine=self.machine,
            hotkeys=keymap.build_hotkeys(),
            gestures=keymap.build_gestures(),
            actions=self.actions,
            seen=self.seen,
            menu_open=lambda: self.menu.open,
        )
        # AHK hot_vectors.ahk `__New`: ayarlar dinleniyor. Imlec dondurma
        # kararini dispatcher veriyor, o yuzden buradan baglaniyor.
        self.dispatcher.freeze_cursor = bool(keymap.VECTOR_FREEZE.get())
        keymap.VECTOR_FREEZE.subscribe(
            lambda value, _old: setattr(self.dispatcher, "freeze_cursor", bool(value))
        )
        self.dispatcher.drag_px = int(keymap.VECTOR_IGNORE_PX.get())
        keymap.VECTOR_IGNORE_PX.subscribe(
            lambda value, _old: setattr(self.dispatcher, "drag_px", int(value))
        )

        self.hook = HookThread(
            self.events,
            key_filter=self.dispatcher.key_filter,
            mouse_filter=self.dispatcher.mouse_filter,
            # Jest icin sart. Hareket olayi sik gelir (saniyede yuzlerce),
            # o yuzden mouse_filter'in ilk satiri erken cikis.
            watch_mouse_move=True,
        )

        # tip: imlecin yaninda 2 sn gorunup kaybolur.  notify: kalici tepsi balonu.
        self.runner.register("tip", lambda text: self.tip.show_text(text, 2000))
        # Jest bitince ipucu da gitsin: 2 sn'lik sure jestten sonra da ekranda
        # kaliyordu (dispatch._end_gesture).
        self.runner.register("tip.hide", lambda _: self.tip.hide())
        self.runner.register("tip_html", lambda body: self.tip.show_html(body, 2000))
        self.runner.register("notify", lambda text: self.tray.notify("cascade", text))
        self.runner.register("app.restart", lambda _: self.restart())
        self.runner.register("app.exit", lambda _: self.quit())
        # Arizali fare: yutulan ikinci basim (dispatch.DOUBLE_CLICK_MS).
        self.runner.register("click.bounce", self.on_click_bounce)
        # AHK cascadeCaps: kisa basim SetCapsLockState -- tusu yuttugumuz
        # icin Windows kendi cevirmiyor.
        self.runner.register("caps.toggle", lambda _: self.toggle_caps())
        self.runner.register("menu.f13", lambda _: self.show_f13_menu())
        self.runner.register("menu.sys", lambda _: self.show_sys_menu())
        self.runner.register("menu.close", lambda _: self.menu.close())
        # Surukleme anlasilinca gecikmeli enjekte edilen gercek fare basimi.
        self.runner.register("button_down", press_button)
        self.runner.register("yok", self.not_ported)
        self.runner.register("click_then", self.click_then)
        self.runner.register("click3_then", lambda keys: self.click_then(keys, times=3))
        self.runner.register("app.monitor", lambda _: self.show_monitor())
        self.runner.register("app.settings", lambda _: self.show_settings())
        self.runner.register("app.pause", lambda _: self.toggle_pause())
        self.runner.register("busy.free", lambda _: self.free_busy())
        self.runner.register("errors.show", lambda _: self.show_errors())
        self.runner.register("errors.copy", lambda _: self.copy_last_error())
        # AHK memory_slots.ahk. Argumani olanlar slot numarasi aliyor.
        self.runner.register("memslots.start", lambda _: self.show_mem_slots())
        self.runner.register(
            "memslots.paste_slot", lambda n: self.mem_slots.paste_slot(int(n))
        )
        self.runner.register(
            "memslots.paste_hist", lambda n: self.mem_slots.paste_history(int(n))
        )
        self.runner.register(
            "memslots.save_slot", lambda n: self.mem_slots.save_slot(int(n))
        )
        # AHK smartPaste(middlePressed): orta tus / Insert ile gelen cagri
        # yapistirdiktan sonra siradaki kayda gecer, tus kombosu gecmez.
        self.runner.register(
            "memslots.paste", lambda arg: self.mem_slots.smart_paste(arg == "middle")
        )
        # AHK handleMButton pt2: yapistir + Shift+Enter.
        self.runner.register("memslots.paste_enter", lambda _: self.memslots_paste_enter())
        # F14 -- surukleyince ekran alani secimi, kimildatmadan birakinca menu.
        # Secim acikken tusa yeniden basmak da buraya gelir: show_snip
        # pencerenin acik oldugunu gorup bastan sectiriyor.
        self.runner.register("select.start", self.show_snip)
        # Secim cubugundaki "Alan" menusu -- konsept. Kayit yok, is yok:
        # ne dusundugumuz gorunsun diye ekranda duruyor.
        self.snip.placeholder.connect(self._area_placeholder)
        # F13 menusu: alan secilir secilmez OCR baslasin (AHK'de bu iki oge
        # App.ScreenOcr.snipInteractive / snip("plain") idi).
        self.runner.register("select.ocr", lambda _: self.show_snip_auto("ocr"))
        self.runner.register("select.ocr_adv", lambda _: self.show_snip_auto("ocr_adv"))
        # AHK menus.ahk: menuAlwaysOnTop -- pencereyi hep ustte tut.
        self.runner.register("window.pin", self.toggle_pin)
        # AHK magnifier.ahk. Islemler ayri thread'de kosuyor: icinde uyku var.
        self.runner.register("magnifier.zoom", self.zoom)
        self.runner.register("magnifier.toggle", lambda _: self.magnifier.toggle())
        self.runner.register("magnifier.reset", lambda _: self.magnifier.reset())
        self.runner.register("magnifier.panic", lambda _: self.panic())

        # AHK clip_slot.ahk: slot yapistirma, gruplar ve F14 menusu.
        self.slots = SlotController(
            self.slot_store,
            tip_html=self.tip.show_html,
            show_menu=self.menu.show,
            paste_text=self.clip.paste_text,
            set_clipboard=self.clip.watcher.set_text,
            show_filter=self.show_filter_items,
            send_key=self.runner.run,
        )
        self.slots.register(self.runner)

        # AHK: App.AppShorts (app_shorts.ahk). On plandaki pencereye gore
        # F13 menusune ekstra kisayol maddeleri girer.
        self.shorts = ShortcutStore()
        self.runner.register("shorts.play", self.play_shortcut)
        self.runner.register("shorts.edit", lambda _: self.edit_shortcuts())

        # AHK menus.ahk `DialogPauseGui`: Pause tusu basili tutulunca acilir.
        self.pause_dialog = PauseDialog()
        self.pause_dialog.resume.connect(lambda: self.set_paused(False))
        self.pause_dialog.restart.connect(self.restart)
        self.pause_dialog.restart_nosave.connect(self._restart_without_saving)
        self.pause_dialog.exit_app.connect(self.quit)
        self.runner.register("app.pause_dialog", lambda _: self.show_pause_dialog())

        # AHK turkish_layout_addon.ahk -- ScrollLock. Hangi VK hangi harf,
        # duzene sorularak bulunuyor; kararlari dispatch veriyor.
        self.dispatcher.turkish_keys = keymap.turkish_keys()
        self.runner.register("turkish.toggle", lambda _: self.toggle_turkish())
        self.runner.register("turkish.layout", lambda _: self.switch_turkish_layout())

        self.tray = Tray(
            VERSION,
            on_monitor=self.show_monitor,
            on_restart=self.restart,
            on_exit=self.quit,
            on_toggle_pause=self.toggle_pause,
            on_settings=self.show_settings,
            on_copy_error=self.copy_last_error,
        )
        self.tray.show()

        # Hata olunca tepsi simgesi kirmizi olsun. Hata BASKA THREAD'den
        # gelebiliyor (hook, beep), Qt'ye oradan dokunulamaz -- sinyal
        # kuyruga girip ana thread'de islenir.
        self._errors = _ErrorBridge()
        self._errors.raised.connect(self._on_error_logged)
        logs.errors.subscribe(lambda level, text: self._errors.raised.emit(level, text))

        # Incognito -- AHK incognito.ahk. Modulun kendi zamanlayicisi yok
        # (bkz. incognito.py "QT YOK"): saati burada kuruluyor ve yalnizca
        # acikken donuyor.
        self.incognito = Incognito(ask_recover=self._ask_incognito_recover)
        self._incognito_badge: IncognitoBadge | None = None
        self._incognito_timer = QTimer(app)
        self._incognito_timer.timeout.connect(self.incognito.watch_tick)
        self.runner.register("incognito.open", lambda _: self.open_incognito())

        # Ekran koruyucu engelleyici -- AHK script_state.ahk IdleModule.
        # `on_start` is profilinde bunu baslatiyor, o yuzden cagridan ONCE
        # kuruluyor.
        self._idle_timer = QTimer(app)
        self._idle_timer.timeout.connect(self._idle_tick)

        self.hook.start()
        # Oturum kapanmasi / gorev sonlandirma da OnExit'i calistirsin.
        app.aboutToQuit.connect(self.on_exit)
        self.on_start()

        self._drain_timer = QTimer(app)
        self._drain_timer.timeout.connect(self._drain)
        self._drain_timer.start(8)

        self._tick_timer = QTimer(app)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(20)


    # ---- pano (ana thread) ----

    def show_filter_items(self, items: tuple, title: str) -> None:
        """Filtreli listeyi acan TEK yol -- pano gecmisi de slotlar da buradan.

        `ui_open` burada kalkiyor: pencere acikken kisayollar susmali
        (arama kutusuna yazarken `Caret & 1` tetiklenmesin).
        """
        self.dispatcher.ui_open = True
        self.filter_window.show_items(items, title)

    # ---- F14 secim araci ----

    def _area_placeholder(self, key: str) -> None:
        """"Alan" menusu maddesi secildi. Konsept: yalniz ne olacagini soyler."""
        self.tip.show_html(
            f"🚧 <b>{html.escape(key)}</b> — kavram asamasi<br>"
            "<span style='color:#8b949e;'>alan kaydi ve otomasyon henuz yok</span>",
            2000,
        )

    def show_snip(self, key: str = "") -> None:
        """F14: ekran donar, alan secilir, secim ustunde islem cubugu acilir.

        `select.start:F14@{x},{y}` yazilirsa secim O TUSLA yapilir -- F14
        basili tutuldugu surece fare hareketi dikdortgeni buyutur, tus
        birakilinca secim biter (ui/snip.py `_poll_key`). `{x},{y}`
        suruklemenin basladigi nokta: cerceve oradan baslar (dispatch.py
        dolduruyor). Argumansiz cagrilirsa secim sol fare tusuyla yapilir.
        """
        # `F14@1200,430` -- tus adi ve suruklemenin basladigi ekran noktasi.
        name, _, point = key.partition("@")
        origin: tuple[int, int] | None = None
        if point:
            x, _, y = point.partition(",")
            origin = (int(x), int(y))
        vk = (vk_from_name(name) or 0) if name else 0
        # Secim penceresi hook'u SUSTURMAZ (`ui_open` kurulmuyor): AHK'de de
        # secim acikken butun tuslar calismaya devam ediyordu. Susturursak
        # F13 menusu, kaskadlar, ses tuslari -- hepsi secim boyunca olur.
        # Secimi yapan tusun durumu ayri bir izleyiciden geliyor.
        self.dispatcher.watch(vk)
        # Zaten acik: yeni pencere acmak yerine bastan sec (F14'e tekrar
        # basmak "yeni secim" demek).
        if self.snip.isVisible():
            self.snip.repick(origin)
            return
        self.snip.start(vk, origin, self.dispatcher.watch_held)

    def show_snip_auto(self, action: str) -> None:
        """Secim aracini "bitince su eylemi calistir" diyerek acar."""
        self.snip.auto_action = action
        self.show_snip("")

    def _hide_over_snip(self):
        """Secimin ustunde durabilecek kendi pencerelerimizi gizler.

        Geri gosteren cagrilabilir doner -- yeniden yakalama bitince
        cagriliyor. Gorunmeyen pencere listeye girmez ki kapali bir panel
        yakalama sonrasi kendiliginden acilmasin.
        """
        hidden = [w for w in (self.ocr_view,) if w is not None and w.isVisible()]
        for panel in hidden:
            panel.hide()

        def restore() -> None:
            for panel in hidden:
                panel.show()

        return restore

    def _on_snip_closed(self) -> None:
        self.dispatcher.watch(0)
        self._ocr_image = None

    def _on_snip_done(self, action: str, image: QImage) -> None:
        """Secim bitti: eylem kimligi ui/snip.py ACTIONS tablosundan gelir."""
        if action == "copy":
            QGuiApplication.clipboard().setImage(image)
            self.tip.show_html(
                f"\U0001f4cb <b>goruntu panoda</b> {image.width()}x{image.height()}", 1500
            )
        elif action == "save":
            self.save_capture(image)
        elif action == "clip_image":
            # Secilen alani gorsel gecmisine koy ve pencereyi ac.
            if self.clip.save_image(image) < 0:
                self.tip.show_html("⚠️ <b>gorsel kaydedilemedi</b>", 1500)
                return
            self.clip.show_images()
        elif action in ("ocr", "ocr_adv"):
            self._start_ocr(action, image)

    def _on_snip_rect_changed(self, image: QImage) -> None:
        """OCR+ acikken alan yeniden ayarlandi: taze kirpimla tekrar oku."""
        self._start_ocr("ocr_adv", image)

    def save_capture(self, image: QImage) -> None:
        """AHK'de menuden secilince dosya adi soruluyordu; burada da soruyoruz.

        Varsayilan klasor `Files/captures`, ad zaman damgali. Kullanici
        istedigi yeri secebilir -- sessizce bir yere yazmak, sonradan
        "nereye kaydetti" sorusunu doguruyordu.
        """
        paths.CAPTURES.mkdir(parents=True, exist_ok=True)
        suggested = paths.CAPTURES / f"alinti-{datetime.now():%Y%m%d-%H%M%S}.png"
        target, _filter = QFileDialog.getSaveFileName(
            None,
            "Ekran alintisini kaydet",
            str(suggested),
            "PNG goruntu (*.png);;JPEG goruntu (*.jpg);;Tum dosyalar (*)",
        )
        if not target:
            return  # vazgecildi
        if image.save(target):
            self.tip.show_html(f"\U0001f4be <b>{html.escape(os.path.basename(target))}</b>", 1800)
        else:
            self.tip.show_html("⚠️ <b>goruntu kaydedilemedi</b>", 1800)

    def _start_ocr(self, mode: str, image: QImage) -> None:
        if not ocr.available():
            self.tip.show_html("⚠️ <b>OCR paketi kurulu degil</b> (winrt)", 2000)
            return
        self._ocr_image = image
        if mode == "ocr_adv":
            self.ocr_view.busy()
            scale = self.ocr_view.scale
        else:
            self.tip.show_html("\U0001f524 <b>okunuyor...</b>", 800)
            scale = ocr.DEFAULT_SCALE
        self._run_ocr(mode, image, scale, True, "")

    def _on_reocr(self, scale: int) -> None:
        """Panelde olcek degisti: ekran TEKRAR CEKILMEZ, elimizdeki kirpim
        yeniden okunur (AHK: cache'li bitmap uzerinden)."""
        if self._ocr_image is not None:
            self._run_ocr("ocr_adv", self._ocr_image, scale, True, "")

    def _run_ocr(
        self, mode: str, image: QImage, scale: int, grayscale: bool, language: str
    ) -> None:
        threading.Thread(
            target=self._ocr_work,
            args=(mode, image, scale, grayscale, language),
            name="cascade-ocr",
            daemon=True,
        ).start()

    def _ocr_work(
        self, mode: str, image: QImage, scale: int, grayscale: bool, language: str
    ) -> None:
        """OCR thread'i: motoru bekler, sonucu sinyalle ana thread'e verir."""
        try:
            result = ocr.recognize(image, scale=scale, grayscale=grayscale, language=language)
            self._ocr_bridge.finished.emit(mode, result)
        except Exception as exc:  # motor yok / dil paketi eksik
            log.exception("OCR basarisiz")
            self._ocr_bridge.failed.emit(str(exc))

    def _on_ocr_done(self, mode: str, result) -> None:
        if mode == "ocr":
            # Basit OCR: metin dogrudan panoya (ve oradan gecmise) gider.
            if not result.lines:
                self.tip.show_html("\U0001f524 <b>metin bulunamadi</b>", 1500)
                return
            self.clip.copy_to_history(result.text)
            return
        # OCR+: kelime kutulari panele gider, dizilim orada secilir.
        self.ocr_view.show_result(result.words, result.lines, result.ms)

    def _on_ocr_failed(self, message: str) -> None:
        self.tip.show_html(f"⚠️ <b>OCR hatasi</b><br>{html.escape(shorten(message, 80))}", 2500)

    # ---- hep ustte (AHK: menuAlwaysOnTop) ----

    def toggle_pin(self, argument: str) -> None:
        """`window.pin` (bos = one cikan pencere) / `window.pin:<hwnd>`."""
        try:
            hwnd = int(argument) if argument else 0
        except ValueError:
            return
        title = window_title(hwnd) if hwnd else ""
        state = self.pins.toggle(hwnd, title)
        if state is None:
            self.tip.show_html("⚠️ <b>pencere bulunamadi</b>", 1200)
            return
        name = html.escape(shorten(title or window_title(hwnd) or "pencere", 40))
        if state:
            self.tip.show_html(f"\U0001f4cc <b>hep ustte</b><br>{name}", 1500)
        else:
            self.tip.show_html(f"\U0001f4cd <b>birakildi</b><br>{name}", 1500)

    def _pin_menu_items(self) -> tuple:
        """AHK menuAlwaysOnTop: once "bu pencereyi sabitle", sonra sabitli
        olanlar (tiklayinca birakilir).

        Menu her acilista yeniden kuruluyor -- sabitli pencereler ve one cikan
        pencere degisiyor, statik tablo bunu tasiyamaz.
        """
        self.pins.prune()
        hwnd = foreground_window()
        title = window_title(hwnd)
        items: list = []
        if hwnd and not self.pins.has(hwnd):
            label = shorten(title or "(baslıksiz)", 45)
            items.append((f"📍 Add {label}", f"window.pin:{hwnd}"))
        for pin in self.pins.items():
            label = shorten(pin.title or "(baslıksiz)", 45)
            # Uzerinde durdugun pencere zaten sabitliyse o satir kalin.
            mark = (DEFAULT,) if pin.hwnd == hwnd else ()
            items.append((f"📌 {label}", f"window.pin:{pin.hwnd}", "", *mark))
        return tuple(items)

    # ---- uygulamaya ozel kisayollar (AHK: app_shorts.ahk) ----

    def _shortcut_menu_items(self) -> tuple:
        """AHK `menuAppProfile`: on plandaki pencerenin profili + kisayollari.

        Profil yoksa AHK bir "Ekle" maddesi koyuyordu; bizde duzenleme JSON
        dosyasindan yapildigi icin madde "Profilleri duzenle" oluyor ve
        yaninda pencerenin SINIF adi yaziyor -- dosyaya yazilacak deger o.
        """
        hwnd = foreground_window()
        name = window_class(hwnd)
        profile = self.shorts.find(name, window_title(hwnd))
        if profile is None:
            return ((f"▸ Ekle ({shorten(name, 30)})", "shorts.edit"),)
        items: list = []
        for index, shortcut in enumerate(profile.shortcuts):
            label = f"▸ {shortcut.name}"
            if shortcut.description:
                label += f" - {shortcut.description}"
            items.append((label, f"shorts.play:{profile.name}/{index}"))
        items.append(("Profili duzenle", "shorts.edit"))
        return tuple(items)

    def _profile_label(self, profile) -> str:
        """"Profiller" alt menusundeki etiket."""
        hint = profile.class_name or profile.title
        name = profile.name or "(adsiz)"
        return f"{name} [{shorten(hint, 24)}]" if hint else name

    def _shortcut_manager_item(self) -> tuple:
        """AHK `showManagerGui` karsiligi: TUM profiller F13 menusunde.

        AHK'de bu ayri bir pencereydi (profil listesi + kisayol listesi +
        ekle/sil). Pencereyi port etmek yerine ayni bilgi menuye kondu: her
        profil bir alt menu, altinda kisayollari -- ve tiklanabilir, yani
        yonetici ayni zamanda calistirici. Ekleme/silme hala JSON
        dosyasindan (son madde), cunku ayni dosyayi AHK tarafi da okuyor.
        """
        hwnd = foreground_window()
        active = self.shorts.find(window_class(hwnd), window_title(hwnd))
        profiles: list = []
        for profile in self.shorts.profiles:
            rows: list = []
            for index, shortcut in enumerate(profile.shortcuts):
                label = f"▸ {shortcut.name}"
                if shortcut.description:
                    label += f" - {shortcut.description}"
                rows.append((label, f"shorts.play:{profile.name}/{index}"))
            if not rows:
                rows.append(("(kisayol yok)", "shorts.edit"))
            # On plandaki pencerenin profili kalin.
            mark = (DEFAULT,) if profile is active else ()
            profiles.append((self._profile_label(profile), tuple(rows), "", *mark))
        if not profiles:
            profiles.append(("(profil yok)", "shorts.edit"))
        profiles.append(None)
        profiles.append(("\U0001f4dd profiles.json duzenle", "shorts.edit"))
        return ("Profiller", tuple(profiles))

    def play_shortcut(self, argument: str) -> None:
        """`shorts.play:Chrome/0` -- AHK `ShortCut.play()`.

        Diziler SIRAYLA gonderilir. AHK'nin tek `Send`i yerine iki yol var:
        modifierla baslayan ya da `{...}` iceren dizi kisayol, geri kalani
        duz metin (bkz. app_shorts.stroke_kind).
        """
        profile_name, _, index = argument.rpartition("/")
        shortcut = self.shorts.shortcut(profile_name, int(index) if index.isdigit() else -1)
        if shortcut is None:
            self.tip.show_html("⚠️ <b>kisayol bulunamadi</b>", 1500)
            return
        for stroke in shortcut.strokes:
            if stroke_kind(stroke) == "key":
                self.runner.run(f"send_key:{stroke}")
            else:
                send.type_text(stroke)

    def edit_shortcuts(self) -> None:
        """Profil dosyasini Notepad ile acar (AHK: yonetici GUI'si).

        Dosya yoksa AHK bicimiyle bos bir iskelet yazilir -- bos Notepad
        acmak "neyi nasil yazacagim" sorusunu birakiyordu.
        """
        path = self.shorts.path
        if not path.exists():
            paths.ensure_files_dir()
            path.write_bytes(
                b'{"projectName": "ProfileManager", "profiles": []}\n'
            )
        subprocess.Popen(["notepad.exe", str(path)])  # noqa: S603,S607
        self.tip.show_html(
            "\U0001f4dd <b>profiles.json</b><br>"
            "<span style='color:#8b949e;'>kaydettikten sonra yeniden baslat</span>",
            2500,
        )

    # ---- hafiza slotlari ----

    def memslots_paste_enter(self) -> None:
        """Orta tus UZUN basim -- AHK handleMButton pt2. Yapistirma panoya
        yazip Ctrl+V gonderiyor (asenkron), Shift+Enter onun ARDINDAN
        gitmeli; yoksa satir sonu yapistirmadan once dusuyor."""
        if not self.mem_slots.isVisible():
            return
        self.mem_slots.smart_paste(middle=True)
        QTimer.singleShot(160, lambda: self.runner.run("send_key:+Enter"))

    def show_mem_slots(self) -> None:
        """AHK: singleMemorySlot.getInstance().start()

        Pano modu MEM_SLOTS'a geciyor; onceki mod kapanista geri aliniyor
        (AHK: previousState). Bloklar BELLEKTE yasar (slots.json ile ilgisi
        yok), gecmis listesi pano gecmisinden geliyor.
        """
        self._clip_mode_before = self.clip.state.mode
        self.clip.state.set_mem_slots()
        # Bloklar acilista SILINMEZ: bir onceki oturumda doldurulan yerinde
        # kalir (AHK pencereyi her acilista bosaltiyordu). slots.json'daki
        # slotlar bambaska bir sey -- F14 menusu ve `^`/Tab tuslari onlari
        # kullaniyor, bu pencere onlara hic dokunmaz.
        self.mem_slots.start([entry.text for entry in self.clip.history.entries])

    def _on_memslot_fkeys(self, enabled: bool) -> None:
        """Slot penceresindeki kutu: F1..F10 kaskadlarini takar/soker.

        AHK: _setupFKeys(true/false). Tanimlari tabanla birlestirip
        makineye vermek yeterli -- makine kendi durumunu sifirliyor.
        """
        definitions = dict(self._base_defs)
        if enabled:
            definitions.update(keymap.memslots_defs())
        self.machine.set_definitions(definitions)

    def _on_memslots_closed(self) -> None:
        """AHK: _destroy -- pano modu geri (F tuslari pencerenin kendi
        closeEvent'inde birakildi). Slotlar diske YAZILMAZ: pencere AHK'deki
        gibi oturumluk bir defter, kalici slotlar slots.json'da ayri durur.
        """
        self.clip.state.set_mode(getattr(self, "_clip_mode_before", ClipboardMode.HISTORY))

    # ---- buyutec ----

    def zoom(self, argument: str) -> None:
        """`magnifier.zoom:+` / `magnifier.zoom:-`"""
        if argument.startswith("-"):
            self.magnifier.zoom_out()
        else:
            self.magnifier.zoom_in()

    def panic(self) -> None:
        """AHK: `(App.Magnifier.reset(), WinMinimize("A"))` -- buyutec %100'e
        doner ve one cikan pencere kuculur."""
        self.magnifier.reset()
        self.runner.run("send_key:#Down")

    # ---- menuler ve durum ----

    def free_busy(self) -> None:
        """AHK: `Pause & c:: State.Busy.setFree()`.

        Bir kaskad yarida kalirsa Busy kilitli kalir ve hicbir kisayol
        calismaz. Bu, o durumdan cikis yolu -- AHK'de de acil frendi.
        """
        self.dispatcher.reset()
        self.tip.show_html("\U0001f513 <b>busy kilidi acildi</b>", 1200)

    def show_errors(self) -> None:
        """AHK: getStatsArray / getRecentErrors."""
        QMessageBox.information(
            None,
            f"cascade {VERSION} - son hatalar",
            f"Hook callback  : en uzun {self.hook.max_callback_ms:.3f} ms (sinir 300)\n"
            f"Dusen olay     : {self.hook.dropped}\n"
            f"Pano kaydi     : {len(self.clip.history)}\n"
            f"Yutulan cift tik: {self._bounce_count} (arizali fare)\n"
            f"Log dosyasi    : {paths.LOG}\n\n"
            f"{logs.recent_text(15)}",
        )
        self._clear_error_badge()

    def copy_last_error(self) -> None:
        """AHK: App.ErrHandler.copyLastError()"""
        last = logs.errors.last
        if last is None:
            self.tip.show_html("✅ <b>hata yok</b>", 1200)
            return
        self.clip.watcher.set_text(last.line)
        self.tip.show_html(
            f"\U0001f4cb <b>son hata panoya kopyalandi</b><br>{preview_html(last.line, 3)}",
            2000,
        )
        self._clear_error_badge()

    def _on_error_logged(self, level: str, text: str) -> None:
        """Hata kaydedildi: tepsi rozeti HER ZAMAN yanar. Ipucu ayara bagli
        (logs.SHOW_TIP), tepsi balonu SADECE CRITICAL'da -- her uyarida
        balon cikarsa rahatsiz eder."""
        self._error_count += 1
        self.tray.set_error_count(self._error_count)
        if logs.SHOW_TIP.get():
            self.tip.show_html(
                f"⚠️ <b>{html.escape(level.lower())}</b><br>{preview_html(text, 3)}",
                2500,
            )
        if level == "CRITICAL":
            self.tray.notify("cascade - hata", shorten(text.strip(), 200))

    def _clear_error_badge(self) -> None:
        """Hatalar gorulmus sayilir: rozet sifirlanir, kayitlar durur."""
        self._error_count = 0
        self.tray.set_error_count(0)

    def on_click_bounce(self, argument: str) -> None:
        """AHK: `#HotIf A_TimeSincePriorHotkey < 70` -> LButton yutulur.

        Arizali mikro anahtarin urettigi ikinci basim dispatch'te zaten
        yutuldu; burada yalniz sayim/uyari var. Log'a CRITICAL degil WARNING
        dusuyor: fare yaslaniyor demek, program hatasi degil.
        """
        self._bounce_count += 1
        log.warning("cift tiklama yutuldu (%s ms, toplam %d)", argument, self._bounce_count)
        beep(1000, 100)

    def toggle_caps(self) -> None:
        """Buyuk harf kilidini cevirir ve yeni durumu soyler (AHK ShowTip).

        Onek tusunun keydown'i yutuluyor, yani kilidi Windows cevirmiyor;
        tusu geri gondermek yeterli -- kendi gonderdigimiz basim kilidi
        normal sekilde cevirir.
        """
        state = bool(user32.GetKeyState(VK_CAPITAL) & 1)
        send.tap(VK_CAPITAL)
        self.tip.show_html("<b>CAPSLOCK</b>" if not state else "<b>capslock</b>", 900)

    def show_sys_menu(self) -> None:
        """AHK: sysCommands() -- `´` tusunun menusu."""
        self.menu.show(keymap.SYS_COMMANDS_MENU, title=f"⚙️ cascade {VERSION}")

    def _incognito_menu_item(self) -> tuple:
        """F13 menusundeki tek satir: pencereyi acar (kapatma pencerede)."""
        if self.incognito.active:
            return (f"🏴‍☠️ Incognito ({self.incognito.locked_count})", "incognito.open")
        return ("🏴‍☠️ Incognito", "incognito.open")

    def show_f13_menu(self) -> None:
        """AHK: showF13menu() -- statik tablo + o anki pencere durumu."""
        # 1. kolon tablodan gelir ve COLUMN ile biter; 2. kolonun basi o
        # anki pencereye bagli bloklar, sonu sabit kuyruk -- sira AHK
        # showF13menu ile ayni.
        spec: tuple = (("Clipboard history", self.clip.menu_items()),)
        spec += keymap.F13_MENU
        spec += (*self._shortcut_menu_items(), self._shortcut_manager_item())
        # TEK madde, alt menu yok: pencere acilir, incognito orada yasar.
        spec += (self._incognito_menu_item(),)
        pins = self._pin_menu_items()
        if pins:
            spec += (None, *pins)
        if keymap.F13_MENU_TAIL:
            spec += (None, *keymap.F13_MENU_TAIL)
        # Kalin ogeler (AHK menuAppProfile / menuAlwaysOnTop) ogenin kendi
        # DEFAULT isaretiyle geliyor; bkz. ui/menu.py.
        self.menu.show(spec)

    def not_ported(self, module: str) -> None:
        """Menude `--` ile isaretli ogeler buraya duser."""
        self.tip.show_html(
            f"\U0001f6a7 <b>henuz port edilmedi</b><br>"
            f"<span style='color:#8b949e;'>{html.escape(module)}</span>",
            2000,
        )

    def click_then(self, keys: str, times: int = 1) -> None:
        """AHK: `(Click("Left", 3), Send("^c"))` -- once tikla, sonra gonder.

        Tiklama ile gonderim arasinda kisa bir bosluk var: uc hizli tik
        secim yapiyor ve secimin olusmasi hedef uygulamada zaman aliyor.
        """
        for _ in range(times):
            send.click("left")
        QTimer.singleShot(80, lambda: self.runner.run(f"send_key:{keys}"))

    def show_settings(self) -> None:
        """AHK subMenuSet "Settings" -- ayar ekrani (ui/settings_dialog.py)."""
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog()
        self._settings_dialog.show_dialog()

    # ---- incognito (AHK: incognito.ahk) ----

    @staticmethod
    def _ask_incognito_recover() -> bool:
        """Onceki oturum duzgun kapanmamis: yedek geri yuklensin mi?"""
        answer = QMessageBox.question(
            None,
            "cascade - incognito",
            "Onceki incognito oturumu duzgun kapanmamis.\n"
            "Yedekteki Windows izleri geri yuklensin mi?\n\n"
            "Hayir dersen o oturumun izleri SILINMIS kalir.",
        )
        return answer == QMessageBox.StandardButton.Yes

    def open_incognito(self) -> None:
        """Kisayolun/menunun tek isi: pencereyi acmak.

        Pencere acilinca incognito devreye girer ve pencere kapanana kadar
        acik kalir; kapanista temizligi disable() yapar.
        """
        if not self.incognito.active:
            result = self.incognito.enable()
            if result is None:  # _busy: onceki cagri hala suruyor
                return
            self._incognito_timer.start(Incognito.WATCH_PERIOD_MS)
            kademe = "core + deep" if result.deep else "core"
            self.tip.show_html(
                f"🏴‍☠️ <b>incognito ACIK</b><br>"
                f"<span style='color:#8b949e;'>{result.stores} depo ({kademe}) &nbsp;·&nbsp; "
                f"{result.locked} dosya dondu</span>",
                2000,
            )
        if self._incognito_badge is None:
            self._incognito_badge = IncognitoBadge(self.incognito, self.close_incognito)
        self._incognito_badge.show_badge()

    def close_incognito(self) -> None:
        """Pencerenin "Kapat"i, capraz ve Escape ayni yere gelir."""
        result = self.incognito.disable()
        if result is None:
            return
        self._incognito_timer.stop()
        if self._incognito_badge is not None:
            self._incognito_badge.close()
            self._incognito_badge.deleteLater()
            self._incognito_badge = None
        detay = (
            f"{result.restored} depo geri yuklendi"
            if result.did_restore
            else "geri yukleme KAPALI, izler kaldi"
        )
        self.tip.show_html(
            f"\U0001f441️ <b>incognito kapali</b><br>"
            f"<span style='color:#8b949e;'>{detay}</span>",
            2000,
        )

    def show_monitor(self) -> None:
        self.monitor.show()
        self.monitor.raise_()
        self.monitor.activateWindow()

    # ---- ana thread dongusu ----

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
        # Devralma: yeni ornek kilidi istedi (win32/instance.py). Kapanis
        # ANA THREAD'de olmali -- istegi kaldiran thread Qt'ye dokunamaz.
        if self._quit_requested:
            self._quit_requested = False
            self.quit()
            return
        if self.paused:
            return
        now = time.perf_counter()
        for action in self.machine.tick(now):
            self._apply(action)
        for vk, action in self.dispatcher.tick(now):
            log.debug("basili tutma: %s -> %s", key_name(vk), action)
            self.runner.run(action)

    def _apply(self, action) -> None:
        if isinstance(action, Run):
            self.runner.run(action.action)
        elif isinstance(action, Beep):
            beep(action.freq, action.ms)
        elif isinstance(action, OpenMenu):
            self.tip.show_menu(action.title, action.items)
        elif isinstance(action, CloseMenu):
            self.tip.hide()

    # ---- yasam dongusu ----

    def toggle_pause(self) -> None:
        """AHK: Suspend. Hook yerinde kalir, sadece kararlar devre disi."""
        self.set_paused(not self.paused)

    def set_paused(self, state: bool) -> None:
        """Duraklatma bayragi.

        Hook'u sokup takmak yerine bayrak kullaniliyor: yeniden kurulan hook
        zincirin sonuna duser, baska programlarla sira garantisi kaybolur.
        """
        if state == self.paused:
            return
        self.paused = state
        self.dispatcher.paused = state
        self.dispatcher.reset()
        self.tray.set_paused(state)
        if state:
            self.tip.show_html(
                "⏸️ <b>duraklatildi</b><br>"
                "<span style='color:#8b949e;'>tuslar dokunulmadan geciyor</span>",
                1600,
            )
        else:
            self.tip.show_html("▶️ <b>devam</b>", 1200)

    def toggle_turkish(self) -> None:
        """ScrollLock kisa basim -- AHK: `SetScrollLockState(!state)` + tip.

        Tusu onek olarak yuttugumuz icin ScrollLock lambasini Windows kendi
        cevirmiyor; bayragi cevirdikten sonra tusu biz gonderiyoruz ki lamba
        durumu gostersin (AHK'de durumun KENDISI lambaydi).
        """
        state = self.dispatcher.turkish.toggle()
        send.tap(VK_SCROLL)
        layout = self.dispatcher.turkish.layout
        self.tip.show_html(
            f"🇹🇷 <b>TR: {'acik' if state else 'kapali'}</b>"
            + (f" &nbsp;·&nbsp; dizilim {layout}" if state else ""),
            900,
        )

    def switch_turkish_layout(self) -> None:
        """ScrollLock basili tutma -- AHK: dizilim 1 <-> 2."""
        layout = self.dispatcher.turkish.switch_layout()
        note = "uzun basim (c s i g)" if layout == 1 else "dogrudan remap"
        self.tip.show_html(
            f"🇹🇷 <b>Turkce dizilim: {layout}</b><br>"
            f"<span style='color:#8b949e;'>{note}</span>",
            1200,
        )

    def show_pause_dialog(self, critical: str = "") -> None:
        """AHK `DialogPauseGui`: once duraklat, sonra pencereyi ac.

        Pause tusu BASILI TUTULUNCA geliyor (keymap). Pencere kapaninca
        program devam eder -- AHK'de de `Suspend(0)` kapanisa bagliydi.
        """
        self.set_paused(True)
        beep(750, 120)
        self.pause_dialog.show_paused(critical)

    def _restart_without_saving(self) -> None:
        """AHK: setShouldSaveOnExit(false) + Reload.

        Pano dosyasi supheliyse uzerine yazmadan yeniden baslatmaya yarar.
        """
        self.save_on_exit = False
        self.restart()

    def on_start(self) -> None:
        """AHK: LoadSettings() -- OnExit'in karsiti."""
        log.info("cascade %s basladi", VERSION)
        # AHK LoadSettings: Settings.load() + applyAll(). Ayarlari OKUMAK
        # yetmiyor, abonelere haber vermek de gerek -- yoksa moduller kod
        # icindeki varsayilanla calismaya devam eder.
        SETTINGS.load(paths.SETTINGS)
        SETTINGS.apply_all()
        for action in keymap.START_ACTIONS:
            self.runner.run(action)
        self.clip.load()
        self.shorts.load()
        profile = keymap.current_profile()
        label = keymap.PROFILE_LABELS.get(profile, profile)
        log.info("makine profili: %s (%s)", profile, platform.node())
        self.tray.setToolTip(f"cascade {VERSION} - {profile}")
        # AHK LoadSettings: is bilgisayarinda State.Idle.enable() -- ekran
        # koruyucu devreye girmesin diye 5 dakikada bir fareyi kimildatir.
        if profile == "work":
            self._idle_count = IDLE_TICKS
            self.dispatcher.last_physical = time.perf_counter()
            self._idle_timer.start(IDLE_INTERVAL_MS)
        # Kisa bir acilis bildirimi: yalniz SURUM ve PROFIL. Sayimlar (pano
        # kaydi, uygulama profili) buradan cikarildi -- her acilista okunan
        # bir sey degildi, log'a zaten yaziliyorlar.
        self.tip.show_html(f"✅ <b>cascade {VERSION}</b> &nbsp;·&nbsp; {label}", 1600)

    def _idle_tick(self) -> None:
        """AHK IdleModule.tick(): 5 dakikada bir, kullanici 1 dakikadir
        FIZIKSEL olarak dokunmadiysa fareyi 1 piksel oynatir.

        Fiziksel olmasi sart: kendi hareketimiz sayilsaydi sayac hic
        dolmaz, ekran koruyucu sonsuza dek engellenirdi. Windows'un
        GetLastInputInfo'su enjekte girdiyi de sayar, o yuzden olcum
        hook'un kendisinden geliyor (dispatch.last_physical).

        AHK gibi 60 turdan (5 saat) sonra kendini kapatir: masasindan
        kalkip gitmis birinin ekranini sonsuza dek acik tutmuyoruz.
        """
        idle_ms = (time.perf_counter() - self.dispatcher.last_physical) * 1000.0
        if idle_ms < 60_000:
            self._idle_count = IDLE_TICKS
            return
        self._idle_count -= 1
        if self._idle_count <= 0:
            self._idle_timer.stop()
            log.info("ekran koruyucu engelleyici durdu (%d tur doldu)", IDLE_TICKS)
            return
        send.move_relative(-1, -1)

    def on_exit(self) -> None:
        """AHK: ExitSettings() -- OnExit ile kayitli.

        Iki yerden cagriliyor (kendi quit'imiz ve Qt'nin aboutToQuit'i, yani
        oturum kapanmasi), o yuzden bir kez calismasi garantiye alinmis.
        """
        if self._exited:
            return
        self._exited = True
        for action in keymap.EXIT_ACTIONS:
            self.runner.run(action)
        # Incognito ACIK KALAMAZ: kapatmadan cikarsak jump list dosyalari
        # kilitli, Explorer politikalari kapali kalir ve yedek diskte asili
        # durur (bir sonraki acilista _recover_stale toplar, ama once
        # kullanici bozuk bir Explorer'la yasar).
        if self.incognito.active:
            self.incognito.disable()
        SETTINGS.save(paths.SETTINGS)  # AHK ExitSettings: Settings.save()
        # AHK: ExitSettings -> _save(). Yazma basarisizsa (veri kaybi
        # korumasi ya da disk hatasi) log'da izi kalir, kapanis engellenmez.
        # AHK ExitSettings: State.Window.clearAllOnTop() -- program kapaninca
        # sabitledigimiz pencereler ustte asili kalmasin.
        self.pins.clear_all()
        saved = (
            self.clip.save()
            if self.save_on_exit
            else False
        )
        log.info(
            "cascade kapaniyor (%d pano kaydi, diske yazildi: %s)",
            len(self.clip.history),
            "evet" if saved else "HAYIR",
        )
        self._shutdown()

    def restart(self) -> None:
        """AHK: Pause+Home -> reloadScript()

        Cocuk surec AYRIK ve JOB DISINDA baslatilir:

        * SIRA ONEMLI: once kendi kapanisimiz (pano diske yazilir, hook
          sokulur), SONRA kilidi BIRAK, en son cocuk surec. Ters sirada
          cocuk dosyayi biz yazmadan okur ya da mutex'i bekleyip saniyelerce
          gec acilir.
        * pythonw + NO_WINDOW: konsollu python.exe ile baslatilan ayrik
          cocuk kendine YENI bir konsol penceresi aciyordu ve o pencereyi
          kapatmak programi olduruyordu. pythonw hic konsol edinmez;
          bulunamazsa CREATE_NO_WINDOW konsolu gizli tutar.
        * NEW_PROCESS_GROUP: konsoldan/VSCode'dan baslatildiginda ebeveynin
          Ctrl+C / kapanis sinyalleri cocuga gitmesin.
        * BREAKAWAY_FROM_JOB: debugpy (VSCode F5) programi oldurmeli-job'a
          koyuyor; bayraksiz cocuk, debugger kapaninca aninda olduruluyordu
          -- "yeniden baslat deyince cikti" bunun yuzundendi.
        * Temiz ortam (_child_env): debugpy degiskenleri miras kalirsa cocuk
          olu debug oturumuna baglanmaya calisiyor. (launch.json'daki
          "subProcess": false ayni derdin komut satiri ayagini kapatir.)
        """
        self.on_exit()
        if self.lock is not None:
            self.lock.release()

        executable = sys.executable
        pythonw = os.path.join(os.path.dirname(executable), "pythonw.exe")
        if os.path.exists(pythonw):
            executable = pythonw

        script = os.path.join(paths.ROOT, "main.py")
        base_flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            try:
                subprocess.Popen(
                    [executable, script, RESTART_FLAG],
                    cwd=str(paths.ROOT),
                    close_fds=True,
                    env=_child_env(),
                    creationflags=base_flags | CREATE_BREAKAWAY_FROM_JOB,
                )
            except OSError:
                # Job breakaway'e izin vermiyorsa (debugpy veriyor, ama
                # baska bir sarmalayici vermeyebilir) bayraksiz dene.
                subprocess.Popen(
                    [executable, script, RESTART_FLAG],
                    cwd=str(paths.ROOT),
                    close_fds=True,
                    env=_child_env(),
                    creationflags=base_flags,
                )
        except OSError as exc:
            # Sessizce cikmaktansa soyle: eskiden "yeniden baslat" cikis gibi
            # gorunuyordu, cunku hata kimseye ulasmiyordu.
            QMessageBox.critical(None, "cascade", f"Yeniden baslatilamadi: {exc}")
            self.app.quit()
            return
        log.info("yeniden baslatiliyor")
        self.app.quit()

    def request_quit(self) -> None:
        """Yeni bir ornek acildi: yerimizi birak (win32/instance.py).

        BASKA THREAD'den cagriliyor -- burada Qt'ye dokunulmuyor, sadece
        bayrak kalkiyor; kapanisi ana thread'deki `_tick` yapiyor.
        """
        log.info("yeni ornek acildi, kapaniyoruz")
        self._quit_requested = True

    def quit(self) -> None:
        """AHK: Pause & End -> ExitApp()"""
        self.on_exit()
        self.app.quit()

    def _shutdown(self) -> None:
        """Yalniz on_exit'ten cagrilir; sirasi onemli: once zamanlayicilar,
        sonra hook, en son pencereler."""
        self._drain_timer.stop()
        self._tick_timer.stop()
        self.clip.close()
        self.filter_window.close()
        self.snip.close()
        self.ocr_view.close()
        self.mem_slots.close()
        self.pause_dialog.close()
        self.machine.reset()
        self.hook.stop()
        self.tip.hide()
        self.monitor.close()
        self.tray.hide()
