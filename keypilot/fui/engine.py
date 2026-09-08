"""Tek Flet penceresini KENDI THREAD'inde kosturan motor.

NEDEN THREAD. Qt'de `app.exec()` ana thread'i tutuyor ve birakamaz:
tepsi, ipucu, 17 PySide penceresi ve `_drain`/`_tick` zamanlayicilari
oraya bagli. Flet'in `ft.run()` fonksiyonu da ayni seyi istiyor --
govdesi `asyncio.run(...)`, yani cagrildigi thread'i sonuna kadar
tutuyor. Ikisine birden ana thread verilemez, o yuzden Flet ARKA
thread'e aliniyor.

Bunun bedava olmasinin sebebi klavye hook'unun ZATEN ayri bir thread'de
olmasi (win32/hook.py): `SetWindowsHookEx` kendi mesaj pompasini
kuruyor, Qt'nin ana dongusune bagli degil. Yani ana thread "kutsal"
degil; Flet'i yanina koymak tuslara dokunmuyor.

    ana thread     app.exec()            Qt: tepsi, PySide pencereleri
    hook thread    GetMessage            tuslar (bu dosyadan etkilenmez)
    flet thread    ft.run() + asyncio    BU DOSYA: tek Flet penceresi

IKI YON, IKI KURAL:

    Qt  -> Flet    `call()`. Dogrudan `page.update()` cagirmak SESSIZCE
                   OLU: Flet cerceveyi bir asyncio kuyruguna birakip bir
                   `Event` set ediyor, ikisi de thread guvenli DEGIL --
                   is kuyruga girer, dongu UYANMAZ, ekranda hicbir sey
                   olmaz ve log'a tek satir dusmez.
    Flet -> Qt     QObject sinyali. Dispatcher'in durum makineleri
                   kilitsiz yazildi; `ui_open` yazmak `reset()` cagirip
                   onlara dokunuyor, yani Qt'nin ana thread'inde kosmali.
                   Alicisi ana thread'de olan bir sinyal Qt tarafindan
                   kendiliginden kuyruga alinir. Panelin KENDI `closed`
                   sinyali bu yonu kullaniyor (bkz. fui/key_map.py);
                   "su isi orada kostur" diyen genel yol ise `ask_qt()`.

OTOMATIK GUNCELLEME KAPALI. Flet 0.86 her olay isleyicisinden sonra
kendiliginden bir guncelleme yapiyor (`session.after_event`) ve izole tek
denetim `Page` oldugu icin bu HER SEFERINDE TUM SAYFA demek. Bu programda
gereksiz -- her isleyici cizimini zaten kendi yapiyor -- ve pahali:
kaydirma olayi saniyede onlarca kez geliyor, log listesinde bir tam cizim
0.4-1.0 saniye tutuyor, dongu bir daha bosalmiyor ve pencere kapatma
dugmesine bile yanit vermiyor. Bkz. `_disable_auto_update`.

PENCERE KAPANMAZ, GIZLENIR. `ft.run()` pencere kapaninca doner ve thread
oldur; bir daha acmak 3.5 saniyelik Flet basligini yeniden odetirdi.
`prevent_close` ile kapatma yakalanip pencere gizleniyor: thread ayakta
kalir, ikinci acilis aninda olur.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import signal
import threading
from collections.abc import Callable
from typing import Any

import flet as ft
from PySide6.QtCore import QObject, Signal

log = logging.getLogger("keypilot.fui.engine")

#: `stop()` thread'i bu kadar bekler. Cikista harcanan sure: Flet
#: istemcisinin kapanmasi normalde bunun cok altinda.
STOP_TIMEOUT = 2.0

_real_signal = signal.signal
_shim_installed = False


def _signal_main_only(signum, handler):  # type: ignore[no-untyped-def]
    """`signal.signal`, ana thread disindan cagrilirsa sessizce gecer.

    `ft.run()` icinde SIGINT/SIGTERM icin nazik kapanis kaydediliyor
    (flet/app.py) ve CPython bunu yalnizca ana thread'de kabul ediyor:
    arka thread'de `ValueError: signal only works in main thread` ile
    Flet daha pencereyi acmadan dusuyor.

    Kaybedilen davranis YOK: o cagri arka thread'de zaten istisna
    atiyordu, yani hicbir isleyici kurulmuyordu. Ana thread'den gelen
    cagrilar gercek `signal.signal`a gidiyor -- Qt ya da baska bir kod
    kendi isleyicisini kurmak isterse etkilenmez.
    """
    if threading.current_thread() is threading.main_thread():
        return _real_signal(signum, handler)
    return None


def _install_signal_shim() -> None:
    """Yamayi bir kez tak. Thread baslatilmadan ONCE cagrilmali."""
    global _shim_installed
    if _shim_installed:
        return
    signal.signal = _signal_main_only
    _shim_installed = True


_auto_update_disabled = False


def _disable_auto_update() -> None:
    """Flet'in "olaydan sonra kendiliginden guncelle" davranisini kapat.

    NE OLUYORDU. `BaseControl._trigger_event` isleyiciyi cagirdiktan sonra
    `session.after_event`i bekliyor; orada isleyici KENDI `update()`ini
    cagirmadiysa "otomatik guncelleme" devreye giriyor ve en yakin IZOLE
    ataya kadar yukari yuruyup onu guncelliyor. Flet'te izole isaretli tek
    denetim `Page` (`@control("Page", isolated=True)`), yani bu her zaman
    TUM SAYFANIN yeniden diff'lenmesi demek.

    Log penceresinde bunun bedeli olculdu: liste `auto_scroll` ile
    kaydiginda `on_scroll` saniyede onlarca kez geliyor, isleyicisi
    yalnizca kaydirma konumunu not ediyor (`update()` cagirmiyor) ve her
    biri 500 satirlik tam bir cizim baslatiyor -- tanesi 0.4-1.0 saniye.
    Cizim surerken dongu BASKA HICBIR SEYE bakmadigi icin isler birikiyor
    ve pencere kapanmaz oluyor. Bildirilen hata buydu.

    KAPATMAK GUVENLI, cunku bu paketteki her isleyici cizimini zaten
    acikca yapiyor: ya `page.update()` cagiriyor (`_hide_now`, `_refresh`,
    `_apply_and_update`), ya isi `call()` ile kuyruga birakiyor (`_draw`),
    ya da gorunen bir sey degistirmiyor (`_on_scroll`). Kutular da kendi
    denetimlerini guncelliyor (`show_dialog` / `pop_dialog`).

    NASIL. Flet bayragi bir `ContextVar`da tutuyor ve varsayilani MODUL
    DUZEYINDE PAYLASILAN tek bir nesne. Degeri hic `set` edilmemis bir
    baglamdan `get()` o paylasilan nesneyi veriyor; uzerinde kapatinca
    varsayilana dusen butun baglamlar kapali goruyor. `reset_auto_update`
    de bayragi ustten KOPYALADIGI icin oturum ve olay baglamlarina kapali
    olarak geciyor. Yani buranin sarti tek: `ft.run()` BASLAMADAN once,
    bayragi kimsenin ayarlamadigi bir thread'den cagrilmak. `start()`
    bunu saglar (ana thread, thread baslatilmadan once).

    Panel basina bir motor var ama ayar SUREC genelinde -- hepsi ayni
    davranisi istiyor, o yuzden bir kez.
    """
    global _auto_update_disabled
    if _auto_update_disabled:
        return
    ft.context.disable_auto_update()
    _auto_update_disabled = True


class FletEngine(QObject):
    """Bir Flet sayfasi ve onu tasiyan thread. Panel basina bir tane.

    `build` sayfa hazir olunca FLET thread'inde cagrilir; denetimleri
    orada kurmak gerekiyor.

    `QObject` mirasi `ask_qt()` icin: sinyal tasiyabilmesi gerekiyor.
    ANA THREAD'DE KURULMALI -- nesnenin thread'i sinyalin nerede
    kosacagini belirliyor ve `ask_qt`in butun anlami "Qt'nin ana
    thread'i". Paneller zaten `app.py`de kuruluyor, yani kendiliginden
    saglaniyor.
    """

    #: "Su isi Qt'nin ana thread'inde kostur" -- `call()`in TERS yonu.
    #: Disaridan `ask_qt()` ile kullanilir.
    _to_qt = Signal(object)

    def __init__(self, build: Callable[[ft.Page], None]) -> None:
        super().__init__()
        self._build = build
        self._page: ft.Page | None = None
        self._thread: threading.Thread | None = None
        self._to_qt.connect(self._run_job)

    @property
    def page(self) -> ft.Page | None:
        """Sayfa hazirsa o, degilse None. Qt tarafi buna bakip karar verir."""
        return self._page

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Thread'i baslat ve HEMEN don -- sayfa hazir olmasini BEKLEME.

        Beklemek ana thread'i 3.5 saniye dondururdu: tepsi menusu takilir,
        ipucu cizilmez, tus kuyrugu bosalmaz. Panel kendini `build`
        icinde gosteriyor, yani bekleyecek bir sey yok.
        """
        if self.alive:
            return
        _install_signal_shim()
        _disable_auto_update()
        self._thread = threading.Thread(target=self._run, name="keypilot-flet", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Pencereyi GERCEKTEN kapat ve thread'i bekle. Cikista SART.

        Pencere normalde kapanmiyor, gizleniyor (`prevent_close`, bkz.
        dosya basi). Thread daemon oldugu icin yorumlayici kapanirken
        aniden olduruluyor ve Flet kendi istemcisini (`flet.exe`)
        kapatma sansi bulamiyor: gorev cubugunda SAHIPSIZ bir pencere
        kaliyor, her oturum bir tane. `destroy` `prevent_close`u
        dinlemiyor -- pencere gercekten kapanir, `ft.run` doner ve Flet
        istemciyi kendi kapatir.
        """
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        page = self._page
        if page is not None:
            self.call(page.window.destroy)
        thread.join(STOP_TIMEOUT)
        if thread.is_alive():
            # Beklemeyi uzatmiyoruz: cikis takilmasin. Iz kaliyor ki
            # "gorev cubugunda flet penceresi kaldi" sikayetinin sebebi
            # aranabilsin.
            log.warning("Flet thread'i %.1f saniyede kapanmadi", STOP_TIMEOUT)

    def call(self, job: Callable[[], Any]) -> None:
        """Isi FLET dongusunde calistir. Arayuze dokunan tek guvenli yol.

        `job` es zamansiz olabilir: Flet 0.86'da pencereye dokunan bazi
        cagrilar (`window.to_front()`, `TextField.focus()`) coroutine
        donduruyor ve beklenmezlerse SESSIZCE hicbir sey yapmiyorlar --
        geriye yalnizca bir `RuntimeWarning` kaliyor.
        """
        page = self._page
        if page is None:
            # Sayfa daha kurulmadi ya da dongu oldu. Sessiz gecmek dogru:
            # panel bir sonraki `start()`ta guncel veriyle kendini cizer.
            return

        async def run() -> None:
            result = job()
            if inspect.isawaitable(result):
                await result

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            # Bu thread'de kosan bir dongu var: zaten Flet'teyiz, kendi
            # donguse dogrudan birakabiliriz.
            asyncio.ensure_future(run())
            return

        try:
            page.run_task(run)
        except Exception:
            # Kapanis sirasinda oturum gitmis olabilir. Sessiz dusmek
            # yerine iz birakiyoruz: "panel acilmadi" vakasinda tek kanit.
            log.exception("Flet dongusune is verilemedi")

    def ask_qt(self, job: Callable[[], None]) -> None:
        """Isi QT'NIN ANA THREAD'INDE calistir. `call()`in ters yonu.

        Panelin dugmesi bazen Flet'in yapamayacagi bir sey istiyor: panoya
        yazmak (`QApplication.clipboard`), `QFileDialog` acmak, diskten
        okumak. Bunlar Flet dongusunde kosmamali -- hem Qt nesneleri ana
        thread'e ait, hem de uzun suren is cizimi bekletiyor (dongu
        mesguken pencere Esc'e bile yanit vermiyor).

        Sinyalin alicisi bu nesne ve nesne ana thread'de kuruldu, yani Qt
        baglantiyi kendiliginden KUYRUGA aliyor: `emit` Flet thread'inde
        hemen doner, `job` ana thread'in sirasi gelince kosar.

        Adim 4'te `fui/log_view.py` icinde dogdu, adim 5'te `fui/qr.py`ye
        birebir kopyalandi; ucuncu kullanici (`fui/monitor.py`) gelmeden
        once ortak yere alindi.
        """
        self._to_qt.emit(job)

    @staticmethod
    def _run_job(job: Callable[[], None]) -> None:
        """`_to_qt`nin alicisi -- ana thread'de kosar."""
        job()

    def _run(self) -> None:
        """Flet thread'inin govdesi. `ft.run` pencere olene kadar donmez."""
        try:
            ft.run(self._on_page)
        except BaseException:
            # Dusen Flet PROGRAMI dusurmemeli: burasi arka thread, Qt
            # tarafi calismaya devam ediyor ve tuslar susmuyor.
            log.exception("Flet dongusu dustu")
        finally:
            self._page = None
            log.info("Flet dongusu bitti")

    def _on_page(self, page: ft.Page) -> None:
        self._page = page
        self._build(page)
