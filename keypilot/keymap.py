"""Tus haritasi -- SCRIPT katmani. AHK'deki `AutoHotkey.ahk`'nin karsiligi.

Bu dosyada MANTIK YOK: hangi tusun ne yapacagi, menulerde ne yazacagi ve
jestlerin hangi yone bagli oldugu burada VERI olarak durur. Tuslarin nasil
calistigi (yutma, onek, basim suresi) keypilot/dispatch.py'de; eylem
kimliklerinin gercek isi keypilot/app.py + keypilot/actions.py'de.

Yeni bir tus baglamak istediginde SADECE bu dosyaya dokunman gerekir.
Ileride JSON'a tasinacak yer de burasi (builder.def_from_dict hazir).

Bagli tuslar (build_hotkeys). Uc ayri kombo bicimi var, ucu de AHK'den:

    F13              kisa: acilir menu     basili tut: pano hizli menusu
    F14              kisa: slot menusu     surukle: ekran alani sec
    ^ (Caret)        kisa: `^` yazilir     basili tut: hizli panel (Slot sekmesi)
    Tab              kisa: Tab yazilir     basili tut: yan grup slotlari
    CapsLock         kisa: kilit cevrilir  basili tut: hizli panel (sekmeli liste)
    Tab & 1 .. 0     SECILI yan gruptan yapistirir (0 = slot 10)
    CapsLock & 1..9  pano gecmisinden yapistirir
    Ctrl+<           VSCode satir sil (Ctrl+Shift+K)
    Win+WASD/Q/E/Y   klavyeyle fare: 10px oynat, sol/sag tik, Enter
    F13 & F14        onek kombosu -- onek YUTULUR
    ~LButton & F16   tilde: onek yutulmaz, sol tik yerine gider
    F19 & LButton    onek klavyede, kombo tusu FARE dugmesi
    RButton & Wheel  sag tus basiliyken tekerlek -> ses; sag tik yutulur
    RButton+LButton  sag basiliyken sol tik -> Ctrl (coklu secim)
    MButton+LButton  orta basiliyken sol tik -> Shift (aralik secimi)
    F13 + fare yonu  jest: dikey = buyutec, yatay = ses (core/hot_vectors.py)
    ~F13 & WheelUp   basili tutup tekerlek
    Pause            basili tut: duraklatma penceresi (AHK DialogPauseGui)
    Pause & Home     yeniden baslat (AHK: reloadScript)
    Pause & End      yeniden baslat    Pause & c   takilan durumu sifirlar
    ^ & 1 .. 0       base grubun (defaultGroup=='') slotunu yapistirir
    ScrollLock       kisa: Turkce ac/kapa   basili tut: dizilim 1<->2
    ~MButton/~Insert memslots penceresi acikken akilli yapistirma
"""

from __future__ import annotations

import platform

from keypilot.commands import Cmd
from keypilot.core import turkish
from keypilot.core.builder import CascadeDef, KeyBuilder, PressType
from keypilot.core.hot_vectors import (
    LOCK_AXIS,
    LOCK_DIRECTION,
    LOCK_MODES,
    Direction,
    HotVectors,
)
from keypilot.core.hotkey import HotkeyTable
from keypilot.core.keynames import register_name
from keypilot.settings import Category, between, setting
from keypilot.win32 import send
from keypilot.win32.menu import CHECKED, COLUMN

# AHK hot_vectors.ahk: prefDirThreshold / prefStepSize. Ivme carpani
# (prefAcceleration) PORT EDILMEDI -- AHK 3.0 da kaldirmisti, duz piksel
# sayimi kaliyor.
VECTOR_LOCK_PX = setting(
    "hotVector.dirThreshold",
    "Yon kilidi esigi",
    default=8,
    category=Category.GESTURE,
    tags="fare hassasiyet vektor jest",
    desc=(
        "F13 basiliyken fareyi bu kadar piksel surukleyince jest BASLAR ve yon "
        "kilitlenir. Kucuk deger: jest cabuk baslar ama yanlislikla da baslar. "
        "Buyuk deger: baslatmak icin daha cok surukleman gerekir."
    ),
    validate=between(1, 100, "px"),
)
VECTOR_LOCK_MODE = setting(
    "hotVector.lockMode",
    "Jest kilidi",
    default=LOCK_AXIS,
    choices=LOCK_MODES,
    labels={LOCK_AXIS: "eksen", LOCK_DIRECTION: "yon"},
    legacy={"eksen": LOCK_AXIS, "yon": LOCK_DIRECTION},
    category=Category.GESTURE,
    tags="fare vektor jest eksen yon kilit",
    desc=(
        "Jest baslayinca ne kilitlenir. eksen: dikey/yatay secilir, o eksenin "
        "IKI yonu de canli kalir (yukari surukleyip sonra asagi donebilirsin). "
        "yon: yalniz ilk yon calisir, geri hareket bir sey yapmaz."
    ),
)
# Jest sirasinda imlec her olayda baslangic noktasina geri konur ve mesafe
# `olay - baslangic` diye olculur. Kapatilirsa hareket olayi yine yutulur ama
# imlec ilerlemedigi icin ardisik olaylarin farki +1/-1 diye sifirlanir ve
# yavas hareket esigi hic gecemez (docs/hot_vectors.md D-1).
VECTOR_FREEZE = setting(
    "hotVector.freezeCursor",
    "Jest sirasinda imleci dondur",
    default=True,
    category=Category.GESTURE,
    tags="fare vektor jest imlec",
    desc=(
        "Jest boyunca imlec basladigi noktada durur, ekranda gezinmez. "
        "KAPATMA: imlec ilerlemedigi icin yavas hareket olculemez ve jest "
        "hic tetiklenmez (docs/hot_vectors.md D-1)."
    ),
)
# Titreme toleransi: tusa basarken imlec bir iki piksel oynuyor. Bu kadarlik
# hareket "surukleme" sayilmaz. Once dispatch.py'de sabitti (DRAG_PX = 6).
VECTOR_IGNORE_PX = setting(
    "hotVector.ignorePx",
    "Yoksayilan titreme",
    default=6,
    category=Category.GESTURE,
    tags="fare hassasiyet vektor jest titreme surukleme",
    desc=(
        "Tusa basarken el titrer ve imlec bir iki piksel oynar. Bu kadarlik "
        "hareket surukleme SAYILMAZ -- F14 ile ekran alani secimi ya da sag "
        "tus suruklemesi bosuna baslamasin diye."
    ),
    validate=between(0, 50, "px"),
)
VECTOR_STEP_PX = setting(
    "hotVector.stepSize",
    "Adim esigi",
    default=14,
    category=Category.GESTURE,
    tags="fare hassasiyet vektor jest",
    desc=(
        "Jest basladiktan sonra her bu kadar piksel bir ADIM sayilir; eylem "
        "adim sayisi kadar calisir (ses kac kademe artacak, buyutec ne kadar "
        "yakinlasacak). Kucultursen jest hizlanir."
    ),
    validate=between(1, 400, "px"),
)

KEY_F13 = 0x7C  # jest tanimlari / testler icin; keynames tablosuyla ayni deger

# ---- BILGISAYAR -- AHK: LoadSettings() icindeki A_ComputerName testi ----
# AHK bu ayrimla is bilgisayarinda ekran koruyucu engellemeyi ve Outlook'u
# simge durumunda baslatmayi aciyordu. Burada SIMDILIK yalnizca hangi
# bilgisayarda acildigini bildiriyoruz; buna bagli acilis eylemleri
# eklenecekse yerleri START_ACTIONS'in yanidir.
#
# ADI NEDEN "PROFIL" DEGIL: proje "profil" kelimesini UYGULAMA profilleri
# icin kullaniyor (Files/profiles.json -- pencereye bagli kisayol kumeleri).
# Iki kavramin ortak hicbir yani yok; ayni kelime menude, log'da ve tepsi
# ipucunda yan yana geldiginde "hangi profil" diye sormak gerekiyordu.
WORK_COMPUTERS = ("LAPTOP-UTN6L5PA",)
COMPUTER_LABELS = {"work": "🏢 Work", "home": "🏠 Home"}


def current_computer() -> str:
    """Bu bilgisayar `work` mu `home` mu (AHK ile ayni olcut)."""
    name = platform.node().strip().upper()
    return "work" if name in {item.upper() for item in WORK_COMPUTERS} else "home"


#: Win+WASD sanal fare tuslari. Menu de tablo da BU listeyi okuyor: iki yerde
#: ayri liste tutulursa biri guncellenip digeri unutulur.
VIRTUAL_MOUSE_KEYS = (
    ("#a", "mouse.move:-10,0", "fare sol"),
    ("#s", "mouse.move:0,10", "fare asagi"),
    ("#d", "mouse.move:10,0", "fare sag"),
    ("#w", "mouse.move:0,-10", "fare yukari"),
    ("#q", "mouse.click:left", "sol tik"),
    ("#e", "mouse.click:right", "sag tik"),
    ("#y", "send_key:Enter", "Enter"),
)

#: ScrollLock menusundeki radyo grubu. Sira = `turkish.set` argumani:
#: 0 kapali, 1 uzun basim dizilimi, 2 dogrudan remap.
TURKISH_LAYOUTS = (
    "Kapali",
    "Dizilim 1 -- c s i g o u tuslarini basili tut",
    "Dizilim 2 -- harfler dogrudan Turkce basar",
)

VIRTUAL_MOUSE_NOTE = "Win+WASD imlec, Q/E tik, Y Enter"

VIRTUAL_MOUSE = setting(
    "mouse.virtualWasd",
    "WASD sanal fare",
    default=False,
    category=Category.MOUSE,
    tags="fare klavye wasd win sanal imlec",
    #: AYAR EKRANINDA YOK. Kipin asil yeri ScrollLock menusu: orada tuslarin
    #: listesiyle birlikte duruyor ve acilir acilmaz denenebiliyor. Ayar
    #: ekranindaki ikinci kopya ayni salteri iki yerden gostermekten baska
    #: is yapmiyordu. Deger yine diske yaziliyor, kip acik kalmaya devam eder.
    hidden=True,
    desc=(
        "Win+WASD imleci oynatir, Win+Q/E tiklar, Win+Y Enter yollar. "
        "KAPALIYKEN bu kombolar hic yutulmaz -- Win+D (masaustunu goster), "
        "Win+E (Gezgin), Win+W gibi Windows kisayollari serbest kalir. "
        "ScrollLock'u basili tutunca acilan menuden degistirilir."
    ),
)

#: Arizali (yipranmis) fare filtresi. Mikro anahtar eskidikce tek basimi
#: iki basim olarak gonderiyor; ikinci basim ilkinden 70 ms'den once
#: geliyorsa (dispatch.DOUBLE_CLICK_MS) insan eli degildir ve yutuluyor.
#: Esik AHK'den beri sabit: gercek cift tiklamada iki basim arasi 100
#: ms'nin altina inmiyor, yani normal kullanim bu filtreden etkilenmiyor.
BOUNCE_LEFT = setting(
    "mouse.bounceGuardLeft",
    "Sol tus: arizali fare filtresi",
    default=False,
    category=Category.MOUSE,
    tags="fare arizali cift tiklama bounce sol tus yipranmis",
    desc=(
        "Sol tusta 70 ms'den kisa arayla gelen IKINCI basimi yutar -- yipranmis "
        "mikro anahtarin tek tiklamayi ikiye bolmesine karsi. Yutulan her basim "
        "log'a uyari olarak dusuyor ve kisa bir bip caliyor: fare yasleniyor "
        "demek, program hatasi degil.\n\n"
        "KAPATMA: cok hizli ard arda tiklaman gereken bir isteyse (oyun, cizim) "
        "kapatilabilir; o zaman arizali basimlar da uygulamaya gider."
    ),
)

BOUNCE_MIDDLE = setting(
    "mouse.bounceGuardMiddle",
    "Orta tus: arizali fare filtresi",
    default=False,
    category=Category.MOUSE,
    tags="fare arizali cift tiklama bounce orta tus mbutton yipranmis",
    desc=(
        "Ayni filtre orta tus icin. Orta tus tarayicida 'yeni sekmede ac' "
        "demek, yani arizali ikinci basim ya fazladan sekme aciyor ya da "
        "tarayici iki basimi tek tiklama saymayip HICBIR sey yapmiyor -- "
        "'tusa bastim, olmadi' halinin sebebi cogu zaman bu."
    ),
)

BUTTON_AS_MODIFIER = setting(
    "mouse.buttonAsModifier",
    "Sag/orta tus: sol tikta Ctrl/Shift",
    default=True,
    category=Category.MOUSE,
    tags="fare sag orta ctrl shift coklu secim modifier rbutton mbutton",
    desc=(
        "Sag tus basiliyken sol tik = Ctrl+tik (coklu secim). "
        "Orta tus basiliyken sol tik = Shift+tik (aralik secimi). "
        "Sag/orta tus bu basimda TUKETILIR: birakilinca baglam menusu / "
        "orta tik gitmez. Tek basina sag/orta tik eskisi gibi calisir."
    ),
)


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


def screen_menu() -> tuple:
    """F14 menusundeki "Area" alt menusu -- monitorun TAMAMINI secer.

    Madde adi `prm 1920x1080` bicimde: birincil monitor `prm`, digerleri
    sirasiyla numarali (win32/screen.py `monitors`). Secilince alan secimi
    o monitorun tamami olarak acilir, islem cubugu hazir gelir -- surukleme
    yok. Liste her acilista taze uretiliyor: monitor takilip cikarilabilir.

    Menude adi "Area": secilen sey bir ALAN, yalnizca alani ekranin tamami.
    """
    from keypilot.win32.screen import monitors

    spec: tuple = ()
    for index, (name, (_x, _y, width, height)) in enumerate(monitors()):
        spec += ((f"{name} {width}x{height}", f"select.screen:{index}"),)
    return spec or (("(monitor bulunamadi)", "notify:Monitor bulunamadi"),)


#: Menu ikonlari AHK ile AYNI numaralar (menus.ahk `menuIcon`): sayi
#: DLL icindeki 1 tabanli ikon sirasi. Emoji yerine gercek ikon: klasik
#: Win32 menusu metni GDI ile ciziyor ve renkli emoji tablosunu
#: kullanmiyor, o yuzden emoji hep tek renk (siyah/beyaz) cikiyor.
F13_MENU = (
    # ---- 1. KOLON: pano, ekran goruntusu, OCR (AHK showF13menu) ----
    ("Clipboard history win", "send_key:#v", "res:243"),  # panodan pencereye
    None,
    # Secim/OCR/buyutec maddeleri BURADA YOK: hepsi fare tuslarina bagli
    # (F14 surukleme = alan secimi, cubuktan OCR; F13&F14 = buyutec).
    # Menude ikinci bir yol tutmak ayni isi iki yerde bakim ettiriyordu.
    ("Hafiza bloklari", Cmd.Memslots.START, "res:30"),  # bellek cubugu
    None,
    ("Macro recorder", Cmd.Macro.RECORDER),
    # ---- 2. KOLON: aktif pencere profili, araclar, hep ustte ----
    # Kolon ayracini COLUMN ciziyor; bu yuzden 1. kolonun sonunda ayrica
    # yatay ayrac YOK -- AHK'de de oyle, kolon dibinde boslukta asili bir
    # cizgi kalmasin diye. Profil ve "hep ustte" bloklarini app.py
    # ekliyor (o anki pencereye bagli).
    COLUMN,
)
"""AHK: showF13menu()'nun 1. KOLONU. Oge basina bir kod satiri degil, tek
veri tablosu. Isimlendirme, sira ve ikon numaralari AHK ile ayni; port
edilmemis ogeler (Repository GUI, Macro recorder) `´` menusunde `--` isaretli."""

F13_MENU_TAIL: tuple = ()
"""2. kolonun SONU. Arasina app.py o anki pencereye bagli bloklari koyar:
uygulama profili + kisayollari (AHK menuAppProfile) ve hep-ustte listesi
(AHK menuAlwaysOnTop). Special keys ve System AHK'de de yalniz F14'te.

"""

# AHK: sysCommands() -- `´` tusu (SC00D / VK 0xDD). Kaskad menusu olarak
# degil acilir menu olarak veriliyor: icerigi uzun ve fare ile de secilecek.
# Port edilmemis olanlarin basinda `--` var, tiklanabilirler ama uyari verir.
SYS_COMMANDS_MENU = (
    ("1: Reload script", Cmd.App.RESTART),
    ("2: Show stats", Cmd.Errors.SHOW),
    # app_shorts.ahk portu: profiller Files/profiles.json'dan okunuyor,
    # duzenleme dosyanin kendisinden (AHK'nin yonetici GUI'si port edilmedi).
    ("3: Profile manager", Cmd.Shorts.MANAGE),
    ("4: Key history", Cmd.App.MONITOR),
    ("k: Kisayol haritasi", Cmd.Keys.MAP),
    ("5: Memory slots", Cmd.Memslots.START),
    ("6: Macro recorder", Cmd.Macro.RECORDER),
    ("7: F13 menu", Cmd.Menu.F13),
    ("8: F14 menu", Cmd.Menu.SLOTS),
    ("9: Pause script", Cmd.App.PAUSE),
    # AHK menus.ahk `DialogPauseGui` (Pause basili tutunca acilan pencere):
    # duraklat + yeniden baslat + kaydetmeden yeniden baslat + cikis.
    ("p: Pause menu...", Cmd.App.PAUSE_DIALOG),
    ("0: Exit script", Cmd.App.EXIT),
    # repository.ahk'nin veri yarisi port edildi (keypilot/repository.py);
    # yonetici GUI'si degil -- duzenleme dosyanin kendisinden.
    ("r. Repository (repository.md)", Cmd.Repository.OPEN),
    # Tek madde: pencereyi acar. Mod pencerede yasar, kapatma da orada.
    ("i: Incognito", Cmd.Incognito.OPEN),
    ("a: TrayTip test", "notify:Mesaj icerigi"),
    None,
    # AHK'de olmayan, bize ozgu olanlar ayracin altinda.
    ("Pano gecmisi...", Cmd.Clip.FILTER),
    ("Pano gorselleri...", Cmd.Clip.IMAGES),
    None,
    ("⚙️ Ayarlar...", Cmd.App.SETTINGS),
    ("\U0001f4cb Son hatayi kopyala", Cmd.Errors.COPY),
)

#: F14 menusundeki "System" alt menusu, `´` menusunun TA KENDISI. Ayri bir
#: tablo tutulunca ikisi zamanla birbirinden koptu (F14'te Ayarlar vardi,
#: `´`de yoktu); tek kaynak kalsin diye takma ad.
SYSTEM_MENU = SYS_COMMANDS_MENU

# ---- OnStart / OnExit -- AHK: LoadSettings() ve ExitSettings() ----
# Pano gecmisinin diskten okunmasi/yazilmasi app.py on_start/on_exit icinde;
# buraya yalniz "acilista/kapanista su eylemler de calissin" turu script
# istekleri girer.
START_ACTIONS: tuple[str, ...] = ()
EXIT_ACTIONS: tuple[str, ...] = ()


def build_cascades() -> dict[int, CascadeDef]:
    """F13 jest + F15..F20 kaskad -- AHK handleF* KeyBuilder zinciri.

    F13: jest tanimi burada (tek yer). Basim/hold/cift HotkeyTable prefix'te
    kalir; `run_cascade=False` ile CascadeMachine'e girmez (F13 & F15 akoru
    bozulmasin). F14 jesti sonraki adimda.

    F15..F20: kisa/orta/uzun + kombo -- CascadeMachine.
    """
    defs: list[CascadeDef] = [
        # handleF13 jestleri -- tek kayit yeri.
        KeyBuilder("F13", short=350)
        .gesture(Direction.UP, "Zoom+", "send_key:#NumpadAdd")
        .gesture(Direction.DOWN, "Zoom-", "send_key:#NumpadSub")
        .gesture(Direction.RIGHT, "Vol +", "send_key:Volume_Up")
        .gesture(Direction.LEFT, "Vol -", "send_key:Volume_Down")
        .gestureVisible(True)
        .run_cascade(False)
        .build(),
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
        # handleF17: kisa Alt+Sag, orta Delete, uzun End + yatay jest
        KeyBuilder("F17", short=350, long=800)
        .main_key(PressType.SHORT, "send_key:!Right")
        .main_key(PressType.MEDIUM, "send_key:Delete", "Del")
        .main_key(PressType.LONG, "send_key:End", "End")
        .combo("F18", "panic (buyutec %100 + kucult)", Cmd.Magnifier.PANIC)
        .gesture(Direction.LEFT, "Undo", "send_key:^z")
        .gesture(Direction.RIGHT, "Back", "send_key:Backspace")
        .gestureVisible(True)
        .show_menu(False)
        .named("F17")
        .build(),
        # handleF18: kisa Alt+Sol, orta Backspace, uzun Home + jest
        KeyBuilder("F18", short=350, long=800)
        .main_key(PressType.SHORT, "send_key:!Left")
        .main_key(PressType.MEDIUM, "send_key:Backspace", "Back")
        .main_key(PressType.LONG, "send_key:Home", "Home")
        .combo("F17", "panic (buyutec %100 + kucult)", Cmd.Magnifier.PANIC)
        .combo("LButton", "VSCode/Cursor: satiri sil", "send_key:^+k")
        .combo("MButton", "ipucu", "tip:RButton + MButton: Zoom in/out")
        .gesture(Direction.LEFT, "Del", "send_key:Delete")
        .gestureVisible(True)
        .show_menu(False)
        .named("F18")
        .build(),
        # handleF19: kisa ^v, orta ^a^v, uzun MemSlots
        KeyBuilder("F19", short=300, long=800)
        .main_key(PressType.SHORT, "send_key:^v")
        .main_key(PressType.MEDIUM, "send_keys:^a ^v")
        .main_key(PressType.LONG, Cmd.Memslots.START)
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
        .main_key(PressType.LONG, Cmd.Memslots.START)
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
    ekleniyor (app.KeyPilot._on_memslot_fkeys); kapaninca cikiyorlar. AHK'de
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
    table.add("F13", Cmd.Menu.F13, "kisa: menu")
    # AHK handleF13: pt1 menu, pt2 pano menusu, pt4 (CIFT basim) gecmiste
    # arama -- `EM.enableDoubleClick()`. Cift basim tanimli oldugu icin kisa
    # basim eylemi bir sure BEKLETILIR (bkz. core/prefix.py).
    table.prefix(
        "F13",
        hold_action=Cmd.Menu.CLIP,
        double_action=Cmd.Clip.FILTER,
        desc="basili tut: pano menusu / cift: gecmiste ara",
    )
    # F14 iki islevli: SURUKLERSEN ekran alani secimi baslar (ui/snip.py),
    # kimildatmadan birakirsan slot menusu acilir. AHK handleF14'te kisa
    # basim showF14menu (slotlar) idi; secim oraya sonradan eklendi ve
    # tusun eski isini yemesin diye surukleme ile ayrildi.
    table.add("F14", Cmd.Menu.SLOTS, "kisa: slot menusu")
    # CIFT BASIM YOK. AHK handleF14 pt4 (showSlotsSearch) buradaydi ama
    # `double_action` tanimli olunca KISA basim eylemi `double_ms` kadar
    # BEKLETILIYOR (core/prefix.py): menu tus birakildiktan ~200 ms sonra
    # aciliyordu. Bekleme surukleme icin gerekli degil -- surukleme basim
    # aninda karara baglaniyor, birakma aninda menunun acilacagi kesin.
    # Slotlarda arama menude "Search in slots" maddesi olarak duruyor.
    # Eylemin argumani secimi yapacak TUS: F14 basili kaldigi surece
    # dikdortgen buyur, birakilinca secim biter (ui/snip.py). Argumansiz
    # birakilirsa secim sol fare tusuna kalirdi -- F14 ile secmek isterken
    # bir de fareye basmak gerekiyordu.
    table.prefix("F14", drag_action="select.start:F14@{x},{y}", desc="surukle: ekran alani sec")

    # --- F13 & F15..F20: slots.json'daki slotlardan yapistir. AHK
    # handleF14'un slot kombolari (F14 secim tusu olunca F13'e tasindi).
    # Siralama AHK ile ayni ters duzende: en yakin tus F20 = Slot 1.
    for offset, fkey in enumerate(("F20", "F19", "F18", "F17", "F16", "F15")):
        table.add(f"F13 & {fkey}", f"slot.paste:{offset + 1}", f"slot {offset + 1}")
    # AHK key_handler_mouse.ahk: iki yonde de TOGGLE idi -- buyutulmusse
    # %100'e doner, degilse %200'e cikar (x2 / :2). Yon ayirmayi denedik ama
    # hangi tusa once basildigini ayirt etmek kullanicida "hep yakinlastiriyor"
    # hissi verdi; AHK'deki tek davranisa geri donuldu.
    table.add("F13 & F14", Cmd.Magnifier.TOGGLE, "buyutec: x2 / :2")
    table.add("F14 & F13", Cmd.Magnifier.TOGGLE, "buyutec: x2 / :2")

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
    # Sag tus onek: tekerlek + sol tikta Ctrl (buttonAsModifier). Onek
    # kaydi Wheel satirlariyla zaten olusuyor; yine de acik olsun.

    # --- `´` (SC00D, VK 0xDD): AHK sysCommands(). Kaskad degil menu. ---
    backtick = send.vk_for_char("´") or 0xDD
    register_name(backtick, "Backtick")
    table.add("Backtick", Cmd.Menu.SYS, "sistem menusu")

    # --- Pause kombolari. AHK'de bunlar scriptin acil cikis yolu. ---
    # AHK menus.ahk `DialogPauseGui`: Pause basili tutulunca duraklat +
    # pencere (devam / kaydetmeden yeniden baslat / yeniden baslat / cikis).
    table.prefix("Pause", hold_action=Cmd.App.PAUSE_DIALOG, desc="basili tut: duraklat")
    table.add("Pause & Home", Cmd.App.RESTART, "yeniden baslat")  # AHK: reloadScript()
    # AHK'de cikisti. Pratikte gereken sey programi OLDURMEK degil temiz
    # duruma donmek (takilmis onek, olmus kanca): ikisini de reload cozuyor.
    # Cikis tepsi menusunde ve Pause duraklatma penceresinde duruyor.
    table.add("Pause & End", Cmd.App.RESTART, "yeniden baslat")
    table.add("Pause & c", "state.reset", "takilan durumu sifirla")

    # `^` basiliyken rakam: pano gecmisinin o sirasindaki kaydi yapistirir.
    # 1 en yeni kopya, 2 bir onceki... AHK'deki `clip_slot` mantiginin
    # gecmis listesi uzerinde calisan hali.
    caret = send.vk_for_char("^")
    if caret is not None:
        register_name(caret, "Caret")
        # AHK cascadeCaret: kisa basim `^` yazar (yuttugumuz tusu geri
        # gondererek), basili tutma menu acar, rakamlar slot yukler.
        # Basili tutma artik CapsLock'un hizli paneli, klasik Win32 slot
        # menusu degil: ayni liste iki ayri pencerede yasiyordu ve panelin
        # arama kutusu, uc satira sarilan ogesi burada da isine yariyor.
        # Sekme "Slot", cunku `^ & 1..0` base slotlari yapistiriyor.
        table.prefix("Caret", hold_action="menu.quick:Slot", desc="basili tut: hizli panel (Slot)")
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
    table.prefix("Tab", hold_action=Cmd.Menu.SIDE_SLOTS, desc="basili tut: yan grup")
    for index in range(10):
        table.add(
            f"Tab & {index}",
            f"slot.paste_side:{index or 10}",
            "yan grup slot 1-10" if index == 1 else "",
        )

    # --- CapsLock: AHK cascadeCaps(). Kisa basim buyuk harf kilidini cevirir
    # (tusu yuttugumuz icin Windows kendi cevirmiyor, biz ceviriyoruz),
    # basili tutma pano gecmisi menusu, rakamlar gecmisten yapistirir. ---
    table.add("CapsLock", Cmd.Caps.TOGGLE, "kisa: buyuk harf kilidi")
    # AHK'de burasi da duz pano menusuydu; artik sekmeli hizli panel
    # (ui/quick_panel.py). F13 basili tutma eski menude BIRAKILDI:
    # tek elle, tek tusla acilan kisa liste orada daha hizli.
    table.prefix("CapsLock", hold_action=Cmd.Menu.QUICK, desc="basili tut: hizli panel")
    for index in range(1, 10):
        table.add(
            f"CapsLock & {index}",
            f"clip.paste:{index}",
            "pano gecmisi 1-9" if index == 1 else "",
        )

    # --- Ctrl+< -> Ctrl+Shift+K (satiri sil). `<` tusu duzene bagli
    # (Turkce Q'da OEM_102), Caret gibi calisma aninda soruluyor.
    # Cursor VSCode catallamasi: varsayilan tus haritasini oldugu gibi
    # devraliyor, yani ayni `^+k` orada da satiri siler -- ayri bir tanim
    # GEREKMIYOR. Etikette ikisi de yaziyor, yoksa "Cursor'de calisir mi"
    # sorusunun cevabi denemekten geciyordu. ---
    less = send.vk_for_char("<")
    if less is not None:
        register_name(less, "Less")
        table.add("^Less", "send_key:^+k", "satiri sil (VSCode/Cursor)")

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
        hold_action=Cmd.Memslots.PASTE_ENTER,
        hold_ms=300,
        desc="basili tut: akilli yapistir + Shift+Enter",
    )
    table.add("~Insert", Cmd.Memslots.PASTE, "memslots: akilli yapistir")

    # --- ScrollLock: Turkce eklentisi (AHK turkish_layout_addon.ahk).
    # Kisa basim Turkce harfleri acar/kapar, BASILI TUTMAK dizilim 1 ile 2
    # arasinda gecer. Harflerin kendisi tabloda degil: karar dispatch'te,
    # tusun ne kadar basili tutuldugunu bilmek gerekiyor. ---
    table.add("ScrollLock", Cmd.Turkish.TOGGLE, "kisa: Turkce ac/kapa")
    table.prefix(
        "ScrollLock",
        hold_action=Cmd.Menu.SCROLLLOCK,
        hold_ms=600,  # AHK: `duration >= 600`
        desc="basili tut: Turkce + sanal fare menusu",
    )

    # --- Klavyeyle fare (AHK AutoHotkey.ahk'nin `#a/#s/#d/#w/#q/#e/#y`
    # satirlari). KIP KAPALIYSA HIC EKLENMIYOR: tabloya girmeyen kombo
    # yutulmaz, Win+D/Win+E gibi Windows kisayollari calismaya devam eder.
    # Kip degisince app.py tabloyu yeniden kuruyor (`rebuild_hotkeys`). ---
    if VIRTUAL_MOUSE.get():
        for spec, action, desc in VIRTUAL_MOUSE_KEYS:
            table.add(spec, action, desc)

    return table


def scroll_lock_menu(layout: int, enabled: bool = False) -> tuple:
    """ScrollLock BASILI TUTULUNCA acilan menu.

    Turkce eklentisinin butun durumu TEK radyo grubu: kapali, dizilim 1,
    dizilim 2. Ucu birbirini disliyor, biri hep secili -- "acik mi" ile
    "hangi dizilim" ayri iki soru degil, ayni sorunun uc cevabi.

        Kapali        turkish.set:0
        Dizilim 1     turkish.set:1
        Dizilim 2     turkish.set:2
        ------------
        Fare WASD     bagimsiz ac/kapa (onay kutusu)

    Secili olan TIKLI cizilir (`CHECKED`). Kalin YOK: Win32 menusunde kalin
    "varsayilan oge" demek ve menu basina YALNIZ BIR TANE olabiliyor --
    burada iki isaret gerekiyor (bir dizilim + acikken sanal fare), kalin
    olsa ikincisi birincisini silerdi.
    """
    rows: list[tuple | None] = []  # None = yatay ayrac (ui/menu.py)
    current = layout if enabled else 0
    for number, name in enumerate(TURKISH_LAYOUTS):
        marks = (CHECKED,) if current == number else ()
        rows.append((name, f"turkish.set:{number}", *marks))
    rows.append(None)
    rows.append(
        (
            "Fare WASD tuslariyla -- " + VIRTUAL_MOUSE_NOTE,
            "vmouse.toggle",
            *((CHECKED,) if VIRTUAL_MOUSE.get() else ()),
        )
    )
    return tuple(rows)


def build_gestures() -> HotVectors:
    """CascadeDef.gesture satirlarindan HotVectors kurar (tek kaynak)."""
    tracker = HotVectors(step_px=float(VECTOR_STEP_PX.get()), lock_px=float(VECTOR_LOCK_PX.get()))
    VECTOR_STEP_PX.subscribe(lambda value, _old: setattr(tracker, "step_px", float(str(value))))
    VECTOR_LOCK_PX.subscribe(lambda value, _old: setattr(tracker, "lock_px", float(str(value))))
    tracker.lock_mode = str(VECTOR_LOCK_MODE.get())
    VECTOR_LOCK_MODE.subscribe(lambda value, _old: setattr(tracker, "lock_mode", str(value)))
    for definition in build_cascades().values():
        _harvest_gestures(tracker, definition)
    return tracker


def _harvest_gestures(tracker: HotVectors, definition: CascadeDef) -> None:
    """CascadeDef jest + P/S + visible bilgisini HotVectors'a yazar."""
    for spec in definition.gestures:
        tracker.register(
            definition.key,
            spec.direction,
            spec.action,
            spec.label,
            every=spec.every,
        )
    center = definition.overlay_center
    if center:
        tracker.center(definition.key, center.get("P", ""), center.get("S", ""))
    tracker.set_visible(definition.key, definition.gesture_visible)
