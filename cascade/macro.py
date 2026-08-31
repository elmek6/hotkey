"""Makro kaydi -- AHK `Lib/macro_recorder.ahk` portunun VERI katmani.

AHK kaydi `rec1.ahk` olarak, yani CALISTIRILABILIR KAYNAK KOD olarak
yaziyordu ve oynatmak icin ikinci bir AutoHotkey sureci baslatiyordu
(`RunWait`). Iki sebeple aynen tasinmadi:

1. Bir veri dosyasinin keyfi kod calistirmasi istenmez; elle duzenlenen tek
   satir butun kaydi goturur. AHK bunu yapabildi cunku elinde zaten bir
   yorumlayici vardi, bizde o gerekce yok.
2. Ikinci surece de gerek yok: hook enjekte girdiyi zaten ayirt ediyor
   (`KeyEvent.injected` + `.ours`), yani kendi oynattigimizi tekrar
   kaydetmeyiz. Oynatma kendi thread'imizde kosabilir.

Bicim JSONL -- satir basina bir olay:

    {"e": "meta", "name": "Adsiz", "created": "2026-08-31 12:00:00"}
    {"dt": 0,   "e": "window", "class": "Notepad", "title": "Adsiz"}
    {"dt": 340, "e": "key",  "vk": 65, "down": true}
    {"dt": 15,  "e": "key",  "vk": 65, "down": false}
    {"dt": 120, "e": "text", "s": "merhaba"}
    {"dt": 200, "e": "mouse", "btn": "left", "down": true,
     "x": 900, "y": 400, "wx": 120, "wy": 80, "dx": 5, "dy": -3}
    {"dt": 60,  "e": "wheel", "delta": 120, "horizontal": false}

`dt` = bir oncekinden gecen ms. JSONL secildi cunku olaylar tekduze
kayitlar, sira anlamli ve kayit sirasinda satir satir eklenebiliyor: kayit
ortasinda cokme olursa o ana kadarki kisim saglam kalir. (repository.md'nin
serbest metin gerekcesi burada gecerli degil -- makro URETILMIS veri.)

AHK ile PAYLASILMIYOR: `clipboards.bin`/`slots.json`in aksine `rec*.ahk`
bir programdi, biz onu calistiramayiz.

Fare olayinda UC koordinat birden yazilir (ekran / pencereye goreli /
onceki noktaya goreli); hangisinin kullanilacagina OYNATIRKEN `mouseMode`
karar verir. AHK bunun icin ayni tiklamayi uc kez yazip ikisini yorum
satiri yapiyordu; boylece mod degistiginde eski kayitlar bozulmuyordu ama
dosya uc katina cikiyordu. Tek olayda uc alan ayni dayanikliligi veriyor.

Bilinmeyen olay turu oynatmada SESSIZCE ATLANIR -- eski surum yeni kaydi
acabilsin.

Saf Python: Qt yok, Win32 yok -- test edilebilir.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from pathlib import Path

from cascade import paths
from cascade.settings import Category, setting

log = logging.getLogger("cascade.macro")

#: Kayit bu kadar saniye sonra kendiliginden durur (AHK: maxRecordTime).
MAX_RECORD_SEC = 300
#: Bu kadar olaydan sonra kayit durur (AHK: maxLines).
MAX_EVENTS = 500
#: Bundan kisa boslukler kayda bekleme olarak GECMEZ (AHK: Delay > 250).
MIN_GAP_MS = 250
#: Kaydi ve oynatmayi kesen panik tusu. Oynatma sirasinda klavye
#: kullanicinin kontrolunden cikiyor, cikis yolu her zaman acik olmali.
VK_ESCAPE = 0x1B

#: Kayit turu -- AHK `recType`. Kimlik, ekranda gorunen ad degil.
KEY = "key"
MOUSE = "mouse"
HYBRID = "hybrid"
REC_TYPES = (KEY, MOUSE, HYBRID)

#: Fare dugmesi VK'lari (`send.MOUSE_VK_NAMES` ile ayni adlar). Hook bize
#: mesaj numarasi veriyor, kayda ADI yaziyoruz: dosya okunabilir kalsin.
MOUSE_BUTTONS = {
    0x0201: ("left", True),
    0x0202: ("left", False),
    0x0204: ("right", True),
    0x0205: ("right", False),
    0x0207: ("middle", True),
    0x0208: ("middle", False),
    0x020B: ("x", True),
    0x020C: ("x", False),
}
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
#: `btn` -> `send.button_down/up` icin VK. "x" kaydi XButton numarasina
#: (`data`) gore x1/x2'ye ayrilir.
BUTTON_VK = {"left": 0x01, "right": 0x02, "middle": 0x04, "x1": 0x05, "x2": 0x06}

SLOT_COUNT = setting(
    "macro.slotCount",
    "Kayit slotu sayisi",
    default=3,
    category=Category.MACRO,
    tags="macro kayit slot",
    desc="Macro Recorder ekranindaki rec dosyasi sayisi",
    validate=lambda v: "" if 1 <= int(v) <= 9 else "1-9 arasi olmali",
)
KEY_DELAY = setting(
    "macro.keyDelay",
    "Tus gecikmesi",
    default=30,
    category=Category.MACRO,
    tags="macro oynatma hiz gecikme",
    desc="Oynatmada tuslar arasi bekleme (ms)",
    validate=lambda v: "" if 0 <= int(v) <= 500 else "0-500 ms olmali",
)
SPEED_UP = setting(
    "macro.speedUp",
    "Sleep carpani",
    default=0.0,
    category=Category.MACRO,
    tags="macro oynatma hiz",
    desc="Kayittaki beklemeler bu katsayiyla carpilir (0 = beklemesiz)",
    validate=lambda v: "" if 0.0 <= float(v) <= 10.0 else "0-10 arasi olmali",
)
MOUSE_MODE = setting(
    "macro.mouseMode",
    "Fare koordinat modu",
    default="window",
    choices=("screen", "window", "relative"),
    category=Category.MACRO,
    tags="macro fare koordinat",
    desc="Tiklamalarin ekrana mi, pencereye mi, onceki noktaya gore mi oynatilacagi",
)
RECORD_TYPE = setting(
    "macro.recordType",
    "Kayit turu",
    default=KEY,
    choices=REC_TYPES,
    labels={KEY: "Yalniz klavye", MOUSE: "Yalniz fare", HYBRID: "Klavye + fare"},
    category=Category.MACRO,
    tags="macro kayit tur klavye fare",
    desc="Kayit ekranindaki acilir listenin baslangic degeri (AHK: recType)",
)
RECORD_WINDOW = setting(
    "macro.recordWindow",
    "Pencere degisimini kaydet",
    default=False,
    category=Category.MACRO,
    tags="macro pencere kayit",
    desc="Kayit sirasinda one gelen pencerenin sinifi ve basligi da yazilir",
)
ACTIVATE_WINDOW = setting(
    "macro.activateWindow",
    "Oynatirken pencereyi one getir",
    default=False,
    category=Category.MACRO,
    tags="macro pencere aktif oynatma",
    desc="Kayitli pencere olayina gelince o pencere one cikarilir (AHK: WinActivate)",
)


def slot_path(slot: int) -> Path:
    """`Files/rec1.jsonl` -- AHK ile ayni klasor, ayni adlandirma."""
    return paths.FILES / f"rec{slot}.jsonl"


# ---- dosya ----


def write(path: Path, events: Iterable[dict], name: str = "") -> None:
    """Ilk satir meta, sonrasi olaylar."""
    paths.ensure_files_dir()
    meta = {
        "e": "meta",
        "name": name,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for event in events:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def read(path: Path) -> tuple[str, list[dict]]:
    """(ad, olaylar). Bozuk satir ATLANIR -- kayit ortasinda cokme olduysa
    elde ne varsa onunla oynatilir, dosya butunuyle reddedilmez."""
    name = ""
    events: list[dict] = []
    if not path.exists():
        return name, events
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            log.warning("makro: okunamayan satir atlandi (%s)", path.name)
            continue
        if not isinstance(item, dict):
            continue
        if item.get("e") == "meta":
            name = str(item.get("name", ""))
            continue
        events.append(item)
    return name, events


def slot_name(slot: int) -> str:
    return read(slot_path(slot))[0]


def set_slot_name(slot: int, name: str) -> None:
    """Adi degistir, olaylara dokunma. Dosya yoksa bir sey yapmaz --
    AHK de bos slotun adini tutmuyordu."""
    path = slot_path(slot)
    if not path.exists():
        return
    old, events = read(path)
    name = name.strip()
    if old == name:
        return
    write(path, events, name)


def slot_label(slot: int) -> str:
    """AHK: slotLabel() -- "rec1.jsonl  -  ad"."""
    name = slot_name(slot)
    base = f"rec{slot}.jsonl"
    return base if not name else f"{base}  -  {name}"


def iter_slots() -> Iterator[tuple[int, str]]:
    """(slot, etiket) -- GUI'deki slot listesi."""
    for slot in range(1, int(SLOT_COUNT.get()) + 1):
        yield slot, slot_label(slot)


# ---- Win32 koprusu ----
#
# Win32 ithali FONKSIYON ICINDE: bu modul saf veri katmani, testler ve
# ayar ekrani Win32 olmadan da ithal edebilmeli.


def _foreground_rect() -> tuple[int, int, int, int]:
    from cascade.win32 import window

    return window.window_rect(window.foreground_window())


def _find_window(cls: str, title: str) -> int:
    from cascade.win32 import window

    return window.find_window(cls, title)


def _activate(hwnd: int) -> bool:
    from cascade.win32 import window

    return window.activate(hwnd)


# ---- kayit ----


class Recorder:
    """Hook olaylarindan JSONL olaylari uretir.

    Hook thread'ine DEGIL, `app._drain` icindeki `seen` kuyruguna baglanir:
    olaylar oraya zaten (olay, yutuldu mu) ciftleri olarak ana thread'de
    geliyor, kaydedici icin ayri bir dinleyici gerekmiyor.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.perf_counter,
        rect: Callable[[], tuple[int, int, int, int]] | None = None,
    ) -> None:
        self._clock = clock
        #: One cikan pencerenin ekran dikdortgeni -- pencereye goreli
        #: koordinat icin. Disaridan verilebiliyor ki testler Win32
        #: istemesin.
        self._rect = rect or _foreground_rect
        self.events: list[dict] = []
        self.recording = False
        self.record_type = KEY
        self._last_t = 0.0
        self._started = 0.0
        self._last_window: tuple[str, str] | None = None
        self._last_point = (0, 0)

    def start(self, record_type: str = "") -> None:
        self.events = []
        self.recording = True
        self.record_type = record_type or str(RECORD_TYPE.get())
        self._started = self._last_t = self._clock()
        self._last_window = None
        self._last_point = (0, 0)

    def stop(self) -> None:
        self.recording = False

    def _gap_ms(self, t: float) -> int:
        """AHK log(): 250 ms altindaki bosluk kayda gecmez -- tus arasi
        dogal gecikme zaten oynatmada `keyDelay` ile veriliyor."""
        gap = int((t - self._last_t) * 1000.0)
        self._last_t = t
        return gap if gap >= MIN_GAP_MS else 0

    def feed_key(self, event) -> None:
        """`hook.KeyEvent`. Kendi enjekte ettigimiz tuslar kaydedilmez:
        oynatirken kaydin kendisini yeniden kaydetmeyelim."""
        if not self.recording or event.injected or event.ours:
            return
        if event.vk == VK_ESCAPE:
            self.stop()
            return
        if self.record_type == MOUSE:
            return
        self._push({"e": "key", "vk": event.vk, "down": bool(event.down)}, event.t)

    def feed_mouse(self, event) -> None:
        """`hook.MouseEvent`. Hareket kaydedilmez -- yalniz dugme ve
        tekerlek. Ara hareketleri yazmak dosyayi yuzlerce olayla sisirir ve
        oynatmada hicbir sey kazandirmaz; tiklamanin NEREDE oldugu zaten
        olayin kendi koordinatinda."""
        if not self.recording or event.injected or event.ours:
            return
        if self.record_type == KEY:
            return
        if event.message in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
            self._push(
                {
                    "e": "wheel",
                    "delta": int(event.data),
                    "horizontal": event.message == WM_MOUSEHWHEEL,
                },
                event.t,
            )
            return
        found = MOUSE_BUTTONS.get(event.message)
        if found is None:
            return
        button, down = found
        if button == "x":
            button = f"x{event.data or 1}"
        left, top, _r, _b = self._rect()
        prev_x, prev_y = self._last_point
        self._last_point = (event.x, event.y)
        self._push(
            {
                "e": "mouse",
                "btn": button,
                "down": down,
                "x": event.x,
                "y": event.y,
                "wx": event.x - left,
                "wy": event.y - top,
                "dx": event.x - prev_x if prev_x or prev_y else 0,
                "dy": event.y - prev_y if prev_x or prev_y else 0,
            },
            event.t,
        )

    def feed_window(self, cls: str, title: str) -> None:
        """Ayar kapaliysa hic yazilmaz; ayni pencere iki kez yazilmaz."""
        if not self.recording or not RECORD_WINDOW.get():
            return
        if not cls and not title:
            return
        current = (cls, title[:50])
        if current == self._last_window:
            return
        self._last_window = current
        self._push({"e": "window", "class": current[0], "title": current[1]}, self._clock())

    def _push(self, event: dict, t: float) -> None:
        event["dt"] = self._gap_ms(t)
        self.events.append(event)
        if len(self.events) >= MAX_EVENTS or t - self._started >= MAX_RECORD_SEC:
            self.stop()

    def save(self, slot: int, name: str = "") -> Path | None:
        """Bos kayit dosyaya YAZILMAZ -- var olan kaydin uzerine bosluk
        basmak AHK'de de kacinilan bir kayipti."""
        if not self.events:
            return None
        path = slot_path(slot)
        write(path, self.events, name)
        return path


# ---- oynatma ----


def _sleep_ms(ms: float) -> None:
    if ms > 0:
        time.sleep(ms / 1000.0)


class Player:
    """Kaydi `send.py` ile oynatir.

    `sender` ve `sleep` disaridan verilebiliyor: oynatma mantigi Win32
    olmadan test edilsin. `stop` her olaydan once sorulur -- panik tusu
    (Esc) uzun bir makronun ortasinda da is gormeli.
    """

    def __init__(
        self,
        sender=None,
        sleep: Callable[[float], None] = _sleep_ms,
        stop: Callable[[], bool] | None = None,
        rect: Callable[[], tuple[int, int, int, int]] | None = None,
        find_window: Callable[[str, str], int] | None = None,
        activate: Callable[[int], bool] | None = None,
    ) -> None:
        if sender is None:
            from cascade.win32 import send as sender  # gec ithal: testler Win32 istemiyor
        self.sender = sender
        self.sleep = sleep
        self.stop = stop or (lambda: False)
        self.rect = rect or _foreground_rect
        self.find_window = find_window or _find_window
        self.activate = activate or _activate
        self.playing = False

    def play(self, events: Iterable[dict], repeat: int = 1) -> int:
        """Oynatilan olay sayisi. Kesilirse o ana kadarki sayi doner."""
        key_delay = int(KEY_DELAY.get())
        speed_up = float(SPEED_UP.get())
        items = list(events)
        done = 0
        self.playing = True
        try:
            for _ in range(max(1, repeat)):
                for event in items:
                    if self.stop():
                        return done
                    self.sleep(int(event.get("dt", 0)) * speed_up)
                    if self._apply(event):
                        self.sleep(key_delay)
                    done += 1
        finally:
            self.playing = False
        return done

    def _apply(self, event: dict) -> bool:
        """Girdi gonderildiyse True (arkasina `keyDelay` girer)."""
        kind = event.get("e")
        if kind == "key":
            vk = int(event.get("vk", 0))
            if event.get("down"):
                self.sender.key_down(vk)
            else:
                self.sender.key_up(vk)
            return True
        if kind == "text":
            self.sender.type_text(str(event.get("s", "")))
            return True
        if kind == "mouse":
            return self._mouse(event)
        if kind == "wheel":
            self.sender.wheel(int(event.get("delta", 0)), bool(event.get("horizontal")))
            return True
        if kind == "window":
            return self._window(event)
        log.debug("makro: bilinmeyen olay atlandi: %r", kind)
        return False

    def _mouse(self, event: dict) -> bool:
        """`mouseMode` hangi koordinati kullanacagimizi soyler.

        screen    kayittaki ekran noktasi -- cozunurluk degisirse kayar
        window    o anki pencerenin sol-ustune goreli -- pencere tasinsa da tutar
        relative  bir onceki tiklamadan sapma -- imlecin bulundugu yere gore
        """
        mode = str(MOUSE_MODE.get())
        if mode == "relative":
            self.sender.move_relative(int(event.get("dx", 0)), int(event.get("dy", 0)))
        else:
            x, y = int(event.get("x", 0)), int(event.get("y", 0))
            if mode == "window":
                left, top, _r, _b = self.rect()
                x, y = left + int(event.get("wx", 0)), top + int(event.get("wy", 0))
            self.sender.set_cursor_pos(x, y)
        vk = BUTTON_VK.get(str(event.get("btn", "left")))
        if vk is None:
            return False
        if event.get("down"):
            self.sender.button_down(vk)
        else:
            self.sender.button_up(vk)
        return True

    def _window(self, event: dict) -> bool:
        """Ayar kapaliyken olay yalniz BILGI: dosyada durur, bir sey yapmaz.

        AHK burada `WinWait` + `WinActivate` yaziyordu. `WinWait` port
        EDILMEDI (bkz. dosya sonundaki TODO): beklemek oynatmayi kilitler,
        pencere hic acilmazsa panik tusundan baska cikis kalmaz.
        """
        if not ACTIVATE_WINDOW.get():
            return False
        hwnd = self.find_window(str(event.get("class", "")), str(event.get("title", "")))
        if not hwnd:
            log.info("makro: pencere bulunamadi: %r", event.get("title"))
            return False
        self.activate(hwnd)
        return True


def play_slot(slot: int, repeat: int = 1, **kwargs) -> int:
    _, events = read(slot_path(slot))
    return Player(**kwargs).play(events, repeat)


# TODO(AHK): macro_recorder.ahk logWindow() -- `WinWait(tt)` port edilmedi.
#     AHK oynatirken once pencerenin ACILMASINI bekliyor, sonra
#     aktiflestiriyordu; ustelik bu satirlari `mouseMode != "window"` iken
#     yorum satiri yaptigi icin pratikte cogu zaman kapaliydi. Bizde
#     yalnizca aktiflestirme var (`macro.activateWindow`, varsayilan
#     kapali). Beklemenin eklenmesi bir zaman asimi ister: pencere hic
#     acilmazsa oynatma panik tusuna kadar kilitli kalir.
# TODO(AHK): macro_recorder.ahk `isStrokeOnlyMode` port edilmedi -- kaydi
#     dosyaya yazmadan ham tus dizisi olarak dondurup app_shorts'a
#     ("Record Macro" dugmesi) veriyordu. Once o dugme portlanmali
#     (ui/profiles_view.py).
# TODO(AHK): fare surukleme (basma ve birakma arasi hareket) kaydedilmiyor.
#     AHK down/up arasindaki yer degisimini olcup surukleme olarak
#     yaziyordu; bizde down ve up ayri olaylar oldugu icin surukleme
#     ARADAKI hareketi olmadan, iki nokta arasinda ani sicrama gibi
#     oynatiliyor. Cizim uygulamalarinda fark eder.
