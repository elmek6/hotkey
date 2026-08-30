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
import html
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from cascade import keymap, logs, paths
from cascade.actions import ActionRunner, beep
from cascade.core.cascade import Beep, CascadeMachine, CloseMenu, OpenMenu, Run
from cascade.core.clip_history import ClipHistory
from cascade.core.filter import FilterItem
from cascade.core.keynames import key_name, vk_from_name
from cascade.core.state import Busy, ClipboardMode, ClipboardState
from cascade.dispatch import Dispatcher
from cascade.store import ClipStore, SlotStore
from cascade.ui.array_filter import ArrayFilter
from cascade.ui.clipboard import ClipboardWatcher
from cascade.ui.mem_slots import MemSlots
from cascade.ui.menu import PopupMenu
from cascade.ui.monitor import EventMonitor
from cascade.ui.ocr_view import OcrView
from cascade.ui.snip import SnipOverlay
from cascade.ui.tip import Tip
from cascade.ui.tray import Tray
from cascade.win32 import ocr, send
from cascade.win32.hook import HookThread
from cascade.win32.instance import SingleInstance
from cascade.win32.magnifier import Magnifier

log = logging.getLogger("cascade.app")

VERSION = "0.1.0"

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

    finished = Signal(str, str)  # mod ("ocr" / "ocr_adv"), metin
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

        definition = keymap.demo_cascade()
        # Taban tanimlar ayri duruyor: hafiza slotlari acikken F1..F10
        # bunlarin USTUNE ekleniyor, kapaninca tabana geri donuluyor.
        self._base_defs = {definition.key: definition, **keymap.build_cascades()}
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
        self.menu = PopupMenu(self.runner.run)

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
        self.mem_slots.closed.connect(self._on_memslots_closed)

        # F14 secim araci (ui/snip.py) + OCR koprusu. Secim acikken
        # kisayollar susar (ui_open) -- fare secime, Esc iptale gitsin.
        self.snip = SnipOverlay()
        self.snip.done.connect(self._on_snip_done)
        self.snip.closed.connect(lambda: setattr(self.dispatcher, "ui_open", False))
        self.ocr_view = OcrView()
        self.ocr_view.copy_text.connect(self._copy_to_history)
        self._ocr_bridge = _OcrBridge()
        self._ocr_bridge.finished.connect(self._on_ocr_done)
        self._ocr_bridge.failed.connect(self._on_ocr_failed)

        self.paused = False
        self._exited = False

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
        self.runner.register("memslots.paste", lambda _: self.mem_slots.smart_paste())
        # F13 & F15..F20 -- slots.json'daki slotlardan yapistirma.
        self.runner.register("slot.paste", self.paste_slot)
        # F14 -- ekran alani secimi (kopyala / sakla / OCR).
        self.runner.register("select.start", lambda _: self.show_snip())
        # AHK magnifier.ahk. Islemler ayri thread'de kosuyor: icinde uyku var.
        self.runner.register("magnifier.zoom", self.zoom)
        self.runner.register("magnifier.toggle", lambda _: self.magnifier.toggle())
        self.runner.register("magnifier.reset", lambda _: self.magnifier.reset())
        self.runner.register("magnifier.panic", lambda _: self.panic())

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
        """Metin olmayan icerik -- simdilik yalniz 'gordum'.

        TODO(AHK): gorsel pano (clip_image_store.ahk) bilerek port edilmedi;
        ayrintili not ui/clipboard.py icinde.
        """
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
        self.tip.show_html(
            f"\U0001f4e5 <b>{html.escape(slot.name)}</b> "
            f"{html.escape(_shorten(slot.content, 40))}",
            1200,
        )
        self.paste_text(slot.content)

    # ---- F14 secim araci ----

    def show_snip(self) -> None:
        """F14: ekran donar, alan secilir, secim ustunde islem cubugu acilir."""
        self.dispatcher.ui_open = True
        self.snip.start()

    def _copy_to_history(self, text: str) -> None:
        """Panoya oyle yaz ki pano dinleyicisi NORMAL kopya sansin: metin
        gecmise de girer (clip_watcher.set_text kendi yazdigimizi gecmis
        disi tutar, burada tam tersi isteniyor)."""
        if text:
            QGuiApplication.clipboard().setText(text)

    def _on_snip_done(self, action: str, image: QImage) -> None:
        """Secim bitti: eylem kimligi ui/snip.py ACTIONS tablosundan gelir."""
        if action == "copy":
            QGuiApplication.clipboard().setImage(image)
            self.tip.show_html(
                f"\U0001f4cb <b>goruntu panoda</b> {image.width()}x{image.height()}", 1500
            )
        elif action == "save":
            paths.CAPTURES.mkdir(parents=True, exist_ok=True)
            target = paths.CAPTURES / f"alinti-{datetime.now():%Y%m%d-%H%M%S}.png"
            if image.save(str(target), "PNG"):
                self.tip.show_html(f"\U0001f4be <b>{target.name}</b>", 1800)
            else:
                self.tip.show_html("⚠️ <b>goruntu kaydedilemedi</b>", 1800)
        elif action in ("ocr", "ocr_adv"):
            if not ocr.available():
                self.tip.show_html("⚠️ <b>OCR paketi kurulu degil</b> (winrt)", 2000)
                return
            self.tip.show_html("\U0001f524 <b>okunuyor...</b>", 800)
            threading.Thread(
                target=self._ocr_work, args=(action, image), name="cascade-ocr", daemon=True
            ).start()

    def _ocr_work(self, mode: str, image: QImage) -> None:
        """OCR thread'i: motoru bekler, sonucu sinyalle ana thread'e verir."""
        try:
            self._ocr_bridge.finished.emit(mode, ocr.recognize(image))
        except Exception as exc:  # motor yok / dil paketi eksik
            log.exception("OCR basarisiz")
            self._ocr_bridge.failed.emit(str(exc))

    def _on_ocr_done(self, mode: str, text: str) -> None:
        if not text:
            self.tip.show_html("\U0001f524 <b>metin bulunamadi</b>", 1500)
            return
        if mode == "ocr":
            # Basit OCR: metin dogrudan panoya (ve oradan gecmise) gider.
            self._copy_to_history(text)
            return
        self.ocr_view.show_text(text)  # OCR+: pencerede goster, oradan kopyala

    def _on_ocr_failed(self, message: str) -> None:
        self.tip.show_html(f"⚠️ <b>OCR hatasi</b><br>{html.escape(_shorten(message, 80))}", 2500)

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

    def show_sys_menu(self) -> None:
        """AHK: sysCommands() -- `´` tusunun menusu."""
        self.menu.show(keymap.SYS_COMMANDS_MENU, title=f"⚙️ cascade {VERSION}")

    def show_f13_menu(self) -> None:
        """AHK: showF13menu()"""
        self.menu.show(keymap.F13_MENU, title=f"cascade {VERSION}", default="clip.filter")

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
        """AHK: Suspend. Hook yerinde kalir, sadece kararlar devre disi.

        Hook'u sokup takmak yerine bayrak kullaniliyor: yeniden kurulan hook
        zincirin sonuna duser, baska programlarla sira garantisi kaybolur.
        """
        self.paused = not self.paused
        self.dispatcher.paused = self.paused
        self.dispatcher.reset()
        self.tray.set_paused(self.paused)
        if self.paused:
            self.tip.show_html(
                "⏸️ <b>duraklatildi</b><br>"
                "<span style='color:#8b949e;'>tuslar dokunulmadan geciyor</span>",
                1600,
            )
        else:
            self.tip.show_html("▶️ <b>devam</b>", 1200)

    def on_start(self) -> None:
        """AHK: LoadSettings() -- OnExit'in karsiti."""
        log.info("cascade %s basladi", VERSION)
        for action in keymap.START_ACTIONS:
            self.runner.run(action)
        count = self.clip_history.load(self.clip_store.load_entries())
        log.info("%d pano kaydi diskten okundu (%s)", count, self.clip_store.path)
        # Kisa bir acilis bildirimi. "Hangi tuslar bagli" listesi DEGIL --
        # onu her acilista okumak istemiyorsun; sadece "ayaktayim" demesi
        # yeter, gerisi tepsi ve F13 menusunde.
        self.tip.show_html(
            f"✅ <b>cascade {VERSION}</b> hazir<br>"
            f"<span style='color:#8b949e;'>{count} pano kaydi &nbsp;·&nbsp; "
            f"F13 menu</span>",
            1800,
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
        saved = self.clip_store.save_entries(self.clip_history.entries)
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
        self.mem_slots.close()
        self.machine.reset()
        self.hook.stop()
        self.tip.hide()
        self.monitor.close()
        self.tray.hide()
