"""cascade -- giris noktasi. Tek isi kilit + Qt + Cascade kurulumu.

Katmanlar (AHK'deki dosya ayriminin karsiligi):

    cascade/keymap.py    tus tablolari, menuler, kaskadlar   AutoHotkey.ahk
    cascade/dispatch.py  yutma/onek/jest karar mantigi       key_handler_*.ahk
    cascade/app.py       kurulum, pano/slot/buyutec, yasam   LoadSettings/OnExit
    cascade/core/        saf durum makineleri (Win32'siz)    Lib/*.ahk mantigi
    cascade/win32/       isletim sistemine dokunan TEK yer   AHK'nin yerlesikleri
    cascade/ui/          PySide6 pencereleri                 Gui/Menu/ToolTip

Hangi tusun ne yaptigi keymap.py'nin dosya basinda listeli.

Calistir:  hotkey.vbs         cift tiklama, konsol yok, normal kullanim
                              (cokerse konsolda yeniden baslatmayi kendi onerir)
           VSCode F5          "cascade (ana program)"

Cikis kodlari -- gozetmen (hotkey.vbs) bunlara gore davraniyor:

    0                    normal cikis
    2  ALREADY_RUNNING   bu oturumda zaten bir cascade var (cokme DEGIL)
    3  RESTART           yerimize bir cocuk baslatildi (cokme DEGIL)
    digeri               gercek cokme: uv sync + bir kez daha denenir
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from cascade import logs
from cascade.app import Cascade
from cascade.win32.instance import SingleInstance

#: Gozetmene (hotkey.vbs) "cokme degil" diyen cikis kodu: bu oturumda
#: zaten bir cascade var. Sifirdan farkli her kodu cokme sayan gozetmen
#: bunun icin bosuna `uv sync` calistirip hata kutusu aciyordu.
EXIT_ALREADY_RUNNING = 2


def main() -> int:
    # GIL DEVRI: varsayilan 5 ms. Dusuk seviye hook callback'i AYRI bir
    # thread'de kosuyor ve Windows'un butcesi 300 ms; ana thread uzun bir
    # Python isi yaparken (ayar okuma, liste kurma) callback her GIL
    # devrini beklemek zorunda ve gecikme birikiyor. 1 ms'ye cekmek
    # callback'i yuk altinda one aliyor -- asilirsa hook SESSIZCE dusuyor
    # ve program ayakta gorunurken hicbir tus calismiyor.
    sys.setswitchinterval(0.001)
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
        # Log'a da dusuyor: "yeniden baslat dedim, geri gelmedi" vakasinda
        # geriye tek kanit bu satir -- kutuyu kapatan kimse ne gordugunu
        # bes dakika sonra hatirlamiyor.
        logs.lifecycle("kilit alinamadi, cikiliyor (kod %d)", EXIT_ALREADY_RUNNING)
        QMessageBox.warning(
            None, "cascade", "Onceki cascade kapanmadi; yenisi baslatilamadi."
        )
        return EXIT_ALREADY_RUNNING

    cascade = Cascade(app, lock)  # referans sart: PySide6 sinyalleri zayif tutar
    # Bizden sonra acilan ornek kilidi isterse yerimizi birakiriz.
    lock.watch_quit(cascade.request_quit)
    try:
        return app.exec()  # EXIT_RESTART ise yerimize bir cocuk baslatildi
    finally:
        cascade.on_exit()
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
