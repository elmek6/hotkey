"""cascade -- giris noktasi.

Mimari kural: hook callback'i (ayri thread) yalnizca yut/birak karari verir ve
eylemleri kuyruga atar. Butun is ana thread'de, Qt zamanlayicisinda yapilir.
Callback icinden SendInput cagrilmaz -- yeniden giris ve kilitlenme olur.

Bagli tuslar (build_hotkeys). Uc ayri kombo bicimi var, ucu de AHK'den:

    F13              kisa: acilir menu     basili tut: pano hizli menusu
    ^ (Caret)        kisa: `^` yazilir     basili tut: pano hizli menusu
    F13 & F14        onek kombosu -- onek YUTULUR
    ~LButton & F16   tilde: onek yutulmaz, sol tik yerine gider
    F19 & LButton    onek klavyede, kombo tusu FARE dugmesi
    RButton & Wheel  sag tus basiliyken tekerlek -> ses; sag tik yutulur
    F13 + fare yonu  jest: dikey = buyutec, yatay = ses (core/gesture.py)
    ~F13 & WheelUp   basili tutup tekerlek
    Pause & End      cikis        Pause & c   busy kilidini acar
    ^ & 1 .. 9       pano gecmisinin o kaydini yapistirir
    ScrollLock       kaskad menusu (demo_cascade)

Pano kopyalandigi anda gecmise dusuyor (ui/clipboard.py + core/clip_history.py).
Gorunur yuzu iki tane: kisa ipucu (tip) ve filtreli liste penceresi
(ui/array_filter.py -- arama + onizleme). Acilista diskten okunuyor,
kapanista yaziliyor (store.py -- bozuk dosya yedeklenip sifirdan baslanir).

Calistir:  baslat.vbs          cift tiklama, konsol yok, normal kullanim
           hata-ayikla.cmd    konsol acik kalir, hatalari gorursun
           VSCode F5          "cascade (ana program)"
"""

from __future__ import annotations

import contextlib
import html
import logging
import os
import queue
import subprocess
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from cascade import logs, paths
from cascade.actions import ActionRunner, beep
from cascade.core.builder import CascadeDef, KeyBuilder, PressType
from cascade.core.cascade import Beep, CascadeMachine, CloseMenu, OpenMenu, Run
from cascade.core.clip_history import ClipHistory
from cascade.core.combo import ComboTracker
from cascade.core.filter import FilterItem
from cascade.core.gesture import Direction, GestureTracker
from cascade.core.hotkey import HotkeyTable
from cascade.core.keynames import key_name, register_name, vk_from_name
from cascade.core.mouse import WM_MOUSEMOVE, mouse_key
from cascade.core.prefix import Outcome, PrefixTracker
from cascade.core.state import Busy, ClipboardMode, ClipboardState
from cascade.store import ClipStore, SlotStore
from cascade.ui.array_filter import ArrayFilter
from cascade.ui.clipboard import ClipboardWatcher
from cascade.ui.mem_slots import MemSlots
from cascade.ui.menu import PopupMenu
from cascade.ui.monitor import EventMonitor
from cascade.ui.tip import Tip
from cascade.ui.tray import Tray
from cascade.win32 import send
from cascade.win32.hook import HookThread, KeyEvent, MouseEvent
from cascade.win32.instance import SingleInstance
from cascade.win32.magnifier import Magnifier

log = logging.getLogger("cascade.main")

VERSION = "0.1.0"

KEY_F13 = 0x7C  # jest tanimlari icin; keynames tablosuyla ayni deger
VK_ESCAPE = 0x1B

# Fare onegi basiliyken bu kadar piksel oynarsa "surukleme" sayilir.
# Altinda kalan hareket titremedir; sag tik yaparken imlec bir iki piksel oynar.
DRAG_PX = 6

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


# AHK: showF14menu() icindeki subMenuKey. F14'un kendisi sende baska is
# icin duruyor, ozel tuslar F13 menusune tasindi.
SPECIAL_KEYS_MENU = (
    ("\u23ce Enter", "send_key:Enter"),
    ("\u232b Backspace", "send_key:Backspace"),
    ("\u2326 Delete", "send_key:Delete"),
    ("\u238b Esc", "send_key:Escape"),
    None,
    ("Hepsini sec + kes", "send_keys:^a ^x"),
    ("Hepsini sec + kopyala", "send_keys:^a ^c"),
    ("Bicimsiz yapistir", "send_key:^+v"),
)

# AHK: showF14menu() icindeki subMenuSet.
SYSTEM_MENU = (
    ("\U0001f440 Olay izleyici...", "app.monitor"),
    ("\u23f8\ufe0f Duraklat / Devam", "app.pause"),
    ("\U0001f513 Busy kilidini ac", "busy.free"),
    None,
    ("\U0001f4c4 Son hatalar...", "errors.show"),
    ("\U0001f4cb Son hatayi kopyala", "errors.copy"),
    None,
    ("\U0001f501 Yeniden baslat", "app.restart"),
    ("\U0001f6d1 Cikis", "app.exit"),
)

F13_MENU = (
    ("\U0001f4cb Pano gecmisi...", "clip.filter"),
    ("\U0001f5c2\ufe0f Windows pano gecmisi", "send_key:#v"),
    None,
    ("\U0001f5bc\ufe0f Ekran alintisi", "send_key:#+s"),
    ("\U0001f4f7 Pencere goruntusu", "send_key:!PrintScreen"),
    ("\U0001f524 OCR ile metin sec", "send_key:#+t"),
    ("\U0001f50d Buyutec ac / kapa", "magnifier.toggle"),
    None,
    # TODO(AHK): screen_ocr.ahk / OCR.ahk port edilmedi -- yukaridaki OCR
    # ogesi Windows'un kendi kisayolunu (#+t) cagiriyor, AHK'nin kendi
    # ekran-okuma penceresini degil.
    ("\u2328\ufe0f Ozel tuslar", SPECIAL_KEYS_MENU),
    ("\u2699\ufe0f Sistem", SYSTEM_MENU),
)
"""AHK: showF13menu() + showF14menu(). Oge basina bir kod satiri degil, tek
veri tablosu -- ileride JSON'a tasinacak yer burasi. AHK'nin OCR / buyutec /
makro kaydedici ogeleri henuz port edilmedigi icin yok; Windows'un kendi
kisayoluyla yapilabilenler (ekran alintisi, OCR) duruyor."""

# ---- OnStart / OnExit -- AHK: LoadSettings() ve ExitSettings() ----
# Simdilik ikisi de neredeyse bos. Yer tutuyorlar cunku Faz 5'te pano
# gecmisinin diskten okunmasi ve yazilmasi tam olarak buraya girecek;
# baslangicta yazmak, sonradan cagri yerlerini aramaktan ucuz.
START_ACTIONS: tuple[str, ...] = ()
EXIT_ACTIONS: tuple[str, ...] = ()


def build_cascades() -> dict[int, CascadeDef]:
    """F15..F20 -- AHK key_handler_mouse.ahk'deki handleF15..handleF20.

    Bunlar kisayol degil KASKAD: kisa/orta/uzun basim ayri eylem, ustune
    basili tutulurken baska tusa basilinca kombo. Tam olarak
    CascadeMachine'in isi, o yuzden HotkeyTable'a degil oraya giriyorlar.
    Onceki surumde bunlari elimden uydurmustum; asagisi AHK'deki tablonun
    kendisi.

    Port edilmemis eylemler `--` ile isaretli ve calismiyor; menude de oyle
    gorunurler ki neyin hazir olmadigi belli olsun:
        ClipSlot (clip_slot.ahk)     Magnifier (magnifier.ahk)
    MemSlots port edildi: ui/mem_slots.py, F19/F20 uzun basim.
    """
    defs: list[CascadeDef] = [
        # handleF15: kisa ^y (yinele), orta Escape
        KeyBuilder("F15", short=350)
        .main_key(PressType.SHORT, "send_key:^y")
        .main_key(PressType.MEDIUM, "send_key:Escape")
        .show_menu(False)
        .named("F15")
        .build(),
        # handleF16: kisa ^z (geri al), orta Enter
        KeyBuilder("F16", short=350)
        .main_key(PressType.SHORT, "send_key:^z")
        .main_key(PressType.MEDIUM, "send_key:Enter")
        .show_menu(False)
        .named("F16")
        .build(),
        # handleF17: kisa Alt+Sag, orta Delete, uzun End
        KeyBuilder("F17", short=350, long=800)
        .main_key(PressType.SHORT, "send_key:!Right")
        .main_key(PressType.MEDIUM, "send_key:Delete")
        .main_key(PressType.LONG, "send_key:End")
        # AHK: .combo("F18", "panic", Magnifier.reset + WinMinimize)
        .combo("F18", "panic (buyutec %100 + kucult)", "magnifier.panic")
        .show_menu(False)
        .named("F17")
        .build(),
        # handleF18: kisa Alt+Sol, orta Backspace, uzun Home
        KeyBuilder("F18", short=350, long=800)
        .main_key(PressType.SHORT, "send_key:!Left")
        .main_key(PressType.MEDIUM, "send_key:Backspace")
        .main_key(PressType.LONG, "send_key:Home")
        .combo("F17", "panic (buyutec %100 + kucult)", "magnifier.panic")
        .combo("LButton", "VSCode: satiri sil", "send_key:^+k")
        .combo("MButton", "ipucu", "tip:RButton + MButton: Zoom in/out")
        .show_menu(False)
        .named("F18")
        .build(),
        # handleF19: kisa ^v, orta ^a^v, uzun MemSlots
        KeyBuilder("F19", short=300, long=800)
        .main_key(PressType.SHORT, "send_key:^v")
        .main_key(PressType.MEDIUM, "send_keys:^a ^v")
        .main_key(PressType.LONG, "memslots.start")
        .combo("F20", "Hepsini sec + yapistir", "send_keys:^a ^v")
        .combo("LButton", "Tikla + yapistir", "click_then:^v")
        .combo("MButton", "3x tikla + yapistir", "click3_then:^v")
        .show_menu(False)
        .named("F19")
        .build(),
        # handleF20: kisa ^c, orta ^x, uzun MemSlots
        KeyBuilder("F20", short=300, long=800)
        .main_key(PressType.SHORT, "send_key:^c")
        .main_key(PressType.MEDIUM, "send_key:^x")
        .main_key(PressType.LONG, "memslots.start")
        .combo("F19", "Hepsini sec + kopyala", "send_keys:^a ^c")
        .combo("LButton", "Tikla + kopyala", "click_then:^c")
        .combo("MButton", "3x tikla + kopyala", "click3_then:^c")
        .show_menu(False)
        .named("F20")
        .build(),
    ]
    return {definition.key: definition for definition in defs}


# AHK: sysCommands() -- `´` tusu (SC00D / VK 0xDD). Kaskad menusu olarak
# degil acilir menu olarak veriliyor: icerigi uzun ve fare ile de secilecek.
# Port edilmemis olanlarin basinda `--` var, tiklanabilirler ama uyari verir.
SYS_COMMANDS_MENU = (
    ("1  Yeniden baslat", "app.restart"),
    ("2  Durum ve hatalar", "errors.show"),
    # TODO(AHK): app_shorts.ahk -- uygulamaya ozel kisayol profilleri
    # (Files/profiles.json). Aktif pencereye gore kisayol tablosu degistiriyordu.
    ("3  -- Profil yoneticisi", "yok:app_shorts.ahk"),
    ("4  Olay izleyici", "app.monitor"),
    ("5  Hafiza slotlari", "memslots.start"),
    # TODO(AHK): macro_recorder.ahk -- tus/fare dizisi kaydedip tekrar oynatma
    # (Files/rec1.ahk gibi uretilmis dosyalar).
    ("6  -- Makro kaydedici", "yok:macro_recorder.ahk"),
    None,
    ("7  F13 menusu", "menu.f13"),
    ("8  Pano gecmisi...", "clip.filter"),
    ("9  Duraklat / Devam", "app.pause"),
    ("0  Cikis", "app.exit"),
    None,
    # TODO(AHK): repository.ahk (Files/repository.json) -- kod parcasi deposu.
    ("r  -- Repository", "yok:repository.ahk"),
    # TODO(AHK): incognito.ahk (Files/incognito_appids.json) -- secili
    # uygulamalarda pano gecmisine hic yazmama modu.
    ("i  -- Incognito", "yok:incognito.ahk"),
    ("a  Tepsi balonu denemesi", "notify:Mesaj icerigi"),
)


MEMSLOT_SHORT_MS = 300.0
MEMSLOT_LONG_MS = 800.0


def memslots_defs() -> dict[int, CascadeDef]:
    """F1..F10 -- AHK memory_slots.ahk `_setupFKeys` + `_handleFKey`.

    Bu tanimlar SADECE pencere acik ve kutusu isaretliyken makineye
    ekleniyor (Cascade._on_memslot_fkeys); kapaninca cikiyorlar. AHK'de de
    `Hotkey("F1", ..., "On"/"Off")` boyle acilip kapaniyordu -- F1..F10
    surekli ele gecirilecek tuslar degil.

    AHK cift basimla "slota kaydet" diyordu; bizde bloke eden basim
    olcumu yok, onun yerine UZUN basim (bkz. ui/mem_slots.py).
    """
    defs = [
        KeyBuilder(f"F{index}", short=MEMSLOT_SHORT_MS, long=MEMSLOT_LONG_MS)
        .main_key(PressType.SHORT, f"memslots.paste_slot:{index}")
        .main_key(PressType.MEDIUM, f"memslots.paste_hist:{index}")
        .main_key(PressType.LONG, f"memslots.save_slot:{index}")
        .show_menu(False)
        .named(f"F{index} (slot {index})")
        .build()
        for index in range(1, 11)
    ]
    return {definition.key: definition for definition in defs}


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

    # --- F13: kisa basim menu, basili tutma pano hizli menusu ---
    # AHK handleF13: pt1 showF13menu, pt2 showQuickHistoryMenu. Kisa basim
    # tablodan, basili tutma prefix tanimindan geliyor.
    table.add("F13", "menu.f13", "kisa: menu")
    table.prefix("F13", hold_action="menu.clip", desc="basili tut: pano menusu")
    table.add(
        "F14",
        "tip_html:<b>F14</b> \U0001f5b1️ fare yan tusu",
        "ipucu goster",
    )
    # AHK key_handler_mouse.ahk: handleF13 `.combo("F14", "Magnifier", ...)`
    # ve handleF14 `.combo("F13", ...)`. Orada ikisi de toggle'di; burada
    # yon ayrildi -- hangi tusa ONCE bastigin kademeyi belirliyor.
    table.add("F13 & F14", "magnifier.zoom:+", "buyutec: yakinlastir")
    table.add("F14 & F13", "magnifier.zoom:-", "buyutec: uzaklastir")

    # --- tekerlek kombolari. AHK'de bu satirlar `~F13 & WheelUp::` diye
    # yazili; burada `~` YOK ve olmamali. AHK'de tilde gerekiyordu cunku
    # orada onek tusu tamamen bloklanir; bizde onek zaten birakilinca kendi
    # eylemini calistiriyor, ustune bir de F13'u uygulamaya gecirmenin
    # anlami yok. `~` bizde per-tus: bir satirda yazarsan o tus HIC
    # yutulmaz. ---
    table.add("F13 & WheelUp", "send_key:#NumpadAdd", "buyut")
    table.add("F13 & WheelDown", "send_key:#NumpadSub", "kucult")
    table.add("F14 & WheelUp", "send_key:Volume_Up", "ses +")
    table.add("F14 & WheelDown", "send_key:Volume_Down", "ses -")

    # --- fare dugmesi onek olarak. `~` SART: LButton'i yutarsak hicbir
    # yere tiklayamayiz. AHK handleLButton ile ayni fikir. ---
    table.add("~LButton & F16", "send_key:^v", "tikla + yapistir")
    table.add("~LButton & F19", "send_keys:^a ^v Enter", "hepsini sec + yapistir")
    table.add("~LButton & F20", "send_keys:^a ^c", "hepsini kopyala")

    # F15..F20 BURADA DEGIL: onlar kaskad (kisa/orta/uzun basim + kombo),
    # build_cascades() icinde. AHK'de de `F19::` satiri handleF19()'a
    # gidiyor ve orada bir KeyBuilder kuruluyor.

    # --- Sag tus basiliyken tekerlek -> ses. Sag tus once yutuluyor ki
    # tekerlek cevrilirken baglam menusu acilmasin; ama SADECE tekerlek
    # cevrilirse tuketiliyor. Fare surulurse "bu bir surukleme" deyip
    # gercek basim o anda enjekte ediliyor, tek basina birakilirsa normal
    # sag tik gonderiliyor. Sira main._hotkey_up / _mouse_filter icinde. ---
    table.add("RButton & WheelUp", "send_key:Volume_Up", "ses +")
    table.add("RButton & WheelDown", "send_key:Volume_Down", "ses -")

    # --- `´` (SC00D, VK 0xDD): AHK sysCommands(). Kaskad degil menu. ---
    backtick = send.vk_for_char("\u00b4") or 0xDD
    register_name(backtick, "Backtick")
    table.add("Backtick", "menu.sys", "sistem menusu")

    # --- Pause kombolari. AHK'de bunlar scriptin acil cikis yolu. ---
    table.add("Pause & End", "app.exit", "cikis")
    table.add("Pause & c", "busy.free", "busy kilidini ac")

    # `^` basiliyken rakam: pano gecmisinin o sirasindaki kaydi yapistirir.
    # 1 en yeni kopya, 2 bir onceki... AHK'deki `clip_slot` mantiginin
    # gecmis listesi uzerinde calisan hali.
    caret = send.vk_for_char("^")
    if caret is not None:
        register_name(caret, "Caret")
        # AHK cascadeCaret: kisa basim `^` yazar (yuttugumuz tusu geri
        # gondererek), basili tutma menu acar, rakamlar slot yukler.
        table.prefix("Caret", hold_action="menu.clip", desc="basili tut: pano menusu")
        for index in range(1, 10):
            table.add(
                f"Caret & {index}",
                f"clip.paste:{index}",
                "pano gecmisi 1-9" if index == 1 else "",
            )

    return table


def build_gestures() -> GestureTracker:
    """AHK: hgsRight.Register(...) -- ama sekil tanima degil, yon + kademe.

    F13 basili tutulup fare bir yone surulunce her `step_px` piksel bir
    adim uretir; adim sayisi eylemin kac kez calisacagidir (ses kac kademe
    artacak). Jest tetiklendiginde F13'un kendi isi iptal olur: ne menu
    acilir ne baska kombo beklenir.

    Dikey eksen Windows buyutecinin yakinlastirmasi, yatay eksen ses.
    Eksen bir kez kilitlendikten sonra dik yondeki hareket OKUNMAZ
    (core/gesture.py `_lock`): hafif capraz bir hareket artik yanlis
    eksene dusmez.
    """
    tracker = GestureTracker(step_px=60.0)
    tracker.register(KEY_F13, Direction.UP, "send_key:#NumpadAdd", "yakinlastir")
    tracker.register(KEY_F13, Direction.DOWN, "send_key:#NumpadSub", "uzaklastir")
    tracker.register(KEY_F13, Direction.RIGHT, "send_key:Volume_Up", "ses +")
    tracker.register(KEY_F13, Direction.LEFT, "send_key:Volume_Down", "ses -")
    return tracker


def press_button(name: str) -> None:
    """`button_down:RButton` -- dugmeyi basili birakir, birakmayi gercek
    fare yapar. Surukleme anlasildiginda cagriliyor."""
    vk = vk_from_name(name)
    if vk is not None:
        send.button_down(vk)


def _shorten(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Cascade:
    def __init__(self, app: QApplication, lock: SingleInstance | None = None) -> None:
        self.app = app
        # Tek ornek kilidi. restart() cocuk sureci baslatmadan ONCE birakmak
        # zorunda: birakmazsak cocuk kilidi bekler ve program saniyelerce
        # kapali kalir -- "reload calismiyor" boyle gorunuyordu.
        self.lock = lock
        self.tip = Tip()
        self.monitor = EventMonitor()
        self.runner = ActionRunner()

        definition = demo_cascade()
        # Taban tanimlar ayri duruyor: hafiza slotlari acikken F1..F10
        # bunlarin USTUNE ekleniyor, kapaninca tabana geri donuluyor.
        self._base_defs = {definition.key: definition, **build_cascades()}
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
        # susar (_ui_open): arama kutusuna yazarken `Caret & 1` tetiklenmesin.
        self.filter_window = ArrayFilter()
        self.filter_window.chosen.connect(self.paste_text)
        self.filter_window.closed.connect(lambda: setattr(self, "_ui_open", False))
        self.menu = PopupMenu(self.runner.run)
        self._ui_open = False

        # Hafiza slotlari (AHK memory_slots.ahk). Pencere panoyu kendisi
        # yazmaz; her sey sinyalle buraya gelir. `_ui_open` BILEREK
        # kurulmuyor: F1..F10 sistem geneli calismali, pencere onde
        # degilken de.
        # AHK: App.Magnifier. Magnify.exe bir kez acilir ve acik kalir;
        # biz yalniz zoom kademesini degistiriyoruz (win32/magnifier.py).
        self.magnifier = Magnifier()

        self.mem_slots = MemSlots()
        self._clip_mode_before = self.clip_state.mode
        self.mem_slots.paste_text.connect(self.paste_text)
        self.mem_slots.copy_text.connect(self.clip_watcher.set_text)
        self.mem_slots.grab_clip.connect(lambda: self.runner.run("send_key:^c"))
        self.mem_slots.tip.connect(lambda body: self.tip.show_html(body, 1500))
        self.mem_slots.fkeys_toggled.connect(self._on_memslot_fkeys)
        self.mem_slots.closed.connect(self._on_memslots_closed)

        # Kaskad disi kisayollar. tracker basili tuslari bilir (hangi modifier,
        # hangi onek); tablo "bu kombo bize mi ait" sorusunu cevaplar.
        self.tracker = ComboTracker()
        self.hotkeys = build_hotkeys()
        # Onek tuslari ayri bir durum makinesinde: yutma, basili tutma esigi
        # ve "kombo yapildi mi" bilgisi orada (core/prefix.py).
        self.prefixes = PrefixTracker(self.hotkeys.prefix_defs)
        # Jestler ayri bir izleyicide: fare hareketi sadece jest tanimli bir
        # onek basiliyken isleniyor, geri kalan zamanda hicbir sey yapmiyor.
        self.gestures = build_gestures()
        self.paused = False
        self._exited = False
        self._hk_swallowed: set[int] = set()  # yuttugumuz keydown'in keyup'i
        # Jest sirasinda imlecin tutulacagi nokta ve son geri bildirim ani.
        self._freeze_at: tuple[int, int] | None = None
        self._prefix_at: tuple[int, int] | None = None
        self._tip_t = 0.0
        # Yutup beklettigimiz fare onegi surukleme oldugu anlasilinca gercek
        # basimi enjekte ediliyor; bu kume onlari tutuyor ki birakma olayi
        # da uygulamaya gecsin.
        self._passed_through: set[int] = set()

        self.events: queue.Queue = queue.Queue(maxsize=4096)
        self.actions: queue.Queue = queue.Queue(maxsize=4096)
        self.seen: queue.Queue = queue.Queue(maxsize=4096)  # (olay, yutuldu mu) -> izleyici
        self.hook = HookThread(
            self.events,
            key_filter=self._key_filter,
            mouse_filter=self._mouse_filter,
            # Jest icin sart. Hareket olayi sik gelir (saniyede yuzlerce),
            # o yuzden _mouse_filter'in ilk satiri erken cikis.
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

    # ---- hook thread ----

    def _key_filter(self, event: KeyEvent) -> bool:
        """Hook thread'inde calisir. O(1): karar ver, kuyruga at, don."""
        if event.ours or self.paused or self._ui_open:
            return False

        # Acik menuyu Esc kapatsin. Menu klavye yakalamasini her zaman
        # alamiyor (tepsi uygulamasinin aktif penceresi yok), ama hook
        # her tusu goruyor -- en guvenli yer burasi.
        if event.down and event.vk == VK_ESCAPE and self.menu.open:
            with contextlib.suppress(queue.Full):
                self.actions.put_nowait(Run("menu.close"))
            return True

        swallow, actions = self.machine.feed_key(event.vk, event.down, event.t)
        if not swallow:
            swallow, extra = self._dispatch(event.vk, event.down, event.t)
            actions += extra

        for action in actions:
            with contextlib.suppress(queue.Full):
                self.actions.put_nowait(action)
        with contextlib.suppress(queue.Full):
            self.seen.put_nowait((event, swallow))
        return swallow

    def _mouse_filter(self, event: MouseEvent) -> bool:
        """Fare de ayni yoldan gecer: dugme bir tus koduna cevrilir ve ayni
        tabloya sorulur. Boylece `~LButton & F16` yazimi calisiyor -- fare
        ile klavye tek bir kombo evreninde.

        Tekerlegin birakma olayi yok: basili kalmis gorunmesin diye
        ComboTracker'a basim ve birakma ard arda veriliyor. Verilmezse
        WheelUp sonsuza kadar "basili" sayilir ve sonraki tuslara onek olur.
        """
        if event.ours or self.paused or self._ui_open:
            return False

        if event.message == WM_MOUSEMOVE:
            # Sicak yol: jest izlenmiyorsa tek bir bayrak kontrolu.
            if not self.gestures.watching:
                self._drag_check(event)
                return False
            return self._gesture_move(event)

        key = mouse_key(event.message, event.data)
        if key is None:
            return False
        vk, down = key

        # Gercek basimini gecirdigimiz onek (surukleme): birakmasi da gecsin.
        if not down and vk in self._passed_through:
            self._passed_through.discard(vk)
            self._prefix_at = None
            self.prefixes.key_up(vk, event.t)
            self.tracker.key_up(vk, event.t)
            return False

        # AHK handleF19'daki `.combo("LButton", ...)` icin: fare dugmesi
        # kaskad makinesine de gidiyor, yoksa F19 basiliyken sol tik
        # gorunmezdi.
        swallow, actions = self.machine.feed_key(vk, down, event.t)
        if not swallow:
            swallow, extra = self._dispatch(vk, down, event.t, momentary=vk > 0xFF)
            actions += extra
        for action in actions:
            with contextlib.suppress(queue.Full):
                self.actions.put_nowait(action)
        return swallow

    def _gesture_move(self, event: MouseEvent) -> bool:
        """Jest sirasindaki fare hareketi. Hook thread'i.

        Imlec DONDURULUYOR: hareket olayi yutuluyor ve imlec baslangictaki
        noktaya geri konuyor. AHK'de de jest sirasinda imlec sabitti --
        yanlislikla bir seye tiklanmasin ve jest bitince imlec yerinde
        kalsin diye. Yutuldugu icin mutlak konum akmaz; delta, dondurma
        noktasina gore olculur.
        """
        anchor = self._freeze_at
        if anchor is None:
            return False
        dx = event.x - anchor[0]
        dy = event.y - anchor[1]
        # Kendi SetCursorPos'umuzun urettigi olay: delta sifir, isleme.
        if dx or dy:
            for gesture in self.gestures.move(dx, dy):
                self.prefixes.combo_used(gesture.prefix)
                for _ in range(gesture.steps):
                    with contextlib.suppress(queue.Full):
                        self.actions.put_nowait(
                            Run(gesture.action, key=gesture.prefix, desc=gesture.desc)
                        )
            self._gesture_tip(event.t)
        # Yutmak cogu farede imleci zaten dondurur; surucusu kendi konumunu
        # yazanlar icin ikinci kemer. Cagri hook thread'inde ama SendInput
        # degil, yeniden girisli degil.
        send.set_cursor_pos(*anchor)
        return True

    def _gesture_tip(self, t: float) -> None:
        """Yon ve mesafe geri bildirimi. AHK jest sirasinda bunu yaziyordu.

        Kisilmis: hareket olayi saniyede yuzlerce geliyor, ipucunu o hizda
        yeniden cizmek gereksiz. 60 ms'de bir yeter.
        """
        if (t - self._tip_t) < 0.06:
            return
        self._tip_t = t
        for prefix in self.gestures.active:
            status = self.gestures.status(prefix)
            if status is None:
                continue
            with contextlib.suppress(queue.Full):
                self.actions.put_nowait(Run(f"tip:{status.text}", key=prefix))

    def _drag_check(self, event: MouseEvent) -> None:
        """Yutup beklettigimiz bir fare onegi varken fare suruldu mu?

        Sag tus icin: basimi yutuyoruz ki tekerlek cevrilince baglam menusu
        acilmasin. Ama kullanici sag tusu basili tutup fareyi suruyorsa bu
        bir SURUKLEME -- beklemeyi burada bitirip gercek basimi enjekte
        ediyoruz, o andan sonra her sey uygulamaya geciyor. Istenen sira
        buydu: tuketme YALNIZCA tekerlek cevrildiginde.
        """
        origin = self._prefix_at
        if origin is not None and max(abs(event.x - origin[0]), abs(event.y - origin[1])) < DRAG_PX:
            return  # titreme: sag tik yaparken imlec bir iki piksel oynar
        for vk in self.prefixes.held:
            if vk not in send.MOUSE_VK_NAMES or vk in self._passed_through:
                continue
            if vk not in self._hk_swallowed:
                # Yutmadigimiz onek (`~LButton`) zaten uygulamaya gitti;
                # bir de biz basim enjekte edersek CIFT basim olur ve
                # Paint'te cizgi cekmek gibi surukleme isleri bozulur.
                # Sol tus hicbir kosulda tuketilmez.
                continue
            self._passed_through.add(vk)
            self._hk_swallowed.discard(vk)
            self.prefixes.combo_used(vk)  # birakilinca tap eylemi calismasin
            with contextlib.suppress(queue.Full):
                self.actions.put_nowait(Run(f"button_down:{key_name(vk)}", key=vk))

    def _dispatch(
        self, vk: int, down: bool, t: float, momentary: bool = False
    ) -> tuple[bool, list]:
        """Klavye ve farenin ortak yolu: kombo takibi + kisayol tablosu."""
        if down:
            chord = self.tracker.key_down(vk, t)
            if momentary:  # tekerlek: basili kalmaz
                self.tracker.key_up(vk, t)
        else:
            self.tracker.key_up(vk, t)
            chord = None
        return self._hotkey_key(vk, down, t, chord)

    def _hotkey_key(self, vk: int, down: bool, t: float, chord) -> tuple[bool, list]:
        """Kaskadin ilgilenmedigi tus: kisayol tablosuna bakilir.

        Onek tusu (F13, `^`) basildigi anda karar verilmek zorunda -- LL hook
        keydown'da cevap veriyor, AHK gibi bekleyemez. Yutup yutmamayi
        PrefixTracker soyler (`~` ile tanimlananlar yutulmaz); ne olacagi
        birakildiginda ya da esik gecince belli olur.
        """
        if not down:
            return self._hotkey_up(vk, t)

        if chord is None:  # modifier'in kendisi: dokunma
            return False, []

        # Onek tusu, uzerinde baska onek yokken: kararı ertele.
        if self.prefixes.is_prefix(vk) and chord.prefix is None:
            swallow = self.prefixes.key_down(vk, t)
            if swallow:
                self._hk_swallowed.add(vk)
            # Jest baslar: sayaclar sifirlanir ve imlecin donacagi nokta
            # not edilir. Hareket olaylari bundan sonra yutulur.
            if self.gestures.has(vk):
                self.gestures.start(vk)
                self._freeze_at = send.cursor_pos()
            elif vk in send.MOUSE_VK_NAMES:
                # Fare onegi: surukleme mi tekerlek mi, imlecin nereden
                # kalktigina bakarak anlayacagiz.
                self._prefix_at = send.cursor_pos()
            return swallow, []

        binding = self.hotkeys.match(vk, chord.modifiers, chord.prefix)
        if binding is None:
            return False, []
        if chord.prefix is not None:
            self.prefixes.combo_used(chord.prefix)
        if vk <= 0xFF:  # tekerlegin birakma olayi yok, listede birakmayalim
            self._hk_swallowed.add(vk)
        if chord.repeat:  # basili tutmada eylem tekrarlanmaz, yutma surer
            return True, []
        return True, [Run(binding.action, key=vk, desc=binding.desc)]

    def _hotkey_up(self, vk: int, t: float) -> tuple[bool, list]:
        was_ours = vk in self._hk_swallowed
        self._hk_swallowed.discard(vk)
        if not self.prefixes.is_prefix(vk):
            return was_ours, []

        # Jest yapildiysa tusun isi bitti: ne menu, ne tap eylemi, ne de
        # tusun geri gonderilmesi. Istenen davranis buydu.
        if self.gestures.stop(vk):
            self.prefixes.key_up(vk, t)
            if not self.gestures.watching:
                self._freeze_at = None
            return was_ours, []

        if self.prefixes.key_up(vk, t) is Outcome.NOTHING:
            return was_ours, []  # kombo yapildi ya da basili tutma calisti

        if not self.gestures.watching:
            self._freeze_at = None
        if vk in send.MOUSE_VK_NAMES:
            self._prefix_at = None

        binding = self.hotkeys.match(vk)  # onegin kendi tanimi var mi
        if binding is not None:
            return was_ours, [Run(binding.action, key=vk, desc=binding.desc)]
        if was_ours:
            # Hicbir sey olmadi: yuttugumuz tusu geri ver, `^` yazilabilsin.
            return was_ours, [Run(f"send_key:{key_name(vk)}", key=vk)]
        return was_ours, []

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

        TODO(AHK): gorsel pano (clip_image_store.ahk) port edilmedi;
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
        self._ui_open = True
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

    def _on_memslot_fkeys(self, enabled: bool) -> None:
        """Slot penceresindeki kutu: F1..F10 kaskadlarini takar/soker.

        AHK: _setupFKeys(true/false). Tanimlari tabanla birlestirip
        makineye vermek yeterli -- makine kendi durumunu sifirliyor.
        """
        definitions = dict(self._base_defs)
        if enabled:
            definitions.update(memslots_defs())
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

    def free_busy(self) -> None:
        """AHK: `Pause & c:: State.Busy.setFree()`.

        Bir kaskad yarida kalirsa Busy kilitli kalir ve hicbir kisayol
        calismaz. Bu, o durumdan cikis yolu -- AHK'de de acil frendi.
        """
        self.machine.reset()
        self.prefixes.reset()
        self.tracker.reset()
        self.gestures.reset()
        self._freeze_at = None
        self._prefix_at = None
        self._passed_through.clear()
        self._hk_swallowed.clear()
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
            self.tip.show_html("\u2705 <b>hata yok</b>", 1200)
            return
        self.clip_watcher.set_text(last.line)
        self.tip.show_html("\U0001f4cb <b>son hata panoya kopyalandi</b>", 1500)

    def show_sys_menu(self) -> None:
        """AHK: sysCommands() -- `´` tusunun menusu."""
        self.menu.show(SYS_COMMANDS_MENU, title=f"\u2699\ufe0f cascade {VERSION}")

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
        now = time.perf_counter()
        for action in self.machine.tick(now):
            self._apply(action)
        # Onek tuslarinin basili-tutma esigi. Hook thread'inde yapilamaz:
        # tus BASILI dururken hicbir olay gelmiyor, esigi yoklayan bir
        # zamanlayici gerekiyor. AHK bunu bloke eden dongude yapiyordu.
        for vk, action in self.prefixes.tick(now):
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
        self.prefixes.reset()
        self._hk_swallowed.clear()
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
        """AHK: LoadSettings() -- OnExit'in karsiti.

        Faz 5'te pano gecmisinin diskten okunmasi buraya girecek.
        """
        log.info("cascade %s basladi", VERSION)
        for action in START_ACTIONS:
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

        Faz 5'te pano gecmisinin diske yazilmasi buraya girecek. Iki yerden
        cagriliyor (kendi quit'imiz ve Qt'nin aboutToQuit'i, yani oturum
        kapanmasi), o yuzden bir kez calismasi garantiye alinmis.
        """
        if self._exited:
            return
        self._exited = True
        for action in EXIT_ACTIONS:
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

        Cocuk surec AYRIK baslatilir. Boyle olmazsa VSCode/konsoldan
        baslatildiginda ebeveynle ayni surec grubunda kalir ve ebeveyn
        olunce o da olur -- "yeniden baslat deyince cikti" bunun yuzunden.
        Yeni ornek --restart ile aciliyor: tek ornek kilidini eskisi
        birakana kadar bekliyor.
        """
        # SIRA ONEMLI: once kendi kapanisimiz (pano diske yazilir, hook
        # sokulur), SONRA kilidi BIRAK, en son cocuk surec. Ters sirada
        # cocuk dosyayi biz yazmadan okuyor ve o oturumun kopyalari
        # kayboluyordu; kilidi birakmadan baslatinca da cocuk mutex'i
        # bekliyor ve yeniden baslatma ~10 saniye suruyordu.
        self.on_exit()
        if self.lock is not None:
            self.lock.release()

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
        self.mem_slots.close()
        self.machine.reset()
        self.hook.stop()
        self.tip.hide()
        self.monitor.close()
        self.tray.hide()


def main() -> int:
    logs.setup()
    logs.install_qt_handler()
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

    Cascade(app, lock)
    try:
        return app.exec()
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
