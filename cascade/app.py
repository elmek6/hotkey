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

from cascade import autostart, keymap, logs, paths, repository, theme
from cascade.actions import ActionRunner, beep, command
from cascade.app_shorts import ShortcutStore, stroke_kind
from cascade.clip_ctl import ClipController
from cascade.core.cascade import Beep, CascadeMachine, CloseMenu, OpenMenu, Run
from cascade.core.keynames import key_name, vk_from_name
from cascade.dispatch import Dispatcher
from cascade.incognito import Incognito
from cascade.macro_ctl import MacroController
from cascade.repository import Repository
from cascade.settings import SETTINGS
from cascade.slots_ctl import SlotController
from cascade.store import SlotStore, slot_display
from cascade.ui.array_filter import ArrayFilter
from cascade.ui.incognito_badge import IncognitoBadge
from cascade.ui.key_map_view import KeyMapView
from cascade.ui.mem_slots import MemSlots
from cascade.ui.menu import CHECKED, DEFAULT, PopupMenu
from cascade.ui.monitor import EventMonitor
from cascade.ui.ocr_view import OcrView
from cascade.ui.pause import PauseDialog
from cascade.ui.preview import preview_html, shorten
from cascade.ui.profiles_view import ProfilesView
from cascade.ui.qr_view import QrDialog
from cascade.ui.quick_panel import QuickItem, QuickPanel, QuickTab
from cascade.ui.repository_view import RepositoryView
from cascade.ui.settings_dialog import SettingsDialog
from cascade.ui.snip import SnipOverlay
from cascade.ui.tip import Tip
from cascade.ui.tray import Tray
from cascade.version import VERSION, build_stamp, full_version
from cascade.win32 import ocr, send, shell
from cascade.win32.hook import HookThread
from cascade.win32.instance import SingleInstance
from cascade.win32.magnifier import Magnifier
from cascade.win32.screen import monitors
from cascade.win32.window import (
    WindowPins,
    foreground_window,
    minimize,
    topmost_windows,
    window_class,
    window_title,
)

log = logging.getLogger("cascade.app")

#: Ekran koruyucu engelleyici -- AHK IdleModule: 5 dakikada bir, en cok
#: 60 tur (5 saat) boyunca.
IDLE_INTERVAL_MS = 5 * 60 * 1000
IDLE_TICKS = 60

VK_CAPITAL = 0x14  # buyuk harf kilidi (caps.toggle)
VK_SCROLL = 0x91  # ScrollLock lambasi (turkish.toggle)
user32 = ctypes.windll.user32

# restart() cocuk surece bunu gecer: eski ornek kilidi birakana kadar bekle.
RESTART_FLAG = "--restart"

#: "Yeniden baslat" cikis kodu. Gozetmen (hotkey.vbs) bunu cokme SAYMAZ;
#: gorunce programi kendisi tekrar calistirir.
EXIT_RESTART = 3

#: Gozetmen bu bayragi gecerek "seni ben calistirdim ve BEKLIYORUM" diyor.
#: Bayrak varsa yeniden baslatma hicbir surec BASLATMAZ: sadece
#: EXIT_RESTART ile cikariz, ayni gozetmen programi tekrar calistirir.
#:
#: Eskiden yerimize yeni bir `wscript hotkey.vbs` aciyorduk ve bir sure
#: IKI gozetmen birden yasiyordu -- ikisi de ayni konsol gunlugunu yazmak
#: isteyince cmd "dosya kullanimda" deyip cocugu HIC baslatmiyordu. Iki
#: bekci zaten gereksizdi: tek program calistiriyoruz, basinda tek bekci
#: olmali. Bayrak yoksa (VSCode F5 / dogrudan python) eski yol geceli:
#: cocugu kendimiz baslatiyoruz, yoksa "yeniden baslat" cikis olurdu.
SUPERVISED_FLAG = "--supervised"

#: Gozetmenin aninda olup olmadigini anlamak icin beklenen sure. Cocuk
#: saglamsa wscript uygulama boyunca ayakta kalir; bu surede olduyse
#: baslatamamis demektir ve dogrudan python ile yeniden deneniyor.
SUPERVISOR_PROBE_SECONDS = 0.5

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
        # Tema, pencerelerden ONCE: palet degisimi kurulmus pencerelere
        # de yansir ama acilista bir kez dogru kurmak daha ucuz.
        theme.install()
        self.tip = Tip()
        self.monitor = EventMonitor()
        #: Ayar ekrani ilk istendiginde kuruluyor -- acilista maliyeti olmasin.
        self._settings_dialog: SettingsDialog | None = None
        self._key_map_view: KeyMapView | None = None
        self.runner = ActionRunner()

        # Taban tanimlar ayri duruyor: hafiza slotlari acikken F1..F10
        # bunlarin USTUNE ekleniyor, kapaninca tabana geri donuluyor.
        self._base_defs = dict(keymap.build_cascades())
        self.machine = CascadeMachine(dict(self._base_defs))

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

        # Makro kaydi: olaylar asagidaki `_drain` icinden besleniyor,
        # hook callback'ine dokunulmuyor (macro_ctl.py).
        self.macro = MacroController(tip=self.tip.show_text)
        self.macro.register(self.runner)

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
        #: Fare kimildatma bir kez engellendi mi (bkz. _idle_tick).
        self._idle_blocked = False
        self._exited = False
        # Yeni bir ornek acildi mi (win32/instance.py devralmasi). Hook
        # disi bir thread kaldiriyor, `_tick` gorup kapatiyor.
        self._quit_requested = False
        # Arizali farenin yutulan basim sayisi (AHK: KeyCounts "DoubleCount").
        self._bounce_count = 0
        #: Tepsi rozetindeki kayit sayisi -- son hata okununca sifirlanir.
        self._error_count = 0
        #: Bunlarin kaci ERROR+ (yani simgeyi kirmiziya boyayan).
        self._severe_count = 0
        # AHK: State.Script.shouldSaveOnExit. "Kaydetmeden yeniden baslat"
        # bunu indirir; kapanista pano dosyasina DOKUNULMAZ.
        self.save_on_exit = True
        #: Cikista sabitlenen pencereler birakilsin mi. `restart` kapatiyor.
        self._release_pins_on_exit = True

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
        # Sanal fare kombolari TABLODA duruyor (bkz. keymap.build_hotkeys):
        # ayar degisince tablo yeniden kurulmali. Abonelik burada, cunku
        # ayar tepsi menusunden de ayar EKRANINDAN da degisebiliyor -- iki
        # yol da ayni yerden gecsin.
        keymap.VIRTUAL_MOUSE.subscribe(lambda value, old: self.rebuild_hotkeys())

        # Ham olay kuyrugu ISTENMIYOR (birinci konum bos): olaylari
        # `seen` kuyrugundan aliyoruz. Hook'un kendi kuyrugu buraya kadar
        # doluyor ve `_drain` icinde okunmadan bosaltiliyordu -- olay
        # basina 4 mikrosaniye, hem de callback'in icinde.
        self.hook = HookThread(
            key_filter=self.dispatcher.key_filter,
            mouse_filter=self.dispatcher.mouse_filter,
            # Jest icin sart. Hareket olayi sik gelir (saniyede yuzlerce),
            # o yuzden mouse_filter'in ilk satiri erken cikis.
            watch_mouse_move=True,
        )

        # Burada kalanlar: isi BASKA bir nesnenin yaptigi kayitlar (tip,
        # mem_slots, magnifier) ve tek metodun iki ayri kimlikle farkli
        # parametre aldigi haller. Cascade'in kendi metoduna giden kayitlar
        # metodun ustundeki `@command` ile veriliyor -- kimlik ile is ayni
        # yerde dursun (bkz. actions.command / ActionRunner.adopt).
        # tip: imlecin yaninda 2 sn gorunup kaybolur.  notify: kalici tepsi balonu.
        self.runner.register("tip", lambda text: self.tip.show_text(text, 2000))
        # Jest bitince ipucu da gitsin: 2 sn'lik sure jestten sonra da ekranda
        # kaliyordu (dispatch._end_gesture).
        self.runner.register("tip.hide", lambda _: self.tip.hide())
        self.runner.register("tip_html", lambda body: self.tip.show_html(body, 2000))
        self.runner.register("notify", lambda text: self.tray.notify("cascade", text))
        self.runner.register("menu.close", lambda _: self.menu.close())
        # Surukleme anlasilinca gecikmeli enjekte edilen gercek fare basimi.
        self.runner.register("button_down", press_button)
        self.runner.register("click3_then", lambda keys: self.click_then(keys, times=3))
        # AHK memory_slots.ahk. Argumani olanlar slot numarasi aliyor.
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
        # Kural penceresi acilirken hook susmali (tus yakalanacak), kural
        # kisayolu da kayit defterine tutulmali: ikisi de app.py'nin isi,
        # snip'in dispatcher'a erisimi yok.
        self.snip.set_ui_open = self._set_ui_open
        self.snip.bind_rule = self._bind_area_rule
        self.snip.release_rules = self._release_area_rules
        # F13 menusu: alan secilir secilmez OCR baslasin (AHK'de bu iki oge
        # App.ScreenOcr.snipInteractive / snip("plain") idi).
        self.runner.register("select.ocr", lambda _: self.show_snip_auto("ocr"))
        self.runner.register("select.ocr_adv", lambda _: self.show_snip_auto("ocr_adv"))
        # AHK magnifier.ahk. Islemler ayri thread'de kosuyor: icinde uyku var.
        self.runner.register("magnifier.toggle", lambda _: self.magnifier.toggle())
        self.runner.register("magnifier.reset", lambda _: self.magnifier.reset())

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

        # CapsLock basili tutunca acilan panel (ui/quick_panel.py). Ayri bir
        # veri kaynagi YOK: sekmeler slot / yan grup / pano gecmisinin ayni
        # eylem kimliklerini gosterir, panel yalnizca cizer.
        self._quick: QuickPanel | None = None

        # AHK: App.AppShorts (app_shorts.ahk). On plandaki pencereye gore
        # F13 menusune ekstra kisayol maddeleri girer.
        self.shorts = ShortcutStore()
        self.profiles_view = ProfilesView(self.shorts)
        self.profiles_view.keys_changed = self.bind_profile_keys

        # repository.ahk'nin VERI yarisi (cascade/repository.py). Yonetici
        # GUI'si henuz yok; profillerde oldugu gibi duzenleme dosyanin
        # kendisinden -- bicim zaten bunun icin metin (bkz. repository.py).
        self.repository = Repository(paths.REPOSITORY)
        self.repository.load()
        self.repository_view = RepositoryView(self.repository)
        self.runner.register("repository.open", lambda _: self.repository_view.open())

        # QR (qr-plani.md): pencere panodakiyle acilir, PC -> telefon.
        # Nesne her acilista yeniden kuruluyor -- durum tasimiyor ve
        # panodaki metin her seferinde bastan okunmali.
        self._qr_view: QrDialog | None = None

        # AHK menus.ahk `DialogPauseGui`: Pause tusu basili tutulunca acilir.
        self.pause_dialog = PauseDialog()
        self.pause_dialog.resume.connect(lambda: self.set_paused(False))
        self.pause_dialog.restart.connect(self.restart)
        self.pause_dialog.restart_nosave.connect(self._restart_without_saving)
        self.pause_dialog.exit_app.connect(self.quit)

        # AHK turkish_layout_addon.ahk -- ScrollLock. Hangi VK hangi harf,
        # duzene sorularak bulunuyor; kararlari dispatch veriyor.
        self.dispatcher.turkish_keys = keymap.turkish_keys()

        self.tray = Tray(
            VERSION,
            on_monitor=self.show_monitor,
            on_restart=self.restart,
            on_exit=self.quit,
            on_pause_dialog=self.show_pause_dialog,
            on_toggle_pause=self.toggle_pause,
            on_settings=self.show_settings,
            on_copy_error=self.copy_last_error,
            on_show_log=self.show_log_file,
            on_show_errors=self.show_errors,
        )
        self.tray.show()

        # Hata olunca tepsi simgesi kirmizi olsun. Hata BASKA THREAD'den
        # gelebiliyor (hook, beep), Qt'ye oradan dokunulamaz -- sinyal
        # kuyruga girip ana thread'de islenir.
        #: Kritik hata penceresi acik mi -- ust uste acilmasin.
        self._critical_open = False
        #: Gosterilmeyi bekleyen kritik hatalar (bkz. _queue_critical).
        self._critical_pending: list[str] = []
        self._critical_scheduled = False
        self._errors = _ErrorBridge()
        self._errors.raised.connect(self._on_error_logged)
        # Referans SAKLANIYOR: kapanista abonelikten cikmak icin gerek
        # (bkz. _shutdown). `logs.errors` modul duzeyinde tek ornek.
        self._error_sub = lambda level, text: self._errors.raised.emit(level, text)
        logs.errors.subscribe(self._error_sub)

        # Incognito -- AHK incognito.ahk. Modulun kendi zamanlayicisi yok
        # (bkz. incognito.py "QT YOK"): saati burada kuruluyor ve yalnizca
        # acikken donuyor.
        self.incognito = Incognito(ask_recover=self._ask_incognito_recover)
        self._incognito_badge: IncognitoBadge | None = None
        self._incognito_timer = QTimer(app)
        self._incognito_timer.timeout.connect(self.incognito.watch_tick)

        # Ekran koruyucu engelleyici -- AHK script_state.ahk IdleModule.
        # `on_start` is profilinde bunu baslatiyor, o yuzden cagridan ONCE
        # kuruluyor.
        self._idle_timer = QTimer(app)
        self._idle_timer.timeout.connect(self._idle_tick)

        # `@command` ile isaretli metotlar -- kimlik metodun ustunde duruyor,
        # kayit tek satirda burada. Kurulum bittikten sonra cagriliyor.
        self.runner.adopt(self)

        # Oturum kapanmasi / gorev sonlandirma da OnExit'i calistirsin.
        app.aboutToQuit.connect(self.on_exit)
        self.on_start()

        self._drain_timer = QTimer(app)
        self._drain_timer.timeout.connect(self._drain)
        self._drain_timer.start(8)

        self._tick_timer = QTimer(app)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(20)

        # HOOK EN SON KURULUYOR. Eskiden `on_start`ten ONCE kuruluyordu ve
        # ACILISTA ISIRIYORDU: `on_start` ayar/pano dosyalarini okuyup
        # ayristirirken GIL ana thread'de kaliyor, o sirada gelen ilk
        # callback'ler gecikiyor ve Windows 300 ms'yi asan hook'u SESSIZCE
        # dusuruyor. Bilgisayar acilirken disk ve CPU zaten dolu oldugu
        # icin tam da o anda oluyordu: tepsi simgesi yerinde, program
        # ayakta, hicbir tus calismiyor. Kurulumu yukun BITTIGI yere almak
        # sebebi ortadan kaldiriyor; nobetci yine de duruyor -- acilis tek
        # sebep degil.
        self.hook.start()

        # NOBETCI: hook sessizce dusuruldu mu diye yokluyor, dusmusse
        # yeniden kuruyor (win32/hook.py `looks_dead`).
        self._watchdog_timer = QTimer(app)
        self._watchdog_timer.timeout.connect(self._watchdog_tick)
        self._watchdog_timer.start(2000)


    # ---- pano (ana thread) ----

    def show_filter_items(self, items: tuple, title: str) -> None:
        """Filtreli listeyi acan TEK yol -- pano gecmisi de slotlar da buradan.

        `ui_open` burada kalkiyor: pencere acikken kisayollar susmali
        (arama kutusuna yazarken `Caret & 1` tetiklenmesin).
        """
        self.dispatcher.ui_open = True
        self.filter_window.show_items(items, title)

    def _set_ui_open(self, state: bool) -> None:
        """Snip'in kancasi: pencere acikken dusuk seviye hook sussun."""
        self.dispatcher.ui_open = state

    def _bind_area_rule(self, owner: str, spec: str, area_name: str, index: int) -> str:
        """Kural kisayolunu tutar. Catisma varsa TUTMAZ, sahibini doner.

        Once ayni sahibin eski tanimi birakiliyor: kuralin tusu
        degistirildiginde eskisi tutulu kalmasin. Bos `spec` "tus yok"
        demek -- kural periyodik ya da elle calisiyordur.
        """
        table = self.dispatcher.hotkeys
        table.release(owner)
        if not spec:
            return ""
        action = f"area.run:{area_name}#{index}"
        clash = table.claim(owner, spec, action, f"alan kurali: {area_name}")
        if clash is not None:
            log.warning("kisayol catismasi: %s -> %s", spec, clash.owner)
            return clash.owner
        return ""

    def _release_area_rules(self, area_name: str) -> None:
        """Alan silindi: butun kurallarinin tuslarini birak."""
        table = self.dispatcher.hotkeys
        prefix = f"area:{area_name}#"
        for owner in {b.owner for b in table.bindings if b.owner.startswith(prefix)}:
            table.release(owner)

    @command("area.run")
    def run_area_rule(self, argument: str) -> None:
        """`area.run:<alan>#<sira>` -- kuralin kisayoluna basildi.

        Kuralin kisayolu buraya duser (bkz. `_bind_area_rule`).

        Kural MOTORU henuz yok: burasi kuralin dogru baglandigini ve tusun
        gercekten bize geldigini gosteriyor. Motor yazildiginda degisecek
        tek yer bu govde -- alan dikdortgeni yakalanip `do`/`to` islenecek.
        """
        name, _, index = argument.rpartition("#")
        area = self.snip.store.find(name)
        rule = area.rules[int(index)] if area and index.isdigit() else None
        if rule is None:
            self.tip.show_html("⚠️ <b>kural bulunamadi</b>", 1500)
            return
        self.tip.show_html(
            f"⚡ <b>{html.escape(name)}</b><br>"
            f"<span style='color:#8b949e;'>{html.escape(rule.label())}</span><br>"
            "<span style='color:#8b949e;'>kural motoru henuz yok</span>",
            2500,
        )

    @command("keys.map")
    def show_key_map(self, _argument: str = "") -> None:
        """`keys.map` -- HANGI TUS KIMDE. Kendi penceresi (ui/key_map_view).

        Kisayollar uc ayri yerden geliyor: keymap.py'deki sabit tablo,
        kaskadlar (F15..F20) ve calisma aninda tutulanlar (alan, makro,
        profil). Kullanicinin sorusu her zaman ayni: "bu tus bosta mi, kim
        tutuyor?" -- cevabi tek yerde vermek, uc ayri menude aramaktan iyi.
        """
        table = self.dispatcher.hotkeys
        conflicting = {text for text, _items in table.conflicts()}
        rows = [
            (owner, key, desc, action, key in conflicting)
            for key, action, owner, desc in table.entries()
        ]
        # Kaskadlar ayri bir makinede yasiyor (core/cascade.py); tablo onlari
        # bilmiyor ama kullanici acisindan onlar da "dolu tuslar".
        for vk, definition in self.dispatcher.machine.definitions.items():
            detail = ", ".join(
                f"{press.name.lower()}: {action}"
                for press, action in definition.main.items()
            )
            combos = " ".join(f"+{combo.key_text}" for combo in definition.combos)
            rows.append(("cascade", key_name(vk), combos, detail, False))
        if self._key_map_view is None:
            self._key_map_view = KeyMapView()
            # `ui_open` acik kalirsa hook susar ve pencere kapandiktan
            # sonra HICBIR kisayol calismaz; kapanis sinyali sart.
            self._key_map_view.closed.connect(
                lambda: setattr(self.dispatcher, "ui_open", False)
            )
        self.dispatcher.ui_open = True
        self._key_map_view.show_rows(tuple(rows))

    # ---- F14 secim araci ----

    @command("select.start")
    def show_snip(self, key: str = "") -> None:
        """F14: ekran donar, alan secilir, secim ustunde islem cubugu acilir.

        Surukleyince alan secimi, kimildatmadan birakinca menu. Secim
        acikken tusa yeniden basmak da buraya gelir: pencerenin acik
        oldugunu gorup bastan sectiriyor.

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

    @command("select.screen")
    def show_snip_screen(self, index: str = "0") -> None:
        """`select.screen:<sira>` -- o monitorun tamami secili acilir.

        F14 menusu > Screen maddesi buraya geliyor (keymap.screen_menu).
        Liste menu acilirken uretildigi icin sira bir sonraki ana kadar
        gecerli; arada monitor cikarilmis olabilir, o yuzden sinir kontrolu.
        """
        screens = monitors()
        number = int(index or 0)
        if not 0 <= number < len(screens):
            self.tip.show_html("🚧 <b>monitor bulunamadi</b>", 1500)
            return
        self.dispatcher.watch(0)
        self.snip.start_rect(screens[number][1])

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
            # Ipucunu BIZ gostermiyoruz. Panoya resim koyunca pano
            # dinleyicisi zaten uyaniyor (clip_ctl.on_other): gorseli
            # gecmise yaziyor ve KUCUK RESIMLI ipucunu kendisi cikariyor.
            # Ikisi birden calisinca ard arda IKI ipucu goruluyordu -- biri
            # duz metin, oteki resimli. Resimli olan hem olcuyu veriyor hem
            # neyi kopyaladigini gosteriyor; buradaki yalnizca fazlaligi.
            QGuiApplication.clipboard().setImage(image)
        elif action == "save":
            self.save_capture(image)
        elif action == "clip_image":
            # Secilen alani gorsel gecmisine koy ve pencereyi ac.
            if self.clip.save_image(image) < 0:
                self.tip.show_html("⚠️ <b>gorsel kaydedilemedi</b>", 1500)
                return
            self.clip.show_images()
        elif action == "paint":
            self.paint_capture(image)
        elif action in ("ocr", "ocr_adv"):
            self._start_ocr(action, image)

    def _on_snip_rect_changed(self, image: QImage) -> None:
        """OCR+ acikken alan yeniden ayarlandi: taze kirpimla tekrar oku."""
        self._start_ocr("ocr_adv", image)

    def paint_capture(self, image: QImage) -> None:
        """Secimi gecici bir PNG'ye yazip Paint'te acar.

        Gorsel gecmisindeki "Paint+pano" ile ayni mantik (ui/clip_images.py
        `paint_selected`): dosya SABIT adla yazilir, ustune yazilir, silinmez
        -- Paint dosyayi acik tutuyor ve kullanici uzerinde calisip
        "Kaydet" diyebilir.
        """
        paths.PAINT.mkdir(parents=True, exist_ok=True)
        target = paths.PAINT / "snip.png"
        if not image.save(str(target), "PNG") or not shell.open_in_paint(target):
            self.tip.show_html("⚠️ <b>Paint'te acilamadi</b>", 1500)

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

    @command("window.pin")
    def toggle_pin(self, argument: str) -> None:
        """`window.pin` (bos = one cikan pencere) / `window.pin:<hwnd>`.

        AHK menus.ahk `menuAlwaysOnTop` -- pencereyi hep ustte tut.
        """
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
        """AHK menuAlwaysOnTop: once "bu pencereyi sabitle", sonra ustte
        duran pencereler (tiklayinca birakilir).

        Liste bellekten DEGIL, Windows'tan (`topmost_windows`): boylece
        cokmus bir programin asili biraktigi pencere ve uygulamanin kendi
        actigi "hep ustte" de menude gorunur ve buradan birakilabilir.
        Windows kimin sabitledigini soylemedigi icin ayrimi kendi
        sozlugumuz yapiyor -- yabancilarin yanina `(win)` yaziliyor.

        Menu her acilista yeniden kuruluyor -- sabitli pencereler ve one
        cikan pencere degisiyor, statik tablo bunu tasiyamaz. Tarama
        olculdu: ~0.5 ms, menu acilisinda gorunmez.
        """
        self.pins.prune()
        hwnd = foreground_window()
        title = window_title(hwnd)
        items: list = []
        tops = topmost_windows()
        if hwnd and not any(top.hwnd == hwnd for top in tops):
            label = shorten(title or "(basliksiz)", 45)
            items.append((f"Add {label}", f"window.pin:{hwnd}"))
        for top in tops:
            label = shorten(top.title or "(basliksiz)", 45)
            # Bizim sabitlemediklerimiz "(win)": onlari kullanici ya da
            # uygulamanin kendisi asmis, tiklayinca yine birakiliyorlar.
            if not self.pins.has(top.hwnd):
                label = f"{label}  (win)"
            # Hepsi ustte, hepsi TIKLI -- tekrar basmak birakir. Uzerinde
            # durdugun pencereninki ayrica kalin.
            marks = (CHECKED, DEFAULT) if top.hwnd == hwnd else (CHECKED,)
            items.append((label, f"window.pin:{top.hwnd}", "", *marks))
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
            return ((f"▸ Profil ekle ({shorten(name, 30)})", "shorts.manage"),)
        items: list = []
        for index, shortcut in enumerate(profile.shortcuts):
            label = f"▸ {shortcut.name}"
            if shortcut.description:
                label += f" - {shortcut.description}"
            items.append((label, f"shorts.play:{profile.name}/{index}"))
        items.append(("Profili duzenle...", f"shorts.manage:{profile.name}"))
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
                rows.append(("(kisayol yok)", f"shorts.manage:{profile.name}"))
            # On plandaki pencerenin profili kalin.
            mark = (DEFAULT,) if profile is active else ()
            profiles.append((self._profile_label(profile), tuple(rows), "", *mark))
        if not profiles:
            profiles.append(("(profil yok)", "shorts.manage"))
        profiles.append(None)
        profiles.append(("\U0001f4dd profiles.json duzenle", "shorts.edit"))
        return ("Profiller", tuple(profiles))

    @command("shorts.manage")
    def open_profiles(self, argument: str = "") -> None:
        """`shorts.manage[:<profil adi>]` -- yonetici penceresi.

        AHK showManagerGui portu; `shorts.manage:<ad>` verilen profili
        secili acar (AHK editProfileForActiveWindow ile ayni fikir).
        """
        self.profiles_view.open(argument.strip())

    def bind_profile_keys(self) -> None:
        """Profil aksiyonlarina atanmis tuslari kayit defterine tutturur.

        Acilista ve profil penceresi her kayit yaptiginda cagriliyor. Once
        BUTUN profil tanimlari birakiliyor: aksiyon silinmis, sirasi
        degismis ya da tusu bosaltilmis olabilir; tek tek takip etmek
        yerine hepsini yeniden kurmak hem kisa hem de kacak birakmiyor.
        """
        table = self.dispatcher.hotkeys
        for owner in {b.owner for b in table.bindings if b.owner.startswith("profile:")}:
            table.release(owner)
        for owner, spec, action, desc in self.shorts.bindings():
            clash = table.claim(owner, spec, action, desc)
            if clash is not None:
                log.warning(
                    "profil kisayolu atlandi: %s zaten %s tarafinda", spec, clash.owner
                )

    @command("shorts.play")
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

    @command("repository.edit")
    def edit_repository(self, _argument: str = "") -> None:
        """Kod parcasi deposunu Notepad ile acar.

        Dosya yoksa ORNEK bir kayit yaziliyor: bos Notepad "hangi alanlar
        vardi" sorusunu birakiyordu (edit_shortcuts ile ayni gerekce).
        """
        path = self.repository.path
        if not path.exists():
            paths.ensure_files_dir()
            self.repository.add(
                repository.Item(
                    title="ornek",
                    category="",
                    text="Govdeye ne yazarsan yaz -- kayit ayraci === satiridir.",
                    tags=["ornek"],
                )
            )
            self.repository.save()
        subprocess.Popen(["notepad.exe", str(path)])  # noqa: S603,S607
        self.tip.show_html(
            "📝 <b>repository.md</b><br>"
            "<span style='color:#8b949e;'>kaydettikten sonra yeniden baslat</span>",
            2500,
        )

    @command("shorts.edit")
    def edit_shortcuts(self, _argument: str = "") -> None:
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

    @command("memslots.paste_enter")
    def memslots_paste_enter(self, _argument: str = "") -> None:
        """Orta tus UZUN basim -- AHK handleMButton pt2. Yapistirma panoya
        yazip Ctrl+V gonderiyor (asenkron), Shift+Enter onun ARDINDAN
        gitmeli; yoksa satir sonu yapistirmadan once dusuyor."""
        if not self.mem_slots.isVisible():
            return
        self.mem_slots.smart_paste(middle=True)
        QTimer.singleShot(160, lambda: self.runner.run("send_key:+Enter"))

    @command("memslots.start")
    def show_mem_slots(self, _argument: str = "") -> None:
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
        self.clip.state.set_mode(self._clip_mode_before)

    # ---- buyutec ----

    @command("magnifier.zoom")
    def zoom(self, argument: str) -> None:
        """`magnifier.zoom:+` / `magnifier.zoom:-`"""
        if argument.startswith("-"):
            self.magnifier.zoom_out()
        else:
            self.magnifier.zoom_in()

    @command("magnifier.panic")
    def panic(self, _argument: str = "") -> None:
        """AHK: `(App.Magnifier.reset(), WinMinimize("A"))` -- buyutec %100'e
        doner ve one cikan pencere kuculur."""
        self.magnifier.reset()
        minimize()

    # ---- menuler ve durum ----

    @command("state.reset")
    def reset_state(self, _argument: str = "") -> None:
        """Acil fren: takilmis onek / yarida kalmis kaskad varsa temizler.

        AHK karsiligi `Pause & c:: State.Busy.setFree()` idi; o global bayrak
        artik yok (bkz. core/state.py), ama `dispatcher.reset()` ayni ise
        yariyor: makine IDLE'a doner, onek ve jest takipcileri bosalir.
        """
        self.dispatcher.reset()
        self.tip.show_html("\U0001f513 <b>durum sifirlandi</b>", 1200)

    @command("errors.show")
    def show_errors(self, _argument: str = "") -> None:
        """AHK: getStatsArray / getRecentErrors."""
        QMessageBox.information(
            None,
            f"cascade {VERSION} - son hatalar",
            f"Hook callback  : en uzun {self.hook.max_callback_ms:.3f} ms (sinir 300)\n"
            f"Dusen olay     : {self.hook.dropped}\n"
            f"Hook tamiri    : {self.hook.reinstalls} kez yeniden kuruldu\n"
            f"Hayalet tus    : {self.dispatcher.phantom_drops} dusuruldu\n"
            f"Pano kaydi     : {len(self.clip.history)}\n"
            f"Yutulan cift tik: {self._bounce_count} (arizali fare)\n"
            f"Log dosyasi    : {paths.LOG}\n\n"
            f"{logs.recent_text(15)}",
        )
        self._clear_error_badge()

    def show_log_file(self) -> None:
        """Tepsi menusu "Show log..." -- log dosyasini Notepad ile acar.

        Ayar ekranindaki "settings.json" dugmesiyle ayni yol. Dosya henuz
        yoksa bos olarak yaratiliyor: Notepad'in "olusturulsun mu" sorusu
        cikmasin.
        """
        try:
            paths.ensure_files_dir()
            paths.LOG.touch(exist_ok=True)
            subprocess.Popen(["notepad.exe", str(paths.LOG)])  # noqa: S603, S607
        except OSError:
            log.exception("log dosyasi acilamadi")

    @command("errors.copy")
    def copy_last_error(self, _argument: str = "") -> None:
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
        """Hata kaydedildi: tepsi rozeti HER ZAMAN yanar, ama RENGI siddete
        gore -- ERROR+ kirmizi, WARNING sari (bkz. ui/tray.py dosya basi).
        Ipucu ayara bagli (logs.SHOW_TIP), tepsi balonu SADECE CRITICAL'da --
        her uyarida balon cikarsa rahatsiz eder."""
        self._error_count += 1
        if level in ("ERROR", "CRITICAL"):
            self._severe_count += 1
        self.tray.set_error_count(self._error_count, self._severe_count)
        if logs.SHOW_TIP.get():
            self.tip.show_html(
                f"⚠️ <b>{html.escape(level.lower())}</b><br>{preview_html(text, 3)}",
                2500,
            )
        if level == "CRITICAL":
            self.tray.notify("cascade - hata", shorten(text.strip(), 200))
            self._queue_critical(text)

    def _queue_critical(self, text: str) -> None:
        """Kritik hatayi biriktirir; pencereyi bir SONRAKI olay turuna birakir.

        Dogrudan acmak yanlisti: `on_start` uc depoyu SIRAYLA okuyor ve uc
        dosya birden bozuksa her biri kendi penceresini aciyordu -- kullanici
        arka arkaya uc kez "Tamam"a basiyordu. Ust uste acilmayi engelleyen
        bayrak burada ise yaramiyor, cunku cagrilar IC ICE degil ARDISIK:
        ilk pencere kapanmadan ikinci hata zaten olusmuyor.

        `singleShot(0)` cagri yiginini bosaltiyor; acilis okumalari bittikten
        sonra elde ne birikmisse TEK pencerede gosteriliyor. Acilista olay
        dongusu henuz baslamamis olsa bile calisir: zamanlayici `app.exec()`
        basladigi anda tetiklenir.
        """
        self._critical_pending.append(text.strip())
        if not self._critical_scheduled:
            self._critical_scheduled = True
            QTimer.singleShot(0, self._flush_critical)

    def _flush_critical(self) -> None:
        """Biriken kritik hatalari TEK pencerede gosterir."""
        self._critical_scheduled = False
        if self._critical_open or not self._critical_pending:
            return
        pending, self._critical_pending = self._critical_pending, []
        self._critical_open = True
        try:
            headers = [item.splitlines()[0] for item in pending if item.splitlines()]
            box = QMessageBox(QMessageBox.Icon.Critical, "cascade - kritik hata", "")
            note = (
                f"Ayrinti log'da: {paths.LOG}\n"
                "Bozuk dosyanin yedegi Files/ icinde `.bozuk-<zaman>` adiyla duruyor."
            )
            box = QMessageBox(QMessageBox.Icon.Critical, "cascade - kritik hata", "")
            if len(headers) == 1:
                box.setText(shorten(headers[0], 300))
                box.setInformativeText(note)
            else:
                # Coklu bozulmada baslik SAYIYI soyluyor, govde hangileri
                # oldugunu: "bir sey bozuldu" ile "uc dosya birden bozuldu"
                # cok farkli iki durum.
                box.setText(f"{len(headers)} kritik hata:")
                bullets = "\n".join(f"• {shorten(head, 200)}" for head in headers)
                box.setInformativeText(f"{bullets}\n\n{note}")
            box.setDetailedText("\n\n".join(pending) + f"\n\nLog: {paths.LOG}")
            box.exec()
        finally:
            self._critical_open = False
            self._clear_error_badge()
        # Pencere ACIKKEN yeni hata geldiyse onu da goster -- yutmak,
        # "uc pencere" sorununu cozerken hata gizlemek olurdu.
        if self._critical_pending and not self._critical_scheduled:
            self._critical_scheduled = True
            QTimer.singleShot(0, self._flush_critical)

    def _clear_error_badge(self) -> None:
        """Hatalar gorulmus sayilir: rozet sifirlanir, kayitlar durur."""
        self._error_count = 0
        self._severe_count = 0
        self.tray.set_error_count(0, 0)

    @command("click.bounce")
    def on_click_bounce(self, argument: str) -> None:
        """AHK: `#HotIf A_TimeSincePriorHotkey < 70` -> LButton yutulur.

        Arizali mikro anahtarin urettigi ikinci basim dispatch'te zaten
        yutuldu; burada yalniz sayim/uyari var. Log'a CRITICAL degil WARNING
        dusuyor: fare yaslaniyor demek, program hatasi degil.
        """
        self._bounce_count += 1
        log.warning("cift tiklama yutuldu (%s ms, toplam %d)", argument, self._bounce_count)
        beep(1000, 100)

    @command("caps.toggle")
    def toggle_caps(self, _argument: str = "") -> None:
        """AHK cascadeCaps: kilidi cevirir, yeni durumu soyler (AHK ShowTip).

        Onek tusunun keydown'i yutuluyor, yani kilidi Windows cevirmiyor;
        tusu geri gondermek yeterli -- kendi gonderdigimiz basim kilidi
        normal sekilde cevirir.
        """
        state = bool(user32.GetKeyState(VK_CAPITAL) & 1)
        send.tap(VK_CAPITAL)
        self.tip.show_html("<b>CAPSLOCK</b>" if not state else "<b>capslock</b>", 900)

    @command("menu.sys")
    def show_sys_menu(self, _argument: str = "") -> None:
        """AHK: sysCommands() -- `´` tusunun menusu."""
        self.menu.show(keymap.SYS_COMMANDS_MENU, title=f"⚙️ cascade {full_version()}")

    def _incognito_menu_item(self) -> tuple:
        """F13 menusundeki tek satir: pencereyi acar (kapatma pencerede)."""
        if self.incognito.active:
            return (f"🏴‍☠️ Incognito ({self.incognito.locked_count})", "incognito.open")
        return ("🏴‍☠️ Incognito", "incognito.open")

    @command("menu.f13")
    def show_f13_menu(self, _argument: str = "") -> None:
        """AHK: showF13menu() -- statik tablo + o anki pencere durumu."""
        # 1. kolon tablodan gelir ve COLUMN ile biter; 2. kolonun basi o
        # anki pencereye bagli bloklar, sonu sabit kuyruk -- sira AHK
        # showF13menu ile ayni.
        spec: tuple = (("Clipboard history", self.clip.menu_items()),)
        spec += keymap.F13_MENU
        spec += (*self._shortcut_menu_items(), self._shortcut_manager_item())
        # Profillerden AYRI blok: ikisi de kendi penceresini acar, alt menu
        # yok -- icerik pencerede yasiyor (AHK'de Repository de boyleydi).
        spec += (
            None,
            ("📚 Repository", "repository.open"),
            self._incognito_menu_item(),
        )
        pins = self._pin_menu_items()
        if pins:
            spec += (None, *pins)
        if keymap.F13_MENU_TAIL:
            spec += (None, *keymap.F13_MENU_TAIL)
        # Kalin ogeler (AHK menuAppProfile / menuAlwaysOnTop) ogenin kendi
        # DEFAULT isaretiyle geliyor; bkz. ui/menu.py.
        self.menu.show(spec)

    # ---- hizli panel ----

    def _quick_tabs(self) -> tuple[QuickTab, ...]:
        """Panel sekmeleri. Saglayicilar panel her acildiginda cagriliyor.

        PANO ILK SIRADA, cunku paneli acan tus CapsLock: "basili tut,
        numaraya bas, yapistir" isinin hedefi pano gecmisi. Slotlarin kendi
        tuslari zaten var (`^`, Tab, F14 menusu).
        """
        return (
            QuickTab("Pano", self._clip_items),
            QuickTab("Slot", lambda: self._slot_items("")),
            QuickTab("Side", lambda: self._slot_items(self.slot_store.default_group)),
        )

    def _slot_items(self, group: str) -> tuple[QuickItem, ...]:
        """Bir grubun ilk on slotu. Disk TAZE okunuyor -- dosyayi AHK tarafi
        ya da elle duzenleme degistirmis olabilir (slots_ctl ile ayni kural)."""
        self.slot_store.load()
        return tuple(
            QuickItem(
                content=slot.content,
                action=f"slot.paste_group:{group}/{index}",
                label=f"{slot.name or f'Slot {index}'}: "
                + (slot_display(index, " ".join(slot.content.split()), lambda t: t) or "(bos)"),
            )
            for index, slot in enumerate(self.slot_store.slots(group)[:10], start=1)
        )

    def _clip_items(self) -> tuple[QuickItem, ...]:
        """Pano gecmisinin TAMAMI. Kopya sayisi birden coksa etiketin sonunda
        "x3". Kirpma panelin isi: onarli sayfalar halinde gosteriyor."""
        return tuple(
            QuickItem(
                content=entry.text,
                action=f"clip.paste:{index}",
                label=entry.preview + (f"  x{entry.count}" if entry.count > 1 else ""),
            )
            for index, entry in enumerate(self.clip.history.entries, start=1)
        )

    @command("menu.quick")
    def show_quick_panel(self, argument: str = "") -> None:
        """`menu.quick[:sekme]` -- CapsLock ve `^` basili tutunca acilan panel.

        Arguman acilista SECILI gelecek sekmenin adi. CapsLock adsiz cagirir
        ve Pano'da acilir; `^` "Slot" der, cunku o tusun rakamlari (`^ & 1..0`)
        zaten base slotlari yapistiriyor -- panel ayni listeyi gostermeli.
        """
        if self._quick is None:
            self._quick = QuickPanel(self._quick_tabs())
            self._quick.chosen.connect(self.runner.run)
            self._quick.qr_requested.connect(self.show_qr_text)
        self._quick.open(self._quick.tab_index(argument))

    @command("qr.show")
    def show_qr(self, _argument: str = "") -> None:
        """F14 menusu > QR kod. Panodaki metinle acilir."""
        self.show_qr_text(QGuiApplication.clipboard().text() or "")

    def show_qr_text(self, text: str) -> None:
        """Verilen metinle QR penceresi. Hizli panelde Alt+q buraya gelir:
        orada QR'i gorulmek istenen sey PANODAKI degil SECILI ogedir."""
        if self._qr_view is not None:
            self._qr_view.close()
        self._qr_view = QrDialog(text.strip(), self.slot_store)
        self._qr_view.show()
        self._qr_view.raise_()
        self._qr_view.activateWindow()

    @command("yok")
    def not_ported(self, module: str) -> None:
        """Menude `--` ile isaretli ogeler buraya duser."""
        self.tip.show_html(
            f"\U0001f6a7 <b>henuz port edilmedi</b><br>"
            f"<span style='color:#8b949e;'>{html.escape(module)}</span>",
            2000,
        )

    @command("click_then")
    def click_then(self, keys: str, times: int = 1) -> None:
        """AHK: `(Click("Left", 3), Send("^c"))` -- once tikla, sonra gonder.

        Tiklama ile gonderim arasinda kisa bir bosluk var: uc hizli tik
        secim yapiyor ve secimin olusmasi hedef uygulamada zaman aliyor.
        """
        for _ in range(times):
            send.click("left")
        QTimer.singleShot(80, lambda: self.runner.run(f"send_key:{keys}"))

    @command("app.settings")
    def show_settings(self, _argument: str = "") -> None:
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

    @command("incognito.open")
    def open_incognito(self, _argument: str = "") -> None:
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

    @command("app.monitor")
    def show_monitor(self, _argument: str = "") -> None:
        """`´` menusu 4 + tepsi -- olay gecmisi penceresi (ui/monitor.py)."""
        self.monitor.show()
        self.monitor.raise_()
        self.monitor.activateWindow()

    # ---- ana thread dongusu ----

    def _drain(self) -> None:
        showing = self.monitor.isVisible()
        for _ in range(200):
            try:
                event, swallowed = self.seen.get_nowait()
            except queue.Empty:
                break
            self.macro.feed(event)
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

    def _watchdog_tick(self) -> None:
        """Hook hala ayakta mi? Degilse yeniden kur -- KENDI KENDINI TAMIR.

        Windows, callback'i LowLevelHooksTimeout'u (300 ms) asan hook'u
        haber vermeden zincirden cikariyor. Program o andan sonra ayakta
        GORUNUR ama hicbir tus calismaz; tek care yeniden kurmak.

        `dispatcher.reset()` sart: hook olu gectigi surede birakma olaylari
        kayboldu, geride hayalet tuslar kalir (bkz. dispatch._reconcile).
        """
        if self._exited:
            return
        try:
            if not self.hook.ensure_alive(time.perf_counter()):
                return
        except Exception:
            # SetWindowsHookEx her zaman basarili olmaz (oturum degisimi,
            # kaynak sikintisi). Zamanlayici yuvasindan disari kacan bir
            # hata programi dusururdu; iki saniye sonra tekrar denenecek.
            log.exception("hook yeniden kurulamadi, sonraki turda tekrar denenecek")
            return
        self.dispatcher.reset()
        log.warning(
            "hook dusmustu, yeniden kuruldu (%d. kez, en uzun callback %.1f ms)",
            self.hook.reinstalls,
            self.hook.max_callback_ms,
        )
        self.tip.show_html(
            "🔁 <b>hook yeniden kuruldu</b><br>"
            "<span style='color:#8b949e;'>Windows dusurmustu; tuslar geri geldi</span>",
            2500,
        )

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

    @command("app.pause")
    def toggle_pause(self, _argument: str = "") -> None:
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

    @command("turkish.toggle")
    def toggle_turkish(self, _argument: str = "") -> None:
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

    @command("turkish.layout")
    def switch_turkish_layout(self, _argument: str = "") -> None:
        """ScrollLock basili tutma -- AHK: dizilim 1 <-> 2."""
        self.dispatcher.turkish.switch_layout()
        self.switch_turkish_layout_tip()

    @command("turkish.set")
    def set_turkish_layout(self, arg: str) -> None:
        """Menuden dizilim SECIMI -- `turkish.set:1` / `turkish.set:2`.

        `switch_turkish_layout` sirayla gecerken bu dogrudan atiyor: menude
        hangi maddeye bastigin ne olacagini belirlemeli, sira degil.
        """
        want = 2 if arg.strip() == "2" else 1
        if self.dispatcher.turkish.layout != want:
            self.dispatcher.turkish.switch_layout()
        self.switch_turkish_layout_tip()

    def switch_turkish_layout_tip(self) -> None:
        layout = self.dispatcher.turkish.layout
        note = "uzun basim (c s i g)" if layout == 1 else "dogrudan remap"
        self.tip.show_html(
            f"🇹🇷 <b>Turkce dizilim: {layout}</b><br>"
            f"<span style='color:#8b949e;'>{note}</span>",
            1200,
        )

    @command("menu.scrolllock")
    def show_scroll_lock_menu(self, _argument: str = "") -> None:
        """ScrollLock basili tutulunca: Turkce seti + sanal fare kipi.

        Turkceyi ACIP KAPAMAK menude yok, o KISA basim (`turkish.toggle`).
        """
        self.menu.show(
            keymap.scroll_lock_menu(self.dispatcher.turkish.layout),
            title="ScrollLock",
        )

    def rebuild_hotkeys(self) -> None:
        """Kisayol tablosunu bastan kurar -- CALISMA ANINDA tutulanlarla birlikte.

        Tabloda yalniz keymap.py yok: profil kisayollari (`profile:*`) ve
        alan kurallari (`area:*`) calisma aninda `claim` ile giriyor. Ciplak
        tabloyu takip birakmak onlari sessizce dusuruyordu -- sanal fareyi
        bir kez ac-kapa yapan kullanici butun profil ve alan tuslarini
        kaybediyor, program yeniden baslayana kadar da geri gelmiyordu.

        Onek tanimlarina dokunulmuyor: bu kombolarin onegi yok, dolayisiyla
        PrefixTracker'in durumu gecerli kaliyor.
        """
        self.dispatcher.hotkeys = keymap.build_hotkeys()
        self.bind_profile_keys()
        for area in self.snip.store.areas:
            for index, rule in enumerate(area.rules):
                self._bind_area_rule(
                    area.rule_owner(index),
                    rule.key if rule.enabled else "",
                    area.name,
                    index,
                )

    @command("vmouse.toggle")
    def toggle_virtual_mouse(self, _argument: str = "") -> None:
        """Win+WASD sanal faresini ac/kapa.

        Yalniz ayari ceviriyor: tabloyu yeniden kurma isi ayarin
        abonesinde (bkz. `__init__`), boylece AYAR EKRANINDAN degistirmek
        de ayni yoldan geciyor. Once yalnizca burada yapiliyordu ve ayar
        ekranindan acilan sanal fare yeniden baslatana kadar olu kaliyordu.
        """
        keymap.VIRTUAL_MOUSE.set(not keymap.VIRTUAL_MOUSE.get())
        on = keymap.VIRTUAL_MOUSE.get()
        self.tip.show_html(
            f"🖱️ <b>WASD sanal fare: {'acik' if on else 'kapali'}</b><br>"
            + (
                "<span style='color:#8b949e;'>Win+WASD imlec, Q/E tik, Y Enter</span>"
                if on
                else "<span style='color:#8b949e;'>Win+D / Win+E serbest</span>"
            ),
            1400,
        )

    @command("app.pause_dialog")
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
        logs.lifecycle("cascade %s basladi", full_version())
        # AHK LoadSettings: Settings.load() + applyAll(). Ayarlari OKUMAK
        # yetmiyor, abonelere haber vermek de gerek -- yoksa moduller kod
        # icindeki varsayilanla calismaya devam eder.
        SETTINGS.load(paths.SETTINGS)
        # Baslangic kisayolu ayardan ONCE okunur: kaynagi dosya sistemi,
        # settings.json degil (bkz. autostart.sync).
        autostart.sync()
        SETTINGS.apply_all()
        for action in keymap.START_ACTIONS:
            self.runner.run(action)
        self.clip.load()
        self.shorts.load()
        self.bind_profile_keys()
        profile = keymap.current_profile()
        label = keymap.PROFILE_LABELS.get(profile, profile)
        log.info("makine profili: %s (%s)", profile, platform.node())
        self.tray.setToolTip(f"cascade {full_version()} - {profile}")
        # AHK LoadSettings: is bilgisayarinda State.Idle.enable() -- ekran
        # koruyucu devreye girmesin diye 5 dakikada bir fareyi kimildatir.
        if profile == "work":
            self._idle_count = IDLE_TICKS
            self.dispatcher.last_physical = time.perf_counter()
            self._idle_timer.start(IDLE_INTERVAL_MS)
        # Acilis karti: profil, surum, yapim damgasi. Uc satir ve 4 saniye
        # -- hata bildiriminde istenen bilgi bu ucu ve acilista bir kez
        # bakip gorulebilsin diye okunacak kadar duruyor. Sayimlar (pano
        # kaydi, uygulama profili) burada yok, log'a zaten yaziliyorlar.
        card = (
            f"✅ <b>cascade</b> &nbsp;·&nbsp; {label}<br>"
            f"<span style='color:#8b949e;'>version</span> {VERSION}<br>"
            f"<span style='color:#8b949e;'>build</span> {build_stamp()}"
        )
        # Onceki oturumdan (ya da baska programdan) ustte kalmis pencereler.
        # Acilista bir kez soyleniyor: bizim sozlugumuz her baslangicta bos,
        # yani bu pencereleri baska kimse hatirlamiyor.
        stray = len(topmost_windows())
        if stray:
            log.info("%d pencere ustte sabitli (Windows taramasi)", stray)
            card += (
                f"<br><span style='color:#8b949e;'>ustte sabitli</span> "
                f"{stray} pencere &nbsp;·&nbsp; F13 menusu"
            )
        self.tip.show_html(card, 4000)

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
        # GIT-GEL: tek yonlu -1,-1 imleci her turda bir piksel sol uste
        # kaydiriyordu -- bes saatte 59 piksel. Ayni turda geri aliniyor;
        # iki hareketin ikisi de bos zaman sayacini sifirliyor, imlec ise
        # yerinde kaliyor.
        #
        # SendInput, on plandaki pencere BIZDEN YUKSEK butunlukteyse
        # (yonetici hakkiyla acilmis bir program, UAC istemi) UIPI ile geri
        # cevriliyor. Microsoft'un notu: "neither GetLastError nor the return
        # value will indicate the failure was caused by UIPI blocking" -- yani
        # kod da guvenilir degil, OSError'un tamami yakalanmali. Bizim hatamiz
        # degil ve gecici: odak degisince duzelir. Yakalanmadigi surece Qt
        # yuvasindan disari kaciyor, sys.excepthook onu CRITICAL yaziyor ve
        # her turda -- bes dakikada bir -- kirmizi tepsi + modal "kritik hata"
        # penceresi cikiyordu. Bir kez soylenir, sonra susulur.
        try:
            send.move_relative(-1, -1)
            send.move_relative(1, 1)
        except OSError as exc:
            if not self._idle_blocked:
                self._idle_blocked = True
                log.warning(
                    "ekran koruyucu engelleyici: fare kimildatilamadi (%s); "
                    "on plandaki pencere yonetici hakkiyla calisiyor olabilir. "
                    "Bu uyari oturumda bir kez yazilir.",
                    exc,
                )

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
        # Yeniden baslatmada sabitler BIRAKILMIYOR: reload kullanicinin
        # ekranini degistirmemeli, yalnizca programi tazelemeli. Cikista
        # birakiliyor ki ekranda sahipsiz asili pencere kalmasin.
        if self._release_pins_on_exit:
            self.pins.clear_all()
        saved = (
            self.clip.save()
            if self.save_on_exit
            else False
        )
        logs.lifecycle(
            "cascade kapaniyor (%d pano kaydi, diske yazildi: %s)",
            len(self.clip.history),
            "evet" if saved else "HAYIR",
        )
        self._shutdown()

    @command("app.restart")
    def restart(self, _argument: str = "") -> None:
        """AHK: Pause+Home -> reloadScript()

        GOZETMEN ALTINDAYSAK (hotkey.vbs, normal kullanim) hicbir surec
        baslatilmaz: EXIT_RESTART ile cikariz, bizi bekleyen bekci programi
        tekrar calistirir. Asagisi yalnizca gozetmensiz calisirken (VSCode
        F5, dogrudan python) gecerli -- orada cocugu kendimiz acmazsak
        "yeniden baslat" duz bir cikis olurdu.

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
        # SIRA: bayrak on_exit'ten ONCE. Sonda kaldigi surece hicbir ise
        # yaramiyordu -- sabitleri birakan kod coktan kosmus oluyordu.
        self._release_pins_on_exit = False
        self.on_exit()
        if self.lock is not None:
            self.lock.release()

        if SUPERVISED_FLAG in sys.argv:
            # Bekci kapida bekliyor: ona "beni tekrar calistir" demek icin
            # cikis kodu yetiyor. Surec baslatmiyoruz -- ne ikinci bir
            # gozetmen, ne konsol gunlugu icin bogusma, ne de "cocuk
            # kalkabildi mi" sorusu.
            logs.lifecycle("yeniden baslatiliyor (gozetmen devraliyor)")
            self.app.exit(EXIT_RESTART)
            return

        executable = sys.executable
        pythonw = os.path.join(os.path.dirname(executable), "pythonw.exe")
        if os.path.exists(pythonw):
            executable = pythonw

        script = os.path.join(paths.ROOT, "main.py")
        # Gozetmen uzerinden: cocuk hatayla olurse hotkey.vbs `uv sync`
        # deneyip mesaj verir. Dogrudan pythonw sessizce oluyordu.
        supervisor = os.path.join(paths.ROOT, "hotkey.vbs")
        windir = os.environ.get("SYSTEMROOT") or "C:\\Windows"
        wscript = os.path.join(windir, "System32", "wscript.exe")
        direct = [executable, script, RESTART_FLAG]
        via_supervisor = os.path.exists(supervisor) and os.path.exists(wscript)
        command = [wscript, supervisor, RESTART_FLAG] if via_supervisor else direct
        try:
            child = self._spawn(command)
        except OSError as exc:
            # Sessizce cikmaktansa soyle: eskiden "yeniden baslat" cikis gibi
            # gorunuyordu, cunku hata kimseye ulasmiyordu.
            QMessageBox.critical(None, "cascade", f"Yeniden baslatilamadi: {exc}")
            self.app.quit()
            return

        # COCUK GERCEKTEN KALKTI MI? Gozetmen (wscript) uygulama boyunca
        # ayakta kalir -- yarim saniyede olduyse baslatamamis demektir ve
        # geriye HICBIR SEY kalmaz: "yeniden baslat dedim, program kapanip
        # gitti" tam olarak bu. Kod cerezi degil: WSH kayitli degilse,
        # bir politika wscript'i engelliyorsa ya da .vbs uzantisi baska bir
        # programa baglanmissa bu yol sessizce olur.
        if via_supervisor:
            time.sleep(SUPERVISOR_PROBE_SECONDS)
            if child.poll() is not None:
                log.warning(
                    "gozetmen aninda oldu (kod %s), dogrudan python deneniyor",
                    child.returncode,
                )
                try:
                    self._spawn(direct)
                except OSError as exc:
                    QMessageBox.critical(
                        None, "cascade", f"Yeniden baslatilamadi: {exc}"
                    )
                    self.app.quit()
                    return
        logs.lifecycle("yeniden baslatiliyor (gozetmensiz: cocugu kendimiz actik)")
        self.app.quit()

    def _spawn(self, command: list[str]):
        """Ayrik, job'dan kopmus cocuk surec. Bkz. `restart` notlari."""
        base_flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            return subprocess.Popen(
                command,
                cwd=str(paths.ROOT),
                close_fds=True,
                env=_child_env(),
                creationflags=base_flags | CREATE_BREAKAWAY_FROM_JOB,
            )
        except OSError:
            # Job breakaway'e izin vermiyorsa (debugpy veriyor, ama baska
            # bir sarmalayici vermeyebilir) bayraksiz dene.
            return subprocess.Popen(
                command,
                cwd=str(paths.ROOT),
                close_fds=True,
                env=_child_env(),
                creationflags=base_flags,
            )

    def request_quit(self) -> None:
        """Yeni bir ornek acildi: yerimizi birak (win32/instance.py).

        BASKA THREAD'den cagriliyor -- burada Qt'ye dokunulmuyor, sadece
        bayrak kalkiyor; kapanisi ana thread'deki `_tick` yapiyor.
        """
        logs.lifecycle("yeni ornek acildi, kapaniyoruz")
        self._release_pins_on_exit = False
        self._quit_requested = True

    @command("app.exit")
    def quit(self, _argument: str = "") -> None:
        """AHK: Pause & End -> ExitApp()"""
        self.on_exit()
        self.app.quit()

    def _shutdown(self) -> None:
        """Yalniz on_exit'ten cagrilir; sirasi onemli: once zamanlayicilar,
        sonra hook, en son pencereler."""
        # ONCE abonelikten cik: kapanirken dusen bir hata olu pencereleri
        # canlandirmasin (kritik hata penceresi acmaya calisirdi).
        logs.errors.unsubscribe(self._error_sub)
        self._drain_timer.stop()
        self._tick_timer.stop()
        self._watchdog_timer.stop()
        self.clip.close()
        self.filter_window.close()
        self.snip.close()
        self.ocr_view.close()
        self.mem_slots.close()
        self.repository_view.close()
        if self._qr_view is not None:
            self._qr_view.close()
        self.profiles_view.close()
        self.macro.shutdown()
        self.macro.view.close()
        self.pause_dialog.close()
        self.machine.reset()
        self.hook.stop()
        self.tip.hide()
        self.monitor.close()
        self.tray.hide()
