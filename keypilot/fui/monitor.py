"""Olay izleyici -- ui/monitor.py'nin Flet karsiligi.

ALTINCI PANEL, ASAMA 1'IN SONU. Oncekilerin hicbiri SANIYEDE ONLARCA KEZ
guncellenmiyordu; buranin tek yeni sorusu bu.

CIZIM NEDEN ARTIMLI. Onceki panellerde cizim "listeyi bastan kur"du
(`fui/log_view.py` `_render`): her satir icin YENI denetim nesneleri
uretilip `listing.controls`a atanir. Olculdu -- 400 satir, satir basina
iki denetim:

    listeyi bastan kur                 145-162 ms
    yalnizca 2 yeni satir ekle          26-31 ms
    20 yeni satir ekle                  31 ms
    hicbir sey degistirmeden update     25-30 ms

Iki sonuc cikiyor. Birincisi, bastan kurmak BES KAT pahali: saniyede 10
cizimde Flet dongusunu tumuyle doldururdu ve pencere -- log penceresinde
yasandigi gibi -- kapatma dugmesine bile yanit vermezdi. Bu yuzden
denetim nesneleri YASIYOR, her cizimde yalnizca YENI satirlar ekleniyor
(bkz. `_draw`). Ikincisi, hicbir sey degismese bile bir `page.update()`
25 ms tutuyor -- Flet agaci her seferinde bastan yuruyor. Yani cizim
SAYISI da onemli, bkz. `DRAW_MS`.

BIRIKTIR, SONRA CIZ. Qt surumunde `add()` her olayda tabloya bir satir
ekliyordu ve `QTableWidget` bunu ucuza yapiyordu. Burada `add()` yalnizca
listeye yaziyor, cizimi zamanlayici yapiyor:

    hook -> app.py `_drain` -> add()   -> deque   (ana thread, CIZMEZ)
                               QTimer  -> _draw   (Flet thread)

GORUNURLUK BAYRAGI ANA THREAD'DE. `app.py` `_drain` her turda "pencere
acik mi" diye soruyor ve kapaliyken hic beslemiyor -- kapaliyken maliyet
sifir. Qt'de bu `isVisible()` idi; Flet penceresinin durumu FLET
thread'inde ve her tus icin oraya gidip donmek olmaz. `visible` duz bir
bayrak, ana thread'in okudugu yerde duruyor.

Qt surumunden farklar (bilerek):

    sag tik menusu   Flet'te baglam menusu yok. Menudeki uc secenekten
                     ikisi (satiri, tumunu kopyala) zaten alt siradaki
                     dugmelerdi; ucuncusu HUCRE kopyalamaydi, o dustu.
    cift tiklama     Satiri panoya kopyaliyordu; Flet'te cift dokunma
                     olayi yok. Ayni is "Satiri kopyala" dugmesinde --
                     once satira tiklanip secilmesi gerekiyor.
    gecikmeli cizim  Olaylar aninda degil, en fazla `DRAW_MS` gecikmeyle
                     goruntuye giriyor.

ARAYUZ Qt surumuyle AYNI (`add` + `close`): `app.py`de degisen iki sey,
hangi sinifin kuruldugu ve "acik mi" sorusunun `isVisible()` yerine
`visible` diye sorulmasi.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

import flet as ft
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from keypilot.core.keynames import key_name
from keypilot.fui import theme
from keypilot.fui.engine import FletEngine

#: Listede tutulan en fazla olay -- Qt surumundeki sayi.
MAX_ROWS = 400

#: Cizim araligi. Her olayda cizmek yerine biriktirilip bu araliklarla bir
#: kez ciziliyor. Sayinin sebebi olcum: 400 satirlik agacta bir
#: `page.update()` degisiklik olmasa bile ~25 ms tutuyor, yani 100 ms'de
#: bir cizmek Flet dongusunun dortte birini yerdi. 150 ms'de beste biri
#: kaliyor ve gecikme goz icin hala aninda.
DRAW_MS = 150

#: Qt `resize(660, 460)`. GENISLIK BUYUTULDU: alt sirada sayac, iki onay
#: kutusu ve uc dugme yan yana duruyor; Flet'in Material denetimleri
#: Qt'nin widget'larindan genis ve 660'a sigmiyorlar (bkz. flet-plan.md
#: PENCERE OLCUSU kurali).
SIZE = (820, 520)

MONO = "Consolas"
TEXT_SIZE = 12
ROW_PAD = 2

COLUMNS = ("t", "tus", "vk", "sc", "yon", "durum")

#: Sutun genislikleri (karakter). Sabit genislikli yazi tipinde butun
#: satir TEK bir `Text`e siginca satir basina iki denetim kaliyor (kap +
#: yazi); sutun basina bir yazi kursaydik yedi olurdu ve cizim maliyeti
#: denetim sayisiyla dogru orantili.
W_T = 7  # "1234.56"
W_KEY = 16  # en uzun ad "Media_Play_Pause"
W_VK = 4  # "0xNN"
W_SC = 9  # "0xNN", fare olayinda "1920,1080"
W_DIR = 4  # "down"


def header_text() -> str:
    """Sutun basliklari -- satirlarla AYNI dolguyla dizilir."""
    t, key, vk, scan, direction, state = COLUMNS
    return (
        f"{t:>{W_T}} {key:<{W_KEY}} {vk:<{W_VK}} "
        f"{scan:<{W_SC}} {direction:<{W_DIR}} {state}"
    )


def row_text(event, elapsed: float, swallowed: bool) -> str:
    """Bir olayin satiri -- Qt surumundeki alti sutun, ayni sirada.

    ANA THREAD'de kosuyor: bicimlemenin maliyeti Flet dongusune degil,
    olayi zaten isleyen thread'e dusmeli.
    """
    # Fare olayinda tarama kodu yok; `sc` sutununda imlecin konumu yazar
    # (core/mouse.py `MouseSeen`).
    scan = (
        f"{event.x},{event.y}"
        if getattr(event, "mouse", False)
        else f"0x{event.scan:02X}"
    )
    key = key_name(event.vk, event.scan, event.extended)
    vk = f"0x{event.vk:02X}"
    direction = "down" if event.down else "up"
    state = "YUTULDU" if swallowed else ""
    return (
        f"{elapsed:{W_T}.2f} {key:<{W_KEY}} {vk:<{W_VK}} "
        f"{scan:<{W_SC}} {direction:<{W_DIR}} {state}"
    )


class MonitorPanel(QObject):
    """Olay listesi. Qt'deki `EventMonitor` ile ayni arayuz."""

    #: Pencere gizlendi. `app.py` DINLEMIYOR (bu pencere kisayollari
    #: susturmuyor); zamanlayiciyi durdurmak icin ICERIDE kullaniliyor.
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        #: (sira, satir metni, yutuldu_mu). `maxlen` eskisini kendisi
        #: dusuruyor -- Qt'de `removeRow` idi. deque'nin uclarindaki
        #: islemler kilitsiz guvenli: `add` ana thread'de yazarken `_draw`
        #: Flet thread'inde kopyasini aliyor.
        self._events: deque[tuple[int, str, bool]] = deque(maxlen=MAX_ROWS)
        #: Satirin degismez kimligi. Secili satir ve "hangileri yeni"
        #: sorusu bununla izleniyor; liste basindan eksildigi icin sira
        #: numarasi indeksten guvenli.
        self._seq = 0
        #: Cizilmis en son sira. `_draw` bundan sonrasini ekliyor.
        self._drawn = 0
        self._t0: float | None = None
        self._count = 0
        self._swallowed = 0
        #: Yeni olay geldi mi -- bosuna cizim yapilmasin.
        self._dirty = False
        #: Listeyi BASTAN kurmayi gerektiren degisiklik: sira tersine
        #: dondu, liste temizlendi ya da pencere yeni aciliyor.
        self._rebuild = False
        self._selected: int | None = None

        #: ANA THREAD'IN sorusu: "pencere acik mi". `app.py` `_drain` her
        #: turda buna bakiyor ve kapaliyken besleme yapmiyor.
        self.visible = False
        #: Kutular Flet'te ama karari ANA THREAD veriyor -- `add` bunlari
        #: okuyor. Flet tarafindan yazilan tek sey bir `bool`; bolunmez,
        #: ve `ask_qt` ile dolastirmak "Duraklat"i gecikmeli yapardi.
        self._paused = False
        self._newest_first = False

        self._engine = FletEngine(self._build)
        self._page: ft.Page | None = None
        self._list: ft.ListView | None = None
        self._status: ft.Text | None = None

        # Cizim ANA THREAD'den tetikleniyor ama Flet thread'inde kosuyor.
        # Pencere kapaliyken zamanlayici duruyor: maliyet sifir.
        self._timer = QTimer(self)
        self._timer.setInterval(DRAW_MS)
        self._timer.timeout.connect(self._flush)
        self.closed.connect(self._timer.stop)

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def show_monitor(self) -> None:
        """Pencereyi acar/one getirir. Qt'de `show`+`raise_`+`activateWindow`."""
        self.visible = True
        self._rebuild = True
        self._timer.start()
        if self._engine.page is None:
            # Sayfa yok: thread'i baslat, `_build` kendini cizecek.
            # Beklemiyoruz -- ana thread saniyelerce donarsa tepsi takilir.
            self._engine.start()
            return
        self._engine.call(self._show_now)

    def add(self, event, swallowed: bool) -> None:
        """`app.py` `_drain` her klavye/fare olayinda cagirir (pencere acikken).

        CIZMIYOR. Yaptigi is bir string bicimleyip listeye koymak; cizimi
        `DRAW_MS`lik zamanlayici yapiyor -- sebebi dosya basinda.
        """
        if self._paused:
            return
        if self._t0 is None:
            self._t0 = event.t
        self._count += 1
        if swallowed:
            self._swallowed += 1
        self._seq += 1
        self._events.append(
            (self._seq, row_text(event, event.t - self._t0, swallowed), swallowed)
        )
        self._dirty = True

    def close(self) -> None:
        """Pencereyi gizle. `app.py` `_shutdown` bunu cagiriyor."""
        self.visible = False
        self._timer.stop()
        self._engine.call(self._hide_now)

    def shutdown(self) -> None:
        """Program kapaniyor: Flet istemcisini (`flet.exe`) gercekten kapat."""
        self._timer.stop()
        self._engine.stop()

    # -- ana thread: zamanlayici, pano, liste -------------------------------

    def _flush(self) -> None:
        """Degisen bir sey varsa TEK bir cizim istegi birak (ana thread)."""
        if not self.visible or not (self._dirty or self._rebuild):
            return
        self._dirty = False
        self._engine.call(self._draw)

    def _clear(self) -> None:
        """"Temizle" dugmesi. Sayaclar ve liste ANA THREAD'de sifirlaniyor
        ki `add` ile arasina girmesin."""
        self._events.clear()
        self._count = self._swallowed = 0
        self._t0 = None
        self._selected = None
        self._drawn = 0
        self._rebuild = True

    def _copy(self, text: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None and text:
            clipboard.setText(text)

    def _copy_row(self) -> None:
        """Secili satir. Qt surumu hucreleri sekmeyle ayirip veriyordu;
        burada satir zaten tek metin ve sutunlar bosluklarla hizali."""
        selected = self._selected
        if selected is None:
            return
        for seq, text, _swallowed in tuple(self._events):
            if seq == selected:
                self._copy(text.rstrip())
                return

    def _copy_all(self) -> None:
        self._copy("\n".join(text.rstrip() for _seq, text, _sw in tuple(self._events)))

    # -- Flet thread'i: kurulum ---------------------------------------------

    def _build(self, page: ft.Page) -> None:
        """Sayfa hazir. Denetimleri kur ve hemen goster (FLET thread'i)."""
        self._page = page
        page.title = "KeyPilot - olay izleyici"
        page.bgcolor = theme.BG
        page.padding = 8
        page.window.width, page.window.height = SIZE
        # Kapatma DUSMESIN: `ft.run` doner, thread olur ve bir sonraki
        # acilis Flet'in baslama suresini yeniden odetirdi.
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        self._list = ft.ListView(controls=[], spacing=0, expand=True)
        self._status = ft.Text("", color=theme.MUTED, size=TEXT_SIZE, font_family=MONO)

        page.controls.append(
            ft.Column(
                controls=[
                    self._header_row(),
                    self._list,
                    ft.Row(
                        controls=[
                            self._status,
                            ft.Container(expand=True),
                            # AHK'de liste akarken durdurmanin yolu yoktu;
                            # olayi okumak icin pencereyi kapatmak
                            # gerekiyordu. Isaretliyken hook calismaya
                            # devam eder, yalniz bu liste yazmayi birakir.
                            self._check("Duraklat", self._on_paused),
                            # Isaretliyken yeni olay EN USTE giriyor ve
                            # liste kaymiyor -- son basilan tusa bakarken
                            # listenin pesinden kosmak gerekmesin.
                            self._check("Yeni ustte", self._on_newest),
                            self._button("Satiri kopyala", self._copy_row),
                            self._button("Tumunu kopyala", self._copy_all),
                            self._button("Temizle", self._clear),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=6,
                expand=True,
            )
        )
        self._engine.call(self._show_now)

    def _header_row(self) -> ft.Container:
        return ft.Container(
            bgcolor=theme.FIELD_BG,
            padding=ft.Padding(6, 4, 6, 4),
            content=ft.Text(
                header_text(),
                color=theme.MUTED,
                size=TEXT_SIZE,
                font_family=MONO,
                no_wrap=True,
            ),
        )

    def _button(self, label: str, job: Callable[[], None]) -> ft.ElevatedButton:
        """Dugmelerin ucu de Qt tarafinda kosmali: ikisi panoya yaziyor,
        biri ana thread'in listesine dokunuyor."""
        return ft.ElevatedButton(
            content=ft.Text(label, size=TEXT_SIZE, color=theme.FG),
            height=30,
            bgcolor=theme.FIELD_BG,
            on_click=lambda _e: self._engine.ask_qt(job),
        )

    def _check(self, label: str, on_change: Callable[[ft.Event], None]) -> ft.Checkbox:
        return ft.Checkbox(
            label=label,
            value=False,
            on_change=on_change,
            label_style=ft.TextStyle(color=theme.FG, size=TEXT_SIZE),
        )

    # -- Flet thread'i: cizim -----------------------------------------------

    async def _show_now(self) -> None:
        """Pencereyi goster ve one getir (FLET thread'i)."""
        page = self._page
        if page is None:
            return
        page.window.visible = True
        self._draw()
        await page.window.to_front()

    def _hide_now(self) -> None:
        page = self._page
        if page is None:
            return
        page.window.visible = False
        page.update()

    def _draw(self) -> None:
        """Yeni satirlari EKLE ve ekrana yaz. Cizime giren TEK yol.

        Denetim nesneleri yasiyor: her cizimde yalnizca yeni satirlar
        uretiliyor, eskiler listenin oteki ucundan dusuyor. Bastan kurmak
        bes kat pahali -- olcumu dosya basinda.
        """
        listing, page = self._list, self._page
        if listing is None or page is None:
            return
        # Kopya aliniyor: `add` ana thread'de yazmaya devam ediyor.
        events = tuple(self._events)
        newest_first = self._newest_first

        if self._rebuild:
            self._rebuild = False
            ordered = tuple(reversed(events)) if newest_first else events
            listing.controls = [self._line(row) for row in ordered]
        else:
            for row in (row for row in events if row[0] > self._drawn):
                if newest_first:
                    listing.controls.insert(0, self._line(row))
                else:
                    listing.controls.append(self._line(row))
            # `deque` kendi ucunu kirpiyor ama denetim listesi ayri
            # tutuluyor: ayni siniri burada da uygulamak gerekiyor.
            while len(listing.controls) > MAX_ROWS:
                listing.controls.pop(-1 if newest_first else 0)

        if events:
            self._drawn = events[-1][0]
        # Sona kaydirma `scroll_to` ile DEGIL `auto_scroll` ile: `scroll_to`
        # istemciye gidip donen bir cagri ve olculdu, 0.3-0.4 saniye.
        # "Yeni ustte" isaretliyken kaydirma YOK -- Qt surumu de oyleydi.
        listing.auto_scroll = not newest_first
        if self._status is not None:
            self._status.value = f"olay {self._count}    yutulan {self._swallowed}"
        page.update()

    def _line(self, row: tuple[int, str, bool]) -> ft.Container:
        """Bir olay satiri: kap + tek yazi. Satir basina IKI denetim."""
        seq, text, swallowed = row
        return ft.Container(
            # Satiri secilebilir yapan kimlik ("Satiri kopyala" bunu
            # kullaniyor); denetimi bastan kurmadan bulmayi da sagliyor.
            data=seq,
            bgcolor=theme.SELECT_BG if seq == self._selected else None,
            padding=ft.Padding(6, ROW_PAD, 6, ROW_PAD),
            on_click=lambda _e, s=seq: self._on_row_click(s),
            content=ft.Text(
                text,
                # Yutulan olaylar kirmizi -- Qt surumundeki gibi.
                color=theme.ERROR_FG if swallowed else theme.FG,
                size=TEXT_SIZE,
                font_family=MONO,
                no_wrap=True,
            ),
        )

    # -- Flet thread'i: olaylar ---------------------------------------------

    def _on_row_click(self, seq: int) -> None:
        """Satir secimi. Liste BASTAN KURULMUYOR: yalnizca iki satirin
        zemini degisiyor, cizim 25 ms."""
        previous, self._selected = self._selected, seq
        listing = self._list
        if listing is None:
            return
        for control in listing.controls:
            if control.data in (previous, seq):
                control.bgcolor = theme.SELECT_BG if control.data == seq else None
        if self._page is not None:
            self._page.update()

    def _on_paused(self, event: ft.Event) -> None:
        # Karari ANA THREAD okuyor (`add`); buradan yazilan tek sey bir
        # bool ve bolunmez.
        self._paused = bool(event.control.value)

    def _on_newest(self, event: ft.Event) -> None:
        self._newest_first = bool(event.control.value)
        # Sira tersine dondu: liste bu TEK durumda bastan kuruluyor.
        self._rebuild = True
        self._draw()

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        if event.key == "Escape":
            self._hide()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self._hide()

    def _hide(self) -> None:
        """Pencereyi gizle, thread'i YASAT, Qt'ye kapandigini bildir --
        zamanlayici orada duruyor ve `visible` bayragi burada iniyor."""
        self.visible = False
        self._hide_now()
        self.closed.emit()
