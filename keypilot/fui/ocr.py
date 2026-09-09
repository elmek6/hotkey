"""Gelismis OCR paneli -- ui/ocr_view.py'nin Flet karsiligi.

SEKIZINCI PANEL. Adim 7'nin kalibinin aynisi (disaridan gelen durumu
yazan form) uzerine IKI yeni sey:

  * **HEP USTTE.** Qt'de `WindowStaysOnTopHint`; Flet'te
    `page.window.always_on_top` -- adim 2'de (`fui/pause.py`) denenmis
    ve calisan bir sey, burada YENI olan penceresinin uzun sure acik
    kalmasi. Gerekcesi: secim cercevesi (`ui/snip.py`) de ustte
    duruyor, panel altina duserse kayboluyor.
  * **SECIM SIRASINDA GIZLENME.** `app.py` `_hide_over_snip` ekrani
    yeniden yakalamadan once kendi pencerelerini gizliyor -- yoksa
    panel kirpimin icine giriyor. Qt'de `isVisible()`/`hide()`/`show()`
    idi; burada `visible` bayragi + `hide()`/`show()`.

BU EKRAN DA KARAR VERMEZ ama HESAP YAPAR: kelime kutularini dizen
`core/ocr_layout.layout` her bicim/ayrac degisiminde kosuyor. O hesap
QT TARAFINDA yapiliyor (`ask_qt`), cizim sonra `call` ile geri
donuyor -- Flet dongusu bir OCR sonucunu dizerken pencere Esc'e bile
yanit vermemeli degil (adim 4'un dersi).

    Flet (kutu degisti) -> ask_qt -> _relayout (metni HESAPLA, ana thread)
                                  -> call    -> _draw (Flet thread'i)
    app.py              -> show_result / busy (ana thread)
                                  -> call    -> _draw

Qt surumunden farklar (bilerek):

    metin kutusu   Qt'de duzenlenebilir bir `QPlainTextEdit`ti
                   (kopyalamadan once elle duzeltilebiliyordu); burada
                   SECILEBILIR ama duzenlenemez bir metin. Sebep
                   hizalama: `TextField` satiri sarar, kolonlu/tablo
                   dizilimi bozulur. Yatay + dikey kaydirma
                   `fui/log_view.py`deki kalibin ayni (Row+Column
                   `scroll=AUTO`, `no_wrap` metin).
    boyut tutamagi Qt'de sag altta `QSizeGrip` vardi; Flet penceresi
                   kenarlarindan zaten boyutlandiriliyor.
    konum          Qt penceresi kendi yerinde aciliyordu; Flet de oyle.

PENCERE KAPANMIYOR, GIZLENIYOR (oteki paneller gibi). Kapatmak `closed`
yayiyor ve `app.py` bunu `snip.end_session`e bagliyor -- yani secim
cercevesi de kapaniyor. O bag AYNEN duruyor.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
from PySide6.QtCore import QObject, Signal

from keypilot.core.ocr_layout import (
    SEPARATORS,
    LayoutMode,
    Word,
    layout,
    separator_from_text,
)
from keypilot.fui import theme
from keypilot.fui.engine import FletEngine

#: AHK: GUTTERS -- kolon esigi icin hazir secenekler (duzenlenebilir kutu).
GUTTERS = ("Otomatik", "20px", "40px", "80px", "150px")

MODES = (
    ("Duz metin", LayoutMode.PLAIN),
    ("Kolonlu", LayoutMode.COLUMNS),
    ("Tablo (ayracli)", LayoutMode.TABLE),
)

SCALES = (1, 2, 3, 4)

#: AHK varsayilani.
DEFAULT_SCALE = 2

#: Qt `resize(620, 460)`. Ustteki dort etiket+kutu ciftinin yan yana
#: sigmasi icin genislik buyutuldu (PENCERE OLCUSU kurali); dar
#: pencerede satir kendini SARIYOR (`wrap=True`), kutular kirpilmiyor.
SIZE = (860, 560)

#: Sonuc metni sabit genislikte: kolonlu/tablo dizilimi ancak boyle
#: hizali kaliyor (Qt'de `QFont("Cascadia Mono")` idi).
MONO = "Cascadia Mono"
TEXT_SIZE = 12
LABEL_SIZE = 12

#: Tek satirlik denetimlerin yuksekligi -- verilmezse Material
#: varsayilani ~48 piksel (PENCERE OLCUSU kurali).
FIELD_H = 38

FIELD_STYLE = {
    "dense": True,
    "text_size": 12,
    "color": theme.FG,
    "bgcolor": theme.FIELD_BG,
    "border_color": theme.BORDER,
    "border_radius": 4,
    "content_padding": 8,
}

SEP_TIP = "Kacislar:  \\t = TAB   \\n = satir sonu   \\s = bosluk"
GUTTER_TIP = "Kolon ayraci sayilacak en kucuk bos dikey serit"


def gutter_px(text: str) -> int:
    """Kutudaki metni piksele cevirir; "Otomatik" ya da sacma deger -> 0."""
    cleaned = text.strip().lower().removesuffix("px").strip()
    try:
        return max(0, int(float(cleaned)))
    except ValueError:
        return 0


class OcrPanel(QObject):
    """OCR sonucu + dizilim ayarlari. Qt'deki `OcrView` ile ayni yuz."""

    #: "Kopyala" -- panoya yazmayi app.py yapar (pano gecmisine de dussun)
    copy_text = Signal(str)
    #: olcek degisti: yeniden OCR gerekiyor (yeni olcek)
    reocr_requested = Signal(int)
    #: "Yenile" -- ekran TEKRAR CEKILIP ayni alan yeniden okunsun.
    refresh_requested = Signal()
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        #: OCR sonucunun ham hali -- dizilim bundan hesaplaniyor.
        self._words: tuple[Word, ...] = ()
        self._lines: tuple[str, ...] = ()
        self._ms = 0.0

        #: Denetimlerin ANA THREAD'in okudugu degerleri. `scale`
        #: dogrudan `app.py`den okunuyor (`_start_ocr`).
        self._mode_index = 0
        self._sep_text = SEPARATORS[0][0]
        self._gutter_text = GUTTERS[0]
        self._scale = DEFAULT_SCALE

        #: Cizilecek durum.
        self._text = ""
        self._info = ""

        #: Pencere acik mi -- `app.py` `_hide_over_snip` buna bakiyor.
        #: Qt'de `isVisible()` idi.
        self.visible = False
        #: `hide()` ile gizlendi mi. `show()` yalnizca boyle gizlenmis
        #: pencereyi geri getiriyor -- Qt'de listeye alinan pencereler de
        #: oyleydi.
        self._hidden_for_snip = False

        self._engine = FletEngine(self._build)
        self._page: ft.Page | None = None
        self._body: ft.Text | None = None
        self._info_text: ft.Text | None = None
        self._mode: ft.Dropdown | None = None
        self._sep: ft.Dropdown | None = None
        self._scale_box: ft.Dropdown | None = None
        self._gutter: ft.Dropdown | None = None

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def show_result(self, words: tuple[Word, ...], lines: tuple[str, ...], ms: float) -> None:
        """Yeni OCR sonucu geldi: kutulari sakla, secili bicimle diz."""
        self._words, self._lines, self._ms = words, lines, ms
        self._hidden_for_snip = False
        self.visible = True
        self._relayout()
        if self._engine.page is None:
            # Sayfa yok: thread'i baslat, `_build` bu degerlerle cizecek.
            self._engine.start()
            return
        self._engine.call(self._show_now)

    def busy(self, message: str = "okunuyor...") -> None:
        """Alt satira "bekle" yazar. OCR baslarken cagriliyor."""
        self._info = message
        self._engine.call(self._draw)

    @property
    def scale(self) -> int:
        """Secili olcek. `app.py` OCR baslatirken ANA THREAD'den okuyor;
        Qt'de `self._scale.currentData()` idi."""
        return self._scale

    def hide(self) -> None:
        """Secim yeniden yakalanirken gizle (`app.py` `_hide_over_snip`).

        `close()`den farki: `closed` YAYILMIYOR -- pencere kapanmadi,
        yalnizca kirpimin disina cekildi ve birazdan `show()` ile geri
        gelecek.
        """
        if not self.visible:
            return
        self.visible = False
        self._hidden_for_snip = True
        self._engine.call(self._hide_now)

    def show(self) -> None:
        """`_hide_over_snip`in geri getirdigi yol."""
        if not self._hidden_for_snip:
            return
        self._hidden_for_snip = False
        self.visible = True
        self._engine.call(self._show_now)

    def close(self) -> None:
        """Pencereyi gizle ve `closed` yay -- `app.py` `_shutdown` ve
        Qt'nin `close()`u ile ayni is."""
        if not self.visible and not self._hidden_for_snip:
            return
        self.visible = False
        self._hidden_for_snip = False
        self._engine.call(self._hide_now)
        self.closed.emit()

    def shutdown(self) -> None:
        """Program kapaniyor: Flet istemcisini (`flet.exe`) gercekten kapat."""
        self._engine.stop()

    # -- Qt thread'i: dizilim hesabi (`ask_qt` ile) --------------------------

    def _relayout(self) -> None:
        """Bicim / ayrac / kolon esigi: OCR gerekmez, kutular yeniden
        dizilir. ANA THREAD'de kosuyor -- hesap Flet dongusune dusmemeli."""
        mode = MODES[max(0, self._mode_index)][1]
        result = layout(
            list(self._words),
            list(self._lines),
            mode,
            separator_from_text(self._sep_text),
            gutter_px(self._gutter_text),
        )
        self._text = result.text
        self._info = f"{result.info}  ·  {len(result.text)} karakter  ·  {self._ms:.0f} ms"

    def _relayout_and_draw(self) -> None:
        self._relayout()
        self._engine.call(self._draw)

    # -- Flet thread'i: kurulum ---------------------------------------------

    def _build(self, page: ft.Page) -> None:
        """Sayfa hazir. Denetimleri kur ve hemen goster (FLET thread'i)."""
        self._page = page
        page.title = "\U0001f9e0 OCR sonucu"
        page.bgcolor = theme.BG
        page.padding = 10
        page.window.width, page.window.height = SIZE
        # Secim cercevesi de ustte: panel altina duserse kaybolur
        # (Qt: `WindowStaysOnTopHint`).
        page.window.always_on_top = True
        # Kapatma DUSMESIN: `ft.run` doner, thread olur ve bir sonraki
        # acilis Flet'in baslama suresini yeniden odetirdi.
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        self._mode = ft.Dropdown(
            options=[ft.DropdownOption(key=label, text=label) for label, _m in MODES],
            value=MODES[self._mode_index][0],
            on_select=lambda _e: self._on_mode(),
            width=150,
            height=FIELD_H,
            **FIELD_STYLE,
        )
        # Duzenlenebilir: listeden secilebilir ya da elle yazilabilir
        # (Qt'de `setEditable(True)`; AHK'deki "Ozel..." satirinin yerine).
        self._sep = ft.Dropdown(
            options=[ft.DropdownOption(key=label, text=label) for label, _r in SEPARATORS],
            value=self._sep_text,
            editable=True,
            tooltip=SEP_TIP,
            on_select=lambda e: self._on_sep(e),
            on_text_change=lambda e: self._on_sep(e),
            width=150,
            height=FIELD_H,
            **FIELD_STYLE,
        )
        self._scale_box = ft.Dropdown(
            options=[ft.DropdownOption(key=f"{v}x", text=f"{v}x") for v in SCALES],
            value=f"{self._scale}x",
            on_select=lambda _e: self._on_scale(),
            width=90,
            height=FIELD_H,
            **FIELD_STYLE,
        )
        self._gutter = ft.Dropdown(
            options=[ft.DropdownOption(key=v, text=v) for v in GUTTERS],
            value=self._gutter_text,
            editable=True,
            tooltip=GUTTER_TIP,
            on_select=lambda e: self._on_gutter(e),
            on_text_change=lambda e: self._on_gutter(e),
            width=130,
            height=FIELD_H,
            **FIELD_STYLE,
        )
        self._body = ft.Text(
            self._text,
            color=theme.FG,
            size=TEXT_SIZE,
            font_family=MONO,
            # Sarma YOK: kolonlu/tablo dizilimi ancak boyle hizali kalir.
            # Tasan satir yatay kaydirmayla geliyor (asagidaki Row).
            no_wrap=True,
            selectable=True,
        )
        self._info_text = ft.Text(self._info, color=theme.MUTED, size=LABEL_SIZE)

        page.controls.append(
            ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            *self._labelled("Bicim", self._mode),
                            *self._labelled("Ayrac", self._sep),
                            *self._labelled("Olcek", self._scale_box),
                            *self._labelled("Kolon esigi", self._gutter),
                        ],
                        spacing=6,
                        # Dar pencerede kutular kirpilmasin, alt satira
                        # dussun -- Qt'de `QGridLayout` tek satirda
                        # tutuyordu ve pencere daraltilinca sikisiyordu.
                        wrap=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    # Iki eksende kaydirma: `fui/log_view.py`deki detay
                    # kutusuyla ayni kalip.
                    ft.Container(
                        expand=True,
                        bgcolor=theme.FIELD_BG,
                        border_radius=4,
                        padding=8,
                        content=ft.Row(
                            scroll=ft.ScrollMode.AUTO,
                            controls=[
                                ft.Column(
                                    scroll=ft.ScrollMode.AUTO,
                                    expand=True,
                                    controls=[self._body],
                                )
                            ],
                        ),
                    ),
                    ft.Row(
                        controls=[
                            self._info_text,
                            ft.Container(expand=True),
                            self._button(
                                "\U0001f504 Yenile",
                                self.refresh_requested.emit,
                                tooltip="Ayni alani ekrandan tekrar oku",
                                busy=True,
                            ),
                            self._button("\U0001f4cb Kopyala", self._on_copy),
                            self._button("Kapat", self._on_close_click),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=8,
                expand=True,
            )
        )
        self._engine.show_on_build(self._show_now)

    def _labelled(self, label: str, field: ft.Control) -> tuple[ft.Control, ft.Control]:
        return ft.Text(label, color=theme.MUTED, size=LABEL_SIZE), field

    def _button(
        self,
        label: str,
        job: Callable[[], None],
        *,
        tooltip: str | None = None,
        busy: bool = False,
    ) -> ft.ElevatedButton:
        """Dugmelerin isi ANA THREAD'de: ikisi sinyal yayiyor (alicilari
        Qt tarafinda), biri pencereyi kapatiyor."""

        def run() -> None:
            if busy:
                # Qt surumu de once "okunuyor..." yaziyordu.
                self._info = "okunuyor..."
                self._engine.call(self._draw)
            job()

        return ft.ElevatedButton(
            content=ft.Text(label, size=LABEL_SIZE, color=theme.FG),
            height=32,
            bgcolor=theme.FIELD_BG,
            tooltip=tooltip,
            on_click=lambda _e: self._engine.ask_qt(run),
        )

    # -- Flet thread'i: cizim -----------------------------------------------

    async def _show_now(self) -> None:
        """Pencereyi goster ve one getir (FLET thread'i)."""
        page = self._page
        if page is None:
            return
        self._draw()
        page.window.visible = True
        page.update()
        await page.window.to_front()

    def _hide_now(self) -> None:
        page = self._page
        if page is None:
            return
        page.window.visible = False
        page.update()

    def _draw(self) -> None:
        """Alanlari denetimlere yaz ve ekrana ciz. Cizime giren TEK yol."""
        page = self._page
        if page is None or self._body is None:
            return
        mode = MODES[max(0, self._mode_index)][1]
        self._body.value = self._text
        if self._info_text is not None:
            self._info_text.value = self._info
        # Ayrac yalniz tablo biciminde is goruyor; digerlerinde kapatiliyor
        # ki kullanici bosuna oynamasin (Qt'de de pasifti).
        if self._sep is not None:
            self._sep.disabled = mode is not LayoutMode.TABLE
        if self._gutter is not None:
            self._gutter.disabled = mode is LayoutMode.PLAIN
        page.update()

    # -- Flet thread'i: olaylar ---------------------------------------------

    def _on_mode(self) -> None:
        if self._mode is None:
            return
        labels = [label for label, _m in MODES]
        value = str(self._mode.value or labels[0])
        self._mode_index = labels.index(value) if value in labels else 0
        self._engine.ask_qt(self._relayout_and_draw)

    def _on_sep(self, event: ft.Event) -> None:
        self._sep_text = self._typed(event, self._sep, self._sep_text)
        self._engine.ask_qt(self._relayout_and_draw)

    def _on_gutter(self, event: ft.Event) -> None:
        self._gutter_text = self._typed(event, self._gutter, self._gutter_text)
        self._engine.ask_qt(self._relayout_and_draw)

    @staticmethod
    def _typed(event: ft.Event, box: ft.Dropdown | None, fallback: str) -> str:
        """Duzenlenebilir acilir kutunun SON metni.

        Iki olay ayni kutudan geliyor: listeden secim (`on_select`, deger
        `value`da) ve elle yazma (`on_text_change`, yeni metin olayin
        `data`sinda). Ikisini de tek yerden okuyoruz.
        """
        data = getattr(event, "data", None)
        if isinstance(data, str) and data:
            return data
        if box is not None and box.value:
            return str(box.value)
        return fallback

    def _on_scale(self) -> None:
        """Olcek degisti: yeniden OCR gerekiyor (ekran TEKRAR CEKILMEZ)."""
        if self._scale_box is None:
            return
        value = str(self._scale_box.value or f"{DEFAULT_SCALE}x")
        try:
            self._scale = int(value.removesuffix("x"))
        except ValueError:
            self._scale = DEFAULT_SCALE
        scale = self._scale
        self._info = "okunuyor..."
        self._draw()
        self._engine.ask_qt(lambda: self.reocr_requested.emit(scale))

    def _on_copy(self) -> None:
        self.copy_text.emit(self._text)

    def _on_close_click(self) -> None:
        """"Kapat" dugmesi -- ANA THREAD'de kosuyor (`_button` `ask_qt`
        ile cagiriyor), yani `close()` ile ayni yol."""
        self.close()

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        if event.key == "Escape":
            self._hide_and_notify()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self._hide_and_notify()

    def _hide_and_notify(self) -> None:
        """Esc / X: pencereyi gizle, `closed` yay. Sinyalin alicisi
        (`snip.end_session`) Qt tarafinda, kuyruga aliniyor."""
        self.visible = False
        self._hidden_for_snip = False
        self._hide_now()
        self.closed.emit()
