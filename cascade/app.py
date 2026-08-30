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

from PIL import Image
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from cascade import keymap, logs, paths
from cascade.actions import ActionRunner, beep
from cascade.app_shorts import ShortcutStore, stroke_kind
from cascade.core.cascade import Beep, CascadeMachine, CloseMenu, OpenMenu, Run
from cascade.core.clip_history import ClipHistory
from cascade.core.filter import FilterItem
from cascade.core.keynames import key_name, vk_from_name
from cascade.core.state import Busy, ClipboardMode, ClipboardState
from cascade.dispatch import Dispatcher
from cascade.imgstore import ClipImageStore
from cascade.store import PASSWORD_SLOT, ClipStore, SlotStore, slot_display
from cascade.ui.array_filter import ArrayFilter
from cascade.ui.clip_images import ClipImages
from cascade.ui.clipboard import ClipboardWatcher
from cascade.ui.mem_slots import MemSlots
from cascade.ui.menu import PopupMenu
from cascade.ui.monitor import EventMonitor
from cascade.ui.ocr_view import OcrView
from cascade.ui.pause import PauseDialog
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


def _shorten(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
        self.runner = ActionRunner()

        # Taban tanimlar ayri duruyor: hafiza slotlari acikken F1..F10
        # bunlarin USTUNE ekleniyor, kapaninca tabana geri donuluyor.
        self._base_defs = dict(keymap.build_cascades())
        self.machine = CascadeMachine(dict(self._base_defs), Busy())

        # Pano. Durum (hangi mod) ile liste (ne saklandi) ayri duruyor;
        # dinleme tek yerde, ui/clipboard.py icinde. AHK'de de boyleydi.
        self.clip_state = ClipboardState()
        self.clip_history = ClipHistory()
        self.clip_store = ClipStore()
        # AHK clip_slot.ahk ile ayni dosya ve bicim: Files/slots.json.
        self.slot_store = SlotStore()
        self.clip_watcher = ClipboardWatcher()
        self.clip_watcher.text_copied.connect(self._on_clip_text)
        self.clip_watcher.other_copied.connect(self._on_clip_other)

        # Filtreli liste ve acilir menu. Liste penceresi acikken kisayollar
        # susar (dispatcher.ui_open): arama kutusuna yazarken `Caret & 1`
        # tetiklenmesin.
        self.filter_window = ArrayFilter()
        self.filter_window.chosen.connect(self.paste_text)
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
        self._clip_mode_before = self.clip_state.mode
        self.mem_slots.paste_text.connect(self.paste_text)
        self.mem_slots.copy_text.connect(self.clip_watcher.set_text)
        self.mem_slots.grab_clip.connect(lambda: self.runner.run("send_key:^c"))
        self.mem_slots.tip.connect(lambda body: self.tip.show_html(body, 1500))
        self.mem_slots.fkeys_toggled.connect(self._on_memslot_fkeys)
        # Ad penceredeyken degisti: diske HEMEN yaz (AHK setName da oyleydi)
        # -- pencere kapanmadan program kapanirsa ad kaybolmasin.
        self.mem_slots.name_changed.connect(
            lambda index, name: self.slot_store.set_slot_name(
                self.slot_store.default_group, index, name
            )
        )
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
        self.ocr_view.copy_text.connect(self._copy_to_history)
        self.ocr_view.reocr_requested.connect(self._on_reocr)
        self.ocr_view.closed.connect(self.snip.end_session)

        # AHK clip_image_store.ahk + clip_image_dialog.ahk. Dosya bicimi
        # AHK ile ayni (clipimg.idx / clipimg.dat), pencere de ayni islevde.
        self.image_store = ClipImageStore()
        self.clip_images = ClipImages(self.image_store)
        self.clip_images.copied.connect(self._on_image_copied)
        #: OCR+ oturumundaki son kirpim -- ayar degisince ekran YENIDEN
        #: CEKILMEDEN bunun uzerinden tekrar okunur (AHK: cache'li bitmap).
        self._ocr_image: QImage | None = None
        self._ocr_bridge = _OcrBridge()
        self._ocr_bridge.finished.connect(self._on_ocr_done)
        self._ocr_bridge.failed.connect(self._on_ocr_failed)

        # AHK: State.Window.onTopWindows -- sabitledigimiz pencereler.
        self.pins = WindowPins()

        self.paused = False
        self._exited = False
        # Yeni bir ornek acildi mi (win32/instance.py devralmasi). Hook
        # disi bir thread kaldiriyor, `_tick` gorup kapatiyor.
        self._quit_requested = False
        # Arizali farenin yutulan basim sayisi (AHK: KeyCounts "DoubleCount").
        self._bounce_count = 0
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
        self.runner.register("tip_html", lambda body: self.tip.show_html(body, 2000))
        self.runner.register("notify", lambda text: self.tray.notify("cascade", text))
        self.runner.register("app.restart", lambda _: self.restart())
        self.runner.register("app.exit", lambda _: self.quit())
        self.runner.register("clip.show", lambda _: self.show_clip_history())
        self.runner.register("clip.filter", lambda _: self.show_clip_filter())
        self.runner.register("clip.paste", self.paste_history)
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
        self.runner.register("app.pause", lambda _: self.toggle_pause())
        self.runner.register("menu.clip", lambda _: self.show_clip_menu())
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
        # F13 & F15..F20 -- slots.json'daki slotlardan yapistirma.
        self.runner.register("slot.paste", self.paste_slot)
        # Grup yonetimi (AHK clip_slot.ahk + menus.ahk buildSideSlotMenu).
        self.runner.register("slot.paste_group", self.paste_slot_of)
        self.runner.register("slots.copy", self.copy_slot)
        self.runner.register("slots.save", self.save_to_slot)
        self.runner.register("slots.rename", self.rename_slot)
        self.runner.register("slots.group_new", lambda _: self.new_slot_group())
        self.runner.register("slots.group_select", self.select_slot_group)
        self.runner.register("slots.group_delete", self.delete_slot_group)
        self.runner.register(
            "slots.edit_file",
            lambda _: subprocess.Popen(  # noqa: S603
                ["notepad.exe", str(self.slot_store.path)]  # noqa: S607
            ),
        )
        # F14 -- surukleyince ekran alani secimi, kimildatmadan birakinca menu.
        # Secim acikken tusa yeniden basmak da buraya gelir: show_snip
        # pencerenin acik oldugunu gorup bastan sectiriyor.
        self.runner.register("select.start", self.show_snip)
        # F13 menusu: alan secilir secilmez OCR baslasin (AHK'de bu iki oge
        # App.ScreenOcr.snipInteractive / snip("plain") idi).
        self.runner.register("select.ocr", lambda _: self.show_snip_auto("ocr"))
        self.runner.register("select.ocr_adv", lambda _: self.show_snip_auto("ocr_adv"))
        self.runner.register("menu.slots", lambda _: self.show_slots_menu())
        # AHK: App.ClipImageDlg.show()
        self.runner.register("clip.images", lambda _: self.show_clip_images())
        # AHK menus.ahk: menuAlwaysOnTop -- pencereyi hep ustte tut.
        self.runner.register("window.pin", self.toggle_pin)
        # AHK magnifier.ahk. Islemler ayri thread'de kosuyor: icinde uyku var.
        self.runner.register("magnifier.zoom", self.zoom)
        self.runner.register("magnifier.toggle", lambda _: self.magnifier.toggle())
        self.runner.register("magnifier.reset", lambda _: self.magnifier.reset())
        self.runner.register("magnifier.panic", lambda _: self.panic())

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
        )
        self.tray.show()

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

    def _on_clip_text(self, text: str) -> None:
        """AHK: processClipboard'in gecmise ekleyen kismi.

        Mod kontrolu AHK'deki `if (!State.Clipboard.isHistory()) return`
        ile ayni yerde: dinleyici her zaman dinler, kaydi durum belirler.
        """
        if self.clip_state.is_mem_slots():
            # AHK: mod MEM_SLOTS iken kopyalanan sey gecmise DEGIL slota
            # gider. Tek dinleyici + mod, iki dinleyiciden ongorulebilir.
            self.mem_slots.on_clip(text)
            return
        if not self.clip_state.is_history():
            return
        entry = self.clip_history.add(text, time.time())
        if entry is None:
            return  # bos, cok buyuk ya da zaten en ustteki kayit
        # Sira numarasi YOK: kopyalarken listedeki yerini degil ne
        # kopyalandigini gormek istiyorsun.
        self.tip.show_html(
            f"📋 {html.escape(_shorten(entry.preview))}",
            1200,
        )

    def _on_clip_other(self) -> None:
        """Metin disi kopya -- AHK: App.ClipImages.saveFromClipboard().

        Panoda gorsel varsa gorsel deposuna dusuyor (clipimg.dat/idx).
        Gorsel degilse (dosya listesi vb.) yalniz "gordum" deniyor.
        """
        image = QGuiApplication.clipboard().image()
        if image.isNull():
            self.tip.show_html("⛵ <span style='color:#8b949e;'>metin disi kopya</span>", 900)
            return
        slot = self.save_clip_image(image)
        if slot < 0:
            self.tip.show_html("⚠️ <b>gorsel kaydedilemedi</b>", 1200)
            return
        self.tip.show_html(
            f"\U0001f5bc️ <b>gorsel</b> {image.width()}x{image.height()}", 1200
        )

    def save_clip_image(self, image: QImage) -> int:
        """QImage -> gorsel deposu. Slot no doner, basarisizsa -1.

        QImage'i PIL'e ham RGBA baytlariyla geciriyoruz: iki kutuphane
        arasinda dosya uzerinden gitmek gereksiz bir kodlama turu olurdu.
        """
        try:
            converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
            width, height = converted.width(), converted.height()
            stride = converted.bytesPerLine()
            raw = converted.constBits().tobytes()
            if stride != width * 4:  # satir dolgusu varsa kirp
                raw = b"".join(
                    raw[row * stride : row * stride + width * 4] for row in range(height)
                )
            pil = Image.frombytes("RGBA", (width, height), raw)
            return self.image_store.save_image(pil)
        except (OSError, ValueError):
            log.exception("pano gorseli kaydedilemedi")
            return -1

    def show_clip_images(self) -> None:
        """AHK: App.ClipImageDlg.show()"""
        self.clip_images.open()

    def _on_image_copied(self, detail: str) -> None:
        if not detail:
            self.tip.show_html("⚠️ <b>panoya konulamadi</b>", 1200)
        elif detail.startswith("kaydedildi:"):
            self.tip.show_html(f"\U0001f4be <b>{html.escape(_shorten(detail, 60))}</b>", 1800)
        else:
            self.tip.show_html(f"\U0001f4cb <b>goruntu panoda</b> {detail}", 1200)

    def paste_text(self, text: str, private: bool = False) -> None:
        """AHK: ArrayFilter.sendText -- panoya yaz, kisa bekle, Ctrl+V.

        Bekleme sus payi degil: panoya yazmak asenkron bitiyor ve hedef
        uygulama Ctrl+V'yi ayni anda alirsa eski icerigi yapistiriyor.
        AHK'de de Sleep(50) vardi. Kendi yazdigimiz metin gecmise ikinci kez
        girmiyor -- ClipboardWatcher.set_text bunu biliyor.

        `private=True` sifre slotu icin: pano gecmisi (bizimki de Windows'un
        Win+V'si de) bu kopyayi HIC kaydetmez.
        """
        if not text:
            return
        self.clip_watcher.set_text(text, private=private)
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
        self.dispatcher.ui_open = True
        self.filter_window.show_items(items, "Pano gecmisi")  # sayiyi pencere ekler

    def show_clip_menu(self) -> None:
        """Pano gecmisinin hizli menusu -- AHK showQuickHistoryMenu.

        Filtreli listeden farki: arama yok, tek tiklamada yapistirir.
        Onek tusunu basili tutunca acilan sey bu.
        """
        entries = self.clip_history.entries[:12]
        if not entries:
            self.tip.show_html("\U0001f4cb <b>pano gecmisi bos</b>", 1500)
            return
        spec = tuple(
            (f"{index}  {_shorten(entry.preview, 48)}", f"clip.paste:{index}")
            for index, entry in enumerate(entries, start=1)
        )
        self.menu.show(
            (*spec, None, ("\U0001f50d Ara...", "clip.filter")),
            title=f"\U0001f4cb Pano ({len(self.clip_history)})",
        )

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

    def paste_slot(self, argument: str) -> None:
        """`F13 & F20` -> slots.json varsayilan grubunun 1. slotu. 1 tabanli.

        Slotlar her basimda diskten taze okunur: dosya kucuk ve AHK tarafi
        ya da elle duzenleme ayni dosyayi degistirmis olabilir.
        """
        try:
            index = int(argument)
        except ValueError:
            return
        self.slot_store.load()
        group = self.slot_store.slots(self.slot_store.default_group)
        if not 1 <= index <= len(group):
            return
        slot = group[index - 1]
        if not slot.content:
            self.tip.show_html(f"⚠️ <b>{html.escape(slot.name)}</b> bos", 1200)
            return
        # Sifre slotunda ipucunda da icerik GORUNMEZ (store.slot_display).
        self.tip.show_html(
            f"\U0001f4e5 <b>{html.escape(slot.name)}</b> "
            f"{html.escape(slot_display(index, slot.content, lambda t: _shorten(t, 40)))}",
            1200,
        )
        self.paste_text(slot.content, private=index == PASSWORD_SLOT)

    # ---- slot gruplari (AHK: clip_slot.ahk) ----

    @staticmethod
    def _group_slot(argument: str) -> tuple[str, int]:
        """`"is/3"` -> ("is", 3). Grup adi bos olabilir (`"/3"`)."""
        group, _, index = argument.rpartition("/")
        return group, int(index) if index.isdigit() else 0

    def paste_slot_of(self, argument: str) -> None:
        """`slot.paste_group:is/3` -- ISTENEN gruptan yapistirir."""
        group, index = self._group_slot(argument)
        self.slot_store.load()
        values = self.slot_store.slots(group)
        if not 1 <= index <= len(values) or not values[index - 1].content:
            self.tip.show_html("⚠️ <b>slot bos</b>", 1200)
            return
        self.paste_text(values[index - 1].content, private=index == PASSWORD_SLOT)

    def copy_slot(self, argument: str) -> None:
        """AHK yan grup menusu: oge tiklaninca icerik PANOYA konur."""
        group, index = self._group_slot(argument)
        self.slot_store.load()
        values = self.slot_store.slots(group)
        if not 1 <= index <= len(values) or not values[index - 1].content:
            self.tip.show_html("⚠️ <b>slot bos</b>", 1200)
            return
        secret = index == PASSWORD_SLOT
        self.clip_watcher.set_text(values[index - 1].content, private=secret)
        self.tip.show_html("📋 <b>kopyalandi</b>", 1200)

    def save_to_slot(self, argument: str) -> None:
        """AHK `promptAndSaveSlot`: panodaki metni slota yazar, adini sorar."""
        group, index = self._group_slot(argument)
        self.slot_store.load()
        content = QGuiApplication.clipboard().text()
        if not content:
            self.tip.show_html("⚠️ <b>pano bos</b>, kaydedilmedi", 1500)
            return
        values = self.slot_store.slots(group)
        current = values[index - 1].name if 1 <= index <= len(values) else ""
        name, ok = QInputDialog.getText(
            None, "Slota kaydet", f"Slot {index % 10} adi:", text=current
        )
        if not ok:
            return
        self.slot_store.set_slot_content(group, index, content)
        self.slot_store.set_slot_name(group, index, name)
        self.tip.show_html(f"💾 <b>{html.escape(name or f'Slot {index}')}</b>", 1500)

    def rename_slot(self, argument: str) -> None:
        """AHK `setName`: yalniz ADI degistirir, icerige dokunmaz."""
        group, index = self._group_slot(argument)
        self.slot_store.load()
        values = self.slot_store.slots(group)
        current = values[index - 1].name if 1 <= index <= len(values) else ""
        name, ok = QInputDialog.getText(
            None, "Slot adi", f"Slot {index % 10} yeni adi:", text=current
        )
        if ok:
            self.slot_store.set_slot_name(group, index, name)
            self._refresh_mem_slots()

    def new_slot_group(self) -> None:
        """AHK `promptNewGroup`: grup acar ve HEMEN yan grup olarak secer."""
        name, ok = QInputDialog.getText(None, "Yeni grup", "Grup adi:")
        if not ok or not name.strip():
            return
        self.slot_store.load()
        if not self.slot_store.add_group(name):
            self.tip.show_html("⚠️ <b>grup zaten var</b>", 1500)
            return
        self.slot_store.set_default_group(name.strip())
        self.tip.show_html(f"🧰 <b>{html.escape(name.strip())}</b> olusturuldu", 1500)

    def select_slot_group(self, name: str) -> None:
        """AHK `setDefaultGroup`: yan grup secimi (bos ad = yan grup yok)."""
        self.slot_store.load()
        if not self.slot_store.set_default_group(name):
            return
        self._refresh_mem_slots()
        self.tip.show_html(
            f"🧰 <b>{html.escape(name)}</b> secildi" if name else "🧰 yan grup yok",
            1200,
        )

    def delete_slot_group(self, name: str) -> None:
        """AHK: MsgBox YesNo -- silme sorulur, sessizce silinmez."""
        if not name:
            return
        answer = QMessageBox.question(
            None, "Grup sil", f"'{name}' grubunu silmek istiyor musun?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.slot_store.load()
        if self.slot_store.delete_group(name):
            self._refresh_mem_slots()
            self.tip.show_html(f"🗑️ <b>{html.escape(name)}</b> silindi", 1500)

    def _refresh_mem_slots(self) -> None:
        """Slot penceresi acikken grup/ad degisti: pencereyi tazele."""
        if not self.mem_slots.isVisible():
            return
        group = self.slot_store.slots(self.slot_store.default_group)
        self.mem_slots.load_slots([(slot.name, slot.content) for slot in group])

    # ---- F14 secim araci ----

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

    def _copy_to_history(self, text: str) -> None:
        """Panoya oyle yaz ki pano dinleyicisi NORMAL kopya sansin: metin
        gecmise de girer (clip_watcher.set_text kendi yazdigimizi gecmis
        disi tutar, burada tam tersi isteniyor)."""
        if text:
            QGuiApplication.clipboard().setText(text)

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
            if self.save_clip_image(image) < 0:
                self.tip.show_html("⚠️ <b>gorsel kaydedilemedi</b>", 1500)
                return
            self.show_clip_images()
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
            self._copy_to_history(result.text)
            return
        # OCR+: kelime kutulari panele gider, dizilim orada secilir.
        self.ocr_view.show_result(result.words, result.lines, result.ms)

    def _on_ocr_failed(self, message: str) -> None:
        self.tip.show_html(f"⚠️ <b>OCR hatasi</b><br>{html.escape(_shorten(message, 80))}", 2500)

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
        name = html.escape(_shorten(title or window_title(hwnd) or "pencere", 40))
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
            label = _shorten(title or "(baslıksiz)", 45)
            items.append((f"📍 Add {label}", f"window.pin:{hwnd}"))
        for pin in self.pins.items():
            label = _shorten(pin.title or "(baslıksiz)", 45)
            items.append((f"📌 {label}", f"window.pin:{pin.hwnd}"))
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
            return ((f"▸ Ekle ({_shorten(name, 30)})", "shorts.edit"),)
        items: list = []
        for index, shortcut in enumerate(profile.shortcuts):
            label = f"▸ {shortcut.name}"
            if shortcut.description:
                label += f" - {shortcut.description}"
            items.append((label, f"shorts.play:{profile.name}/{index}"))
        items.append(("Profili duzenle", "shorts.edit"))
        return tuple(items)

    def _shortcut_manager_item(self) -> tuple:
        """AHK `showManagerGui` karsiligi: TUM profiller F13 menusunde.

        AHK'de bu ayri bir pencereydi (profil listesi + kisayol listesi +
        ekle/sil). Pencereyi port etmek yerine ayni bilgi menuye kondu: her
        profil bir alt menu, altinda kisayollari -- ve tiklanabilir, yani
        yonetici ayni zamanda calistirici. Ekleme/silme hala JSON
        dosyasindan (son madde), cunku ayni dosyayi AHK tarafi da okuyor.
        """
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
            hint = profile.class_name or profile.title
            name = profile.name or "(adsiz)"
            label = f"{name} [{_shorten(hint, 24)}]" if hint else name
            profiles.append((label, tuple(rows)))
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

    def show_mem_slots(self) -> None:
        """AHK: singleMemorySlot.getInstance().start()

        Pano modu MEM_SLOTS'a geciyor; onceki mod kapanista geri aliniyor
        (AHK: previousState). Slotlar diskten (slots.json), gecmis listesi
        bellekten geliyor.
        """
        self._clip_mode_before = self.clip_state.mode
        self.clip_state.set_mem_slots()
        self.slot_store.load()
        group = self.slot_store.slots(self.slot_store.default_group)
        self.mem_slots.load_slots([(slot.name, slot.content) for slot in group])
        self.mem_slots.start([entry.text for entry in self.clip_history.entries])

    def save_mem_slots(self) -> None:
        """Slotlari `slots.json` icine geri yazar. Dokunmadigimiz gruplar
        oldugu gibi kalir (store.SlotStore)."""
        group = self.slot_store.slots(self.slot_store.default_group)
        for index, (name, content) in enumerate(self.mem_slots.slot_values()):
            group[index].name = name
            group[index].content = content
        self.slot_store.save()

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
        """AHK: _destroy -- slotlar diske, pano modu geri (F tuslari
        pencerenin kendi closeEvent'inde birakildi).

        Pencere hic acilmadiysa YAZMIYORUZ: elimizdeki bos varsayilan
        slotlari dosyaya basmak kullanicinin slotlarini silerdi (kapanista
        `_shutdown` gorunmeyen pencereyi de kapatiyor).
        """
        if self.mem_slots.opened:
            self.save_mem_slots()
        self.clip_state.set_mode(getattr(self, "_clip_mode_before", ClipboardMode.HISTORY))

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
            f"Pano kaydi     : {len(self.clip_history)}\n"
            f"Yutulan cift tik: {self._bounce_count} (arizali fare)\n"
            f"Log dosyasi    : {paths.LOG}\n\n"
            f"{logs.recent_text(15)}",
        )

    def copy_last_error(self) -> None:
        """AHK: App.ErrHandler.copyLastError()"""
        last = logs.errors.last
        if last is None:
            self.tip.show_html("✅ <b>hata yok</b>", 1200)
            return
        self.clip_watcher.set_text(last.line)
        self.tip.show_html("\U0001f4cb <b>son hata panoya kopyalandi</b>", 1500)

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

    def show_f13_menu(self) -> None:
        """AHK: showF13menu() -- statik tablo + o anki pencere durumu."""
        # 1. kolon tablodan gelir ve COLUMN ile biter; 2. kolonun basi o
        # anki pencereye bagli bloklar, sonu sabit kuyruk -- sira AHK
        # showF13menu ile ayni.
        spec = keymap.F13_MENU
        spec += (*self._shortcut_menu_items(), self._shortcut_manager_item())
        pins = self._pin_menu_items()
        if pins:
            spec += (None, *pins)
        spec += (None, *keymap.F13_MENU_TAIL)
        self.menu.show(spec, title=f"cascade {VERSION}", default="clip.filter")

    def _slot_items(self, group: str, action: str, prefix: str = "") -> tuple:
        """Bir grubun on slotu, menu ogesi olarak (AHK: addSlotItems).

        `action` her ogeye uygulanacak eylem kimligi: yapistirma, panoya
        kopyalama, uzerine kaydetme ya da ad degistirme. Etiket AHK ile ayni
        duzende: tus numarasi (10 -> "0"), slot adi, icerik onizlemesi.
        Sifre slotunun icerigi maskeli (store.slot_display).
        """
        items: list = []
        for index, slot in enumerate(self.slot_store.slots(group)[:10], start=1):
            text = " ".join(slot.content.split())
            shown = (
                slot_display(index, text, lambda t: _shorten(t, 40)) if text else "(bos)"
            )
            label = f"{prefix}{index % 10}  {slot.name or f'Slot {index}'}: {shown}"
            items.append((label, f"{action}:{group}/{index}"))
        return tuple(items)

    def _side_slot_menu(self) -> tuple:
        """AHK `buildSideSlotMenu`: gruplar, secim, ekle/sil, Notepad."""
        items: list = [
            ("Yeni grup ekle", "slots.group_new"),
            ("Notepad ile ac", "slots.edit_file"),
            None,
            ("No side slot", "slots.group_select:"),
        ]
        for name in self.slot_store.group_names():
            mark = "● " if name == self.slot_store.default_group else ""
            items.append(
                (
                    f"{mark}{name}",
                    (
                        ("Select this group", f"slots.group_select:{name}"),
                        None,
                        # AHK'de bu ogeler icerigi PANOYA koyuyordu
                        # (yapistirmiyordu); ayni davranis.
                        *self._slot_items(name, "slots.copy"),
                        None,
                        ("Rename slot", tuple(self._slot_items(name, "slots.rename"))),
                        ("Save clipboard to slot", tuple(self._slot_items(name, "slots.save"))),
                        None,
                        ("Delete this group", f"slots.group_delete:{name}"),
                    ),
                )
            )
        return tuple(items)

    def show_slots_menu(self) -> None:
        """F14 kisa basim -- AHK `showF14menu` + `showQuickSlotsMenu`.

        Kolon yapisi AHK ile ayni: 1. kolon eylemler ve alt menuler, 2.
        kolon varsayilan grubun slotlari, 3. kolon "yan grup" (secili grup
        varsa onun slotlari da aciliyor). Slotlar diskten TAZE okunuyor --
        dosyayi AHK tarafi ya da elle duzenleme degistirmis olabilir.
        """
        self.slot_store.load()
        side = self.slot_store.default_group
        title = "\U0001f9f0 Slotlar"
        if side:
            title += f" [{side}]"
        spec: tuple = (
            ("Unformatted paste", "send_key:^+v"),
            None,
            # TODO(AHK): macro_recorder.ahk port edilmedi.
            ("Macro recorder", "yok:macro_recorder.ahk"),
            ("Memory clip", "memslots.start", "res:30"),  # bellek cubugu
            ("Clipboard images", "clip.images", "res:109"),
            None,
            ("System", keymap.SYSTEM_MENU),
            ("Special keys", keymap.SPECIAL_KEYS_MENU),
            keymap.COLUMN,
            # TODO(AHK): clip_slot.ahk `showSlotsSearch` -- slotlarda arama.
            ("Search in slots", "yok:clip_slot.ahk showSlotsSearch"),
            None,
            *self._slot_items("", "slot.paste_group"),
            None,
            ("Save to ^ slot", self._slot_items("", "slots.save")),
            ("Rename ^ slot", self._slot_items("", "slots.rename")),
            None,
            ("Clipboard history", "clip.filter"),
            keymap.COLUMN,
            (f"Side slot{f' [{side}]' if side else ''}", self._side_slot_menu()),
        )
        if side and side in self.slot_store.groups:
            spec += (
                None,
                *self._slot_items(side, "slot.paste_group", prefix="⇥ "),
                None,
                (f"Save to ⇥{side}", self._slot_items(side, "slots.save")),
            )
        self.menu.show(spec, title=title)

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
        for action in keymap.START_ACTIONS:
            self.runner.run(action)
        count = self.clip_history.load(self.clip_store.load_entries())
        log.info("%d pano kaydi diskten okundu (%s)", count, self.clip_store.path)
        self.shorts.load()
        profile = keymap.current_profile()
        label = keymap.PROFILE_LABELS.get(profile, profile)
        log.info("makine profili: %s (%s)", profile, platform.node())
        self.tray.setToolTip(f"cascade {VERSION} - {profile}")
        # Kisa bir acilis bildirimi. "Hangi tuslar bagli" listesi DEGIL --
        # onu her acilista okumak istemiyorsun; sadece "ayaktayim" demesi
        # yeter, gerisi tepsi ve F13 menusunde.
        self.tip.show_html(
            f"✅ <b>cascade {VERSION}</b> hazir &nbsp;·&nbsp; {label}<br>"
            f"<span style='color:#8b949e;'>{count} pano kaydi &nbsp;·&nbsp; "
            f"{len(self.shorts.profiles)} uygulama profili &nbsp;·&nbsp; "
            f"F13 menu</span>",
            2200,
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
        # AHK: ExitSettings -> _save(). Yazma basarisizsa (veri kaybi
        # korumasi ya da disk hatasi) log'da izi kalir, kapanis engellenmez.
        # AHK ExitSettings: State.Window.clearAllOnTop() -- program kapaninca
        # sabitledigimiz pencereler ustte asili kalmasin.
        self.pins.clear_all()
        saved = (
            self.clip_store.save_entries(self.clip_history.entries)
            if self.save_on_exit
            else False
        )
        log.info(
            "cascade kapaniyor (%d pano kaydi, diske yazildi: %s)",
            len(self.clip_history),
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
        self.clip_watcher.stop()
        self.filter_window.close()
        self.snip.close()
        self.ocr_view.close()
        self.clip_images.close()
        self.image_store.close()
        self.mem_slots.close()
        self.pause_dialog.close()
        self.machine.reset()
        self.hook.stop()
        self.tip.hide()
        self.monitor.close()
        self.tray.hide()
