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

import logging
import logging.handlers
import sys
import threading
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from cascade import paths

MAX_ERRORS = 50
MAX_BYTES = 512 * 1024
BACKUP_COUNT = 2

log = logging.getLogger("cascade")


@dataclass(frozen=True, slots=True)
class ErrorRecord:
    when: datetime
    level: str
    text: str

    @property
    def line(self) -> str:
        return f"{self.when:%H:%M:%S} {self.level:<7} {self.text}"


class ErrorStore(logging.Handler):
    """Son hatalari bellekte tutar. AHK: ErrorHandler.lastFullError +
    getRecentErrors."""

    def __init__(self, limit: int = MAX_ERRORS) -> None:
        super().__init__(level=logging.WARNING)
        self._items: deque[ErrorRecord] = deque(maxlen=limit)
        self._lock = threading.Lock()

    # logging.Handler
    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        if record.exc_info:
            text += "\n" + "".join(traceback.format_exception(*record.exc_info))
        self.add(record.levelname, text)

    def add(self, level: str, text: str) -> None:
        with self._lock:
            self._items.append(
                ErrorRecord(when=datetime.now(), level=level, text=text.strip())
            )

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

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(threadName)-14s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            paths.LOG, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        pass  # yazilamiyorsa program yine calissin; konsol handler'i kalir

    # hata-ayikla.cmd ile calisirken konsola da bassin.
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


def recent_text(limit: int = 10) -> str:
    """AHK: getRecentErrors -- menude ve panoda gosterilecek metin."""
    items = errors.items[-limit:]
    if not items:
        return "hata yok"
    return "\n".join(item.line for item in items)
