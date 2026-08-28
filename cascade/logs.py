"""DEVRE DISI -- loglama. Istenmedi, kendiliginden eklenmisti.

AHK'deki error_handler.ahk + log.txt karsiligiydi: Files/log.txt'ye yazar,
1 MB'da doner, 3 yedek tutar, yakalanmamis her hatayi oraya duserdi.

Kullanmak icin: asagiyi yorumdan cikar, main.py'de logs.setup() cagir.
"""

#
# from __future__ import annotations
#
# import logging
# import sys
# import threading
# from logging.handlers import RotatingFileHandler
#
# from cascade.paths import LOG, ensure_files_dir
#
# FORMAT = "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"
# DATEFMT = "%Y-%m-%d %H:%M:%S"
#
#
# def setup(level: int = logging.INFO, console: bool = True) -> logging.Logger:
#     ensure_files_dir()
#     root = logging.getLogger()
#     root.setLevel(level)
#     root.handlers.clear()
#
#     file_handler = RotatingFileHandler(
#         LOG, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
#     )
#     file_handler.setFormatter(logging.Formatter(FORMAT, DATEFMT))
#     root.addHandler(file_handler)
#
#     # pythonw.exe ile calisirken stdout yoktur; konsol handler'i ancak varsa eklenir.
#     if console and sys.stderr is not None:
#         stream = logging.StreamHandler()
#         stream.setFormatter(logging.Formatter(FORMAT, DATEFMT))
#         root.addHandler(stream)
#
#     sys.excepthook = _excepthook
#     threading.excepthook = _thread_excepthook
#     return logging.getLogger("cascade")
#
#
# def _excepthook(exc_type, exc, tb) -> None:
#     logging.getLogger("cascade").critical("yakalanmamis hata", exc_info=(exc_type, exc, tb))
#
#
# def _thread_excepthook(args) -> None:
#     logging.getLogger("cascade").critical(
#         "thread hatasi: %s", args.thread.name if args.thread else "?",
#         exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
#     )
