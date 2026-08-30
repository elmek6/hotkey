"""cascade -- giris noktasi. Tek isi kilit + Qt + Cascade kurulumu.

Katmanlar (AHK'deki dosya ayriminin karsiligi):

    cascade/keymap.py    tus tablolari, menuler, kaskadlar   AutoHotkey.ahk
    cascade/dispatch.py  yutma/onek/jest karar mantigi       key_handler_*.ahk
    cascade/app.py       kurulum, pano/slot/buyutec, yasam   LoadSettings/OnExit
    cascade/core/        saf durum makineleri (Win32'siz)    Lib/*.ahk mantigi
    cascade/win32/       isletim sistemine dokunan TEK yer   AHK'nin yerlesikleri
    cascade/ui/          PySide6 pencereleri                 Gui/Menu/ToolTip

Hangi tusun ne yaptigi keymap.py'nin dosya basinda listeli.

Calistir:  baslat.vbs         cift tiklama, konsol yok, normal kullanim
           hata-ayikla.cmd    konsol acik kalir, hatalari gorursun
           VSCode F5          "cascade (ana program)"
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from cascade import logs
from cascade.app import Cascade
from cascade.win32.instance import SingleInstance


def main() -> int:
    logs.setup()
    logs.install_qt_handler()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("cascade")

    # AHK: #SingleInstance Force -- "force", yani YENI ornek kazanir. Iki
    # ornek ayni anda hook kurarsa hangisinin tusu once gordugu garanti
    # edilemez; bu yuzden hafizadaki eski ornek once duzgunce kapatiliyor
    # (SingleInstance devralma olayi), kilit sonra aliniyor. Yeniden
    # baslatilan cocuk (--restart) da ayni yoldan gecer.
    # Ayri bir bekleme suresi verilmiyor: devralma zaten kilidi serbest
    # kalana kadar (en cok TAKEOVER_SECONDS) yokluyor -- yeniden baslatilan
    # cocuk da bu yoldan geciyor.
    lock = SingleInstance("cascade")
    if not lock.acquired:
        QMessageBox.warning(
            None, "cascade", "Onceki cascade kapanmadi; yenisi baslatilamadi."
        )
        return 1

    cascade = Cascade(app, lock)  # referans sart: PySide6 sinyalleri zayif tutar
    # Bizden sonra acilan ornek kilidi isterse yerimizi birakiriz.
    lock.watch_quit(cascade.request_quit)
    try:
        return app.exec()
    finally:
        cascade.on_exit()
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
