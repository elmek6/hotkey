"""Genel bakis -- kisa F13 ile acilan panel.

App shorts, pano ve slotlar tek pencerede; cevresinde menu ve dugme
seritleri (yerlesim `OverviewPanel` basliginda):

    +------------------------------------------------------------+
    |  APP SHORTS (on plandaki uygulama)  Profil v  |  Hep ustte |
    +------------------------------------------------------------+
    +------------------------------------------------------------+
    |  [Pano] [Slot]  [ara] 🔍                                   |
    |  secili sekmenin listesi                                   |
    +------------------------------------------------------------+
    +------------------------------------------------------------+
    |  tus satiri (Enter, Del, ^A ^C ...) / pencere dugmeleri    |
    +------------------------------------------------------------+

Kutular GORUNUSTE ayri, pencere TEK: ekrani kaplamaz ve karartmaz, imlecin
oldugu monitorun ortasinda durur. Bir ogeye tiklamak onu calistirir ve
paneli kapatir; panelin DISINA tiklamak (odak gider), Esc ya da baska
pencereye gecmek yalnizca kapatir. Harfe basmak pano listesini suzen
kutuya yazar; Tab/ok tuslari listeler arasinda gezer.

Panel eylemi KENDISI calistirmaz, `chosen` ile eylem kimligini disari verir
(quick_panel.py ile ayni ayrim). Veri de disaridan gelir: app shorts
listesi katman ACILMADAN once okunmali, yoksa on plandaki pencere
katmanin kendisi olurdu.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal, SignalInstance
from PySide6.QtGui import QColor, QCursor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from keypilot.ui.preview import shorten
from keypilot.ui.quick_panel import QuickItem
from keypilot.win32.menu import COLUMN, Icon, Mark, destroy_icon, force_foreground, icon_handle

#: Kutular arasi bosluk: GOZE gorunmez ama alfa 0 degil. Windows tam saydam
#: pikseldeki tiklamayi alttaki pencereye gecirir; bosluga tiklamak paneli
#: odaksiz birakip kapatirdi. Palet Tokyo Night ailesinden: lacivert zemin,
#: pastel vurgular.
BACKDROP = QColor(0, 0, 0, 1)
PANEL_BG = "rgba(26, 27, 38, 242)"
BUTTON_BG = "rgba(41, 46, 66, 245)"  # dugmeler zeminden bir ton acik
PANEL_BORDER = "#3b4261"
TEXT = "#c0caf5"
MUTED = "#565f89"
TITLE_COLOR = "#7aa2f7"  # genel vurgu: kenarlar, secili dugme
ITEM_HOVER = "rgba(122, 162, 247, 0.20)"
ITEM_SELECTED = "rgba(122, 162, 247, 0.30)"
SEPARATOR = "rgba(59, 66, 97, 0.55)"  # ogeler arasi ince cizgi
#: Kutu basliklari -- her liste kendi renginde, goz hangisinde oldugunu
#: renkten bulsun.
SHORTS_COLOR = "#e0af68"
CLIPS_COLOR = "#7dcfff"
SLOTS_COLOR = "#bb9af7"
PINS_COLOR = "#9ece6a"
CLOSE_BG = "#f7768e"
#: Pano hover dugmelerinden one cikan (V⏎) -- bkz. `app.show_overview`.
HOVER_ALT_COLOR = "#9ece6a"
#: App shorts seridinde yan yana kac kisayol. Her oge hucresinin TAMAMINI
#: kaplar: fare yazinin ustune gelmeden, hucreye girince vurgulanir.
SHORTS_COLUMNS = 2  # ust kutunun SOL yarisinda
#: Panel sabit enli, imlecin yaninda acilir (ekrana sigacak sekilde).
CARD_WIDTH = 600
LIST_HEIGHT = 230  # pano / slot listesinin boyu, piksel
SHORTS_ROWS = 3  # seritte en fazla bu kadar kisayol satiri; fazlasi kayar
LABEL_CHARS = 70  # satirda gosterilen en fazla karakter (liste tam en)
FONT_PT = 10
LEAVE_POLL_MS = 120  # acik menude imlec yoklama araligi (fare cikti mi)
TOOLTIP_CHARS = 600  # ipucunda gosterilen en fazla karakter
#: Pano gecmisi binlerce oge olabilir; katman bakip secmek icin, en
#: yenilerin bu kadari yeter.
MAX_CLIPS = 30

#: Satir verisinde ikinci eylem (hover dugmesi) ve arama metni.
ALT_ROLE = Qt.ItemDataRole.UserRole + 1
SEARCH_ROLE = Qt.ItemDataRole.UserRole + 2

LIST_STYLE = (
    f"QListWidget {{ border: none; background: transparent; color: {TEXT};"
    f" font-size: {FONT_PT}pt; }}"
    # Ogeler arasinda ince ayrac: satirlar birbirine karismasin.
    f"QListWidget::item {{ padding: 1px 4px; border-bottom: 1px solid {SEPARATOR}; }}"
    f"QListWidget::item:hover {{ background: {ITEM_HOVER}; }}"
    # Klavyeyle secili oge (ok tuslari / Tab) fareyle ustune gelinmis gibi.
    f"QListWidget::item:selected {{ background: {ITEM_SELECTED}; color: {TEXT}; }}"
    f"QListWidget::item:disabled {{ color: {MUTED}; }}"
    # Ince, koyu kaydirma cubugu -- varsayilan beyaz cubuk kartta siritiyordu.
    "QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }"
    f"QScrollBar::handle:vertical {{ background: {PANEL_BORDER}; border-radius: 3px;"
    " min-height: 20px; }"
    "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
    "QScrollBar::add-page, QScrollBar::sub-page { background: none; }"
)

BUTTON_STYLE = (
    f"QPushButton {{ background: {BUTTON_BG}; color: {TEXT}; border: 1px solid {PANEL_BORDER};"
    f" border-radius: 5px; padding: 3px 8px; font-size: {FONT_PT}pt; }}"
    f"QPushButton:checked {{ border-color: {TITLE_COLOR}; color: {TITLE_COLOR}; }}"
    f"QPushButton:hover {{ background: {ITEM_HOVER}; border-color: {TITLE_COLOR}; }}"
)
MENU_STYLE = (
    f"QMenu {{ background: {BUTTON_BG}; color: {TEXT}; border: 1px solid {PANEL_BORDER};"
    f" font-size: {FONT_PT}pt; }}"
    f"QMenu::item {{ padding: 4px 18px; }}"
    f"QMenu::item:selected {{ background: {ITEM_HOVER}; }}"
    f"QMenu::item:disabled {{ color: {MUTED}; }}"
    f"QMenu::separator {{ height: 1px; background: {PANEL_BORDER}; margin: 3px 6px; }}"
)


def _hover_style(color: str) -> str:
    """Satir hover dugmesi: `color` renkte cerceve + yazi, ustunde dolgu."""
    return (
        f"QToolButton {{ background: {BUTTON_BG}; color: {color}; border: 1px solid {color};"
        f" border-radius: 4px; font-size: {FONT_PT - 2}pt; font-weight: bold;"
        " padding: 0 3px; }"
        f"QToolButton:hover {{ background: {color}; color: {PANEL_BG}; }}"
    )




def _tab_style(color: str) -> str:
    """Pano / Slot sekmesi: secili olan kendi renginde, altinda cizgi."""
    return (
        f"QPushButton {{ background: transparent; color: {MUTED}; border: none;"
        f" border-bottom: 2px solid transparent; padding: 2px 10px;"
        f" font-size: {FONT_PT - 1}pt; font-weight: bold; }}"
        f"QPushButton:checked {{ color: {color}; border-bottom-color: {color}; }}"
    )


SEARCH_STYLE = (
    f"QLineEdit {{ background: transparent; color: {TEXT}; border: 1px solid {PANEL_BORDER};"
    f" border-radius: 4px; padding: 0 4px; font-size: {FONT_PT - 1}pt; }}"
    f"QLineEdit:focus {{ border-color: {TITLE_COLOR}; }}"
)


def _clear(layout: QHBoxLayout | QVBoxLayout) -> None:
    """Seridi bosaltir; dugmeler her acilista yeniden kuruluyor. Ic ice
    satirlar (alt kutunun sira duzenleri) da bosaltilip atilir."""
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        if isinstance(inner := item.layout(), (QHBoxLayout, QVBoxLayout)):
            _clear(inner)
            inner.deleteLater()
        elif (child := item.widget()) is not None:
            child.deleteLater()


class _Section(QFrame):
    """Baslikli, yuvarlak koseli bir kutu + icinde liste."""

    #: Satirin hover dugmesi tiklandi -- eylem kimligi (bkz. `fill` alts).
    alt_chosen = Signal(str)

    def __init__(self, title: str, flow: bool = False, accent: str = TITLE_COLOR) -> None:
        super().__init__()
        self._flow = flow
        self.setObjectName("section")
        self.setStyleSheet(
            f"QFrame#section {{ background: {PANEL_BG}; border: 1px solid {PANEL_BORDER};"
            " border-radius: 6px; }"
        )
        self.title = QLabel(title)
        self.title.setStyleSheet(f"color: {accent}; font-weight: bold; font-size: {FONT_PT - 1}pt;")

        self.list = QListWidget()
        self.list.setStyleSheet(LIST_STYLE)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setWordWrap(False)
        self.list.setMouseTracking(True)  # hover boyasi icin
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # odak cercevesi cizilmesin
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if flow:
            # Kisayollar yan yana akar, sigmayan alt satira gecer.
            self.list.setFlow(QListView.Flow.LeftToRight)
            self.list.setWrapping(True)
            self.list.setResizeMode(QListView.ResizeMode.Adjust)
            self.list.setSpacing(1)
            # Kaydirma cubugu hucre enini yiyip satirda bir kisayol eksiltiyordu;
            # serit zaten butun satirlari gosterecek boyda (bkz. fill).
            self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        #: Baslik satiri: baslik + (varsa) arama kutusu, dugmeler.
        self.head = _row()
        self.head.addWidget(self.title)

        #: Satirin SAGINDA, fare ustundeyken beliren ek eylem dugmeleri
        #: (pano: hepsini sec + yapistir + Enter, yapistir + Enter, bicimsiz).
        #: Dugmeler bir kez kurulur, fareyle satirdan satira tasinir.
        self.hover_buttons: list[QToolButton] = []
        self.list.viewport().installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 6)
        layout.setSpacing(2)
        layout.addLayout(self.head)
        layout.addWidget(self.list, 1)

    def fill(self, items: tuple[QuickItem, ...], empty: str, alts: tuple[tuple, ...] = ()) -> None:
        """`alts`: ogeyle AYNI sirada, satir basina (etiket, eylem, ipucu
        [, renk]) dizisi -- hover dugmeleri soldan saga; bossa o listede dugme cikmaz."""
        self.list.clear()
        self._hide_hover()
        for index, item in enumerate(items):
            row = QListWidgetItem(shorten(item.text, LABEL_CHARS))
            row.setData(Qt.ItemDataRole.UserRole, item.action)
            row.setData(ALT_ROLE, alts[index] if index < len(alts) else ())
            row.setData(SEARCH_ROLE, f"{item.text}\n{item.content}".casefold())
            row.setToolTip(item.content[:TOOLTIP_CHARS])
            self.list.addItem(row)
        if not items:
            row = QListWidgetItem(empty)
            row.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(row)
        if self._flow:
            self._fit_cells()

    def _fit_cells(self) -> None:
        """Her kisayola hucresinin TAMAMI kadar olcu verir ve seridi satir
        sayisina gore boylar. En, listenin GERCEK eninden: DPI olcegi ve
        kenar paylari sabit bir kart eninden hesaplamayi tutarsiz yapiyordu."""
        spacing = self.list.spacing()
        width = self.list.viewport().width() or CARD_WIDTH - 20
        cell = QSize(
            (width - spacing * 2 * SHORTS_COLUMNS) // SHORTS_COLUMNS - 1,
            self.list.fontMetrics().height() + 6,
        )
        for index in range(self.list.count()):
            row = self.list.item(index)
            # Bos durum yazisi ("profil yok") tek hucreye sigmaz: tam satir.
            enabled = bool(row.flags() & Qt.ItemFlag.ItemIsEnabled)
            row.setSizeHint(cell if enabled else QSize(width - 2 * spacing - 1, cell.height()))
        rows = max(1, min(SHORTS_ROWS, -(-self.list.count() // SHORTS_COLUMNS)))
        self.list.setFixedHeight(rows * (cell.height() + spacing * 2) + 2)

    def filter(self, text: str) -> None:
        """Yazilani ICEREN satirlar kalir (buyuk/kucuk harf fark etmez)."""
        needle = text.strip().casefold()
        for index in range(self.list.count()):
            row = self.list.item(index)
            haystack = row.data(SEARCH_ROLE)
            row.setHidden(bool(needle) and not (haystack and needle in haystack))
        self._hide_hover()

    def _hover_button(self, index: int) -> QToolButton:
        """`index`. hover dugmesi; yoksa kurulur. Eylem dugmenin kendisinde
        (`property`) -- tiklaninca o anki satirinki gider."""
        while len(self.hover_buttons) <= index:
            button = QToolButton(self.list.viewport())
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.hide()
            button.clicked.connect(
                lambda _=False, b=button: self.alt_chosen.emit(str(b.property("action")))
            )
            self.hover_buttons.append(button)
        return self.hover_buttons[index]

    def _hide_hover(self) -> None:
        for button in self.hover_buttons:
            button.hide()

    def _place_hover(self, pos) -> None:
        """Fare hangi satirdaysa, satirin ek eylemleri varsa dugmeleri o
        satirin sag ucuna, verilen sirayla (soldan saga) dizer."""
        row = self.list.itemAt(pos)
        alts = row.data(ALT_ROLE) if row is not None else ()
        if row is None or not alts:
            self._hide_hover()
            return
        rect = self.list.visualItemRect(row)
        size = rect.height() - 4
        right = rect.right() - 4
        # Sagdan sola yerlestir: son dugme satirin en sag ucunda.
        for index in range(len(alts) - 1, -1, -1):
            label, action, tip, *rest = alts[index]
            button = self._hover_button(index)
            color = rest[0] if rest else TITLE_COLOR
            # Dugme satirlar arasi tasiniyor; stil yalniz renk degisince.
            if button.property("color") != color:
                button.setProperty("color", color)
                button.setStyleSheet(_hover_style(color))
            button.setText(label)
            button.setToolTip(tip)
            button.setProperty("action", str(action))
            width = max(size, button.sizeHint().width())
            button.setFixedSize(width, size)
            right -= width
            button.move(right, rect.top() + 2)
            right -= 3  # dugmeler arasi bosluk
            button.show()
        for button in self.hover_buttons[len(alts) :]:
            button.hide()

    def eventFilter(self, watched, event):
        if watched is self.list.viewport():
            kind = event.type()
            if kind == QEvent.Type.Resize and self._flow:
                self._fit_cells()
            elif kind == QEvent.Type.MouseMove:
                self._place_hover(event.position().toPoint())
            elif kind == QEvent.Type.Leave:
                # Dugmenin kendisine gecmek de viewport'tan "cikis" sayilir.
                if not any(button.underMouse() for button in self.hover_buttons):
                    self._hide_hover()
            elif kind == QEvent.Type.Wheel:
                self._hide_hover()  # kayan satirda eski yerde kalmasin
        return super().eventFilter(watched, event)

    def flatten(self) -> None:
        """Baska bir kutunun ICINDE: kendi cercevesi ikinci bir kenar cizmesin."""
        self.setStyleSheet("QFrame#section { background: transparent; border: none; }")
        if (layout := self.layout()) is not None:
            layout.setContentsMargins(0, 0, 0, 0)


class _TabButton(QPushButton):
    """Pano / Slot sekmesi: ustune GELINCE secilir (tiklamak da secer)."""

    def __init__(self, label: str, color: str, on_enter) -> None:
        super().__init__(label)
        self._on_enter = on_enter
        self.setCheckable(True)
        self.setStyleSheet(_tab_style(color))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # tuslar panele gelsin
        self.clicked.connect(lambda _=False: on_enter())

    def enterEvent(self, event) -> None:
        self._on_enter()
        super().enterEvent(event)


def _build_menu(menu: QMenu, spec: tuple, chosen: SignalInstance) -> None:
    """ui/menu.py'nin tanim bicimini (label, eylem|alt tanim, ek...) QMenu'ye
    cevirir -- F13 menusunu besleyen fonksiyonlar oldugu gibi kullanilsin,
    ikinci bir veri kopyasi tutulmasin. Ikonlar (Win32 DLL numarasi) atlanir."""
    for entry in spec:
        if entry is None:
            menu.addSeparator()
            continue
        if entry == COLUMN:
            continue
        label, target, *extras = entry
        marks = {extra for extra in extras if isinstance(extra, Mark)}
        if isinstance(target, tuple):
            sub = menu.addMenu(label)
            _build_menu(sub, target, chosen)
            node = sub.menuAction()
        else:
            node = menu.addAction(label)
            if target:
                node.triggered.connect(lambda _=False, a=str(target): chosen.emit(a))
        if Mark.DISABLED in marks or not target:
            node.setEnabled(False)
        if Mark.CHECKED in marks:
            node.setCheckable(True)
            node.setChecked(True)
        if Mark.DEFAULT in marks:
            font = node.font()
            font.setBold(True)
            node.setFont(font)


class _HoverButton(QPushButton):
    """Ustune GELINCE hemen altinda menu acan dugme (tiklamak da acar).
    Bekleme ve acilis animasyonu yok -- ikisi de zaman kaybiydi."""

    def __init__(self, label: str, spec: tuple, chosen: SignalInstance) -> None:
        super().__init__(f"{label} ▾")
        self.setStyleSheet(BUTTON_STYLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # tuslar katmana gelsin
        self._menu = QMenu(self)
        self.popup_menu = self._menu  # panel kapanisini izlesin (aboutToHide)
        self._menu.setStyleSheet(MENU_STYLE)
        _build_menu(self._menu, spec, chosen)
        self.clicked.connect(self._popup)
        # QMenu yalniz DISARIYA TIKLANINCA kapanir; fare menuden cikinca da
        # kapansin diye acikken imlec yoklaniyor. Olay tabanli yol yok:
        # menu fareyi yakaladigi icin dugmenin leaveEvent'i gelmiyor.
        self._watch = QTimer(self, interval=LEAVE_POLL_MS)
        self._watch.timeout.connect(self._check_leave)
        self._menu.aboutToHide.connect(self._watch.stop)

    def enterEvent(self, event) -> None:
        self._popup()
        super().enterEvent(event)

    def _popup(self) -> None:
        if not self._menu.isVisible():
            self._menu.popup(self.mapToGlobal(self.rect().bottomLeft()))
            self._watch.start()

    def _check_leave(self) -> None:
        """Imlec dugmenin, menunun ve acik alt menulerin HICBIRINDE degilse
        menuyu kapatir. Aralarda gecis icin birkac piksel pay var."""
        pos = QCursor.pos()
        if self.rect().adjusted(-4, -4, 4, 8).contains(self.mapFromGlobal(pos)):
            return
        menus = [self._menu, *self._menu.findChildren(QMenu)]
        if any(m.isVisible() and m.geometry().adjusted(-4, -4, 4, 4).contains(pos) for m in menus):
            return
        self._menu.close()


class _CloseButton(QToolButton):
    """Kartin sag ustundeki kirmizi ✕: ustune GELINCE katmani kapatir.
    Tiklama baglantisi yok -- tiklamaya firsat kalmadan zaten kapaniyor."""

    def __init__(self, target: QWidget) -> None:
        super().__init__()
        self._target = target
        self.setText("✕")
        self.setToolTip("Kapat")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # tuslar katmana gelsin
        self.setStyleSheet(
            f"QToolButton {{ background: {CLOSE_BG}; color: #1a1b26; border: none;"
            " border-radius: 4px; font-weight: bold; padding: 2px 7px; }"
        )

    def enterEvent(self, event) -> None:
        self._target.close()
        super().enterEvent(event)


def _box() -> tuple[QFrame, QVBoxLayout]:
    """Ust ve alt parcanin cercevesi -- `_Section` ile ayni gorunum."""
    frame = QFrame()
    frame.setObjectName("section")
    frame.setStyleSheet(
        f"QFrame#section {{ background: {PANEL_BG}; border: 1px solid {PANEL_BORDER};"
        " border-radius: 6px; }"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(6)
    return frame, layout


_icons: dict[Icon, QIcon] = {}


def _qicon(icon: Icon) -> QIcon:
    """F13/F14 menusundeki Win32 ikonunun (DLL + numara) Qt karsiligi."""
    if icon not in _icons:
        handle = icon_handle(icon, 32)
        image = QImage.fromHICON(handle) if handle else QImage()
        if handle:
            destroy_icon(handle)
        _icons[icon] = QIcon(QPixmap.fromImage(image))
    return _icons[icon]


def _step(widget: QListWidget, row: int, step: int) -> int | None:
    """`row`dan `step` yonunde ilk GORUNUR ve tiklanabilir satir (suzgecin
    gizledigini atlar); yoksa None. Izgarada `step` bir satir kadar hucre."""
    index = row + step
    while 0 <= index < widget.count():
        item = widget.item(index)
        if item is not None and not item.isHidden() and item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return index
        index += step
    return None


def _vline() -> QFrame:
    """Ust kutunun iki kolonunu ayiran ince dikey cizgi."""
    line = QFrame()
    line.setFixedWidth(1)
    line.setStyleSheet(f"background: {PANEL_BORDER};")
    return line


def _hline() -> QFrame:
    """Alt kutudaki iki sirayi ayiran ince cizgi."""
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {SEPARATOR};")
    return line


def _equal(widget: QWidget) -> QWidget:
    """Yatay olcuyu ICERIGE degil yerlesime birakir: ayni `stretch` verilen
    kardesler tam esit en alir. Varsayilan politikada en uzun etiket kendi
    tarafini genisletiyordu (pano / slot yarilari esit durmuyordu)."""
    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    widget.setSizePolicy(policy)
    return widget


def _row() -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    return row


class OverviewPanel(QWidget):
    """Tek pencere, uc kutu. Secim `chosen(eylem)` ile disari cikar.

        +-- UST ---------------------------------------------+
        | App shorts (kisayollar)            | Profil ▾      |
        | Hep ustte: [pencere] [pencere] ...                 |
        +----------------------------------------------------+
        +-- ORTA: [Pano] [Slot]  ara 🔍 ---------------------+
        | secili sekmenin listesi                            |
        +----------------------------------------------------+
        +-- ALT: [dugme] [dugme] [dugme] ... ----------------+
    """

    chosen = Signal(str)

    def __init__(self) -> None:
        # Tool + "odak gidince kapan": array_filter.py ile ayni yol (bkz.
        # `changeEvent`). Popup denendi, disari tiklama yine kacti.
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Kapaninca silinir; app her acilista YENI katman kurar (hover icin,
        # bkz. KeyPilot.show_overview).
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # Acilir menuler animasyonsuz: kayarak acilmasi bekleme kadar zaman
        # kaybi. Ayar uygulama geneli; diger QMenu'ler de ani acilir.
        QApplication.setEffectEnabled(Qt.UIEffect.UI_AnimateMenu, False)
        # Her secim -- liste, dugme ya da ustteki menu -- katmani kapatir.
        self.chosen.connect(lambda _action: self.close())

        self.shorts = _Section("App shorts", flow=True, accent=SHORTS_COLOR)
        self.shorts.flatten()  # ust kutunun ICINDE
        # Pano ve slot ayni kutuda, sekme olarak; basliklarini sekme tasiyor.
        self.clips = _Section("Pano", accent=CLIPS_COLOR)
        self.slots = _Section("Slot", accent=SLOTS_COLOR)
        for section in (self.shorts, self.clips, self.slots):
            section.list.itemClicked.connect(self._on_click)
            section.alt_chosen.connect(self._fire)
        for section in (self.clips, self.slots):
            section.flatten()
            section.title.hide()

        # Sekme satirinda: yazdikca PANOYU suzen kutu + arama penceresi
        # (array filter) dugmesi. Harfe basmak da kutuya yazar (keyPressEvent).
        self.search = QLineEdit()
        self.search.setStyleSheet(SEARCH_STYLE)
        self.search.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.search.textChanged.connect(self.clips.filter)
        self.search.installEventFilter(self)
        self._filter_button = QToolButton()
        self._filter_button.setText("🔍")
        self._filter_button.setStyleSheet(BUTTON_STYLE.replace("QPushButton", "QToolButton"))
        self._filter_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filter_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._filter_button.clicked.connect(lambda: self._fire(self._filter_action))
        self._filter_action = ""

        # ---- ust: IKI ESIT kolon, arada dikey cizgi ----
        #   sol: "App shorts" ... Profil ▾   +  kisayol izgarasi
        #   sag: "Hep ustte" [pencere] [pencere] ...
        top, top_layout = _box()
        columns = _row()
        columns.setSpacing(8)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)
        #: Sol baslik satiri: baslik, bosluk, menu dugmeleri (acilista kurulur).
        self._header = _row()
        left_layout.addLayout(self._header)
        left_layout.addWidget(self.shorts)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        #: Hep-ustte basligi + pencere dugmeleri (acilista kurulur).
        self._pins = _row()
        right_layout.addLayout(self._pins)
        right_layout.addStretch(1)
        columns.addWidget(_equal(left), 1)
        columns.addWidget(_vline())
        columns.addWidget(_equal(right), 1)
        self.close_button = _CloseButton(self)
        columns.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        self._top_columns = columns  # ✕ imlecten kacarken buradan cikiyor
        top_layout.addLayout(columns)

        # ---- orta: Pano / Slot sekmeleri, tek liste alani ----
        # Sekmenin ustune gelmek o sekmeyi gosterir; `_sections` sirasiyla
        # ayni (1 = pano, 2 = slot), klavye de ayni yoldan geciyor.
        middle, middle_layout = _box()
        tabs = _row()
        self._tabs = (
            _TabButton("Pano", CLIPS_COLOR, lambda: self._show_tab(1)),
            _TabButton("Slot", SLOTS_COLOR, lambda: self._show_tab(2)),
        )
        for tab in self._tabs:
            tabs.addWidget(tab)
        tabs.addWidget(self.search, 1)
        tabs.addWidget(self._filter_button)
        self._stack = QStackedWidget()
        self._stack.addWidget(self.clips)
        self._stack.addWidget(self.slots)
        self._stack.setFixedHeight(LIST_HEIGHT)
        middle_layout.addLayout(tabs)
        middle_layout.addWidget(self._stack)

        # ---- alt: iki TEK satir -- ustte tuslar, altta pencereler ----
        foot, foot_layout = _box()
        self._keys = _row()
        self._windows = _row()
        foot_layout.addLayout(self._keys)
        foot_layout.addWidget(_hline())
        foot_layout.addLayout(self._windows)

        #: Klavyeyle gezilen listeler, Tab sirasi. Ok tuslari ETKIN listede.
        self._sections = (self.shorts, self.clips, self.slots)
        self._active = 1  # acilista pano

        # Pencere = kart: sabit enli, boyu icerikten. Disariya tiklamak odagi
        # alir, `changeEvent` kapatir.
        self.setFixedWidth(CARD_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(top)
        layout.addWidget(middle)
        layout.addWidget(foot)

    # ---- disari ----

    def open(
        self,
        shorts_title: str,
        shorts: tuple[QuickItem, ...],
        clips: tuple[QuickItem, ...],
        slots: tuple[QuickItem, ...],
        menus: tuple = (),
        pins: tuple = (),
        keys: tuple = (),
        buttons: tuple = (),
        clip_alts: tuple[tuple, ...] = (),
        filter_action: str = "",
        filter_tip: str = "",
    ) -> None:
        """Listeleri doldurur, imlecin yaninda acar.

        `menus`: (etiket, alt tanim) -- baslik satirinda, ustune gelince acilir.
        `pins`: (etiket, eylem, ek...) -- baslik satirinin sonu; CHECKED isaretli
        olan sabitli, tiklamak degistirir.
        `keys`: (etiket, eylem, ek...) -- alt kutunun UST sirasi, tus gonderir.
        `buttons`: (etiket, eylem, ek...) -- alt kutunun ALT sirasi, pencere acar.
        Hepsi menu tanim bicimi (ui/menu.py).
        `clip_alts`: pano satirlarinin hover dugmeleri, ayni sirada; satir
        basina (etiket, eylem, ipucu [, renk]) dizisi.
        `filter_action`: Pano basligindaki 🔍 dugmesi (arama penceresi).
        """
        # Baslik kalici; _clear dugmelerle birlikte onu da silerdi.
        self._header.removeWidget(self.shorts.title)
        _clear(self._header)
        self._header.addWidget(self.shorts.title)
        self._header.addStretch(1)
        for label, spec in menus:
            button = _HoverButton(label, spec, self.chosen)
            # Menu acikken gelen odak kaybi atlaniyor (bkz. `_close_if_inactive`);
            # menu kapaninca bir daha bakilir -- disari tiklama menuyu kapatmissa.
            button.popup_menu.aboutToHide.connect(self._check_active_later)
            self._header.addWidget(button)

        _clear(self._pins)
        caption = QLabel("Hep ustte")
        caption.setStyleSheet(
            f"color: {PINS_COLOR}; font-weight: bold; font-size: {FONT_PT - 1}pt;"
        )
        self._pins.addWidget(caption)
        for label, action, *extras in pins:
            button = self._button(label, str(action))
            button.setCheckable(True)
            button.setChecked(Mark.CHECKED in extras)
            self._pins.addWidget(button)
        self._pins.addStretch(1)

        self._filter_action = filter_action
        self._filter_button.setToolTip(filter_tip)
        self._filter_button.setVisible(bool(filter_action))

        self._fill_row(self._keys, keys, equal=True)
        self._fill_row(self._windows, buttons)

        self.shorts.title.setText(shorts_title)
        self.shorts.fill(shorts, "(bu pencere icin profil yok)")
        self.search.clear()
        self.clips.fill(clips, "(pano gecmisi bos)", clip_alts)
        self.slots.fill(slots, "(slot yok)")
        # Acilista HICBIR sey secili degil -- fareyle gelen kullanici icin ilk
        # satir "secilmis" gibi duruyordu. Ilk ok / Tab basimi secimi baslatir.
        # Pano bossa bile Pano sekmesiyle acilir; slot sekmesi ustune gelince.
        self._activate(1, -1)
        self._place_near_cursor()
        self.show()
        self.raise_()
        self.activateWindow()
        # Katman bir TUS KANCASINDAN aciliyor; Windows'un on plan kilidi
        # activateWindow'u yutuyor ve pencere tuslari (Esc) hic almiyordu.
        # snip.py ile ayni cozum.
        force_foreground(int(self.winId()))
        self.setFocus()
        self._dodge_cursor(QCursor.pos())

    def _dodge_cursor(self, pos: QPoint) -> None:
        """Katman acildiginda imlec ✕'in USTUNDEYSE, ✕ alt siradaki ⚙️
        dugmesinin yanina tasinir -- yoksa katman acilir acilmaz kapanirdi."""
        button = self.close_button
        if not button.rect().contains(button.mapFromGlobal(pos)):
            return
        self._top_columns.removeWidget(button)
        self._windows.addWidget(button)

    # ---- ic ----

    def _button(self, label: str, action: str) -> QPushButton:
        button = QPushButton(label)
        button.setStyleSheet(BUTTON_STYLE)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Esc pencereye gelsin
        button.clicked.connect(lambda _=False, a=action: self._fire(a))
        return button

    def _fill_row(self, row: QHBoxLayout, spec: tuple, equal: bool = False) -> None:
        """Dugmeleri TEK satira dizer ve satiri BOYDAN BOYA doldurur (sola
        yigilip sagda bosluk birakmasin). `equal`: hepsi ayni en -- kisa
        etiketli tus satiri icin; yoksa artan yer etikete oranla dagilir.
        Ek alanlar: `Icon` dugmenin ikonu, bos olmayan dizgi ipucu (kisa
        etiketli tuslarin uzun adi).
        Menu tanimindaki `None` (ayrac) atlanir."""
        _clear(row)
        for entry in spec:
            if entry is None or entry == COLUMN:
                continue
            label, action, *extras = entry
            button = self._button(label, str(action))
            for extra in extras:
                if isinstance(extra, Icon):
                    button.setIcon(_qicon(extra))
                elif isinstance(extra, str) and extra and not isinstance(extra, Mark):
                    button.setToolTip(extra)
            if equal:
                _equal(button)
            else:
                button.setSizePolicy(
                    QSizePolicy.Policy.Expanding, button.sizePolicy().verticalPolicy()
                )
            row.addWidget(button, 1)

    def _place_near_cursor(self) -> None:
        """Imleci ortalar; ekrandan tasan taraf kenara yaslanir."""
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        pos = QCursor.pos()
        screen = app.screenAt(pos) or app.primaryScreen()
        if screen is None:
            return
        self.adjustSize()  # boy icerikten (listeler acilista doldu)
        frame = self.frameGeometry()
        frame.moveCenter(pos)
        area = screen.availableGeometry()
        x = max(area.left(), min(frame.left(), area.right() - frame.width() + 1))
        y = max(area.top(), min(frame.top(), area.bottom() - frame.height() + 1))
        self.move(x, y)

    def _on_click(self, row: QListWidgetItem) -> None:
        action = row.data(Qt.ItemDataRole.UserRole)
        if not action:
            return
        self._fire(str(action))

    def _fire(self, action: str) -> None:
        self.chosen.emit(action)  # katmani `chosen` baglantisi kapatir

    # ---- olaylar ----

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKDROP)

    def mousePressEvent(self, event) -> None:
        """Kutular arasi bosluk panelin parcasi: tiklamak bir sey yapmaz.
        Panelin DISI zaten odagi alir (bkz. `event`)."""
        event.accept()

    # ---- klavye ----

    def _activate(self, index: int, row: int = 0) -> None:
        """`index` listesini etkin yapar, `row` satirini secer; digerlerinin
        secimini siler -- ekranda tek bir secili oge olsun."""
        self._active = index % len(self._sections)
        for position, section in enumerate(self._sections):
            if position != self._active:
                section.list.clearSelection()
                section.list.setCurrentRow(-1)
        if self._active in (1, 2):  # pano / slot: sekmesi one gelsin
            self._stack.setCurrentIndex(self._active - 1)
            for position, tab in enumerate(self._tabs, start=1):
                tab.setChecked(position == self._active)
        self._select(row)

    def _show_tab(self, index: int) -> None:
        """Sekme ustune gelindi / tiklandi. Zaten gorunuyorsa dokunmaz --
        klavyeyle secilmis satir fare sekmeden gecince silinmesin."""
        if self._stack.currentIndex() != index - 1:
            self._activate(index, -1)

    def _select(self, row: int) -> None:
        widget = self._sections[self._active].list
        if row < 0:
            widget.clearSelection()
            widget.setCurrentRow(-1)
            return
        count = widget.count()
        item = widget.item(max(0, min(row, count - 1))) if count else None
        # "(slot yok)" gibi tiklanamaz satir secilmez.
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            widget.setCurrentRow(-1)
            return
        widget.setCurrentItem(item)
        widget.scrollToItem(item)

    def _next_section(self, step: int) -> None:
        """Tab: sonraki DOLU liste (bos listeye girmek bir tus bosa harcatir)."""
        for offset in range(1, len(self._sections) + 1):
            index = (self._active + step * offset) % len(self._sections)
            first = _step(self._sections[index].list, -1, 1)
            if first is not None:
                self._activate(index, first)
                return

    def keyPressEvent(self, event) -> None:
        """Esc kapatir. Tab / Shift+Tab listeler arasi, ok tuslari liste
        icinde, Enter secili ogeyi calistirir.

        App shorts izgara: sag/sol bir hucre, yukari/asagi bir satir; ilk
        satirdan yukari yok. Pano ve slotta sag/sol iki liste arasi gecis --
        tek kolonda yatay okun baska isi yok (sekme de degisir). Listenin
        ustunden yukari App shorts'a cikar.
        """
        key = event.key()
        widget = self._sections[self._active].list
        row = widget.currentRow()
        grid = self._active == 0
        if key == Qt.Key.Key_Escape:
            self.close()
        elif row < 0 and key in (
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
        ):
            # henuz secim yok: ilk ok etkin listenin (suzgecten gecen) basina
            self._select(_step(widget, -1, 1) or 0)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = widget.currentItem()
            # Aramaya yazip dogrudan Enter: suzgecten gecen ILK pano kaydi.
            if item is None and self.search.text():
                first = _step(self.clips.list, -1, 1)
                item = self.clips.list.item(first) if first is not None else None
            if item is not None:
                self._on_click(item)
        elif key == Qt.Key.Key_Tab:
            self._next_section(1)
        elif key == Qt.Key.Key_Backtab:
            self._next_section(-1)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = (SHORTS_COLUMNS if grid else 1) * (-1 if key == Qt.Key.Key_Up else 1)
            target = _step(widget, row, step)
            if target is not None:
                self._select(target)
            elif step < 0 and not grid:
                self._activate(0, _step(self.shorts.list, -1, 1) or 0)  # ustten App shorts
            elif step > 0 and grid:
                self._activate(1, _step(self.clips.list, -1, 1) or 0)  # alttan Pano
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = -1 if key == Qt.Key.Key_Left else 1
            if grid:
                self._select(max(0, row + step))
            else:
                self._activate(1 if step < 0 else 2, max(0, row))
        elif event.text().isprintable() and event.text() and not (
            event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            # Harf / rakam: Pano aramasina yazilir (odak kutuya gecer).
            self._show_tab(1)
            self.search.setFocus()
            QApplication.sendEvent(self.search, event)
        else:
            super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        """Arama kutusu odaktayken gezinme tuslari yine PANELE gider: kutu
        Tab'i odak degistirmeye, Esc/Enter'i kendine alirdi. Sag/sol yalniz
        kutu BOSKEN panele -- yazi varken imleci gezdirmek dogal olan."""
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            panel_keys = (
                Qt.Key.Key_Up,
                Qt.Key.Key_Down,
                Qt.Key.Key_Tab,
                Qt.Key.Key_Backtab,
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Escape,
            )
            sideways = key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not self.search.text()
            if key in panel_keys or sideways:
                self.keyPressEvent(event)
                return True
        return super().eventFilter(watched, event)

    def event(self, event):
        # Tab Qt'da odak gezintisine gidiyor, keyPressEvent'e hic dusmuyordu.
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Tab,
            Qt.Key.Key_Backtab,
        ):
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def changeEvent(self, event) -> None:
        """Odak baska pencereye gecince kapanir -- array_filter.py ile ayni
        (AHK WatchDog). Karar olay DONGUSUNUN bir sonraki turunda: etkinlik
        degisimi sirasinda `isActiveWindow` ve acik popup henuz oturmamis
        olabiliyor."""
        if event.type() == QEvent.Type.ActivationChange:
            self._check_active_later()
        super().changeEvent(event)

    def _check_active_later(self) -> None:
        # Alici `self`: pencere bu arada silinirse zamanlayici da iptal olur.
        QTimer.singleShot(0, self, self._close_if_inactive)

    def _close_if_inactive(self) -> None:
        """Etkin degilse kapat. Ust seritin menusu acikken DEGIL -- menu odagi
        aliyor; kapaninca `aboutToHide` buraya bir daha getirir."""
        if not self.isVisible() or self.isActiveWindow():
            return
        if isinstance(QApplication.activePopupWidget(), QMenu):
            return
        self.close()
