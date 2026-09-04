"""CapsLock hizli paneli -- eski `showQuickHistoryMenu` Win32 menusunun yerine.

Neden Qt penceresi: Win32 `TrackPopupMenu` (win32/menu.py) tek satirlik
ogeden baskasini cizemiyor ve icine arama kutusu konamiyor. Panoda duran sey
cogu zaman uzun bir metin; tek satira kirpilinca hangisi oldugu
anlasilmiyordu. Burada oge UC SATIRA kadar sarilir, ustte de yazdikca suzen
bir kutu vardir.

Duzen -- her oge KENDI CERCEVESINDE, bitisik liste satirlari degil, ve
KISAYOL RAKAMI CERCEVENIN DISINDA solda durur (rakam ogenin metninin bir
parcasi degil, ona giden tus):

    >Pano<   Slot   Side
    [ arama ]
      +------------------------------------+
    1 | ilk oge, uc satira kadar sarilir   |
      +------------------------------------+
    2 | ikinci oge                         |
      +------------------------------------+

Tuslar:

    1-9, 0      ogeyi sec ve calistir     sag / sol      mod (sekme) degistir
    yukari/asagi  gez                     Tab / Shift+Tab  ayni is
    Enter       secili ogeyi calistir     Ctrl+q         QR penceresi
    Esc         kapat                     harf / bosluk  aramaya yazilir

Onuncu oge `0` ile secilir: SAYFA BASINA 10 satir, kisayollar `1234567890`.

SAYFALAMA: pano binlerce oge tutabiliyor, kisayol ise on tane. Liste
kaymiyor -- son satirda asagi ok SONRAKI ONLU GRUBU yukluyor (ilk satirda
yukari ok oncekini), rakamlar hep 1..0 kaliyor. Sayfa numarasi altyazida.

Pencere olculeri SABIT DEGIL: en, o sayfadaki en uzun satirin piksel
genisliginden; boy, satir yuksekliklerinin toplamindan cikiyor (`_fit`).

TUSLAR ARAMA KUTUSUNDAN GECIRILIYOR (eventFilter): odak hep QLineEdit'te
duruyor ve Tab odak degistirmeye, sag/sol ok imleci kaydirmaya giderdi --
pencerenin keyPressEvent'i bu tuslari HIC gormezdi. Kutuya takilan suzgec
panele ait tuslari once yakalar. Sag/sol yalniz KUTU BOSKEN panele gider;
kullanici bir sey yazmissa metin icinde gezinmek dogal olan.

Alt+harf DENENDI, OLMADI: panel Alt basiliyken tusu hic gormuyor -- Alt
menu cubugu gezinmesini baslatiyor ve tus oraya gidiyor. Sekme degistirme
bu yuzden yatay ok tuslarinda ve Tab'da: liste tek kolon, saga sola
gitmenin baska anlami yok. QR da Ctrl+q'ya tasindi, cunku harfler aramaya
gidiyor.

RAKAMLAR ARAMAYA GITMEZ: 1-9 ve 0 dogrudan secim, cunku panelin asil isi
"CapsLock basili tut, numaraya bas, yapistir". Arama icinde rakam gerekirse
Ctrl+rakam ile yazilir.

Panel eylemi KENDISI calistirmaz, `chosen` ile eylem kimligini disari verir
(array_filter.py ile ayni ayrim): pencere pano nedir, slot nedir bilmez.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cascade import theme
from cascade.ui.place import center_on_cursor_screen

MIN_WIDTH = 380  # bu kadarindan dar olmaz (arama kutusu + altyazi sigsin)
MAX_LINES = 3  # oge basina en fazla satir
PAGE = 10  # bir sayfada gosterilen oge -- 1234567890 kisayolu kadar
MAX_ITEMS = PAGE  # eski ad, sayfa boyu ile ayni
NUMBER_PX = 16  # kutunun SOLUNDAKI kisayol kolonu, piksel
THUMB_PX = 48  # satir basi onizleme resmi
WRAP_WIDTH = 56  # esaralikli yazi tipinde satira sigan EN FAZLA karakter
BOX_PAD = (7, 4, 7, 4)  # kutu ici bosluk. QSS `padding` DEGIL: bicem
#: sayfasindan gelen dolgu oge yuksekligi hesaplanirken (sizeHint) daha
#: uygulanmamis oluyor ve son satir kirpiliyordu -- duzen kenari kesin.
SCREEN_SHARE = 0.85  # panel en fazla ekranin bu kadarini kaplar
FOOTER = "1-0 sec · ↑↓ gez · ←→/Tab mod · Ctrl+q QR · Esc kapat"

#: Oge cercevesi. Koyu/acik temanin ikisinde de okunan gri tonlar; tema
#: paletinden turetmek yerine sabit, cunku ipucu penceresi de (ui/tip.py)
#: ayni ailenin renklerini sabit tutuyor.
ITEM_BORDER = "#3d444d"
TAB_IDLE = "#6e7681"
TAB_ACTIVE = "#58a6ff"
ITEM_ACTIVE = "#539bf5"
ITEM_ACTIVE_BG = "rgba(83, 155, 245, 0.15)"


@dataclass(frozen=True, slots=True)
class QuickItem:
    """Panelde bir satir.

    `content` ham metin (QR penceresine giden sey), `label` gosterilen hali;
    verilmezse `content` tek satira ezilerek kullanilir. `thumb` verilirse
    satirin soluna kucuk resim konur.
    """

    content: str
    action: str
    label: str = ""
    thumb: QImage | None = None

    @property
    def text(self) -> str:
        return self.label or " ".join(self.content.split()) or "(bos)"


@dataclass(frozen=True, slots=True)
class QuickTab:
    """Bir sekme. `provider` panel her acildiginda TAZE cagrilir -- pano
    icerigi panel kapaliyken degismis olabilir."""

    title: str
    provider: Callable[[], tuple[QuickItem, ...]] = field(repr=False)


def wrap(text: str, width: int = WRAP_WIDTH, max_lines: int = MAX_LINES) -> list[str]:
    """Metni kelime kelime sarar, `max_lines` satirda keser.

    Piksel degil KARAKTER hesabi: liste esaralikli yazi tipi kullaniyor ve
    QFontMetrics pencere gosterilmeden guvenilir sonuc vermiyor. Kirpilan
    son satir "…" ile biter -- devami oldugu belli olsun.
    """
    words = " ".join(text.split()).split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        while len(word) > width:  # tek kelime satira sigmiyor: boleriz
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:width])
            word = word[width:]
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if not lines:
        return [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(1, width - 1)].rstrip() + "…"
    return lines


def shortcut(number: int) -> str:
    """1 tabanli sira -> kisayol rakami. Onuncu oge `0` ile secilir."""
    return str(number % 10)


class QuickPanel(QWidget):
    """Sekmeli, aranabilir hizli liste. Secim `chosen(eylem)` ile disari cikar."""

    chosen = Signal(str)
    qr_requested = Signal(str)

    def __init__(self, tabs: tuple[QuickTab, ...]) -> None:
        super().__init__(None, Qt.WindowType.Tool)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._tabs = tabs
        self._index = 0
        self._items: tuple[QuickItem, ...] = ()
        #: Suzgecten gecen HER SEY (pano binlerce oge olabilir).
        self._found: tuple[QuickItem, ...] = ()
        #: O anki sayfada duran ogeler -- kisayol rakamlari bunlari sayar.
        self._shown: tuple[QuickItem, ...] = ()
        self._page = 0

        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)

        self.tabbar = QLabel()
        self.tabbar.setTextFormat(Qt.TextFormat.RichText)

        self.search = QLineEdit()
        self.search.setPlaceholderText("ara... (harfe bas)")
        # Lambda sart: textChanged METNI parametre olarak yolluyor ve
        # dogrudan baglanirsa `keep_page` yerine gecip sayfayi sifirlamiyor.
        self.search.textChanged.connect(lambda _text: self._refresh())
        # Panele ait tuslar kutunun icinde kalmasin -- bkz. modul basligi.
        self.search.installEventFilter(self)

        #: Ekrandaki satirlarin cerceveleri; secim rengi bunlara elle
        #: uygulaniyor (cerceve artik oge DEGIL, oge icindeki bir widget).
        self._boxes: list[QFrame] = []

        self.list = QListWidget()
        self.list.setFont(mono)
        self.list.currentRowChanged.connect(self._mark_current)
        # Sarma ELDE yapiliyor (bkz. wrap): Qt'nin kendi sarmasi oge
        # yuksekligini sinirlamiyor, uzun bir kopya listeyi tek basina
        # doldururdu.
        self.list.setWordWrap(False)
        self.list.setUniformItemSizes(False)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemClicked.connect(lambda _item: self.accept())
        # Her oge KENDI CERCEVESINDE (ornek tasarimdaki pano kutulari gibi),
        # ama cerceve OGENIN KENDISI degil, ogenin icindeki `QFrame#box`:
        # kisayol rakami cercevenin disinda, solda duruyor. Ogenin kendi
        # secim boyasi bu yuzden kapatildi.
        self.list.setStyleSheet(
            "QListWidget { border: none; background: transparent; }"
            "QListWidget::item { background: transparent; }"
            "QListWidget::item:selected { background: transparent; }"
            f"QFrame#box {{ border: 1px solid {ITEM_BORDER}; border-radius: 6px; }}"
            f"QFrame#box[sel=\"true\"] {{ border-color: {ITEM_ACTIVE};"
            f" background: {ITEM_ACTIVE_BG}; }}"
        )

        self.footer = QLabel(FOOTER)
        theme.muted(self.footer)

        layout = QVBoxLayout(self)
        # Pencere DUZENIN olcusune uyar: `resize()` gorunur bir pencerede
        # bekleyen yerlesime yeniliyor, sayfa kisalinca altta bos serit
        # kaliyordu. Olcuyu listeye verip (setFixedHeight/Width, bkz. _fit)
        # pencereyi pesinden surukluyoruz.
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        layout.addWidget(self.tabbar)
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.footer)


    # ---- disari ----

    def open(self, index: int = 0) -> None:
        """Paneli imlecin ekraninda ortalar, odagi arama kutusuna verir."""
        self.select_tab(index)
        center_on_cursor_screen(self)
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

    @property
    def tab(self) -> QuickTab | None:
        return self._tabs[self._index] if self._tabs else None

    @property
    def items(self) -> tuple[QuickItem, ...]:
        """Ekranda duran (o SAYFADAKI) ogeler -- 1-0 bunlari sayar."""
        return self._shown

    @property
    def pages(self) -> int:
        """Suzgecten gecen ogelerin kac sayfa ettigi (en az 1)."""
        return max(1, -(-len(self._found) // PAGE))

    @property
    def page(self) -> int:
        """Gosterilen sayfa, 0 tabanli."""
        return self._page

    def go_page(self, page: int) -> int:
        """Sayfayi degistirir; bastan/sondan tasinca ote uca doner.

        Donen deger yeni sayfadaki oge sayisi -- cagiran hangi satiri
        secmesi gerektigini buna gore biliyor.
        """
        self._page = page % self.pages
        self._refresh(keep_page=True)
        return len(self._shown)

    def tab_index(self, title: str) -> int:
        """Sekme ADINDAN sirasi. Bilinmeyen ad ilk sekmeye duser -- paneli
        acan tusun yanlis yazilmis bir argumani paneli hic acmamaktan iyi."""
        lowered = title.strip().casefold()
        for index, tab in enumerate(self._tabs):
            if tab.title.casefold() == lowered:
                return index
        return 0

    def select_tab(self, index: int) -> None:
        if not self._tabs:
            return
        self._index = index % len(self._tabs)
        # Sekme degisti, eski sorgu anlamsiz. clear() _refresh'i tetikler,
        # ama kutu zaten bossa tetiklemez: _load her halukarda cagriliyor.
        self.search.clear()
        self._load()

    def accept(self, number: int = 0) -> None:
        """`number` verilirse o satiri (1 tabanli), yoksa secili satiri secer."""
        item = self.item_at(number)
        if item is None:
            return
        self.close()
        self.chosen.emit(item.action)

    def item_at(self, number: int = 0) -> QuickItem | None:
        row = number - 1 if number else self.list.currentRow()
        return self._shown[row] if 0 <= row < len(self._shown) else None

    # ---- liste ----

    def _load(self) -> None:
        tab = self.tab
        # Saglayici KIRPILMIYOR: pano binlerce oge olabilir, panel onlari
        # onarli sayfalar halinde gosteriyor (bkz. _move).
        self._items = tab.provider() if tab else ()
        self._page = 0
        self._paint_tabbar()
        self._refresh()

    def _paint_tabbar(self) -> None:
        # Secili sekme yalniz RENKLE ayrilir: `&#9656;...&#9666;` isaretleri
        # daralan cubukta baslik gibi degil, gurultu gibi duruyordu.
        parts = [
            "<span style='color:{}; font-size: 15px;'>{}{}{}</span>".format(
                TAB_ACTIVE if index == self._index else TAB_IDLE,
                "<b>" if index == self._index else "",
                tab.title,
                "</b>" if index == self._index else "",
            )
            for index, tab in enumerate(self._tabs)
        ]
        self.tabbar.setText("&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;".join(parts))

    def _refresh(self, keep_page: bool = False) -> None:
        query = self.search.text().strip().lower()
        self._found = tuple(i for i in self._items if not query or query in i.text.lower())
        if not keep_page:
            self._page = 0
        self._page = min(self._page, max(0, self.pages - 1))
        start = self._page * PAGE
        self._shown = self._found[start : start + PAGE]
        self.list.clear()
        self._boxes.clear()
        for number, item in enumerate(self._shown, start=1):
            row = QListWidgetItem()
            widget = self._row_widget(number, item)
            # +2: kutunun 1'er piksellik kenarligi QLabel'in sizeHint'ine
            # girmiyor, son satir bir tik kirpilmis gozukuyordu.
            hint = widget.sizeHint()
            row.setSizeHint(QSize(hint.width(), hint.height() + 2))
            self.list.addItem(row)
            self.list.setItemWidget(row, widget)
        if self._shown:
            self.list.setCurrentRow(0)
        self._paint_footer()
        self._fit()

    def _paint_footer(self) -> None:
        pages = f"  ·  sayfa {self._page + 1}/{self.pages}" if self.pages > 1 else ""
        self.footer.setText(FOOTER + pages)

    def _fit(self) -> None:
        """Pencereyi ICERIGE gore boyutlandirir -- eni de boyu da.

        Sabit olcude iki dert vardi: 10 oge sigmiyor (dikey kaydirma cikip
        son kutu yariliyordu) ve kisa metinlerde saga bir tutam olu bosluk
        kaliyordu. En, o sayfadaki EN UZUN satirin piksel genisliginden;
        boy, satir yuksekliklerinin toplamindan. Ekrana sigmayan boy
        `SCREEN_SHARE` ile kirpilir, o zaman kaydirma yine devreye girer.
        """
        rows = sum(self.list.item(i).sizeHint().height() for i in range(self.list.count()))
        rows += 2 * self.list.frameWidth()
        screen = self.screen() or QGuiApplication.primaryScreen()
        # Cerceve payi listeden BAGIMSIZ olculuyor: `height() - list.height()`
        # panel daha bir kez bile yerlesmemisken sacma bir sayi veriyordu.
        layout = self.layout()
        margins = layout.contentsMargins()
        chrome = (
            self.tabbar.sizeHint().height()
            + self.search.sizeHint().height()
            + self.footer.sizeHint().height()
            + 3 * layout.spacing()
            + margins.top()
            + margins.bottom()
        )
        limit = int(screen.availableGeometry().height() * SCREEN_SHARE) - chrome
        self.list.setFixedHeight(max(60, min(rows, max(60, limit))))
        self.list.setFixedWidth(self._width())

    def _width(self) -> int:
        """Sayfadaki en uzun satira gore pencere eni."""
        metrics = QFontMetrics(self.list.font())
        text = max(
            (
                metrics.horizontalAdvance(line)
                for item in self._shown
                for line in wrap(item.text)
            ),
            default=0,
        )
        thumb = THUMB_PX + 8 if any(i.thumb is not None for i in self._shown) else 0
        chrome = (
            NUMBER_PX
            + 6  # rakam ile kutu arasi
            + BOX_PAD[0]
            + BOX_PAD[2]
            + 2 * self.list.frameWidth()
            + self.list.verticalScrollBar().sizeHint().width()
            + 8
        )
        cap = int((self.screen() or QGuiApplication.primaryScreen()).availableGeometry().width() * 0.9)
        return max(MIN_WIDTH, min(text + thumb + chrome, cap))

    def _row_widget(self, number: int, item: QuickItem) -> QWidget:
        """"1 [ metin ]" -- rakam kutunun DISINDA, solda."""
        row = QWidget()
        outer = QHBoxLayout(row)
        outer.setContentsMargins(0, 0, 0, 3)
        outer.setSpacing(6)

        key = QLabel(shortcut(number))
        key.setFixedWidth(NUMBER_PX)
        key.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        theme.muted(key)
        outer.addWidget(key)

        box = QFrame()
        box.setObjectName("box")
        inner = QHBoxLayout(box)
        inner.setContentsMargins(*BOX_PAD)
        inner.setSpacing(8)
        if item.thumb is not None and not item.thumb.isNull():
            thumb = QLabel()
            thumb.setPixmap(
                QPixmap.fromImage(item.thumb).scaled(
                    THUMB_PX,
                    THUMB_PX,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            inner.addWidget(thumb)
        text = QLabel("\n".join(wrap(item.text)))
        text.setFont(self.list.font())
        inner.addWidget(text, 1)
        outer.addWidget(box, 1)

        self._boxes.append(box)
        return row

    def _mark_current(self, row: int) -> None:
        """Secim rengi cerceveye: oge boyamasi kapali (bkz. bicem sayfasi)."""
        for index, box in enumerate(self._boxes):
            box.setProperty("sel", "true" if index == row else "false")
            box.style().unpolish(box)
            box.style().polish(box)

    def _move(self, delta: int) -> None:
        """Bir satir gezer; sayfanin ucundan tasarsa SONRAKI ONLUYU yukler.

        Pano binlerce oge tutabiliyor ama kisayol on tane: liste kaymak
        yerine sayfa degistiriyor, rakamlar hep 1..0 kaliyor.
        """
        if not self._shown:
            return
        row = self.list.currentRow() + delta
        if 0 <= row < len(self._shown):
            self.list.setCurrentRow(row)
            return
        count = self.go_page(self._page + (1 if delta > 0 else -1))
        if count:
            self.list.setCurrentRow(0 if delta > 0 else count - 1)

    def _qr(self) -> None:
        item = self.item_at()
        text = item.content if item else ""
        self.close()
        self.qr_requested.emit(text)

    # ---- tuslar ----

    def keyPressEvent(self, event) -> None:
        """Tum tuslar burada toplaniyor.

        Odak hep arama kutusunda duruyor ama 1-9, ok tuslari ve Tab listeye
        ait; QLineEdit'e olay suzgeci takmak yerine pencere duzeyinde
        yakalamak yetiyor, cunku panelde baska odaklanabilir sey yok.
        Buraya dusen tus (harf, bosluk, Backspace) kutuya iletilir.
        """
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        if key == Qt.Key.Key_Q and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._qr()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept()
            return
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._move(-1 if key == Qt.Key.Key_Up else 1)
            return
        # Sag/sol ve Tab ayni isi yapar: liste TEK KOLON, yatay ok tuslarinin
        # baska bir isi yok.
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Right):
            self.select_tab(self._index + 1)
            return
        if key in (Qt.Key.Key_Backtab, Qt.Key.Key_Left):
            self.select_tab(self._index - 1)
            return
        # Ctrl+rakam kutuya yazilsin diye "degistirici yok" sarti var.
        # `0` ONUNCU oge: kisayol seridi 1234567890.
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9 and not modifiers:
            self.accept(10 if key == Qt.Key.Key_0 else key - Qt.Key.Key_0)
            return
        self.search.setFocus()
        self.search.event(event)

    def eventFilter(self, watched, event):
        """Arama kutusuna gelen PANEL tuslarini once panele verir.

        Kutu odakli oldugu icin Tab odak degistirmeye, sag/sol ok imlece,
        rakamlar metne giderdi. Sag/sol yalniz kutu BOSKEN kapiliyor.
        """
        if (
            watched is self.search
            and event.type() == QEvent.Type.KeyPress
            and self._panel_key(event)
        ):
            self.keyPressEvent(event)
            return True
        return super().eventFilter(watched, event)

    def _panel_key(self, event) -> bool:
        key = event.key()
        modifiers = event.modifiers()
        if key in (
            Qt.Key.Key_Escape,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
            Qt.Key.Key_Tab,
            Qt.Key.Key_Backtab,
        ):
            return True
        if key == Qt.Key.Key_Q and modifiers & Qt.KeyboardModifier.ControlModifier:
            return True
        if not modifiers and Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            return True
        return key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not self.search.text()

    def event(self, event):
        """Odak baska pencereye gecince kapanir -- menu gibi davransin."""
        if event.type() == event.Type.WindowDeactivate and self.isVisible():
            self.close()
        return super().event(event)
