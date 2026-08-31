"""Tus haritasi -- SCRIPT katmani. AHK'deki `AutoHotkey.ahk`'nin karsiligi.

Bu dosyada MANTIK YOK: hangi tusun ne yapacagi, menulerde ne yazacagi ve
jestlerin hangi yone bagli oldugu burada VERI olarak durur. Tuslarin nasil
calistigi (yutma, onek, basim suresi) cascade/dispatch.py'de; eylem
kimliklerinin gercek isi cascade/app.py + cascade/actions.py'de.

Yeni bir tus baglamak istediginde SADECE bu dosyaya dokunman gerekir.
Ileride JSON'a tasinacak yer de burasi (builder.def_from_dict hazir).

Bagli tuslar (build_hotkeys). Uc ayri kombo bicimi var, ucu de AHK'den:

    F13              kisa: acilir menu     basili tut: pano hizli menusu
    F14              kisa: slot menusu     surukle: ekran alani sec
    ^ (Caret)        kisa: `^` yazilir     basili tut: base grup slotlari
    Tab              kisa: Tab yazilir     basili tut: yan grup slotlari
    CapsLock         kisa: kilit cevrilir  basili tut: pano menusu (AHK cascadeCaps)
    Tab & 1 .. 0     SECILI yan gruptan yapistirir (0 = slot 10)
    CapsLock & 1..9  pano gecmisinden yapistirir
    Ctrl+<           VSCode satir sil (Ctrl+Shift+K)
    Win+WASD/Q/E/Y   klavyeyle fare: 10px oynat, sol/sag tik, Enter
    F13 & F14        onek kombosu -- onek YUTULUR
    ~LButton & F16   tilde: onek yutulmaz, sol tik yerine gider
    F19 & LButton    onek klavyede, kombo tusu FARE dugmesi
    RButton & Wheel  sag tus basiliyken tekerlek -> ses; sag tik yutulur
    F13 + fare yonu  jest: dikey = buyutec, yatay = ses (core/hot_vectors.py)
    ~F13 & WheelUp   basili tutup tekerlek
    Pause            basili tut: duraklatma penceresi (AHK DialogPauseGui)
    Pause & Home     yeniden baslat (AHK: reloadScript)
    Pause & End      cikis        Pause & c   busy kilidini acar
    ^ & 1 .. 0       base grubun (defaultGroup=='') slotunu yapistirir
    ScrollLock       kisa: Turkce ac/kapa   basili tut: dizilim 1<->2
    ~MButton/~Insert memslots penceresi acikken akilli yapistirma
"""

from __future__ import annotations

import platform

from cascade.core import turkish
from cascade.core.builder import CascadeDef, KeyBuilder, PressType
from cascade.core.hot_vectors import LOCK_AXIS, LOCK_MODES, Direction, HotVectors
from cascade.core.hotkey import HotkeyTable
from cascade.core.keynames import register_name
from cascade.settings import Category, setting
from cascade.win32 import send
from cascade.win32.menu import COLUMN


def _range(low: int, high: int):
    """AHK Setting.validate ile ayni is: araligin disi ret gerekcesi doner."""
    def check(value) -> str:
        return "" if low <= value <= high else f"{low}-{high} arasi olmali"

    return check


# AHK hot_vectors.ahk: prefDirThreshold / prefStepSize. Ivme carpani
# (prefAcceleration) PORT EDILMEDI -- AHK 3.0 da kaldirmisti, duz piksel
# sayimi kaliyor.
VECTOR_LOCK_PX = setting(
    "hotVector.dirThreshold",
    "Yon kilidi esigi",
    default=8,
    category=Category.MOUSE,
    tags="fare hassasiyet vektor jest",
    desc="Yonun kilitlenmesi (ve jestin baslamasi) icin gereken piksel",
    validate=_range(1, 100),
)
VECTOR_LOCK_MODE = setting(
    "hotVector.lockMode",
    "Jest kilidi",
    default=LOCK_AXIS,
    choices=LOCK_MODES,
    category=Category.MOUSE,
    tags="fare vektor jest eksen yon kilit",
    desc="eksen: iki yon de canli (yukari/asagi) - yon: ilk yon kilitlenir",
)
# Jest sirasinda imlec her olayda baslangic noktasina geri konur ve mesafe
# `olay - baslangic` diye olculur. Kapatilirsa hareket olayi yine yutulur ama
# imlec ilerlemedigi icin ardisik olaylarin farki +1/-1 diye sifirlanir ve
# yavas hareket esigi hic gecemez (docs/hot_vectors.md D-1).
VECTOR_FREEZE = setting(
    "hotVector.freezeCursor",
    "Jest sirasinda imleci dondur",
    default=True,
    category=Category.MOUSE,
    tags="fare vektor jest imlec",
    desc="Imlec jest boyunca yerinde durur; kapaliysa yavas hareket okunmaz",
)
# Titreme toleransi: tusa basarken imlec bir iki piksel oynuyor. Bu kadarlik
# hareket "surukleme" sayilmaz. Once dispatch.py'de sabitti (DRAG_PX = 6).
VECTOR_IGNORE_PX = setting(
    "hotVector.ignorePx",
    "Yoksayilan titreme",
    default=6,
    category=Category.MOUSE,
    tags="fare hassasiyet vektor jest titreme surukleme",
    desc="Bu kadar pikselin altindaki hareket titreme sayilir, surukleme baslatmaz",
    validate=_range(0, 50),
)
VECTOR_STEP_PX = setting(
    "hotVector.stepSize",
    "Adim esigi",
    default=14,
    category=Category.MOUSE,
    tags="fare hassasiyet vektor jest",
    desc="Bir tetiklenme icin gereken piksel",
    validate=_range(1, 400),
)

KEY_F13 = 0x7C  # jest tanimlari icin; keynames tablosuyla ayni deger

# ---- makine profili -- AHK: LoadSettings() icindeki A_ComputerName testi ----
# AHK bu ayrimla is bilgisayarinda ekran koruyucu engellemeyi ve Outlook'u
# simge durumunda baslatmayi aciyordu. Burada SIMDILIK yalnizca hangi
# profille acildigini bildiriyoruz; profile bagli acilis eylemleri
# eklenecekse yerleri START_ACTIONS'in yanidir.
WORK_COMPUTERS = ("LAPTOP-UTN6L5PA",)
PROFILE_LABELS = {"work": "\U0001f3e2 Work", "home": "\U0001f3e0 Home"}


def current_profile() -> str:
    """Bu makinenin profili: `work` ya da `home` (AHK ile ayni olcut)."""
    name = platform.node().strip().upper()
    return "work" if name in {item.upper() for item in WORK_COMPUTERS} else "home"


def turkish_keys() -> dict[int, str]:
    """Turkce eklentisinin ilgilendigi tuslar: VK -> tusun kucuk harfi.

    Duzene bagli oldugu icin calisma aninda soruluyor (`^` ve `<` ile ayni
    yontem). Bu makinede olmayan tuslar (AHK dosyasi Alman duzeninde
    yazilmisti, `ä` gibi) sessizce listeye girmez.
    """
    keys: dict[int, str] = {}
    for char in {*turkish.LONG_PRESS, *turkish.DIRECT}:
        vk = send.vk_for_char(char)
        if vk is not None:
            keys[vk] = char
    return keys


# AHK: showF14menu() icindeki subMenuKey. F14'un kendisi sende baska is
# icin duruyor, ozel tuslar F13 menusune tasindi.
SPECIAL_KEYS_MENU = (
    ("⏎ Enter", "send_key:Enter"),
    ("⌫ Backspace", "send_key:Backspace"),
    ("⌦ Delete", "send_key:Delete"),
    ("⎋ Esc", "send_key:Escape"),
    None,
    ("Hepsini sec + kes", "send_keys:^a ^x"),
    ("Hepsini sec + kopyala", "send_keys:^a ^c"),
    ("Bicimsiz yapistir", "send_key:^+v"),
)

# AHK: showF14menu() icindeki subMenuSet.
SYSTEM_MENU = (
    ("\U0001f440 Key history loop", "app.monitor"),
    ("⚙️ Ayarlar...", "app.settings"),
    ("⏸️ Duraklat / Devam", "app.pause"),
    ("\U0001f513 Busy kilidini ac", "busy.free"),
    None,
    ("\U0001f4c4 Son hatalar...", "errors.show"),
    ("\U0001f4cb Son hatayi kopyala", "errors.copy"),
    None,
    ("\U0001f501 Yeniden baslat", "app.restart"),
    ("\U0001f6d1 Cikis", "app.exit"),
)

#: Menu ikonlari AHK ile AYNI numaralar (menus.ahk `menuIcon`): sayi
#: DLL icindeki 1 tabanli ikon sirasi. Emoji yerine gercek ikon: klasik
#: Win32 menusu metni GDI ile ciziyor ve renkli emoji tablosunu
#: kullanmiyor, o yuzden emoji hep tek renk (siyah/beyaz) cikiyor.
F13_MENU = (
    # ---- 1. KOLON: pano, ekran goruntusu, OCR (AHK showF13menu) ----
    ("Clipboard history win", "send_key:#v", "res:243"),  # panodan pencereye
    None,
    ("Select screenshot", "send_key:#+s", "shell:260"),  # makas
    ("Window screenshot", "send_key:!PrintScreen", "shell:196"),  # fotograf makinesi
    ("Select text with OCR", "send_key:#+t"),
    # AHK: App.ScreenOcr.snipInteractive() / snip("plain"). Bizde secim
    # araci aciliyor ve alan secilir secilmez o OCR kipi calisiyor.
    ("OCR Gelismis", "select.ocr_adv"),
    ("OCR Basit", "select.ocr"),
    None,
    ("Clipboard images", "clip.images", "res:109"),  # gorsel
    ("Magnifier", "magnifier.toggle"),
    # ---- 2. KOLON: aktif pencere profili, araclar, hep ustte ----
    # Kolon ayracini COLUMN ciziyor; bu yuzden 1. kolonun sonunda ayrica
    # yatay ayrac YOK -- AHK'de de oyle, kolon dibinde boslukta asili bir
    # cizgi kalmasin diye. Profil ve "hep ustte" bloklarini app.py
    # ekliyor (o anki pencereye bagli).
    COLUMN,
)
"""AHK: showF13menu()'nun 1. KOLONU. Oge basina bir kod satiri degil, tek
veri tablosu. Isimlendirme, sira ve ikon numaralari AHK ile ayni; port
edilmemis ogeler (Repository GUI, Incognito) `´` menusunde `--` isaretli."""

F13_MENU_TAIL: tuple = ()
"""2. kolonun SONU. Arasina app.py o anki pencereye bagli bloklari koyar:
uygulama profili + kisayollari (AHK menuAppProfile) ve hep-ustte listesi
(AHK menuAlwaysOnTop). Special keys ve System AHK'de de yalniz F14'te.

"""

# AHK: sysCommands() -- `´` tusu (SC00D / VK 0xDD). Kaskad menusu olarak
# degil acilir menu olarak veriliyor: icerigi uzun ve fare ile de secilecek.
# Port edilmemis olanlarin basinda `--` var, tiklanabilirler ama uyari verir.
SYS_COMMANDS_MENU = (
    ("1: Reload script", "app.restart"),
    ("2: Show stats", "errors.show"),
    # app_shorts.ahk portu: profiller Files/profiles.json'dan okunuyor,
    # duzenleme dosyanin kendisinden (AHK'nin yonetici GUI'si port edilmedi).
    ("3: Profile manager", "shorts.edit"),
    ("4: Key history", "app.monitor"),
    ("5: Memory slots", "memslots.start"),
    # TODO(AHK): macro_recorder.ahk -- tus/fare dizisi kaydedip tekrar oynatma.
    ("6: -- Macro recorder", "yok:macro_recorder.ahk"),
    ("7: F13 menu", "menu.f13"),
    ("8: F14 menu", "menu.slots"),
    ("9: Pause script", "app.pause"),
    ("0: Exit script", "app.exit"),
    # TODO(AHK): repository.ahk (Files/repository.json) -- kod parcasi deposu.
    ("r. Repository GUI", "yok:repository.ahk"),
    # TODO(AHK): incognito.ahk (Files/incognito_appids.json).
    ("i: Incognito (as)", "yok:incognito.ahk"),
    ("a: TrayTip test", "notify:Mesaj icerigi"),
    None,
    # AHK'de olmayan, bize ozgu olanlar ayracin altinda.
    ("Pano gecmisi...", "clip.filter"),
    ("Pano gorselleri...", "clip.images"),
)

# ---- OnStart / OnExit -- AHK: LoadSettings() ve ExitSettings() ----
# Pano gecmisinin diskten okunmasi/yazilmasi app.py on_start/on_exit icinde;
# buraya yalniz "acilista/kapanista su eylemler de calissin" turu script
# istekleri girer.
START_ACTIONS: tuple[str, ...] = ()
EXIT_ACTIONS: tuple[str, ...] = ()


def build_cascades() -> dict[int, CascadeDef]:
    """F15..F20 -- AHK key_handler_mouse.ahk'deki handleF15..handleF20.

    Bunlar kisayol degil KASKAD: kisa/orta/uzun basim ayri eylem, ustune
    basili tutulurken baska tusa basilinca kombo. Tam olarak
    CascadeMachine'in isi, o yuzden HotkeyTable'a degil oraya giriyorlar.

    Port edilmemis eylemler `--` ile isaretli ve calismiyor; menude de oyle
    gorunurler ki neyin hazir olmadigi belli olsun.
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


MEMSLOT_SHORT_MS = 300.0
MEMSLOT_LONG_MS = 800.0


def memslots_defs() -> dict[int, CascadeDef]:
    """F1..F10 -- AHK memory_slots.ahk `_setupFKeys` + `_handleFKey`.

    Bu tanimlar SADECE pencere acik ve kutusu isaretliyken makineye
    ekleniyor (app.Cascade._on_memslot_fkeys); kapaninca cikiyorlar. AHK'de
    de `Hotkey("F1", ..., "On"/"Off")` boyle acilip kapaniyordu -- F1..F10
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
    # AHK handleF13: pt1 menu, pt2 pano menusu, pt4 (CIFT basim) gecmiste
    # arama -- `EM.enableDoubleClick()`. Cift basim tanimli oldugu icin kisa
    # basim eylemi bir sure BEKLETILIR (bkz. core/prefix.py).
    table.prefix(
        "F13",
        hold_action="menu.clip",
        double_action="clip.filter",
        desc="basili tut: pano menusu / cift: gecmiste ara",
    )
    # F14 iki islevli: SURUKLERSEN ekran alani secimi baslar (ui/snip.py),
    # kimildatmadan birakirsan slot menusu acilir. AHK handleF14'te kisa
    # basim showF14menu (slotlar) idi; secim oraya sonradan eklendi ve
    # tusun eski isini yemesin diye surukleme ile ayrildi.
    table.add("F14", "menu.slots", "kisa: slot menusu")
    # AHK handleF14 pt4: App.ClipSlot.showSlotsSearch().
    table.prefix("F14", double_action="slots.search", desc="cift: slotlarda ara")
    # Eylemin argumani secimi yapacak TUS: F14 basili kaldigi surece
    # dikdortgen buyur, birakilinca secim biter (ui/snip.py). Argumansiz
    # birakilirsa secim sol fare tusuna kalirdi -- F14 ile secmek isterken
    # bir de fareye basmak gerekiyordu.
    table.prefix(
        "F14", drag_action="select.start:F14@{x},{y}", desc="surukle: ekran alani sec"
    )

    # --- F13 & F15..F20: slots.json'daki slotlardan yapistir. AHK
    # handleF14'un slot kombolari (F14 secim tusu olunca F13'e tasindi).
    # Siralama AHK ile ayni ters duzende: en yakin tus F20 = Slot 1.
    for offset, fkey in enumerate(("F20", "F19", "F18", "F17", "F16", "F15")):
        table.add(f"F13 & {fkey}", f"slot.paste:{offset + 1}", f"slot {offset + 1}")
    # AHK key_handler_mouse.ahk: iki yonde de TOGGLE idi -- buyutulmusse
    # %100'e doner, degilse %200'e cikar (x2 / :2). Yon ayirmayi denedik ama
    # hangi tusa once basildigini ayirt etmek kullanicida "hep yakinlastiriyor"
    # hissi verdi; AHK'deki tek davranisa geri donuldu.
    table.add("F13 & F14", "magnifier.toggle", "buyutec: x2 / :2")
    table.add("F14 & F13", "magnifier.toggle", "buyutec: x2 / :2")

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
    # AHK handleLButton: F15 -> base grubun 10. slotu + Enter.
    table.add("~LButton & F15", "slot.paste_enter:/10", "slot 10 + Enter")
    table.add("~LButton & F19", "send_keys:^a ^v Enter", "hepsini sec + yapistir")
    table.add("~LButton & F20", "send_keys:^a ^c", "hepsini kopyala")

    # F15..F20 BURADA DEGIL: onlar kaskad (kisa/orta/uzun basim + kombo),
    # build_cascades() icinde. AHK'de de `F19::` satiri handleF19()'a
    # gidiyor ve orada bir KeyBuilder kuruluyor.

    # --- Sag tus basiliyken tekerlek -> ses. Sag tus once yutuluyor ki
    # tekerlek cevrilirken baglam menusu acilmasin; ama SADECE tekerlek
    # cevrilirse tuketiliyor. Fare surulurse "bu bir surukleme" deyip
    # gercek basim o anda enjekte ediliyor, tek basina birakilirsa normal
    # sag tik gonderiliyor. Sira dispatch.py icinde. ---
    table.add("RButton & WheelUp", "send_key:Volume_Up", "ses +")
    table.add("RButton & WheelDown", "send_key:Volume_Down", "ses -")

    # --- `´` (SC00D, VK 0xDD): AHK sysCommands(). Kaskad degil menu. ---
    backtick = send.vk_for_char("´") or 0xDD
    register_name(backtick, "Backtick")
    table.add("Backtick", "menu.sys", "sistem menusu")

    # --- Pause kombolari. AHK'de bunlar scriptin acil cikis yolu. ---
    # AHK menus.ahk `DialogPauseGui`: Pause basili tutulunca duraklat +
    # pencere (devam / kaydetmeden yeniden baslat / yeniden baslat / cikis).
    table.prefix("Pause", hold_action="app.pause_dialog", desc="basili tut: duraklat")
    table.add("Pause & Home", "app.restart", "yeniden baslat")  # AHK: reloadScript()
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
        table.prefix(
            "Caret", hold_action="menu.base_slots", desc="basili tut: base slotlar"
        )
        # AHK cascadeCaret: rakamlar BASE grubun (defaultGroup == "") slotlarini
        # yapistirir. 0 -> 10. slot, yani sifre slotu: yapistirma `private`
        # gidiyor (AHK ignoreNextClip) -- pano gecmisine hic yazilmiyor.
        for index in range(10):
            table.add(
                f"Caret & {index}",
                f"slot.paste_group:/{index or 10}",
                "base slot 1-10" if index == 1 else "",
            )

    # --- Tab: AHK cascadeTab(). Kisa basim Tab yazar (yuttugumuz tusu geri
    # gondererek), basili tutma slot menusunu acar, rakamlar slot yukler.
    # Modifierli basim (Alt+Tab, Ctrl+Tab, Shift+Tab) onege HIC girmez --
    # sarti dispatch.py `_hotkey_key` koyuyor. ---
    table.prefix("Tab", hold_action="menu.side_slots", desc="basili tut: yan grup")
    for index in range(10):
        table.add(
            f"Tab & {index}",
            f"slot.paste_side:{index or 10}",
            "yan grup slot 1-10" if index == 1 else "",
        )

    # --- CapsLock: AHK cascadeCaps(). Kisa basim buyuk harf kilidini cevirir
    # (tusu yuttugumuz icin Windows kendi cevirmiyor, biz ceviriyoruz),
    # basili tutma pano gecmisi menusu, rakamlar gecmisten yapistirir. ---
    table.add("CapsLock", "caps.toggle", "kisa: buyuk harf kilidi")
    table.prefix("CapsLock", hold_action="menu.clip", desc="basili tut: pano menusu")
    for index in range(1, 10):
        table.add(
            f"CapsLock & {index}",
            f"clip.paste:{index}",
            "pano gecmisi 1-9" if index == 1 else "",
        )

    # --- Ctrl+< -> Ctrl+Shift+K (VSCode: satiri sil). `<` tusu duzene bagli
    # (Turkce Q'da OEM_102), Caret gibi calisma aninda soruluyor. ---
    less = send.vk_for_char("<")
    if less is not None:
        register_name(less, "Less")
        table.add("^Less", "send_key:^+k", "satiri sil (VSCode)")

    # --- Hafiza slotlari penceresi acikken akilli yapistirma (AHK
    # memory_slots.ahk `smartPaste`). Ikisi de `~` ile: orta tus ve Insert
    # her yerde calisan tuslar, YUTULMAMALI -- eylem pencere kapaliyken
    # zaten hicbir sey yapmiyor. ---
    table.add("~MButton", "memslots.paste:middle", "memslots: akilli yapistir")
    # AHK handleMButton pt2: uzun basim yapistirir ve Shift+Enter gonderir
    # (liste halinde yapistirirken satir atlamak icin). Esik AHK ile ayni.
    table.prefix(
        "~MButton",
        passthrough=True,
        hold_action="memslots.paste_enter",
        hold_ms=300,
        desc="basili tut: akilli yapistir + Shift+Enter",
    )
    table.add("~Insert", "memslots.paste", "memslots: akilli yapistir")

    # --- ScrollLock: Turkce eklentisi (AHK turkish_layout_addon.ahk).
    # Kisa basim Turkce harfleri acar/kapar, BASILI TUTMAK dizilim 1 ile 2
    # arasinda gecer. Harflerin kendisi tabloda degil: karar dispatch'te,
    # tusun ne kadar basili tutuldugunu bilmek gerekiyor. ---
    table.add("ScrollLock", "turkish.toggle", "kisa: Turkce ac/kapa")
    table.prefix(
        "ScrollLock",
        hold_action="turkish.layout",
        hold_ms=600,  # AHK: `duration >= 600`
        desc="basili tut: dizilim degistir",
    )

    # --- Klavyeyle fare (AHK AutoHotkey.ahk'nin `#a/#s/#d/#w/#q/#e/#y`
    # satirlari). Win+WASD imleci 10 piksel oynatir, Win+Q/E tiklar,
    # Win+Y Enter gonderir. ---
    for spec, action, desc in (
        ("#a", "mouse.move:-10,0", "fare sol"),
        ("#s", "mouse.move:0,10", "fare asagi"),
        ("#d", "mouse.move:10,0", "fare sag"),
        ("#w", "mouse.move:0,-10", "fare yukari"),
        ("#q", "mouse.click:left", "sol tik"),
        ("#e", "mouse.click:right", "sag tik"),
        ("#y", "send_key:Enter", "Enter"),
    ):
        table.add(spec, action, desc)

    return table


def build_gestures() -> HotVectors:
    """AHK: hot_vectors.ahk -- HotVectors.Register(bDir.upDown, callback).

    F13 basili tutulup fare bir yone surulunce her `step_px` piksel bir
    adim uretir; adim sayisi eylemin kac kez calisacagidir (ses kac kademe
    artacak). Yon KILITLENDIGI anda (lock_px) jest baslamis sayilir: F13
    birakilinca ne menu acilir ne baska kombo beklenir.

    Dikey eksen Windows buyutecinin yakinlastirmasi, yatay eksen ses.
    Eksen bir kez kilitlendikten sonra dik yondeki hareket OKUNMAZ
    (core/hot_vectors.py `_lock`): hafif capraz hareket yanlis eksene
    dusmez. Esikler ayar ekranindan (AHK: hotVector.* ayarlari).
    """
    tracker = HotVectors(
        step_px=float(VECTOR_STEP_PX.get()), lock_px=float(VECTOR_LOCK_PX.get())
    )
    # Ayar degisince yeni deger ANINDA gecerli olsun: tracker tek ornek,
    # yeniden kurulmuyor (AHK'de de subscribe ile sabitler guncelleniyordu).
    VECTOR_STEP_PX.subscribe(lambda value, _old: setattr(tracker, "step_px", float(value)))
    VECTOR_LOCK_PX.subscribe(lambda value, _old: setattr(tracker, "lock_px", float(value)))
    tracker.lock_mode = str(VECTOR_LOCK_MODE.get())
    VECTOR_LOCK_MODE.subscribe(lambda value, _old: setattr(tracker, "lock_mode", str(value)))
    tracker.register(KEY_F13, Direction.UP, "send_key:#NumpadAdd", "yakinlastir")
    tracker.register(KEY_F13, Direction.DOWN, "send_key:#NumpadSub", "uzaklastir")
    tracker.register(KEY_F13, Direction.RIGHT, "send_key:Volume_Up", "ses +")
    tracker.register(KEY_F13, Direction.LEFT, "send_key:Volume_Down", "ses -")
    return tracker
