"""Loglama ve hata yakalama -- error_handler.ahk'nin karsiligi.

AHK'de `OnError(GlobalErrorHandler)` tum thread'lerin hatasini yakaliyordu.
Python'da tek bir kanca yetmiyor, uc ayri yerden gelebiliyor:

    sys.excepthook            ana thread
    threading.excepthook      hook thread, beep thread
    qInstallMessageHandler    Qt'nin kendi uyarilari

Ucu de buraya baglaniyor. Hook callback'i AYRI konu: orada exception
yakalanip yutuluyor (win32/hook.py), cunku callback'ten disari sizan bir
hata Windows'un hook'u dusurmesine yol acar -- program calisir gorunur ama
hicbir tus gelmez.

AHK'den tasinan iki karar:

1. **Kritik hata aninda diske yazilir** (`_logNow`), kapanis beklenmez.
   Cokme aninda kapanis kodu zaten calismayabilir. Burada `FileHandler`
   her kayitta flush ediyor.
2. **Son hata bellekte de durur.** AHK `lastFullError` ile menude
   "Son hatayi kopyala" yapiyordu; `ErrorStore` ayni is.

`ErrorStore` hem kayitci hem de log kaydedicisi olarak calisiyor: logging
uzerinden gelen WARNING+ kayitlari da toplaniyor, boylece ActionRunner'in
`log.exception` cagrilari da menude gorunuyor.
"""

from __future__ import annotations

import contextlib
import logging
import logging.handlers
import re
import sys
import threading
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from keypilot import paths
from keypilot.settings import Category, setting

#: Hata olunca ekranda ipucu cikarilsin mi. Tepsi rozeti HER ZAMAN yanar;
#: bu ayar yalnizca "gozune sokulsun mu"yu belirler.
SHOW_TIP = setting(
    "errors.showTip",
    "Hata olusunca tooltip ile goster",
    default=True,
    category=Category.GENERAL,
    tags="hata error ipucu tooltip bildirim",
    desc=(
        "Bir hata olustugunda imlecin yaninda kisa bir ipucu cikar. Kapatirsan "
        "hata yine log'a ve tepsi simgesine (kirmizi + sayac) dusmeye devam eder, "
        "yalnizca ekrani kesmez."
    ),
)

#: Dosyaya INFO da yazilsin mi. Varsayilan KAPALI: gunluk kullanimda
#: log.txt'yi dolduran satirlarin hepsi INFO ve rotasyon (512 KB x2) bir
#: gun onceki hatayi hizla disari itiyordu. Kapaliyken dosyaya yalnizca
#: WARNING+ dusuyor; konsol her zaman hepsini gorur.
FILE_INFO = setting(
    "log.fileInfo",
    "Log dosyasina INFO da yaz",
    default=False,
    # Gunluk bir tercih degil, sorun ararken acilan bir ayrinti muslugu:
    # yeri gelistirme bolumu (keypilot/dev.py).
    category=Category.DEVELOPMENT,
    tags="log kayit info ayrinti dosya gelistirme",
    desc=(
        "Acikken Files/log.txt her ayrintiyi (INFO) alir -- sorun ararken. "
        "Kapaliyken yalnizca uyari ve hatalar yazilir. Gelistirme modu kapaliysa "
        "bu ayar da yok sayilir."
    ),
    on_change=lambda value, _old: _apply_file_level(),
)

#: `lifecycle()` kayitlarina konan bayrak -- dosya handler'inin suzgeci
#: bunu gorunce seviyeye bakmadan geciriyor.
ALWAYS = "keypilot_always"

# ---- dosya bicimi ----
#
# HER KAYIT `@` ile baslar; detay blogunun ILK satiri `!` ile:
#
#     @2026-09-07 17:04:17 🔵 MainThread   keypilot: gelistirme modu zorlandi
#     @2026-09-07 17:04:18 🔴 keypilot-mag keypilot.magnifier: buyutec baslatilamadi
#     !Traceback (most recent call last):
#       File "...\magnifier.py", line 213, in _ensure_running
#         subprocess.Popen(
#     @2026-09-07 17:04:20 🔵 MainThread   keypilot: KeyPilot basladi
#
#     @ kayit basi        ! detay blogu basi        digerleri: detayin devami
#
# Iki isaret de SATIR BASINDA ve ikisi de bir seyin BASLADIGINI soyluyor.
# Traceback'in kendi girintisine DOKUNULMUYOR: girinti Python'un ciktisinda
# anlam tasiyor (hangi cerceve nerede), bizim ekledigimiz bir bosluk onu
# kaydirir ve kopyalayip yapistirinca fark edilir.
MARK_RECORD = "@"  # kaydin ilk satiri
MARK_DETAIL = "!"  # detay blogunun ilk satiri

#: Seviye adi yerine dosyaya yazilan renkli simge. Kelime yerine simge:
#: "WARNING"/"INFO" sutunu her satirda ayni genislikte gri metin, goz
#: onlarin arasindan hatayi seciyor. Renk bunu bakisla yapiyor.
LEVEL_ICONS = {
    "DEBUG": "⚪",
    "INFO": "🔵",
    "WARNING": "🟡",
    "ERROR": "🔴",
    "CRITICAL": "💥",
}
#: Simge -> seviye adi. Dosyadan okurken ad geri kazaniliyor: filtre ve
#: karsilastirmalar ADLA calisiyor, simge yalniz gorunum.
ICON_LEVELS = {icon: name for name, icon in LEVEL_ICONS.items()}

#: Uyari ve ustu -- "yalniz hatalar" suzgeci ve sayaclar buna bakiyor.
PROBLEM_LEVELS = frozenset({"WARNING", "ERROR", "CRITICAL"})

#: Bir log satirini kayda ayirir. `@` ve simge ISTEGE BAGLI: bu bicimden
#: once yazilmis dosyalar (duz `INFO`, isaretsiz satir basi) da okunuyor.
_LINE_RE = re.compile(
    r"^@?"
    r"(?P<when>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) "
    # Zaman damgasi ile seviye ARASINDA tek karakterlik bir isaret duran
    # ara bicimler oldu (`... 16:47:16 ! INFO ...`). Yutulmazsa o satirlarda
    # seviye bir kayiyor ve `!` seviye adi sanilyordu.
    r"(?:[@!.|] )?"
    r"(?P<level>\S+)\s+(?P<thread>\S+)\s+(?P<source>[^:]+): (?P<message>.*)$"
)


@dataclass(frozen=True, slots=True)
class LogLine:
    """Log DOSYASINDAN okunmus tek kayit (bellekteki `ErrorRecord` degil)."""

    when: str
    level: str  # HER ZAMAN ad ("WARNING"), simge degil
    thread: str
    source: str
    message: str
    detail: str = ""

    def with_detail(self, detail: str) -> LogLine:
        return replace(self, detail=detail)

    @property
    def time(self) -> str:
        """Yalniz saat -- listede tarihi her satirda tekrarlamamak icin."""
        return self.when[11:] if len(self.when) > 11 else self.when

    @property
    def date(self) -> str:
        return self.when[:10]

    @property
    def icon(self) -> str:
        """Seviyenin renkli simgesi. Bilinmeyen seviyede adin kendisi."""
        return LEVEL_ICONS.get(self.level, self.level)

    @property
    def is_problem(self) -> bool:
        return self.level in PROBLEM_LEVELS

    @property
    def text(self) -> str:
        """Panoya kopyalanan tam metin -- dosyadaki bicimin aynisi."""
        # Genislik dosyaya yazan bicimin aynisi (`%(threadName)-14s`):
        # kopyalanan satir log'a geri yapistirildiginda hizada dursun.
        head = (
            f"{MARK_RECORD}{self.when} {self.icon} {self.thread:<14} "
            f"{self.source}: {self.message}"
        )
        if not self.detail:
            return head
        return f"{head}\n{MARK_DETAIL}{self.detail}"


MAX_ERRORS = 50
MAX_BYTES = 512 * 1024
BACKUP_COUNT = 2

log = logging.getLogger("keypilot")

#: Dosya handler'i -- ayar degisince suzgeci buradan guncelleniyor.
_file_handler: logging.Handler | None = None

#: FILE_INFO'nun suzgecin okudugu kopyasi -- suzgec her kayitta ayar
#: nesnesine gitmesin (ve testte ayar kurulmamis olabilir).
_file_info = False


def _apply_file_level() -> None:
    """FILE_INFO ayarini calisan dosya handler'ina uygular.

    Seviye handler'in `level`'ina DEGIL suzgece bakiyor: `Logger.callHandlers`
    seviye kontrolunu suzgeclerden ONCE yapar, yani `setLevel(WARNING)` ile
    `lifecycle()` satirlarini geri getirmenin yolu kalmazdi.
    """
    from keypilot import dev

    global _file_info
    _file_info = dev.file_info()


def refresh_dev_switches() -> None:
    """Gelistirme salteri degisince cagrilir (keypilot/dev.py).

    FILE_INFO'nun kendi `on_change`i yetmiyor: ana salter degistiginde o
    ayarin DEGERI degismiyor, yalnizca gecerliligi degisiyor.
    """
    _apply_file_level()


def _file_filter(record: logging.LogRecord) -> bool:
    """Dosyaya ne yazilacagina karar verir.

    FILE_INFO kapaliyken dosyaya yalnizca WARNING+ dusuyordu ve "basladi /
    kapaniyor / yeniden baslatiliyor" satirlarinin hepsi INFO. Sonuc: program
    kapandiktan sonra log'da NEDEN kapandigina dair tek satir yoktu --
    duzgun cikis mi, devralma mi, yeniden baslatma mi, cokme mi ayirt
    edilemiyordu. Bu bir avuc satir gunluk gurultu degil, kapanisin tek tanigi;
    `lifecycle()` onlari ayara bakmadan geciriyor.
    """
    return (
        record.levelno >= logging.WARNING
        or _file_info
        or getattr(record, ALWAYS, False)
    )


class MarkFormatter(logging.Formatter):
    """Dosya bicimini yazan taraf (bkz. dosya basi).

    Iki is yapiyor:

    1. Seviye ADI yerine renkli simge (`%(icon)s`).
    2. Detay blogunun ILK satirina `!` koyar. Blogun geri kalanina
       DOKUNMAZ -- traceback'in kendi girintisi Python'un ciktisindaki
       anlami tasiyor.

    Satir basindaki `@` bicim dizgisinde sabit: her kayitta var.
    """

    def format(self, record: logging.LogRecord) -> str:
        record.icon = LEVEL_ICONS.get(record.levelname, record.levelname)
        return super().format(record)

    def formatException(self, ei) -> str:
        return MARK_DETAIL + super().formatException(ei)

    def formatStack(self, stack_info: str) -> str:
        return MARK_DETAIL + super().formatStack(stack_info)


def lifecycle(message: str, *args) -> None:
    """Yasam dongusu satiri: INFO seviyesinde ama dosyaya HER ZAMAN yazilir."""
    log.info(message, *args, extra={ALWAYS: True})


@dataclass(frozen=True, slots=True)
class ErrorRecord:
    """Bellekteki tek hata kaydi.

    `text` ozeti ve detayi BIRLIKTE tutar (menu ve pano bunu istiyor);
    `summary`/`detail` ayrimini pencere kullaniyor -- traceback listede
    degil alttaki panelde durmali. Ayrim veri seviyesinde YOKTU ve "son
    hatalar" penceresi 15 traceback'i alt alta basip ekrani asiyordu.
    """

    when: datetime
    level: str
    text: str
    source: str = ""  # logger adi: keypilot.magnifier
    thread: str = ""

    @property
    def line(self) -> str:
        return f"{self.when:%H:%M:%S} {self.level:<7} {self.text}"

    @property
    def summary(self) -> str:
        """Ilk satir -- listede gorunen kisim."""
        return self.text.splitlines()[0] if self.text else ""

    @property
    def detail(self) -> str:
        """Ilk satirdan sonrasi (traceback). Yoksa bos."""
        _, _, rest = self.text.partition("\n")
        return rest


class ErrorStore(logging.Handler):
    """Son hatalari bellekte tutar. AHK: ErrorHandler.lastFullError +
    getRecentErrors."""

    def __init__(self, limit: int = MAX_ERRORS) -> None:
        super().__init__(level=logging.WARNING)
        self._items: deque[ErrorRecord] = deque(maxlen=limit)
        self._lock = threading.Lock()
        #: Yeni kayit gelince cagrilir (level, text). Hata HANGI THREAD'den
        #: gelirse gelsin buradan haber ediliyor -- abone Qt tarafindaysa
        #: sinyal uzerinden ana thread'e gecmek ZORUNDA.
        self._subs: list[Callable[[str, str], None]] = []

    # logging.Handler
    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        if record.exc_info:
            text += "\n" + "".join(traceback.format_exception(*record.exc_info))
        self.add(record.levelname, text, record.name, record.threadName or "")

    def add(self, level: str, text: str, source: str = "", thread: str = "") -> None:
        with self._lock:
            self._items.append(
                ErrorRecord(
                    when=datetime.now(),
                    level=level,
                    text=text.strip(),
                    source=source,
                    thread=thread,
                )
            )
        for callback in tuple(self._subs):
            with contextlib.suppress(Exception):  # abone loglamayi kirmasin
                callback(level, text)

    def subscribe(self, callback: Callable[[str, str], None]) -> None:
        self._subs.append(callback)

    def unsubscribe(self, callback: Callable[[str, str], None]) -> None:
        """Abonelikten cikar. KAPANISTA SART: `errors` modul duzeyinde tek
        ornek, yani kapanan bir KeyPilot abone kalirsa olu nesnesine hata
        akmaya devam eder (ve o nesne pencere aciyor)."""
        with contextlib.suppress(ValueError):
            self._subs.remove(callback)

    @property
    def items(self) -> tuple[ErrorRecord, ...]:
        with self._lock:
            return tuple(self._items)

    @property
    def last(self) -> ErrorRecord | None:
        items = self.items
        return items[-1] if items else None

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


#: Tek ortak depo -- menu ve durum penceresi buradan okur.
errors = ErrorStore()


def setup(level: int = logging.INFO) -> None:
    """Kok logger'i kurar ve butun hata kanallarini baglar.

    Iki kez cagrilmasi zararsiz (restart yolunda oluyor): eldeki
    handler'lar temizlenip yeniden kuruluyor.
    """
    paths.ensure_files_dir()

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = MarkFormatter(
        MARK_RECORD + "%(asctime)s %(icon)s %(threadName)-14s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    global _file_handler
    _file_handler = None
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            paths.LOG, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        # Suzgec handler'da, root'ta DEGIL: konsol ve ErrorStore ayrinti
        # gormeye devam etsin.
        file_handler.addFilter(_file_filter)
        root.addHandler(file_handler)
        _file_handler = file_handler
        _apply_file_level()
    except OSError:
        pass  # yazilamiyorsa program yine calissin; konsol handler'i kalir

    # Gorunur konsolda calisirken (hotkey.vbs cokme sonrasi sorar) konsola da bassin.
    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    root.addHandler(errors)

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    log.critical("yakalanmamis hata", exc_info=(exc_type, exc_value, exc_tb))


def _thread_excepthook(args) -> None:
    if issubclass(args.exc_type, SystemExit):
        return
    log.critical(
        "thread hatasi (%s)",
        args.thread.name if args.thread else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def install_qt_handler() -> None:
    """Qt'nin kendi uyarilarini da log'a alir. QApplication'dan once cagrilmali.

    Ayri fonksiyon cunku setup() PySide6 olmadan da (testte) calisabilsin.
    """
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode, context, message: str) -> None:
        logging.getLogger("qt").log(levels.get(mode, logging.INFO), "%s", message)

    qInstallMessageHandler(handler)


def parse_log_text(text: str) -> tuple[LogLine, ...]:
    """Log metnini kayitlara ayirir. ESKI bicimdeki satirlari da okur.

    Kural sirasi:

        `@` + zaman damgasi -> YENI kayit
        `!` ile baslayan     -> DETAY blogunun ilk satiri (isaret soyulur)
        digerleri            -> detayin devami, OLDUGU GIBI

    Eski dosyalar icin `@` ve simge istege bagli: bicim degisti diye
    gecmis log okunamaz olmamali.
    """
    records: list[LogLine] = []
    details: list[list[str]] = []
    for raw in text.splitlines():
        match = _LINE_RE.match(raw)
        if match:
            level = match["level"]
            records.append(
                LogLine(
                    when=match["when"],
                    # Simge de ad da kabul: dosyada simge duruyor, kod
                    # her yerde ADLA calisiyor.
                    level=ICON_LEVELS.get(level, level),
                    thread=match["thread"],
                    source=match["source"],
                    message=match["message"],
                )
            )
            details.append([])
            continue
        if raw.strip() == MARK_DETAIL:
            # Kisa omurlu bir ara bicimde `!` blogun SONUNA tek basina
            # konuyordu; bugun bir kaydin parcasi degil.
            continue
        # `| ` kisa omurlu bir ara bicimdi; donmus yedeklerde (log.txt.1)
        # kalmis olabilir. `!` disindaki satirlar OLDUGU GIBI aliniyor:
        # traceback'in girintisi Python'un ciktisindaki anlami tasiyor.
        if raw.startswith(MARK_DETAIL):
            line = raw[1:]
        elif raw.startswith("| "):
            line = raw[2:]
        else:
            line = raw
        if not records:
            # Rotasyon dosyayi bir traceback'in ORTASINDAN kesmis olabilir;
            # bas taraftaki oksuz satirlar atilmasin.
            records.append(
                LogLine(when="", level="", thread="", source="",
                        message="(onceki dosyanin devami)")
            )
            details.append([])
        details[-1].append(line)
    return tuple(
        record.with_detail("\n".join(lines))
        for record, lines in zip(records, details, strict=True)
    )


def read_log(path=None, limit: int = 0) -> tuple[LogLine, ...]:
    """Log dosyasini okur. `limit` > 0 ise yalnizca SON o kadar kayit."""
    target = paths.LOG if path is None else path
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    records = parse_log_text(text)
    return records[-limit:] if limit > 0 else records


def clear_log(path=None) -> bool:
    """Log dosyasini bosaltir (pencere altindaki "log temizle" dugmesi).

    Dosya SILINMIYOR, iceriginin uzerine yaziliyor: calisan handler acik
    tutamaci elinde tutuyor, dosyayi silmek onu kor birakirdi.
    """
    target = paths.LOG if path is None else path
    try:
        target.write_text("", encoding="utf-8")
    except OSError:
        log.exception("log dosyasi temizlenemedi")
        return False
    return True


def recent_text(limit: int = 10) -> str:
    """AHK: getRecentErrors -- menude ve panoda gosterilecek metin."""
    items = errors.items[-limit:]
    if not items:
        return "hata yok"
    return "\n".join(item.line for item in items)
