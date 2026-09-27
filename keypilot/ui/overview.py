"""Genel bakis -- F15 + F16 birlikte basilinca acilan tam ekran katman.

Uc liste AYNI ANDA ekranda:

    +------------------------------------------------------------+
    |  APP SHORTS (on plandaki uygulamanin kisayollari)          |
    +------------------------------------------------------------+
    +---------------------------+    +---------------------------+
    |  PANO GECMISI             |    |  SLOTLAR                  |
    |                           |    |                           |
    +---------------------------+    +---------------------------+

Arka plan hafif saydam, ekranin tamamini kaplar (imlecin oldugu
monitorde). Bir ogeye tiklamak onu calistirir ve katmani kapatir;
listelerin DISINA tiklamak, Esc ya da baska pencereye gecmek yalnizca
kapatir. Arama yok -- ilk surum yalniz gosterip tiklatiyor.

Panel eylemi KENDISI calistirmaz, `chosen` ile eylem kimligini disari verir
(quick_panel.py ile ayni ayrim). Veri de disaridan gelir: app shorts
listesi katman ACILMADAN once okunmali, yoksa on plandaki pencere
katmanin kendisi olurdu.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from keypilot.ui.preview import shorten
from keypilot.ui.quick_panel import QuickItem

#: Arka plan ortusu -- "hafif saydam": arkadaki pencere secilir, yazilar
#: okunmaz.
BACKDROP = QColor(13, 17, 23, 150)
PANEL_BG = "rgba(22, 27, 34, 235)"
PANEL_BORDER = "#3d444d"
TITLE_COLOR = "#58a6ff"
ITEM_HOVER = "rgba(83, 155, 245, 0.18)"
SEPARATOR = "rgba(61, 68, 77, 0.6)"  # ogeler arasi ince cizgi
#: App shorts seridinde yan yana kac kisayol. Her oge hucresinin TAMAMINI
#: kaplar: fare yazinin ustune gelmeden, hucreye girince vurgulanir.
SHORTS_COLUMNS = 3
#: Kart ORTUNUN ortasinda sabit olculu durur; ekrani doldurmaz.
CARD_WIDTH = 640
LIST_HEIGHT = 230  # pano ve slot listelerinin boyu, piksel
SHORTS_ROWS = 3  # seritte en fazla bu kadar kisayol satiri; fazlasi kayar
LABEL_CHARS = 40  # satirda gosterilen en fazla karakter
FONT_PT = 9
TOOLTIP_CHARS = 600  # ipucunda gosterilen en fazla karakter
#: Pano gecmisi binlerce oge olabilir; katman bakip secmek icin, en
#: yenilerin bu kadari yeter.
MAX_CLIPS = 30

LIST_STYLE = (
    f"QListWidget {{ border: none; background: transparent; color: #e6edf3;"
    f" font-size: {FONT_PT}pt; }}"
    # Ogeler arasinda ince ayrac: satirlar birbirine karismasin.
    f"QListWidget::item {{ padding: 1px 4px; border-bottom: 1px solid {SEPARATOR}; }}"
    f"QListWidget::item:hover {{ background: {ITEM_HOVER}; }}"
    "QListWidget::item:disabled { color: #6e7681; }"
    # Ince, koyu kaydirma cubugu -- varsayilan beyaz cubuk kartta siritiyordu.
    "QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }"
    f"QScrollBar::handle:vertical {{ background: {PANEL_BORDER}; border-radius: 3px;"
    " min-height: 20px; }"
    "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
    "QScrollBar::add-page, QScrollBar::sub-page { background: none; }"
)


class _Section(QFrame):
    """Baslikli, yuvarlak koseli bir kutu + icinde liste."""

    def __init__(self, title: str, flow: bool = False) -> None:
        super().__init__()
        self._flow = flow
        self.setObjectName("section")
        self.setStyleSheet(
            f"QFrame#section {{ background: {PANEL_BG}; border: 1px solid {PANEL_BORDER};"
            " border-radius: 6px; }"
        )
        self.title = QLabel(title)
        self.title.setStyleSheet(
            f"color: {TITLE_COLOR}; font-weight: bold; font-size: {FONT_PT - 1}pt;"
        )

        self.list = QListWidget()
        self.list.setStyleSheet(LIST_STYLE)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
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
            self.list.viewport().installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 6)
        layout.setSpacing(2)
        layout.addWidget(self.title)
        layout.addWidget(self.list, 1)

    def fill(self, items: tuple[QuickItem, ...], empty: str) -> None:
        self.list.clear()
        for item in items:
            row = QListWidgetItem(shorten(item.text, LABEL_CHARS))
            row.setData(Qt.ItemDataRole.UserRole, item.action)
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

    def eventFilter(self, watched, event):
        if watched is self.list.viewport() and event.type() == QEvent.Type.Resize:
            self._fit_cells()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:
        """Kutunun ici (baslik, kenar) tiklaninca katman KAPANMASIN --
        olay ebeveyne tasinirsa `OverviewPanel.mousePressEvent` kapatirdi."""
        event.accept()


class OverviewPanel(QWidget):
    """Tam ekran, yari saydam katman. Secim `chosen(eylem)` ile disari cikar."""

    chosen = Signal(str)

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.shorts = _Section("App shorts", flow=True)
        self.clips = _Section("Pano")
        self.slots = _Section("Slot")

        for section in (self.shorts, self.clips, self.slots):
            section.list.itemClicked.connect(self._on_click)

        self.clips.setFixedHeight(LIST_HEIGHT)
        self.slots.setFixedHeight(LIST_HEIGHT)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(self.clips, 1)
        bottom.addWidget(self.slots, 1)

        # Kart: sabit enli, ortunun ORTASINDA. Ortu yine butun ekrani
        # kapliyor -- disariya tiklamak kapatsin diye.
        card = QWidget()
        card.setFixedWidth(CARD_WIDTH)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(8)
        inner.addWidget(self.shorts)
        inner.addLayout(bottom)

        layout = QVBoxLayout(self)
        layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)

    # ---- disari ----

    def open(
        self,
        shorts_title: str,
        shorts: tuple[QuickItem, ...],
        clips: tuple[QuickItem, ...],
        slots: tuple[QuickItem, ...],
    ) -> None:
        """Listeleri doldurur, imlecin ekranini kaplayarak acar."""
        self.shorts.title.setText(shorts_title)
        self.shorts.fill(shorts, "(bu pencere icin profil yok)")
        self.clips.fill(clips, "(pano gecmisi bos)")
        self.slots.fill(slots, "(slot yok)")
        self._cover_cursor_screen()
        self.show()
        self.raise_()
        self.activateWindow()

    # ---- ic ----

    def _cover_cursor_screen(self) -> None:
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        screen = app.screenAt(QCursor.pos()) or app.primaryScreen()
        if screen is None:
            return
        self.setGeometry(screen.availableGeometry())

    def _on_click(self, row: QListWidgetItem) -> None:
        action = row.data(Qt.ItemDataRole.UserRole)
        if not action:
            return
        self.close()
        self.chosen.emit(str(action))

    # ---- olaylar ----

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKDROP)

    def mousePressEvent(self, event) -> None:
        """Listelerin disi (bos ortu) tiklanirsa kapanir."""
        self.close()
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def event(self, event):
        """Odak baska pencereye gecince kapanir -- menu gibi davransin."""
        if event.type() == event.Type.WindowDeactivate and self.isVisible():
            self.close()
        return super().event(event)
