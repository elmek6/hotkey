"""Log penceresi -- ui/log_view.py'nin Flet karsiligi.

DORDUNCU TASINAN PANEL. Yeni bir engel getirmiyor, buyuk: iki sekme,
suzgec, acilir detay satirlari ve dort dugme. Adim 1'in (kisayol
haritasi) buyugu.

UC YENI SEY VAR:

    Qt'ye is yaptirma    Panoya yazma ve log temizleme QT tarafinda
                         kosmali (`_on_qt`, asagida). Onceki panellerde
                         disari yalnizca "sunu yap" haberi gidiyordu;
                         burada panel isin SONUCUNU da bekliyor
                         (temizlenen dosya yeniden okunuyor).
    zamanlayici          Dosya degisti mi diye 1.5 saniyede bir bakiliyor.
                         `QTimer` Qt tarafinda kaliyor: dosya okuma ana
                         thread'in isi, Flet dongusunu mesgul etmiyor.
    acilir satir         Qt `setSpan` + hucre widget'i ile yapiyordu.
                         Flet'te satirlar `DataTable` degil elle kurulan
                         `Row`lar; detay, satirin hemen ardina eklenen
                         ikinci bir denetim.

TABLO NEDEN `DataTable` DEGIL: `DataTable` satir birlestirme (span)
bilmiyor, yani "satirin altinda tam genislikte detay kutusu" kurulamiyor.
Satirlar elle kuruldugu icin sutun genislikleri de elle veriliyor --
Qt'deki `resizeColumnsToContents` yerine sabit genislikler, yalniz
`kaynak` sutunu veriye gore hesaplaniyor.

Qt surumunden farklar (bilerek):

    cift tik      Qt'de satiri kopyaliyordu. Flet `Container`da cift
                  dokunma olayi yok; "Satiri kopyala" dugmesi ayni isi
                  yapiyor.
    sutun olcusu  Qt icerige gore olcuyordu; burada sabit (bkz. yukarida).
    onay kutusu   "Log temizle" onayi `QMessageBox` yerine pencerenin
                  KENDI icinde bir `AlertDialog` -- kutu iki motorun
                  arasinda kalmasin.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable

import flet as ft
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from keypilot import logs, paths
from keypilot.fui import theme
from keypilot.fui.engine import FletEngine

#: Dosyadan OKUNAN en fazla kayit -- en yenilerden geriye. Suzgec
#: bunlarin hepsinde ariyor.
MAX_ROWS = 2000

#: Ekrana CIZILEN en fazla satir (suzgecten gecenlerin en yenileri).
#:
#: Qt'de boyle bir sinir yoktu, gerekmiyordu da: `QTableWidget` 2000
#: satiri aninda ciziyordu. Flet'te her satir Flutter istemcisine
#: gonderilen bir denetim agaci ve maliyet satir sayisiyla dogru
#: orantili -- olculdu: 2000 satir 2.3 sn, ustelik cizim bitene kadar
#: pencere baska hicbir seye (Esc, dugme, kaydirma) yanit vermiyor.
#: 512 KB'lik dolu bir log ~2900 kayit demek, yani bu VARSAYIMSAL bir
#: durum degil.
#:
#: Kesilen ucun kaybi kucuk: liste zaten sona kayiyor ve bakilan sey en
#: yeni kayitlar. Suzgec TUM `MAX_ROWS` kaydi tariyor, yani eski bir
#: kaydi aramak hala calisiyor -- yalnizca ayni anda ekranda durabilecek
#: satir sayisi sinirli. Durum satiri kesildigini soyluyor.
RENDER_LIMIT = 500

#: Dosya degisti mi diye bakma araligi. Ayristirma 512 KB'lik dosyada
#: milisaniyeler suruyor ama gereksizse hic yapilmiyor: yalniz mtime
#: degisince yeniden okunuyor.
POLL_MS = 1500

#: Filtre kutusunda yazma bittikten sonra cizime kadar beklenen sure.
#: Qt'de `QTimer` idi; burada Flet dongusunde bir `asyncio.sleep`.
FILTER_MS = 150

#: Detayi olan kaydin mesajinin SONUNA konan simge: "devami var, tikla".
DETAIL_MARK = "▾"

#: Acilan detay kutusunun en fazla kac satir yer kaplayacagi.
MAX_DETAIL_LINES = 16

#: Qt `resize(980, 620)`.
SIZE = (980, 620)

#: `_draw(scroll=...)`: listenin SONUNA kaydir. Flet'te `scroll_to`
#: eksi bir konumu "en son" diye anliyor (Qt `scrollToBottom`).
SCROLL_END = -1.0

COLUMNS = ("tarih", "saat", "sev", "kaynak", "mesaj")

#: `sev` sutununun piksel genisligi. TEK ayri sutun bu: seviyenin simgesi
#: emoji ve emoji Consolas'ta sabit genislikte DEGIL -- ayni satirdaki
#: metne karistirilirsa sonraki sutunlar kayiyor.
W_LEVEL = 26

#: Kalan sutunlar TEK bir yazi olarak diziliyor (bkz. `line_text`):
#: tarih 10, saat 8 karakter sabit; `kaynak` veriye gore, bu sinirlar
#: icinde. Kisa kaynak adlarinda bos yer, uzun olanlarda mesaji ezme
#: olmasin.
SOURCE_MIN_CHARS = 12
SOURCE_MAX_CHARS = 26

MONO = "Consolas"
TEXT_SIZE = 12
#: Bir log satirinin yuksekligi -- detay kutusunun boyu da bundan cikiyor.
LINE_H = 18
ROW_PAD = 3


def source_chars(records: tuple[logs.LogLine, ...]) -> int:
    """`kaynak` sutunu KAC KARAKTER: en uzun kaynak adi, sinirlar icinde."""
    longest = max((len(record.source) for record in records), default=0)
    return min(max(longest, SOURCE_MIN_CHARS), SOURCE_MAX_CHARS)


def line_text(record: logs.LogLine, source_width: int) -> str:
    """Bir kaydin `sev` DISINDAKI sutunlari, tek satir halinde.

    Neden tek yazi: sutun basina bir `ft.Text` kurmak satiri yediye
    cikariyordu ve `page.update()` denetim sayisiyla dogru orantili --
    545 kayitta yarim saniye. Yazi tipi zaten sabit genislikte (Qt
    surumu de monospace kullaniyordu), yani hizalama dolguyla saglanir.
    """
    message = f"{record.message} {DETAIL_MARK}" if record.detail else record.message
    return f"{record.date} {record.time} {record.source:<{source_width}} {message}"


def detail_height(detail: str) -> float:
    """Acilan kutunun yuksekligi. Ustu kutunun KENDI kaydirmasina dusuyor:
    200 satirlik bir traceback listeyi tumuyle asagi itmesin."""
    lines = min(len(detail.splitlines()) or 1, MAX_DETAIL_LINES)
    return lines * LINE_H + 2 * ROW_PAD


class LogPanel(QObject):
    """Log listesi + "Durum" sekmesi. Qt'deki `LogView` ile ayni arayuz."""

    #: Pencere gizlendi. app.py bunu DINLEMIYOR (log penceresi kisayollari
    #: susturmuyor); zamanlayiciyi durdurmak icin ICERIDE kullaniliyor.
    closed = Signal()

    #: "Su isi Qt'nin ana thread'inde kostur." `FletEngine.call()`in ters
    #: yonu: pano, `QMessageBox` ve dosya okuma Flet dongusunde
    #: kosmamali. Alicisi bu nesne (ana thread'de kuruldu), yani Qt
    #: sinyali kendiliginden kuyruga aliyor.
    #:
    #: Adlandirilmis dort ayri sinyal yerine tek genel sinyal: dordu de
    #: ayni seyi soruyor. Baska paneller de isterse `fui/engine.py`ye
    #: tasinabilir (bkz. flet-plan.md).
    _on_qt = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[logs.LogLine, ...] = ()
        self._shown: list[logs.LogLine] = []
        self._stats: list[tuple[str, str]] = []
        self._stamp: tuple[float, int] | None = None  # (mtime, boyut)
        #: ACIK detaylar. Kayitlar degerle karsilastiriliyor (`LogLine`
        #: donmus bir dataclass), yani dosya yeniden okununca acik satir
        #: acik kaliyor -- nesneler yeni olsa da.
        self._open: set[logs.LogLine] = set()
        #: Secili kayit -- "Satiri kopyala" bunu aliyor.
        self._selected: logs.LogLine | None = None
        #: Suzgec gecikmesinin kacinci turu. Yazma surerken eski tur
        #: uyandiginda kendini iptal ediyor.
        self._filter_turn = 0
        #: Listenin kaydirma konumu (piksel). Detay acilip kapaninca geri
        #: konuyor: bakilan yer kacmasin.
        self._offset = 0.0
        self._source_w = SOURCE_MIN_CHARS

        self._engine = FletEngine(self._build)
        self._page: ft.Page | None = None
        self._filter: ft.TextField | None = None
        self._only_errors: ft.Checkbox | None = None
        self._list: ft.ListView | None = None
        self._status: ft.Text | None = None
        self._stats_list: ft.ListView | None = None
        self._confirm: ft.AlertDialog | None = None

        self._on_qt.connect(self._run_on_qt)

        # Pencere KAPALIYKEN maliyet sifir olmali: zamanlayici yalniz
        # gorunurken calisiyor (Qt'de showEvent / hideEvent idi).
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(lambda: self.reload())
        self.closed.connect(self._timer.stop)

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def set_stats(self, rows: list[tuple[str, str]]) -> None:
        """"Durum" sekmesini doldurur -- (olcum, deger) ciftleri."""
        self._stats = list(rows)
        self._engine.call(self._render_stats)

    def show_log(self) -> None:
        """Pencereyi acar/one getirir ve dosyayi tazeler."""
        self.reload(force=True)
        self._timer.start()
        if self._engine.page is None:
            # Sayfa yok: thread'i baslat, `_build` okunan kayitlarla
            # kendini cizecek. Beklemiyoruz -- ana thread 3.5 saniye
            # donarsa tepsi takilir.
            self._engine.start()
            return
        self._engine.call(self._show_now)

    def close(self) -> None:
        """Pencereyi gizle. `app.py` `_shutdown` bunu cagiriyor."""
        self._timer.stop()
        self._engine.call(self._hide_now)

    def shutdown(self) -> None:
        """Program kapaniyor: Flet istemcisini (`flet.exe`) gercekten kapat."""
        self._timer.stop()
        self._engine.stop()

    def reload(self, force: bool = False) -> None:
        """Dosya degistiyse yeniden okur. `force` ise her halukarda.

        ANA THREAD'DE kosuyor (zamanlayici da buradan tetikliyor): dosya
        okuma ve ayristirma Flet dongusunu bekletmemeli.
        """
        stamp = self._file_stamp()
        if not force and stamp == self._stamp:
            return
        self._stamp = stamp
        self._rows = logs.read_log(limit=MAX_ROWS)
        self._source_w = source_chars(self._rows)
        self._engine.call(self._draw)

    # -- Flet -> Qt ---------------------------------------------------------

    @staticmethod
    def _run_on_qt(job: Callable[[], None]) -> None:
        """`_on_qt` sinyalinin alicisi -- ana thread'de kosar."""
        job()

    def _copy_selected(self) -> None:
        """"Satiri kopyala". Pano QT nesnesi: ana thread'de yazilmali."""
        record = self._selected
        if record is None:
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(record.text)

    def _clear_log(self) -> None:
        """Onay ALINDIKTAN sonra: dosyayi bosalt ve listeyi tazele."""
        logs.clear_log()
        logs.errors.clear()
        self._open.clear()
        self._selected = None
        self.reload(force=True)

    @staticmethod
    def _open_file() -> None:
        """Log dosyasini Notepad ile acar. Qt gerekmiyor ama dosya isi:
        Flet dongusunu bloklamasin diye o da ana thread'e gidiyor."""
        try:
            paths.ensure_files_dir()
            paths.LOG.touch(exist_ok=True)
            subprocess.Popen(["notepad.exe", str(paths.LOG)])  # noqa: S603, S607
        except OSError:
            logs.log.exception("log dosyasi acilamadi")

    @staticmethod
    def _file_stamp() -> tuple[float, int] | None:
        try:
            info = paths.LOG.stat()
        except OSError:
            return None
        return (info.st_mtime, info.st_size)

    # -- Flet thread'i: kurulum ---------------------------------------------

    def _build(self, page: ft.Page) -> None:
        """Sayfa hazir. Denetimleri kur ve hemen goster (FLET thread'i)."""
        self._page = page
        page.title = "KeyPilot - log"
        page.bgcolor = theme.BG
        page.padding = 8
        page.window.width, page.window.height = SIZE
        # Kapatma DUSMESIN: `ft.run` doner, thread olur ve bir sonraki
        # acilis 3.5 saniyeyi yeniden odetirdi.
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        self._filter = ft.TextField(
            hint_text="filtre: metin, kaynak ya da seviye (ornek: magnifier)",
            # Cizim GECIKMELI: her tusa basista 2000 satir yeniden
            # kuruluyordu. Yazma bitince bir kez ciziliyor.
            on_change=lambda _e: self._engine.call(self._filter_later),
            dense=True,
            text_size=TEXT_SIZE,
            color=theme.FG,
            bgcolor=theme.FIELD_BG,
            border_color=theme.BORDER,
            border_radius=4,
            content_padding=8,
            expand=True,
        )
        # Gunluk soru "ne patladi", ayrinti satirlari onu bogar.
        self._only_errors = ft.Checkbox(
            label="Yalniz hata/uyari",
            value=False,
            on_change=lambda _e: self._engine.call(self._draw),
            label_style=ft.TextStyle(color=theme.FG, size=TEXT_SIZE),
        )
        self._list = ft.ListView(
            controls=[],
            spacing=0,
            expand=True,
            on_scroll=self._on_scroll,
        )
        self._status = ft.Text("", color=theme.MUTED, size=TEXT_SIZE, font_family=MONO)
        self._stats_list = ft.ListView(controls=[], spacing=2, expand=True)

        log_tab = ft.Column(
            controls=[
                ft.Row(controls=[self._filter, self._only_errors]),
                self._header_row(),
                self._list,
                ft.Row(
                    controls=[
                        self._status,
                        ft.Container(expand=True),
                        self._button("Yenile", lambda: self._ask_qt(self._force_reload)),
                        self._button("Satiri kopyala", lambda: self._ask_qt(self._copy_selected)),
                        self._button("Dosyayi ac", lambda: self._ask_qt(self._open_file)),
                        self._button("Log temizle", self._ask_clear),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=6,
            expand=True,
        )

        # Tani sayaclari AYRI SEKMEDE: log listesinin altinda dururken hem
        # yer isgal ediyor hem de her satir degisiminde goz oraya kayiyordu.
        page.controls.append(
            ft.Tabs(
                length=2,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[
                        ft.TabBar(tabs=[ft.Tab(label="Log"), ft.Tab(label="Durum")]),
                        ft.TabBarView(
                            expand=True,
                            controls=[log_tab, self._stats_list],
                        ),
                    ],
                ),
            )
        )
        self._engine.call(self._show_now)

    def _button(self, label: str, action: Callable[[], None]) -> ft.ElevatedButton:
        return ft.ElevatedButton(
            content=ft.Text(label, size=TEXT_SIZE, color=theme.FG),
            height=30,
            bgcolor=theme.FIELD_BG,
            on_click=lambda _e: action(),
        )

    def _header_row(self) -> ft.Container:
        """Sutun basliklari -- satirlarla AYNI dolguyla dizilir."""
        date, time_, level, source, message = COLUMNS
        return ft.Container(
            bgcolor=theme.FIELD_BG,
            padding=ft.Padding(6, 4, 6, 4),
            content=ft.Row(
                spacing=8,
                controls=[
                    ft.Text(level, width=W_LEVEL, color=theme.MUTED, size=TEXT_SIZE),
                    ft.Text(
                        f"{date:<10} {time_:<8} {source:<{self._source_w}} {message}",
                        expand=True,
                        color=theme.MUTED,
                        size=TEXT_SIZE,
                        font_family=MONO,
                        no_wrap=True,
                    ),
                ],
            ),
        )

    # -- Flet thread'i: cizim -----------------------------------------------

    async def _show_now(self) -> None:
        """Pencereyi goster ve one getir (FLET thread'i)."""
        page = self._page
        if page is None:
            return
        self._render_stats()
        page.window.visible = True
        await self._draw()
        await page.window.to_front()

    def _hide_now(self) -> None:
        page = self._page
        if page is None:
            return
        page.window.visible = False
        page.update()

    async def _draw(self, scroll: float | None = SCROLL_END) -> None:
        """Satirlari kur, ekrana yaz, kaydir. Cizime giren TEK yol.

        `scroll`: `SCROLL_END` sona (Qt `scrollToBottom`), bir sayi o
        piksele, `None` kaydirma yok.

        SONA KAYDIRMA `scroll_to` ILE DEGIL `auto_scroll` ile: `scroll_to`
        Flutter istemcisine gidip donen bir cagri ve olculdu, 0.3-0.4
        saniye tutuyor. `auto_scroll` bir OZELLIK -- ayni `update()`
        icinde gidiyor, ek gidis donus yok. Belirli bir piksele donmek
        (detay acilip kapaninca) hala `scroll_to` istiyor ama o nadir.
        """
        listing = self._list
        if listing is not None:
            listing.auto_scroll = scroll == SCROLL_END
        self._render()
        if self._page is not None:
            self._page.update()
        if listing is not None and self._shown and scroll is not None and scroll != SCROLL_END:
            await listing.scroll_to(offset=scroll, duration=0)

    async def _filter_later(self) -> None:
        """Suzgec kutusu: yazma bitene kadar bekle, sonra ciz."""
        self._filter_turn += 1
        turn = self._filter_turn
        await asyncio.sleep(FILTER_MS / 1000)
        if turn == self._filter_turn:
            await self._draw()

    def _matches(self, record: logs.LogLine) -> bool:
        only_errors = bool(self._only_errors.value) if self._only_errors is not None else False
        if only_errors and not record.is_problem:
            return False
        text = self._filter.value if self._filter is not None else ""
        needle = (text or "").strip().lower()
        if not needle:
            return True
        haystack = f"{record.level} {record.source} {record.thread} {record.message}".lower()
        return needle in haystack

    def _render(self) -> None:
        """Suzgeci uygula ve satirlari yeniden kur. Qt surumuyle ayni sira.

        Ekrana YAZMIYOR ve kaydirmiyor -- onlar `_draw`in isi.
        """
        listing, status = self._list, self._status
        if listing is None or status is None:
            return
        self._shown = [record for record in self._rows if self._matches(record)]
        # Yalnizca en YENI `RENDER_LIMIT` satir ciziliyor (bkz. sabitin
        # aciklamasi). Liste zaten sona kayiyor, yani kesilen uc gorunmez.
        visible = self._shown[-RENDER_LIMIT:]

        controls: list[ft.Control] = []
        for record in visible:
            controls.append(self._line(record))
            if record.detail and record in self._open:
                controls.append(self._detail_box(record.detail))
        listing.controls = controls

        errors = sum(1 for record in self._rows if record.is_problem)
        clipped = (
            f"son {len(visible)} gosteriliyor  ·  " if len(visible) < len(self._shown) else ""
        )
        status.value = (
            f"{clipped}{len(self._shown)} / {len(self._rows)} kayit  ·  "
            f"{errors} hata-uyari  ·  {paths.LOG}"
        )

    def _line(self, record: logs.LogLine) -> ft.Container:
        """Bir log satiri: simge hucresi + geri kalan her sey tek yazi.

        Satir basina DORT denetim (kap, satir, iki yazi). Sutun basina
        bir yazi kursaydik yedi olurdu ve `page.update()` bunu doguran
        denetim sayisiyla dogru orantili -- bkz. `line_text`.
        """
        has_detail = bool(record.detail)
        color = theme.ERROR_FG if record.level in ("ERROR", "CRITICAL") else theme.FG
        if record is self._selected:
            background = theme.SELECT_BG
        elif has_detail:
            # Ayri renk, cunku "asagida bakilacak bir sey var mi" sorusu
            # listeye bakinca cevaplanmali -- ok simgesi tek basina kucuk.
            background = theme.DETAIL_BG
        else:
            background = None
        return ft.Container(
            bgcolor=background,
            padding=ft.Padding(6, ROW_PAD, 6, ROW_PAD),
            # Yalnizca ok sutunu degil SATIRIN HER YERI tiklanabilir: ok
            # sutunu bir karakter genisliginde ve isabet ettirmesi zor.
            on_click=lambda _e, r=record: self._on_line_click(r),
            content=ft.Row(
                spacing=8,
                controls=[
                    ft.Text(record.icon, width=W_LEVEL, size=TEXT_SIZE, no_wrap=True),
                    ft.Text(
                        line_text(record, self._source_w),
                        expand=True,
                        color=color,
                        size=TEXT_SIZE,
                        font_family=MONO,
                        no_wrap=True,
                    ),
                ],
            ),
        )

    def _detail_box(self, detail: str) -> ft.Container:
        """Satirin altina acilan detay kutusu.

        Kaydirma KENDI icinde ve metin SARMALANMIYOR: traceback'in
        girintisi ve satir uzunlugu anlam tasiyor.
        """
        # Sondaki bos satirlar KIRPILIYOR: log kaydinin arkasinda kalan
        # bosluk kutuyu bir avuc bos satir kadar sisiriyordu.
        text = detail.strip("\n")
        return ft.Container(
            # Zemin, ustundeki kaydin zemininin ayni: kutunun KIME ait
            # oldugu renkten anlasilsin.
            bgcolor=theme.DETAIL_BG,
            padding=ft.Padding(6, ROW_PAD, 6, ROW_PAD),
            height=detail_height(text),
            content=ft.Row(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Column(
                        scroll=ft.ScrollMode.AUTO,
                        expand=True,
                        controls=[
                            ft.Text(
                                text,
                                color=theme.FG,
                                size=TEXT_SIZE,
                                font_family=MONO,
                                no_wrap=True,
                                selectable=True,
                            )
                        ],
                    )
                ],
            ),
        )

    def _render_stats(self) -> None:
        listing = self._stats_list
        if listing is None:
            return
        listing.controls = [
            ft.Row(
                controls=[
                    ft.Text(name, width=220, color=theme.MUTED, size=TEXT_SIZE, font_family=MONO),
                    ft.Text(value, expand=True, color=theme.FG, size=TEXT_SIZE, font_family=MONO),
                ],
                spacing=8,
            )
            for name, value in self._stats
        ]
        if self._page is not None:
            self._page.update()

    # -- olaylar ------------------------------------------------------------

    def _on_scroll(self, event: ft.OnScrollEvent) -> None:
        self._offset = event.pixels

    def _on_line_click(self, record: logs.LogLine) -> None:
        """Satira tiklama: satiri secer, detayi varsa acar/kapatir."""
        self._selected = record
        if record.detail:
            if record in self._open:
                self._open.discard(record)
            else:
                self._open.add(record)
        # Bakilan yer kacmasin: acma/kapama sonrasi liste sonuna
        # atlanmiyor, kaydirma konumu geri konuyor.
        offset = self._offset
        self._engine.call(lambda: self._draw(offset))

    def _ask_qt(self, job: Callable[[], None]) -> None:
        """Isi Qt'nin ana thread'ine yolla (bkz. `_on_qt`)."""
        self._on_qt.emit(job)

    def _force_reload(self) -> None:
        self.reload(force=True)

    def _ask_clear(self) -> None:
        """"Log temizle" -- onay SART: geri donusu yok."""
        page = self._page
        if page is None:
            return
        self._confirm = ft.AlertDialog(
            modal=True,
            title=ft.Text("Log temizle", color=theme.FG),
            content=ft.Text(
                f"{paths.LOG}\n\nDosyanin icerigi silinsin mi? Geri alinamaz.",
                color=theme.FG,
                size=TEXT_SIZE,
            ),
            bgcolor=theme.FIELD_BG,
            actions=[
                ft.TextButton("Evet", on_click=lambda _e: self._confirm_clear()),
                ft.TextButton("Hayir", on_click=lambda _e: self._close_confirm()),
            ],
        )
        page.show_dialog(self._confirm)

    def _confirm_clear(self) -> None:
        self._close_confirm()
        self._ask_qt(self._clear_log)

    def _close_confirm(self) -> None:
        page = self._page
        if page is not None and self._confirm is not None:
            page.pop_dialog()

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        if event.key == "Escape":
            self._hide()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self._hide()

    def _hide(self) -> None:
        """Pencereyi gizle, thread'i YASAT, Qt'ye kapandigini bildir --
        zamanlayici orada duruyor (pencere kapaliyken maliyet sifir)."""
        self._hide_now()
        self.closed.emit()
