"""KeyPilot -- giris noktasi. Tek isi kilit + Qt + KeyPilot kurulumu.

Katmanlar (AHK'deki dosya ayriminin karsiligi):

    keypilot/keymap.py    tus tablolari, menuler, kaskadlar   AutoHotkey.ahk
    keypilot/dispatch.py  yutma/onek/jest karar mantigi       key_handler_*.ahk
    keypilot/app.py       kurulum, pano/slot/buyutec, yasam   LoadSettings/OnExit
    keypilot/core/        saf durum makineleri (Win32'siz)    Lib/*.ahk mantigi
    keypilot/win32/       isletim sistemine dokunan TEK yer   AHK'nin yerlesikleri
    keypilot/ui/          PySide6 pencereleri                 Gui/Menu/ToolTip

Hangi tusun ne yaptigi keymap.py'nin dosya basinda listeli.

Calistir:  hotkey.vbs         cift tiklama, konsol yok, normal kullanim
                              (cokerse konsolda yeniden baslatmayi kendi onerir)
           VSCode F5          "KeyPilot (ana program)"

Cikis kodlari -- gozetmen (hotkey.vbs) bunlara gore davraniyor:

    0                    normal cikis
    2  ALREADY_RUNNING   bu oturumda zaten bir KeyPilot var (cokme DEGIL)
    3  RESTART           yerimize bir cocuk baslatildi (cokme DEGIL)
    digeri               gercek cokme: uv sync + bir kez daha denenir
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from keypilot import dev, logs
from keypilot.app import KeyPilot
from keypilot.win32.instance import TAKEOVER_SECONDS, SingleInstance

#: Gozetmene (hotkey.vbs) "cokme degil" diyen cikis kodu: bu oturumda
#: zaten bir KeyPilot var. Sifirdan farkli her kodu cokme sayan gozetmen
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
    # Zorlama varsa EN BASTA soyle: "gelistirme modu kapali sanmistim"
    # diye bir sasirma olmasin -- bayrak ayari yeniyor ve ayar ekraninda
    # gorunmuyor. (Bu import ayrica dev ayarlarini ILK kaydeden satir:
    # ayar ekranindaki bolum sirasi kayit sirasindan geliyor.)
    note = dev.override_note()
    if note:
        logs.lifecycle("gelistirme modu zorlandi -- %s", note)
    logs.install_qt_handler()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("KeyPilot")

    # AHK: #SingleInstance Force -- "force", yani YENI ornek kazanir. Iki
    # ornek ayni anda hook kurarsa hangisinin tusu once gordugu garanti
    # edilemez; bu yuzden hafizadaki eski ornek once duzgunce kapatiliyor
    # (SingleInstance devralma olayi), kilit sonra aliniyor. Yeniden
    # baslatilan cocuk (--restart) da ayni yoldan gecer.
    # Ayri bir bekleme suresi verilmiyor: devralma zaten kilidi serbest
    # kalana kadar (en cok TAKEOVER_SECONDS) yokluyor -- yeniden baslatilan
    # cocuk da bu yoldan geciyor.
    lock = SingleInstance("keypilot")
    if not lock.acquired:
        # Log'a da dusuyor: "yeniden baslat dedim, geri gelmedi" vakasinda
        # geriye tek kanit bu satir -- kutuyu kapatan kimse ne gordugunu
        # bes dakika sonra hatirlamiyor.
        logs.lifecycle("kilit alinamadi, cikiliyor (kod %d)", EXIT_ALREADY_RUNNING)
        # Metin AYRINTILI: eski kutu ("Onceki KeyPilot kapanmadi") kimin
        # ayakta kaldigini SOYLEMIYORDU; kullanici yeni surumun calistigini
        # sanip eski surumle deneme yapiyordu.
        QMessageBox.warning(
            None,
            "KeyPilot baslatilamadi",
            "Yeni KeyPilot ACILMADI.\n\n"
            f"Onceki ornek {TAKEOVER_SECONDS:g} saniye icinde kapanmadi, "
            "kilit hala onda.\n\n"
            "SU AN CALISAN: ESKI ornek. Tuslari o yiyor, yaptigin "
            "degisiklikler ETKIN DEGIL.\n\n"
            f"Yeni ornek cikis kodu {EXIT_ALREADY_RUNNING} ile kapandi "
            "(cokme degil, gozetmen yeniden denemez).\n\n"
            "Cozum: tepsi menusunden eski KeyPilot'u kapat, sonra tekrar "
            "baslat.",
        )
        return EXIT_ALREADY_RUNNING

    keypilot = KeyPilot(app, lock)  # referans sart: PySide6 sinyalleri zayif tutar
    # Bizden sonra acilan ornek kilidi isterse yerimizi birakiriz.
    lock.watch_quit(keypilot.request_quit)
    try:
        return app.exec()  # EXIT_RESTART ise yerimize bir cocuk baslatildi
    finally:
        # Sebep verilmiyor: buraya olay dongusu bittikten SONRA geliniyor
        # ve gercek sebep (kullanici cikisi, devralma, oturum sonu) coktan
        # on_exit'i calistirmis olur. Bos kalirsa sebebi shutdown.py'nin
        # biraktigi isaret soyler.
        keypilot.on_exit()
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
