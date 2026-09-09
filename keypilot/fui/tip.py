"""Ipucu penceresi -- ui/tip.py'nin Flet karsiligi. ILK ASAMA 3 PANELI.

Onceki on iki panelden farki: bu pencerenin Flet'te dogrudan karsiligi
OLMAYAN ozellikleri var. Adim 14 bunlardan birini (odak) olcup gecti,
kalani burada cozuluyor.

    ODAK CALMAMA     Qt'de `WA_ShowWithoutActivating` gerekiyordu.
                     ADIM 14'TE OLCULDU: Flet'in VARSAYILANI zaten bu --
                     ayakta duran bir pencereyi gostermek odagi calmiyor
                     (senaryolar A-D). Yani burada yapilacak bir sey YOK;
                     `force_focus` bu panelde CAGIRILMAMALI.
    CERCEVESIZ       `frameless` + `title_bar_hidden` + `skip_task_bar`
                     Flet'te var.
    ICERIGE GORE     Qt `adjustSize()` ile pencereyi metne oturtuyordu;
    BOY              Flet'te karsiligi YOK, olcu elle veriliyor.

ICERIGE GORE BOY -- COZUM SAYDAMLIK. Pencereye "yeterince buyuk" bir olcu
verilip ZEMINI SAYDAM birakiliyor (`window.bgcolor` + `page.bgcolor`
TRANSPARENT); gorunen kutu pencerenin kendisi degil, icindeki
`Container`. Container Flet'in kendi yerlesimiyle iceriginin boyuna
oturuyor, yani "adjustSize" isini Flutter yapiyor ve artan yer saydam
kaliyor. Bu yuzden `window_size` COMERT olabilir: fazlasi gorunmuyor.

METIN HTML KALIYOR. Cagiran taraf kirk yerde `show_html` cagiriyor
(`app.py`, `clip_ctl.py`, `fui/mem_slots.py`) ve hepsi kucuk bir HTML alt
kumesi uretiyor. Arayuzu bozmamak icin (plandaki panel tasima kurali)
HTML burada `ft.TextSpan`lara CEVRILIYOR -- kullanilan butun dagarcik
tarandi: `<b>`, `<br>`, renkli `<span>`, `<div>` ve kacis dizileri.
`<i>` yalnizca ornek metinlerde geciyor ama ucuz oldugu icin destekleniyor.

MENU HTML'DEN GECMIYOR. Qt surumu `show_menu`yu bir HTML TABLOSU olarak
uretiyordu (hucre zemini `bgcolor` ile); Flet'te tablo yok ve gerek de
yok -- satirlar dogrudan denetim olarak kuruluyor. Aciklama metni yine
HTML olabilir, o parcadan geciyor.

ZAMANLAYICI ANA THREAD'DE. `ms` sonunda kendini gizleyen sayac Qt'nin
`QTimer`i; `fui/monitor.py`nin "pencere acik mi ANA THREAD'de cevaplanir"
dersinin ayni kalibi. Flet dongusune `asyncio.sleep` koymak da olurdu ama
o zaman "ipucu suresi doldu" haberi thread'ler arasi gidip donerdi.
"""

from __future__ import annotations

import html as html_mod
import logging
import re
from dataclasses import dataclass

import flet as ft
from PySide6.QtCore import QBuffer, QIODevice, QObject, Qt, QTimer
from PySide6.QtGui import QImage

from keypilot.fui import theme
from keypilot.fui.engine import FletEngine
from keypilot.win32 import screen
from keypilot.win32 import window as win
from keypilot.win32.send import cursor_pos

log = logging.getLogger("keypilot.fui.tip")

#: Kucuk resmin kenar uzunlugu -- ui/tip.py THUMB ile ayni. Depodaki thumb
#: zaten 64x64, buyutmek bulaniklastirir.
THUMB = 64

#: Kutunun ic bosluklari ve kosesi -- Qt bicem sayfasindaki degerler.
PAD = 10
GAP = 8
RADIUS = 6

#: Yazi olculeri. Qt "Segoe UI 10pt" kullaniyordu; Flet'te punto degil
#: piksel veriliyor (10pt ~ 13.3px) ve rozet sabit genislikli.
SIZE = 13
LINE = 19
MONO = "Consolas"

#: Pencere olcusu (bkz. dosya basi: zemin saydam, fazlasi gorunmuyor).
#: Yine de bir tavan var: pencere ekrandan buyuk olursa yerlestirme hesabi
#: anlamsizlasir.
MAX_WIDTH = 620
MAX_HEIGHT = 520

#: Kaba genislik hesabi icin karakter basina piksel. Segoe UI oransal,
#: yani bu bir TAHMIN; comert tarafta tutuluyor.
CHAR_PX = 7.6

#: Imlecin sag altina -- Qt surumundeki 18 piksel.
CURSOR_OFFSET = 18

#: Pencere basligi. Ekranda gorunmuyor (pencere cercevesiz) ama KIMLIK:
#: gorev cubugundan gizleme tutamagi bununla buluyor.
WINDOW_TITLE = "KeyPilot ipucu"

#: Rozet (menudeki tus) ve kutu renkleri -- ui/tip.py ile ayni.
BADGE_BG = "#30363d"
BADGE_FG = "#f0f6fc"
CARD_BG = "#1b1f24"
ACCENT = "#58a6ff"

_TAG = re.compile(r"<[^>]*>")
_COLOR = re.compile(r"color\s*:\s*(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)")

#: Bozuk HTML (kapanmayan etiket) bicim yiginini sonsuz buyutmesin.
MAX_DEPTH = 32


@dataclass(frozen=True, slots=True)
class Piece:
    """Tek bicimli bir metin parcasi -- `ft.TextSpan`in girdisi."""

    text: str
    bold: bool = False
    italic: bool = False
    color: str | None = None


def parse(body: str) -> tuple[Piece, ...]:
    """Ipucu HTML'ini bicimli parcalara ayirir.

    Desteklenen dagarcik OLCULDU (cagiran kirk yer tarandi): kalin, egik,
    satir sonu, renkli span/div ve kacis dizileri. BILINMEYEN ETIKET
    ATILIR, icindeki metin KALIR -- ipucu bir metin kutusu; tanimadigi bir
    etiket yuzunden BOS gorunmesi en kotu sonuc olurdu.

    Kapanan `div` satir sonu demek (Qt'de blok etiketti). Kapanmamis etiket
    ya da fazla kapanis PATLATMIYOR: yigin taban bicimin altina inmiyor.
    """
    pieces: list[Piece] = []
    styles: list[tuple[bool, bool, str | None]] = [(False, False, None)]
    position = 0

    def emit(text: str) -> None:
        if not text:
            return
        bold, italic, color = styles[-1]
        pieces.append(Piece(text, bold, italic, color))

    def push(style: tuple[bool, bool, str | None]) -> None:
        if len(styles) < MAX_DEPTH:
            styles.append(style)

    def pop() -> None:
        # Taban bicim ASLA atilmiyor: fazla kapanis yigini bosaltirdi.
        if len(styles) > 1:
            styles.pop()

    for match in _TAG.finditer(body):
        emit(html_mod.unescape(body[position : match.start()]))
        position = match.end()
        tag = match.group(0)
        closing = tag.startswith("</")
        bare = tag.strip("<>/ ")
        name = bare.split()[0].lower() if bare else ""
        bold, italic, color = styles[-1]
        if name == "br":
            emit("\n")
        elif name in ("b", "strong"):
            if closing:
                pop()
            else:
                push((True, italic, color))
        elif name in ("i", "em"):
            if closing:
                pop()
            else:
                push((bold, True, color))
        elif name in ("span", "div", "font"):
            if closing:
                pop()
                if name == "div":
                    emit("\n")
            else:
                found = _COLOR.search(tag)
                push((bold, italic, found.group(1) if found else color))
        # Bilinmeyen etiket: yalnizca atiliyor, metni kaliyor.
    emit(html_mod.unescape(body[position:]))
    return _tidy(pieces)


def _tidy(pieces: list[Piece]) -> tuple[Piece, ...]:
    """Bitisik ayni bicimli parcalari birlestir, bastaki/sondaki bos
    satirlari at. Az parca az `TextSpan` demek (bkz. cizim maliyeti)."""
    merged: list[Piece] = []
    for piece in pieces:
        last = merged[-1] if merged else None
        if last is not None and (last.bold, last.italic, last.color) == (
            piece.bold,
            piece.italic,
            piece.color,
        ):
            merged[-1] = Piece(last.text + piece.text, last.bold, last.italic, last.color)
        else:
            merged.append(piece)
    if merged:
        first = merged[0]
        merged[0] = Piece(first.text.lstrip("\n"), first.bold, first.italic, first.color)
        last = merged[-1]
        merged[-1] = Piece(last.text.rstrip("\n"), last.bold, last.italic, last.color)
    return tuple(piece for piece in merged if piece.text)


def text_of(pieces: tuple[Piece, ...]) -> str:
    """Parcalarin duz metni -- olcu hesabi ve testler icin."""
    return "".join(piece.text for piece in pieces)


def window_size(pieces: tuple[Piece, ...], has_image: bool = False) -> tuple[int, int]:
    """Pencere olcusu. COMERT olabilir: fazlasi saydam (bkz. dosya basi).

    Yine de icerikle buyuyor, cunku sabit buyuk bir pencere ekranin
    kenarinda yerlestirme hesabini bozardi -- imlec sag alttayken kutu
    gereksiz yere ice cekilirdi.
    """
    lines = text_of(pieces).split("\n")
    widest = max((len(line) for line in lines), default=0)
    width = 2 * PAD + round(widest * CHAR_PX) + 16
    if has_image:
        width += THUMB + GAP
    height = 2 * PAD + max(len(lines), 1) * LINE + 8
    if has_image:
        height = max(height, 2 * PAD + THUMB)
    return (max(120, min(width, MAX_WIDTH)), max(48, min(height, MAX_HEIGHT)))


def place(
    width: int, height: int, cursor: tuple[int, int] | None = None
) -> tuple[int, int]:
    """Imlecin sag alti -- MANTIKSAL pikselde (Flet `window.left/top`).

    Iki cevrim birden: `cursor_pos` ve calisma alani FIZIKSEL piksel
    veriyor (bkz. `win32/screen.py` dosya basi), Flutter ise mantiksal
    piksel istiyor. Bu makinede OLCULEN olcek 1.10 -- uc monitorde de ayni,
    yani plandaki "%135" notu artik gecerli degil. Ham koordinat
    verilseydi pencere yuzlerce piksel sapardi.

    Ekran disina tasarsa ice cekiliyor; Qt surumunun `_place`i ile ayni
    kural, tek farki olceklerin ELLE cevrilmesi.
    """
    x, y = cursor if cursor is not None else cursor_pos()
    scale = screen.dpi_scale_at(x, y) or 1.0
    left, top, right, bottom = screen.work_area_at(x, y)
    # Hesap MANTIKSAL pikselde: pencere olcusu de mantiksal.
    logical_x = (x + CURSOR_OFFSET) / scale
    logical_y = (y + CURSOR_OFFSET) / scale
    logical_x = min(logical_x, right / scale - width - 4)
    logical_y = min(logical_y, bottom / scale - height - 4)
    return (
        round(max(logical_x, left / scale + 4)),
        round(max(logical_y, top / scale + 4)),
    )


def png_bytes(image: QImage | None) -> bytes | None:
    """`QImage` -> PNG bayti. Flet'in `ft.Image`i kodlanmis bayt istiyor.

    `fui/clip_images.py` `thumb_png` ile ayni gerekce; orada kaynak HAM
    tampon, burada zaten bir `QImage` (`clip_ctl.thumb_image` veriyor), o
    yuzden ayri bir govde. ANA THREAD'de kosuyor -- cagiran `show_html`
    zaten orada.
    """
    if image is None or image.isNull():
        return None
    if image.width() > THUMB or image.height() > THUMB:
        image = image.scaled(
            THUMB,
            THUMB,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        log.warning("ipucu kucuk resmi PNG'ye cevrilemedi")
        return None
    return bytes(buffer.data())


class TipPanel(QObject):
    """Ipucu penceresi. Qt'deki `Tip` ile AYNI arayuz.

    `app.py`de degisen tek sey hangi sinifin kuruldugu: `show_html`,
    `show_text`, `show_menu` ve `hide` ayni imzalarla duruyor. Eklenen iki
    metot Flet'e ozgu: `warm` (on isitma) ve `shutdown` (`flet.exe`).
    """

    def __init__(self) -> None:
        super().__init__()
        self._engine = FletEngine(self._build)
        self._page: ft.Page | None = None
        self._body: ft.Column | None = None
        # Gosterilecek icerik. `_build` bitmeden gelen cagri da buraya
        # yaziyor; panel kendini bu veriyle ciziyor (YASAYAN PANEL kurali).
        self._pieces: tuple[Piece, ...] = ()
        self._rows: tuple[tuple[str, str], ...] = ()
        self._title = ""
        self._footer = ""
        self._menu = False
        self._thumb: bytes | None = None
        self._spot: tuple[int, int] = (0, 0)
        self._size: tuple[int, int] = (200, 60)
        # Gorev cubugundan gizleme BIR KEZ yapiliyor (bkz.
        # `_hide_from_taskbar`); pencere tutamagi ancak `flet.exe` ayaga
        # kalkinca bulunuyor, o yuzden basarilana kadar deneniyor.
        self._hidden_from_taskbar = False
        # Kendi kendine gizlenme -- ANA THREAD'de (bkz. dosya basi).
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def show_html(self, body: str, ms: int = 0, image: QImage | None = None) -> None:
        """Ham HTML -- ui/tip.py ile ayni imza (`image` bellekten gelir)."""
        self._menu = False
        self._pieces = parse(body)
        self._thumb = png_bytes(image)
        self._arm(ms)

    def show_text(self, text: str, ms: int = 0) -> None:
        """Duz metin: HTML olarak yorumlanmaz, satir sonlari korunur."""
        self.show_html(html_mod.escape(text).replace("\n", "<br>"), ms)

    def show_menu(
        self,
        title: str,
        items: tuple[tuple[str, str], ...],
        footer: str = "Esc  iptal",
        ms: int = 0,
    ) -> None:
        """Baslik + "tus  aciklama" listesi -- AHK autoPreview'in karsiligi."""
        self._menu = True
        self._title = title
        self._rows = tuple(items)
        self._footer = footer
        self._thumb = None
        self._pieces = ()
        self._arm(ms)

    def hide(self) -> None:
        """Pencereyi gizle. Zamanlayici da duruyor -- ipucu elle kapatilinca
        arkadan gelen "suresi doldu" ikinci kez gizlemeye calismasin."""
        self._timer.stop()
        self._engine.call(self._hide_now)

    def warm(self) -> None:
        """ON ISITMA (adim 15). Ipucu ISITMANIN ILK MUSTERISI: programin
        HER YERINDEN aciliyor ve isitilmazsa ILK ipucu 1-3.5 saniye sonra
        gorunurdu -- cogunun suresi 900-2500 ms, yani hic gorunmemis
        sayilirdi."""
        self._engine.warm()

    def shutdown(self) -> None:
        """Program kapaniyor: `flet.exe`yi gercekten kapat."""
        self._timer.stop()
        self._engine.stop()

    # -- ortak (ANA THREAD) -------------------------------------------------

    def _hide_from_taskbar(self) -> None:
        """Ipucunu gorev cubugundan (ve Alt+Tab'dan) cikar -- BIR KEZ.

        Flet'in `window.skip_task_bar` ayari OLCULDU (`probes/tip.py`) ve
        ISLEMIYOR: pencerede ne WS_EX_TOOLWINDOW var ne bir sahip, yani
        gorev cubugu kuralina gore dugme cikiyor. Qt surumu bunu
        `Qt.ToolTip` bayragiyla bedavaya yapiyordu.

        PENCERE GIZLIYKEN yapilmali (Windows bayrak degisimini gorev
        cubuguna ancak oyle yansitiyor) -- yani ipucu GORUNMEDEN once.
        `_arm` bunu her gosterimden ONCE deniyor; ilk tutan atistan sonra
        bir daha denenmiyor. Ipucular arasinda pencere zaten gizli, yani
        kosul kendiliginden saglaniyor.

        ISITILMIS panelde ILK ipucu da temiz cikiyor (pencere isitmadan
        beri gizli). Isitilmadan kullanilirsa ILK ipucu gorev cubugunda
        gorunebilir, ikinciden itibaren gorunmez -- panel isitilarak
        kullanilmak uzere yazildi (bkz. `warm`).
        """
        if self._hidden_from_taskbar:
            return
        hwnd = win.find_window(title=WINDOW_TITLE, visible_only=False)
        if not hwnd:
            return  # `flet.exe` daha ayaga kalkmadi; sonraki gosterimde
        self._hidden_from_taskbar = win.set_tool_window(hwnd, True)

    def _arm(self, ms: int) -> None:
        """Olcu + yer hesapla, pencereyi goster, sayaci kur.

        Hesap ANA THREAD'de yapiliyor: imlec konumu ve ekran olcegi birer
        Win32 cagrisi, Flet dongusunde kosmalarinin bir anlami yok.
        """
        if self._menu:
            self._size = self._menu_size()
        else:
            self._size = window_size(self._pieces, self._thumb is not None)
        self._spot = place(*self._size)
        self._hide_from_taskbar()
        if self._engine.page is None:
            self._engine.start()
        else:
            self._engine.call(self._show_now)
        if ms > 0:
            self._timer.start(ms)
        else:
            self._timer.stop()

    def _menu_size(self) -> tuple[int, int]:
        """Menu olcusu: baslik + satirlar + dipnot. Satir basina bir de
        rozet genisligi var, o yuzden `window_size` dogrudan kullanilmiyor."""
        widest = max(
            [len(self._title)]
            + [len(text_of(parse(desc))) + len(key) + 4 for key, desc in self._rows]
            + [len(self._footer)],
            default=0,
        )
        lines = 1 + len(self._rows) + (1 if self._footer else 0)
        width = 2 * PAD + round(widest * CHAR_PX) + 24
        height = 2 * PAD + lines * (LINE + 6) + 8
        return (max(160, min(width, MAX_WIDTH)), max(60, min(height, MAX_HEIGHT)))

    # -- Flet thread'i -------------------------------------------------------

    def _build(self, page: ft.Page) -> None:
        self._page = page
        page.title = WINDOW_TITLE
        # SAYDAM ZEMIN: gorunen kutu asagidaki `Container`, pencere DEGIL
        # (bkz. dosya basi -- "icerige gore boy" bu sekilde cozuluyor).
        page.bgcolor = ft.Colors.TRANSPARENT
        page.padding = 0
        page.window.bgcolor = ft.Colors.TRANSPARENT
        page.window.frameless = True
        page.window.title_bar_hidden = True
        page.window.always_on_top = True
        # `skip_task_bar` OLCULDU ve ISLEMIYOR (bkz. `_hide_from_taskbar`);
        # yine de yaziliyor ki Flet bir gun duzeltirse bedava gelsin.
        page.window.skip_task_bar = True
        page.window.resizable = False
        page.window.shadow = False
        # `window.movable = False` KULLANILMIYOR -- OLCULDU (probes/tip.py):
        # o ayar `window.visible = False`i BOZUYOR, yani ipucu bir daha
        # kapanmiyordu. Kaybedilen bir sey yok: pencere cercevesiz, zaten
        # suruklenecek bir baslik cubugu yok.
        page.window.prevent_close = True
        # Odak: ADIM 14'te olculdu, Flet penceresi odagi ZATEN calmiyor.
        # `window.focused` da `force_focus` da burada CAGIRILMAZ.
        self._body = ft.Column(spacing=2, tight=True)
        card = ft.Container(
            content=self._body,
            bgcolor=CARD_BG,
            border=ft.Border.all(1, theme.BORDER),
            border_radius=RADIUS,
            padding=PAD,
        )
        # Kutu SOL USTE yapisiyor: artan yer sagda ve altta SAYDAM kaliyor,
        # yani pencere ne kadar comert olursa olsun gorunen sey icerik kadar.
        page.controls.append(
            ft.Row(
                controls=[ft.Column(controls=[card], tight=True)],
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )
        self._engine.show_on_build(self._show_now)

    def _content(self) -> list[ft.Control]:
        """Kutunun icerigi -- menu ise satirlar, degilse metin (+ resim)."""
        if self._menu:
            return self._menu_content()
        text = self._rich(self._pieces)
        if self._thumb is None:
            return [text]
        return [
            ft.Row(
                controls=[
                    ft.Image(
                        src=self._thumb, width=THUMB, height=THUMB, fit=ft.BoxFit.CONTAIN
                    ),
                    text,
                ],
                spacing=GAP,
                vertical_alignment=ft.CrossAxisAlignment.START,
                tight=True,
            )
        ]

    @staticmethod
    def _rich(pieces: tuple[Piece, ...]) -> ft.Text:
        """Parcalar -> tek `ft.Text` (span'li). Qt'deki zengin metin
        QLabel'inin karsiligi."""
        return ft.Text(
            spans=[
                ft.TextSpan(
                    piece.text,
                    ft.TextStyle(
                        size=SIZE,
                        color=piece.color or theme.FG,
                        weight=ft.FontWeight.BOLD if piece.bold else None,
                        italic=piece.italic or None,
                    ),
                )
                for piece in pieces
            ],
            size=SIZE,
            color=theme.FG,
        )

    def _menu_content(self) -> list[ft.Control]:
        """Qt'nin HTML tablosunun karsiligi -- denetim olarak.

        Rozet sabit genislikli yazi tipinde ve kendi zeminini tasiyor;
        Qt'de hucre zeminiydi.
        """
        rows: list[ft.Control] = [
            ft.Text(self._title, size=SIZE, color=ACCENT, weight=ft.FontWeight.BOLD)
        ]
        for key, desc in self._rows:
            rows.append(
                ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Text(
                                key,
                                size=SIZE,
                                color=BADGE_FG,
                                font_family=MONO,
                                weight=ft.FontWeight.BOLD,
                            ),
                            bgcolor=BADGE_BG,
                            border_radius=3,
                            padding=ft.Padding.symmetric(vertical=2, horizontal=6),
                        ),
                        self._rich(parse(desc)),
                    ],
                    spacing=GAP,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        if self._footer:
            rows.append(ft.Text(self._footer, size=SIZE - 1, color=theme.MUTED))
        return rows

    async def _show_now(self) -> None:
        page, body = self._page, self._body
        if page is None or body is None:
            return
        body.controls = self._content()
        page.window.width, page.window.height = self._size
        page.window.left, page.window.top = self._spot
        page.window.visible = True
        page.update()
        # `to_front()` odagi CALMIYOR (adim 14, senaryo A): pencere yalnizca
        # uste geliyor. Ipucu hep ustte durmali, yani gerekli.
        await page.window.to_front()

    def _hide_now(self) -> None:
        page = self._page
        if page is None:
            return
        page.window.visible = False
        page.update()
