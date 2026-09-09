"""Ekran alani secimi -- F14 surukleme (AHK screen_ocr.ahk'nin secim kismi).

Iki faz var, AHK ile ayni:

**1. Secim fazi.** Tum ekranlarin DONDURULMUS goruntusu alinir ve fare
surukleyerek alan secilir. Goruntu KARARTILMAZ -- secim disi da okunur
kalsin diye (once karartiliyordu, kullanici istegiyle kaldirildi). Orutu
tiklamalari yutar, alttaki uygulamaya kaza tiklamasi gitmez.

**2. Ayar fazi.** Secim birakilinca:

    * 8 tutamac (koseler + kenar ortalari) secimi yeniden boyutlandirir
    * cercevenin ICINDEN tutup surukleyince secim tasinir (modern secim
      araclarindaki davranis; AHK'de ortadaki nokta bu isi yapiyordu)
    * secimin disina tiklamak yeni secim baslatir
    * yanindaki cubuktan islem secilir
    * Esc iptal eder

**Orutu neden yalniz 1. fazda** (AHK'deki ayni karar): OCR+ paneli acikken
cerceve ekranda KALIYOR ve alan yeniden ayarlanabiliyor. Bu sirada ekrani
karartmak altini gormeyi engellerdi. Ayar fazinda pencereye MASKE
uygulaniyor: yalniz secim ve cubuk tiklamalari bize gelir, geri kalan her sey
alttaki uygulamaya gecer.

**Koordinat kurali:** yakalama tamamen Win32 uzerinden, FIZIKSEL pikselde
yapilir (win32/screen.py) ve pencere de fiziksel piksele oturtulur. Qt'nin
mantiksal/fiziksel cevrimi hic kullanilmaz -- karisik DPI'da guvenilir
degil. Widget koordinatlari goruntu pikseline `_scale()` orani ile
cevrilir, boylece monitor eklense de olcek degisse de kod dogru kalir.

**Yakalama neden tek cekim degil:** ilk OCR dondurulmus goruntuden yapilir
(orutu vardi, ekran temizdi). Ayar fazinda alan degistirilirse ekran YENIDEN
cekilir -- cerceve gizlenir, DWM'in temiz kareyi cizmesi icin `SETTLE_MS`
beklenir, sonra yakalanir. Beklenmezse cerceve goruntunun icine karisir ve
OCR onu da okumaya calisir (AHK'de de ayni tuzak vardi).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from enum import IntEnum

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen, QPixmap, QRegion
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from keypilot import paths
from keypilot.areas import (
    DO_CHOICES,
    TO_CHOICES,
    WHEN_CHOICES,
    Area,
    AreaStore,
    Rule,
    default_name,
)
from keypilot.ui.key_capture import KeyCapture
from keypilot.win32 import menu as win32_menu
from keypilot.win32.screen import grab_virtual

#: Hedef klasor soran `to` degerleri (oteki hedeflerde alan gizlenir).
PATH_TARGETS = frozenset({"file", "py"})
#: Aranan metin isteyen `when` degerleri.
NEEDS_TEXT = frozenset({"contains", "missing"})

HANDLE_PX = 4  # tutamac karesinin yarim kenari
GRIP_PX = 8  # tutamaca "isabet etti" sayilan mesafe (AHK: GRAB_TOL)
MIN_SIZE = 8  # bundan kucuk secim "yanlislikla tikladim" sayilir (AHK: MIN_SIZE)
GRIP_MIN = 44  # bu boyutun altinda tutamaclar ust uste biner: yalniz cerceve
SETTLE_MS = 70  # cerceve gizlendikten sonra DWM'in temiz kareyi cizme suresi

# AHK'nin secim cercevesi KIRMIZIYDI (screen_ocr.ahk'deki "kirmizi cerceve"
# notu). Ayni renk: ekranin geri kalaninda nadir, her zaman secilir.
BORDER = QColor(220, 30, 40)
FILL = QColor(220, 30, 40, 22)
# Ayar fazinda secimin ici: gorunmez ama SIFIR DEGIL. Pencere katmanli
# (WA_TranslucentBackground) oldugu icin tamamen saydam piksel fareyi alta
# geciriyor; alfa 0 birakilirsa cercevenin ICINDEN tutup tasima calismaz.
SESSION_FILL = QColor(0, 0, 0, 1)

HWND_TOPMOST = -1
SWP_SHOWWINDOW = 0x0040


class Grip(IntEnum):
    """Tutamaclar. Adlar koseyi/kenari soyler; NONE = tutamac degil."""

    NONE = 0
    TOP_LEFT = 1
    TOP = 2
    TOP_RIGHT = 3
    RIGHT = 4
    BOTTOM_RIGHT = 5
    BOTTOM = 6
    BOTTOM_LEFT = 7
    LEFT = 8
    MOVE = 9  # cercevenin ici: komple tasima


_CURSORS = {
    Grip.TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
    Grip.BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
    Grip.TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
    Grip.BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
    Grip.TOP: Qt.CursorShape.SizeVerCursor,
    Grip.BOTTOM: Qt.CursorShape.SizeVerCursor,
    Grip.LEFT: Qt.CursorShape.SizeHorCursor,
    Grip.RIGHT: Qt.CursorShape.SizeHorCursor,
    Grip.MOVE: Qt.CursorShape.SizeAllCursor,
}

#: Secim cubugunun IKI KIPI var ve ilk dugme oteki kipe geciriyor:
#:
#:     SCREEN kipi   [Area]   Kopyala Sakla Gorsellere Paint OCR OCR+   X
#:     AREA kipi     [Screen] Yeni Alanlar Kaydet Sil             X
#:
#: Ayrim isin TURU: "screen" secili pikselle bir sey yapmak (kaydet, oku),
#: "area" o dikdortgeni ADLANDIRIP saklamak -- ve AREA kipinde cubugun
#: altinda toolbox aciliyor (ad/aciklama, X/Y/W/H). Ikisi tek cubuga
#: sigmiyordu; ayni cerceve, iki takim alet.

#: (etiket, eylem kimligi) -- app.py `done` sinyalinde bu kimligi alir.
#: "ocr_adv" seciminde pencere KAPANMAZ, ayar fazinda kalir.
ACTIONS = (
    ("\U0001f4cb Kopyala", "copy"),
    ("\U0001f4be Sakla", "save"),
    ("\U0001f5bc️ Gorsellere ekle", "clip_image"),
    ("\U0001f3a8 Paint", "paint"),
    ("\U0001f524 OCR", "ocr"),
    ("\U0001f9e0 OCR+", "ocr_adv"),
)

#: Secildikten sonra secim cercevesinin acik kalacagi eylemler.
KEEP_OPEN = frozenset({"ocr_adv"})



class SnipOverlay(QWidget):
    """Tam ekran secim penceresi. Tek ornek app.py'de tutulur."""

    #: eylem kimligi + kirpilmis goruntu
    done = Signal(str, QImage)
    #: OCR+ oturumu acikken alan degisti -- yeni kirpim
    rect_changed = Signal(QImage)
    closed = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setMouseTracking(True)
        # Ayar fazinda (OCR+) ekran goruntusu CIZILMEZ -- alttaki uygulama
        # gorunmeli. Saydamlik olmadan boyanmayan alan pencerenin duz
        # arkaplaniyla, yani BEYAZLA doluyordu.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        #: Kayitli alanlar. Depo su an BELLEKTE (keypilot/areas.py); burasi
        #: onu kalici bir depoymus gibi kullaniyor, diske gecis o modulun
        #: ici olacak.
        self.store = AreaStore()
        self.store.load()
        #: Cubugun kipi: "screen" (piksel islemleri) / "area" (alan kaydi).
        self._mode = "screen"
        #: Toolbox'ta kayitli olandan farkli bir sey yazili mi -- kapanirken
        #: "saklansin mi?" sorusu buna bakiyor.
        self._dirty = False
        #: Kutulari koddan doldururken `valueChanged` geri tetiklenmesin.
        self._syncing = False
        #: Toolbox'ta acik olan kayitli alanin adi (yeni alansa bos).
        self._loaded_name = ""
        self._shot: QPixmap | None = None
        self._rect = QRect()  # secim, widget koordinati
        self._grip = Grip.NONE  # su an suruklenen tutamac
        self._anchor = QPoint()  # surukleme baslangici
        self._rect_at_press = QRect()
        self._picking = False  # ilk secim suruklemesi mi
        self._session = False  # OCR+ acik: cerceve kalir, orutu kalkar
        self._virtual = (0, 0, 0, 0)  # sanal masaustu, FIZIKSEL piksel
        #: Secim biter bitmez KENDILIGINDEN calisacak eylem (ACTIONS'tan bir
        #: kimlik). F13 menusundeki "OCR Gelismis / OCR Basit" boyle
        #: calisiyor: alan secilir secilmez OCR baslar, islem cubugundan
        #: dugmeye basmaya gerek kalmaz. Bir kez kullanilir, sonra silinir.
        self.auto_action = ""
        #: Kural penceresi acilirken hook'u susturan kanca (app.py verir):
        #: `set_ui_open(True/False)`. Verilmezse pencere yine acilir ama
        #: yakalanacak tus once kisayol olarak islenir.
        self.set_ui_open = None
        #: Kural kisayolunu kayit defterine tutturan kanca (app.py verir):
        #: `bind_rule(owner, spec, alan_adi, sira) -> catisan sahip / ""`.
        self.bind_rule = None
        #: Alanin butun kurallarinin tuslarini birakan kanca (app.py verir).
        self.release_rules = None
        #: Yeniden yakalamadan once gizlenecek DIS pencereler (OCR paneli).
        #: app.py doldurur; geri gosteren bir cagrilabilir dondurmeli.
        self.hide_others = None
        # F14 ile secim: tus BASILI oldugu surece fare hareketi dikdortgeni
        # buyutur, tus birakilinca secim biter. Tusun durumu zamanlayiciyla
        # yoklaniyor: pencere odakli oldugu icin tus olaylari Qt'ye degil
        # hook'a gidiyor.
        self._key_vk = 0
        #: Tusun hala basili olup olmadigini soyleyen cagrilabilir. app.py
        #: dispatcher'in izleyicisini veriyor: GetAsyncKeyState burada
        #: yaniltiyor, cunku LL hook'ta YUTULAN keydown Windows'un tus
        #: durumu tablosunu guncellemiyor -- F14 hic basilmamis gorunuyor ve
        #: ilk yoklamada secim aninda bitiyordu.
        self._key_held = None
        #: Suruklemenin BASLADIGI fiziksel ekran noktasi. Widget
        #: koordinatina hemen cevrilemez: `start()` icinde pencere daha yeni
        #: yerlestirilmis olur ve `self.width()` eski degeri dondurur --
        #: cevrim yanlis capa uretirdi. Ilk kullanimda ceviriyoruz.
        self._key_origin: tuple[int, int] | None = None
        #: `start()`e verilen tus ve yoklayicisi -- `repick()` bunlari
        #: kullanir: secim bittikten sonra `_key_vk` sifirlaniyor.
        self._start_vk = 0
        self._start_held = None
        self._key_timer = QTimer(self)
        self._key_timer.setInterval(15)
        self._key_timer.timeout.connect(self._poll_key)

        # TEK KAPSAYICI: cubuk ve Area paneli ayni pencerenin icinde, dikey
        # duzende. Once iki ayri widget'ti; aralarindaki bosluktan orutu
        # goruniyordu ve imlec oralarda secim imlecine (tutamac oku)
        # donuyordu -- ustelik iki ayri yerlestirme ve iki ayri maske parcasi
        # demekti. Bir kapsayici hepsini birden cozuyor.
        self._panel = QWidget(self)
        self._panel.setCursor(Qt.CursorShape.ArrowCursor)
        outer = QVBoxLayout(self._panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._bar = QWidget(self._panel)
        outer.addWidget(self._bar)
        layout = QHBoxLayout(self._bar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # Ilk dugme: Area ACICISI. Basili degilken cubuk eskisi gibi -- alan
        # kaydiyla isi olmayan kullanici hicbir sey ogrenmek zorunda degil.
        # Basilinca panel ASAGI DOGRU aciliyor; screen dugmeleri yerinde
        # kaliyor, cunku alanla ugrasirken de resim alinip OCR yapilabilmeli.
        self._mode_button = QPushButton(self._bar)
        self._mode_button.setObjectName("mode")
        self._mode_button.setCursor(Qt.CursorShape.ArrowCursor)
        self._mode_button.clicked.connect(self._toggle_mode)
        layout.addWidget(self._mode_button)

        for label, action in ACTIONS:
            button = QPushButton(label, self._bar)
            button.setCursor(Qt.CursorShape.ArrowCursor)
            button.clicked.connect(lambda _c=False, a=action: self._finish(a))
            layout.addWidget(button)

        cancel = QPushButton("\u2715", self._bar)
        cancel.setCursor(Qt.CursorShape.ArrowCursor)
        cancel.clicked.connect(self.close)
        layout.addWidget(cancel)
        self._panel.setStyleSheet(
            "QWidget { background: #1f2328; border-radius: 6px; }"
            "QPushButton { background: #2d333b; color: #e6edf3; border: none;"
            "  padding: 6px 10px; border-radius: 4px; font-size: 13px; }"
            "QPushButton:hover { background: #444c56; }"
            "QPushButton#mode { background: #2d333b; color: #8b949e; }"
            "QPushButton#mode:hover { background: #444c56; }"
            "QPushButton#mode[on=\"true\"] { background: #1f6feb; color: #ffffff;"
            "  font-weight: bold; }"
        )
        self._toolbox = self._build_toolbox()
        self._toolbox.currentChanged.connect(self._on_tab)
        outer.addWidget(self._toolbox)
        self._toolbox.hide()
        self._panel.hide()
        self._apply_mode()

    # ---- Area paneli (cubugun altina acilir) ----

    def _build_toolbox(self) -> QWidget:
        """Acilan panel: iki SEKME -- Area ve IFTTT.

        Once ic ice iki acici vardi (Area'nin icinde Kural acicisi) ve panel
        iki kere asagi uzuyordu; ne kadar yer kaplayacagi ongorulemiyordu.
        Sekme ayni bilgiyi SABIT yukseklikte tutuyor: iki is ayri ama esit
        seviyede, birbirinin icinde degil.
        """
        tabs = QTabWidget(self._panel)
        tabs.addTab(self._build_area_tab(tabs), "\U0001f4d0 Area")
        tabs.addTab(self._build_rule_box(tabs), "\u26a1 IFTTT")
        tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #30363d; border-radius: 4px; }"
            "QTabBar::tab { background: #2d333b; color: #8b949e; padding: 5px 12px;"
            "  border-top-left-radius: 4px; border-top-right-radius: 4px;"
            "  margin-right: 2px; }"
            "QTabBar::tab:selected { background: #1f6feb; color: #ffffff; }"
        )
        return tabs

    def _build_area_tab(self, parent) -> QWidget:
        """Area sekmesi: alan secici, olculer, kaydet/sil.

        En ustte SECILI ALAN acilir kutusu -- hem kayitlilar arasindan secmek
        hem de yeni ad yazmak icin (editable). Ad ile aciklama tek alanda
        birlesti: iki kutu doldurmak zahmetti ve aciklama pratikte adin
        devami oluyordu. Olusturma tarihi kutuda degil YANINDA etiket
        olarak -- bilgi, doldurulacak alan degil.

        Olculer DOGAL COZUNURLUKTE (sanal masaustunun fiziksel pikseli) ve
        CIFT YONLU: yazilan deger cerceveyi oynatir, cerceveyi surukleyince
        kutular doner.
        """
        box = QWidget(parent)
        grid = QGridLayout(box)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)

        self._name_box = QComboBox(box)
        self._name_box.setEditable(True)
        self._name_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._name_box.setMinimumWidth(240)
        self._name_box.lineEdit().setPlaceholderText("alan adi")
        # `activated`: yalnizca KULLANICI sectiginde: `currentIndexChanged`
        # liste koddan yeniden dolduruldugunda da atesleniyor ve panel
        # kendi kendine baska alana atliyordu.
        self._name_box.activated.connect(self._on_pick_area)
        self._name_box.lineEdit().textEdited.connect(self._mark_dirty)
        grid.addWidget(QLabel("Alan", box), 0, 0)
        grid.addWidget(self._name_box, 0, 1, 1, 2)
        self._stamp_label = QLabel("", box)
        self._stamp_label.setObjectName("state")
        grid.addWidget(self._stamp_label, 0, 3)

        self._spins = {}
        row = QHBoxLayout()
        for key in ("X", "Y", "W", "H"):
            spin = QSpinBox(box)
            # Sol ustteki monitor negatif koordinatta olabilir: X/Y eksi
            # deger almali, yoksa o ekranda alan tarif edilemez.
            spin.setRange(-32768, 32767)
            spin.valueChanged.connect(self._on_spin)
            row.addWidget(QLabel(key, box))
            row.addWidget(spin)
            self._spins[key] = spin
        row.addStretch(1)
        grid.addLayout(row, 1, 0, 1, 4)

        # Alanin kurali burada SALT OKUNUR ozet: duzenlemek IFTTT
        # sekmesinin isi. Yine de Area sekmesinde gorunuyor, cunku "bu
        # alanda otomasyon var mi" sorusu alanin bilgisi.
        self._rules_label = QLabel("", box)
        self._rules_label.setObjectName("state")
        grid.addWidget(self._rules_label, 2, 0, 1, 2)
        self._state_label = QLabel("", box)
        self._state_label.setObjectName("state")
        grid.addWidget(self._state_label, 2, 2, 1, 2)

        # Alan dugmeleri EN ALTTA: panelin akisi yukaridan asagi "neyi,
        # nerede, nasil" ve en sonda "ne yapayim".
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for label, slot in (
            ("\u2795 Yeni", self._area_new),
            ("\U0001f4be Kaydet", self._area_save),
            ("\U0001f5d1 Sil", self._area_delete),
        ):
            button = QPushButton(label, box)
            button.setCursor(Qt.CursorShape.ArrowCursor)
            button.clicked.connect(lambda _c=False, f=slot: f())
            buttons.addWidget(button)
        grid.addLayout(buttons, 3, 0, 1, 4)

        box.setStyleSheet(
            "QWidget { background: #1f2328; border-radius: 6px; color: #e6edf3;"
            "  font-size: 12px; }"
            "QComboBox, QSpinBox { background: #0d1117; color: #e6edf3;"
            "  border: 1px solid #30363d; border-radius: 3px; padding: 2px 4px; }"
            "QComboBox QAbstractItemView { background: #0d1117; color: #e6edf3;"
            "  selection-background-color: #1f6feb; }"
            "QPushButton { background: #2d333b; color: #e6edf3; border: none;"
            "  padding: 4px 8px; border-radius: 4px; }"
            "QPushButton:hover { background: #444c56; }"
            "QLabel#state { color: #8b949e; }"
        )
        return box

    def _build_rule_box(self, parent) -> QWidget:
        """Kural bolumu: uc liste + hedef klasor + kisayol + periyot.

        Liste kutulari bilerek acilir kutu degil: uc sorunun BUTUN cevaplari
        ekranda toplu duruyor, "neler yapabiliyorum" sorusu tiklamadan
        cevaplaniyor.

        Kisayol ile periyot BAGIMSIZ: ikisi birden dolu olabilir, ikisi de
        bos olabilir. Periyot 0 ise kural tetiklendiginde bir kez calisir.
        `Nasil` bir tetik degil SUZGEC -- tetik geldiginde ise girisilsin
        mi diye bakilir (ornek: her 600 sn OCR oku, metin "TL" iceriyorsa
        kaydet).
        """
        box = QWidget(parent)
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 6, 0, 0)
        grid.setHorizontalSpacing(10)

        self._rule_lists = {}
        for column, (title, choices, attr) in enumerate((
            ("Ne alinacak", DO_CHOICES, "do"),
            ("Nereye alinacak", TO_CHOICES, "to"),
            ("Nasil alinacak", WHEN_CHOICES, "when"),
        )):
            grid.addWidget(QLabel(title, box), 0, column)
            widget = QListWidget(box)
            widget.setFixedHeight(4 * 20)
            for key, label in choices:
                item = QListWidgetItem(label, widget)
                item.setData(Qt.ItemDataRole.UserRole, key)
            widget.setCurrentRow(0)
            widget.currentRowChanged.connect(self._refresh_rule)
            grid.addWidget(widget, 1, column)
            self._rule_lists[attr] = widget

        # Hedef KLASOR: dosya adini kural kendisi uretiyor
        # (`YYYYMMDD_HHmmss`), kullanici yalniz nereye yazilacagini secer.
        path_row = QHBoxLayout()
        self._path_label = QLabel("Path", box)
        path_row.addWidget(self._path_label)
        self._path_edit = QLineEdit(box)
        self._path_edit.setPlaceholderText("klasor sec -- dosya adi otomatik")
        self._path_edit.textChanged.connect(self._refresh_rule)
        path_row.addWidget(self._path_edit, 1)
        self._path_button = QPushButton("...", box)
        self._path_button.setCursor(Qt.CursorShape.ArrowCursor)
        self._path_button.clicked.connect(self._pick_path)
        path_row.addWidget(self._path_button)
        self._text_label = QLabel("Aranan", box)
        path_row.addWidget(self._text_label)
        self._text_edit = QLineEdit(box)
        self._text_edit.setPlaceholderText("aranacak metin")
        self._text_edit.textChanged.connect(self._refresh_rule)
        path_row.addWidget(self._text_edit, 1)
        grid.addLayout(path_row, 2, 0, 1, 3)

        trigger_row = QHBoxLayout()
        trigger_row.addWidget(QLabel("Kisayol", box))
        self._rule_key = KeyCapture("", box)
        self._rule_key.changed.connect(self._refresh_rule)
        trigger_row.addWidget(self._rule_key)
        trigger_row.addSpacing(12)
        trigger_row.addWidget(QLabel("Periyod", box))
        self._rule_every = QSpinBox(box)
        self._rule_every.setRange(0, 3600)
        self._rule_every.setSingleStep(30)
        self._rule_every.setSuffix(" sn")
        self._rule_every.valueChanged.connect(self._refresh_rule)
        trigger_row.addWidget(self._rule_every)
        self._every_hint = QLabel("0 = bir kez calisir", box)
        self._every_hint.setObjectName("state")
        trigger_row.addWidget(self._every_hint)
        trigger_row.addStretch(1)
        save = QPushButton("\U0001f4be Kurali kaydet", box)
        save.setCursor(Qt.CursorShape.ArrowCursor)
        save.clicked.connect(self._save_rule)
        trigger_row.addWidget(save)
        grid.addLayout(trigger_row, 3, 0, 1, 3)
        box.setStyleSheet(
            "QWidget { background: #1f2328; color: #e6edf3; font-size: 12px; }"
            "QLineEdit, QSpinBox, QListWidget { background: #0d1117; color: #e6edf3;"
            "  border: 1px solid #30363d; border-radius: 3px; padding: 2px 4px; }"
            "QListWidget::item:selected { background: #1f6feb; color: #ffffff; }"
            "QPushButton { background: #2d333b; color: #e6edf3; border: none;"
            "  padding: 4px 8px; border-radius: 4px; }"
            "QPushButton:hover { background: #444c56; }"
            "QPushButton#mode[on=\"true\"] { background: #1f6feb; color: #ffffff; }"
            "QLabel#state { color: #8b949e; }"
        )
        return box

    def _on_tab(self, index: int) -> None:
        """IFTTT sekmesine gecildi: alanin kayitli kurali kutulara gelsin.

        Her geciste taze okunuyor -- arada alan degistirilmis olabilir.
        """
        if index != 1:
            return
        area = self.store.find(self._loaded_name)
        self._fill_rule(area.rules[0] if area and area.rules else Rule())

    def _pick_path(self) -> None:
        """Klasor secici. Hook susturuluyor: pencere tuslari yutmasin."""
        if self.set_ui_open:
            self.set_ui_open(True)
        try:
            chosen = QFileDialog.getExistingDirectory(
                self, "Kayit klasoru", self._path_edit.text() or str(paths.CAPTURES)
            )
        finally:
            if self.set_ui_open:
                self.set_ui_open(False)
        if chosen:
            self._path_edit.setText(chosen)

    def _rule_value(self, attr: str) -> str:
        item = self._rule_lists[attr].currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def _fill_rule(self, rule: Rule) -> None:
        """Kutulari verilen kuraldan doldurur."""
        for attr in ("do", "to", "when"):
            widget = self._rule_lists[attr]
            wanted = getattr(rule, attr)
            for row in range(widget.count()):
                if widget.item(row).data(Qt.ItemDataRole.UserRole) == wanted:
                    widget.setCurrentRow(row)
                    break
        self._path_edit.setText(rule.path)
        self._text_edit.setText(rule.text)
        self._rule_key.set_spec(rule.key)
        self._rule_every.setValue(rule.every)
        self._refresh_rule()

    def _current_rule(self) -> Rule:
        to = self._rule_value("to")
        when = self._rule_value("when")
        return Rule(
            do=self._rule_value("do"),
            to=to,
            path=self._path_edit.text().strip() if to in PATH_TARGETS else "",
            when=when,
            text=self._text_edit.text().strip() if when in NEEDS_TEXT else "",
            key=self._rule_key.spec,
            every=self._rule_every.value(),
        )

    def _refresh_rule(self, *_args) -> None:
        """Kosullu alanlari gosterip gizler, ozet satirini tazeler.

        "Panoya" secilmisken klasor kutusu duruyorsa kullanici onu
        doldurmasi gerektigini sanar; gereksiz alan soru isareti uretir.
        """
        needs_path = self._rule_value("to") in PATH_TARGETS
        needs_text = self._rule_value("when") in NEEDS_TEXT
        for widget in (self._path_label, self._path_edit, self._path_button):
            widget.setVisible(needs_path)
        for widget in (self._text_label, self._text_edit):
            widget.setVisible(needs_text)
        self._rules_label.setText(self._current_rule().label())

    def _save_rule(self) -> None:
        """Kurali alana yazar ve kisayolunu kayit defterine tutturur."""
        if not self._loaded_name or self._dirty:
            self._area_save()
        area = self.store.find(self._loaded_name)
        if area is None:
            return
        rule = self._current_rule()
        if area.rules:
            area.rules[0] = rule
        else:
            area.rules.append(rule)
        self.store.save()
        self._bind_rules(area)
        self._state_label.setText(f"kural kaydedildi: {rule.label()}")

    def _toggle_mode(self) -> None:
        """Area panelini acar/kapatir. Kapatirken kaydedilmemis is sorulur."""
        if self._mode == "area" and not self._confirm_discard():
            return
        self._mode = "area" if self._mode == "screen" else "screen"
        if self._mode == "area":
            self._fill_toolbox()
        self._apply_mode()

    def _apply_mode(self) -> None:
        """Acici dugmenin gorunumu ve panelin gorunurlugu."""
        area = self._mode == "area"
        self._mode_button.setText("\u25be Area" if area else "\u25b8 Area")
        self._mode_button.setProperty("on", area)
        # Qt, ozellik degisince stil sayfasini kendiliginden tazelemiyor.
        self._mode_button.style().unpolish(self._mode_button)
        self._mode_button.style().polish(self._mode_button)
        self._toolbox.setVisible(area)
        if self._panel.isVisible():
            self._place_bar()  # panel uzadi/kisaldi: yeniden yerlestir

    def _mark_dirty(self, *_args) -> None:
        self._dirty = True
        self._state_label.setText("kaydedilmedi")

    def _fill_toolbox(self, area: Area | None = None) -> None:
        """Paneli doldurur: verilen kayitli alan ya da SU ANKI secim."""
        self._syncing = True
        self._refill_names(area.name if area else default_name())
        box = self._screen_rect()
        values = (
            (area.x, area.y, area.w, area.h)
            if area
            else (box.x(), box.y(), box.width(), box.height())
        )
        for key, value in zip(("X", "Y", "W", "H"), values, strict=True):
            self._spins[key].setValue(value)
        self._syncing = False
        self._loaded_name = area.name if area else ""
        self._stamp_label.setText(area.stamp if area else default_name())
        self._dirty = False
        self._state_label.setText("kayitli" if area else "yeni alan")
        self._rules_label.setText(
            area.rules[0].label() if area and area.rules else "kural yok"
        )

    def _refill_names(self, text: str) -> None:
        """Acilir kutuyu kayitli alanlarla doldurur, yazili metni korur.

        Liste her doldurmada bastan kuruluyor: yeni kaydedilen alan hemen
        gorunsun, silinen kaybolsun.
        """
        self._name_box.clear()
        for area in self.store.areas:
            # Gorunen etiket olculeriyle birlikte, ama SECILECEK deger sade
            # ad: kullanici "320x240" yazmak zorunda kalmasin.
            self._name_box.addItem(area.label(), area.name)
        self._name_box.setEditText(text)

    def _on_pick_area(self, index: int) -> None:
        """Acilir kutudan kayitli alan secildi."""
        name = self._name_box.itemData(index)
        if name:
            self._area_open(name)

    def _sync_toolbox(self) -> None:
        """Cerceve degisti: kutulari CERCEVEDEN tazele (cift yonun bir yonu)."""
        if self._mode != "area" or self._syncing:
            return
        self._syncing = True
        box = self._screen_rect()
        for key, value in zip(
            ("X", "Y", "W", "H"),
            (box.x(), box.y(), box.width(), box.height()),
            strict=True,
        ):
            self._spins[key].setValue(value)
        self._syncing = False
        self._mark_dirty()

    def _on_spin(self, _value: int) -> None:
        """Kutuya yazildi: cerceveyi oraya tasi (cift yonun oteki yonu)."""
        if self._syncing:
            return
        self._rect = self._rect_from_screen(
            self._spins["X"].value(), self._spins["Y"].value(),
            self._spins["W"].value(), self._spins["H"].value(),
        )
        self._place_bar()
        self._update_mask()
        self.update()
        self._mark_dirty()

    def _bind_rules(self, area: Area) -> None:
        """Kurallarin kisayollarini kayit defterine tutturur.

        Once alanin ESKI tanimlari birakiliyor: kural duzenlendiginde tus
        degismis olabilir ve eski tus sonsuza dek tutulu kalirdi.
        """
        if self.bind_rule is None:
            return
        for index, rule in enumerate(area.rules):
            owner = area.rule_owner(index)
            clash = self.bind_rule(owner, rule.key if rule.enabled else "", area.name, index)
            if clash:
                self._state_label.setText(f"\u26a0 {rule.key} zaten {clash} tarafinda")

    def _current_area(self) -> Area:
        return Area(
            name=self._name_box.currentText().strip() or default_name(),
            x=self._spins["X"].value(),
            y=self._spins["Y"].value(),
            w=self._spins["W"].value(),
            h=self._spins["H"].value(),
            # Olusturma damgasi KORUNUR: kayitli bir alan duzenleniyorsa
            # "ne zaman tarif ettim" bilgisi kaydetmeyle degismemeli.
            stamp=self._stamp_label.text() or default_name(),
        )

    def _area_new(self) -> None:
        """Su anki cerceveyi yeni alan olarak toolbox'a koyar (kaydetmez)."""
        if not self._confirm_discard():
            return
        self._fill_toolbox()

    def _area_save(self) -> None:
        # Ad degistirilerek kaydedilirse eskisi de kalir: "farkli kaydet"
        # davranisi. Silmek isteyen Sil'e basar.
        area = self._current_area()
        # Kayitli alan duzenleniyorsa kurallari korunur: `_current_area`
        # yalnizca kutulari okur, kurallari bilmez.
        old = self.store.find(self._loaded_name) if self._loaded_name else None
        if old is not None:
            area.rules = old.rules
        self.store.put(area)
        self._loaded_name = area.name
        self._dirty = False
        self._syncing = True
        self._refill_names(area.name)
        self._syncing = False
        self._state_label.setText(f"kaydedildi: {area.name}")

    def _area_delete(self) -> None:
        if self._loaded_name and self.store.remove(self._loaded_name):
            gone, self._loaded_name = self._loaded_name, ""
            # Alan gitti: kurallarinin tuttugu tuslar da birakilmali, yoksa
            # olmayan bir alanin kisayolu tusu tutmaya devam eder.
            if self.release_rules is not None:
                self.release_rules(gone)
            self._dirty = False
            self._syncing = True
            self._refill_names(default_name())
            self._syncing = False
            self._state_label.setText(f"silindi: {gone}")
            return
        self._state_label.setText("silinecek kayitli alan yok")

    def _area_open(self, name: str) -> None:
        """Kayitli alani geri cagirir: cerceve oraya oturur."""
        area = self.store.find(name)
        if area is None or not self._confirm_discard():
            return
        self._syncing = True
        self._rect = self._rect_from_screen(area.x, area.y, area.w, area.h)
        self._syncing = False
        self._fill_toolbox(area)
        self._place_bar()
        self._update_mask()
        self.update()

    def _confirm_discard(self) -> bool:
        """Kaydedilmemis degisiklik varsa sorar. False = vazgecildi."""
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "KeyPilot - alan",
            "Degisiklik yapildi, saklansin mi?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            self._area_save()
        self._dirty = False
        return True

    # ---- disari ----

    def start(
        self,
        key_vk: int = 0,
        origin: tuple[int, int] | None = None,
        key_held=None,
    ) -> None:
        """Ekrani dondurur ve secim fazinda acilir.

        `key_vk` verilirse (F14) secim O TUSLA yapilir: fare dugmesine hic
        basilmadan hareket dikdortgeni buyutur, tus birakilinca secim
        tamamlanir ve islem cubugu acilir. `origin` suruklemenin basladigi
        FIZIKSEL ekran noktasidir -- cerceve oradan baslar, pencerenin
        acildigi andaki imlec konumundan degil. Verilmezse eski davranis:
        sol fare tusuyla surukleyerek secim.
        """
        self._session = False
        self._rect = QRect()
        self._grip = Grip.NONE
        self._picking = False
        self._panel.hide()
        self.clearMask()
        self._capture()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.show()
        # SIRA ONEMLI: yerlestirme show()'dan SONRA. Once cagrilirsa Qt
        # pencereyi kendi hesapladigi geometriyle gosterip uzerine yaziyor.
        self._place()
        self.raise_()
        self.activateWindow()
        # Odagi ZORLA al. `activateWindow` tek basina yetmiyor: program
        # yeniden baslatildiginda (app.restart) yeni surec ayrik aciliyor,
        # Windows onunde hic girdi gormedigi icin odak calma hakki yok ve
        # SetForegroundWindow sessizce basarisiz oluyor. Pencere ustte
        # cikiyor ama klavye odagi almiyordu -- Esc iceri hic ulasmiyordu.
        win32_menu.force_foreground(int(self.winId()))
        self._key_vk = key_vk
        self._key_held = key_held
        # Tus secim bitince sifirlaniyor; yeniden secim (`repick`) icin
        # hangi tusla baslandigi ayrica saklaniyor.
        self._start_vk = key_vk
        self._start_held = key_held
        if key_vk:
            # Baslangic noktasi verilmediyse imlecin su anki yeri: cagiran
            # tarafin noktayi bilmedigi durumda secim yine de baslamali.
            if origin is None:
                point = wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
                origin = (point.x, point.y)
            self._key_origin = origin
            self._picking = True
            self._key_timer.start()

    def start_rect(self, box: tuple[int, int, int, int]) -> None:
        """Secimi HAZIR bir dikdortgenle acar (F14 menusu > Screen).

        Surukleme yok: pencere aciliyor, verilen FIZIKSEL dikdortgen secili
        geliyor ve islem cubugu hemen cikiyor. Alan sonradan tutamaclarla
        degistirilebilir -- normal secimden farki yalnizca baslangici.
        """
        self.start()

        def apply() -> None:
            # Bir olay dongusu SONRA: `self.width()` pencere yerlesene kadar
            # eski degeri veriyor ve `_to_widget`in olcegi yanlis cikardi
            # (bkz. `_screen_rect` notu).
            self._rect = self._rect_from_screen(*box)
            self._settle_pick()

        QTimer.singleShot(0, apply)

    def _rect_from_screen(self, x: int, y: int, width: int, height: int) -> QRect:
        """Fiziksel dikdortgeni widget dikdortgenine cevirir.

        Iki NOKTADAN QRect kurmak bir piksel buyuk cikiyor (QRect'te sag/alt
        kenar DAHILDIR): 320 genislik 321 olarak geri okunuyor ve kutuya her
        dokunusta secim bir piksel buyurdu. Genislik farktan hesaplaniyor.
        """
        top_left = self._to_widget(x, y)
        bottom_right = self._to_widget(x + width, y + height)
        return QRect(
            top_left.x(), top_left.y(),
            bottom_right.x() - top_left.x(), bottom_right.y() - top_left.y(),
        ).normalized()

    def _to_widget(self, screen_x: int, screen_y: int) -> QPoint:
        """FIZIKSEL ekran noktasini widget koordinatina cevirir.

        Pencere sanal masaustune fiziksel pikselde oturuyor ama Qt widget
        koordinatlari mantiksal; oran `_scale()` ile ayni (ters yonde).
        """
        sx, sy = self._scale()
        x, y, _w, _h = self._virtual
        return QPoint(round((screen_x - x) / sx), round((screen_y - y) / sy))

    def _cursor_pos(self) -> QPoint:
        """Imlecin su anki konumu, widget koordinatinda."""
        point = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return self._to_widget(point.x, point.y)

    def _resolve_anchor(self) -> None:
        """Bekleyen baslangic noktasini widget koordinatina cevirir.

        Ilk yoklamada yapiliyor: o an pencere yerlesmis, `self.width()`
        gercek degeri veriyor.
        """
        if self._key_origin is None:
            return
        self._anchor = self._to_widget(*self._key_origin)
        self._rect = QRect(self._anchor, self._anchor)
        self._key_origin = None

    def _poll_key(self) -> None:
        """Secimi baslatan tus (F14) hala basili mi?

        Tusun BIRAKMA olayi Qt'ye degil hook'a gidiyor; durumu `key_held`
        cagrilabiliri soyluyor (dispatcher izliyor). Birakildiginda secim,
        fare surukleme birakilmis gibi tamamlanir.

        Yedek yol GetAsyncKeyState: YALNIZCA `key_held` verilmediginde.
        Yutulan bir tusu asla "basili" gostermez, o yuzden tek basina
        birakilirsa secim ilk yoklamada bitiyordu.
        """
        if not self._key_vk:
            self._key_timer.stop()
            return
        held = (
            self._key_held()
            if self._key_held is not None
            else bool(ctypes.windll.user32.GetAsyncKeyState(self._key_vk) & 0x8000)
        )
        if held:
            self._resolve_anchor()
            self._rect = QRect(self._anchor, self._cursor_pos())
            self.update()
            return
        self._key_timer.stop()
        self._key_vk = 0
        self._key_held = None
        self._key_origin = None
        self._settle_pick()
        # Ayar fazinda tusla yapilan yeni secim de paneli tazelemeli --
        # fare ile alan degistirmenin (mouseReleaseEvent) karsiligi.
        if self._session and not self._rect.isEmpty():
            self._recapture(self._emit_rect_changed)

    def _settle_pick(self) -> None:
        """Secim suruklemesi bitti: secim yoksa pencereyi KAPAT, varsa cubugu ac."""
        self._picking = False
        self._grip = Grip.NONE
        rect = self._rect.normalized()
        if rect.width() < MIN_SIZE or rect.height() < MIN_SIZE:
            # Hic secim yapilmadi (bos tiklama ya da MIN_SIZE alti surukleme).
            # Once secim silinip pencere ACIK BEKLIYORDU: ekran donmus
            # duruyor, kullanici ne oldugunu anlamadan ikinci kez tiklamak
            # zorunda kaliyordu. Artik Esc / orta tus ile ayni yol --
            # kapanis tek yerden, `closeEvent` (Area kipinde kaydedilmemis
            # is varsa yine orada soruluyor).
            self._rect = QRect()
            self._update_mask()
            self.update()
            self.close()
            return
        self._rect = rect
        self._place_bar()
        self._update_mask()
        self._sync_toolbox()  # cift yon: cerceve -> kutular
        self.update()
        if self.auto_action:
            action, self.auto_action = self.auto_action, ""
            self._finish(action)

    def repick(self, origin: tuple[int, int] | None = None) -> None:
        """Secim ekranda dururken tusa (F14) yeniden basildi: bastan sec.

        Ayar fazinda (OCR+ acikken) da calisir; maske kaldiriliyor ki yeni
        dikdortgen tum ekranda cizilebilsin, secim bitince `_settle_pick`
        maskeyi geri koyuyor.
        """
        if not self.isVisible() or not self._start_vk:
            return
        self._panel.hide()
        self.clearMask()
        self._grip = Grip.NONE
        self._picking = True
        self._key_vk = self._start_vk
        self._key_held = self._start_held
        if origin is None:
            point = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
            origin = (point.x, point.y)
        self._key_origin = origin
        self._rect = QRect()
        self.update()
        self._key_timer.start()

    def refresh(self) -> None:
        """OCR+ panelindeki "Yenile": AYNI alani ekrandan TEKRAR okur.

        Olcek degistirmenin (`_on_reocr`) aksine elimizdeki kirpim
        kullanilmaz -- ekran yeniden cekilir. Alttaki sayfa degismis
        olabilir; kullanicinin istedigi tam olarak bu.
        """
        if self._session and not self._rect.isEmpty():
            self._recapture(self._emit_rect_changed)

    def end_session(self) -> None:
        """OCR+ paneli kapandi: cerceveyi de kaldir."""
        if self._session:
            self.close()

    # ---- ekran yakalama ----

    def _capture(self) -> None:
        """Tum ekranlari fiziksel pikselde tek karede alir."""
        image, self._virtual = grab_virtual()
        self._shot = QPixmap.fromImage(image) if not image.isNull() else None

    def _place(self) -> None:
        """Pencereyi sanal masaustune BIREBIR oturtur.

        Qt'nin `setGeometry`'si degil `SetWindowPos` kullaniliyor: Qt
        mantiksal piksel bekler ve karisik DPI'da o cevrim tutmuyor (bu
        makinede sanal masaustunu 3338 mantiksal sayiyor, gercegi 3840
        fiziksel). Fiziksel dikdortgeni dogrudan vermek her monitor
        duzeninde dogru sonuc veriyor.
        """
        x, y, width, height = self._virtual
        if width <= 0 or height <= 0:
            return
        ctypes.windll.user32.SetWindowPos(
            ctypes.c_void_p(int(self.winId())),
            ctypes.c_void_p(HWND_TOPMOST),
            x, y, width, height,
            SWP_SHOWWINDOW,
        )

    def _scale(self) -> tuple[float, float]:
        """Widget koordinatindan goruntu pikseline cevrim orani.

        Pencere sanal masaustunun tamamini kapladigi ve goruntu de o alanin
        tamami oldugu icin oran basitce boyut bolumu. Qt'nin dpr'sine hic
        bakilmiyor -- olcek degisse de bu oran dogru kalir.
        """
        if self._shot is None or not self.width() or not self.height():
            return (1.0, 1.0)
        return (self._shot.width() / self.width(), self._shot.height() / self.height())

    def _crop(self) -> QImage | None:
        """Secili alani kaynak pikselde kirpar."""
        return self._crop_screen(self._screen_rect())

    def _screen_rect(self) -> QRect:
        """Secimin FIZIKSEL ekran dikdortgeni (sanal masaustu koordinati).

        Yeniden yakalamanin dayanagi bu: widget koordinati gecici: pencere
        gizlenip gosterildiginde Qt'nin `width()` degeri bir sonraki olay
        dongusune kadar ESKI kalir, o an hesaplanan olcek yanlis cikar ve
        kirpim bambaska bir yere -- cok monitorlu duzende oteki ekrana --
        duserdi. Fiziksel dikdortgen bir kez, geometri otururken hesaplanir.
        """
        sx, sy = self._scale()
        x, y, _w, _h = self._virtual
        rect = self._rect.normalized()
        return QRect(
            round(x + rect.x() * sx), round(y + rect.y() * sy),
            round(rect.width() * sx), round(rect.height() * sy),
        )

    def _crop_screen(self, box: QRect) -> QImage | None:
        """Fiziksel ekran dikdortgenini son karenin uzerinden kirpar."""
        if self._shot is None or box.width() < MIN_SIZE or box.height() < MIN_SIZE:
            return None
        x, y, _w, _h = self._virtual
        device = QRect(box.x() - x, box.y() - y, box.width(), box.height())
        image = self._shot.copy(device).toImage()
        image.setDevicePixelRatio(1.0)  # kaydedilen dosya gercek piksel
        return image

    def _recapture(self, then) -> None:
        """Cerceveyi gizle, bir kare bekle, ekrani yeniden cek, geri goster.

        Ayar fazinda alan degistiginde gerekiyor: orutu kalkmis oldugu icin
        goruntunun uzerinde bizim cercevemiz duruyor ve kirpim ona bulasirdi.

        Yalniz cerceve degil OCR PANELI de gizleniyor (`hide_others`): panel
        ustte duran bir pencere ve secimin uzerine denk gelirse yeni kare
        onu icerir -- OCR kendi yazdigi metni tekrar okuyup "alakasiz"
        sonuc uretiyordu.
        """
        # Dikdortgen HENUZ, geometri otururken fiziksel koordinata cevriliyor:
        # gizle/goster sonrasinda widget olcegi bir sure yanlis kaliyor.
        box = self._screen_rect()
        self.hide()
        restore = self.hide_others() if self.hide_others is not None else None

        def grab() -> None:
            self._capture()
            self.show()
            self._place()  # monitor duzeni degismis olabilir
            self.raise_()
            self._update_mask()
            if restore is not None:
                restore()
            then(box)

        QTimer.singleShot(SETTLE_MS, grab)

    # ---- ic akis ----

    def _finish(self, action: str) -> None:
        image = self._crop()
        if image is None:
            return
        if action in KEEP_OPEN:
            # AHK ayar fazi: orutu kalkar, cerceve ekranda kalir.
            self._session = True
            self._update_mask()
            self.update()
            self.done.emit(action, image)
            return
        self.close()
        self.done.emit(action, image)

    def _grip_at(self, pos: QPoint) -> Grip:
        rect = self._rect.normalized()
        if rect.isEmpty():
            return Grip.NONE
        near_l = abs(pos.x() - rect.left()) <= GRIP_PX
        near_r = abs(pos.x() - rect.right()) <= GRIP_PX
        near_t = abs(pos.y() - rect.top()) <= GRIP_PX
        near_b = abs(pos.y() - rect.bottom()) <= GRIP_PX
        in_x = rect.left() - GRIP_PX <= pos.x() <= rect.right() + GRIP_PX
        in_y = rect.top() - GRIP_PX <= pos.y() <= rect.bottom() + GRIP_PX
        if near_t and near_l:
            return Grip.TOP_LEFT
        if near_t and near_r:
            return Grip.TOP_RIGHT
        if near_b and near_l:
            return Grip.BOTTOM_LEFT
        if near_b and near_r:
            return Grip.BOTTOM_RIGHT
        if near_t and in_x:
            return Grip.TOP
        if near_b and in_x:
            return Grip.BOTTOM
        if near_l and in_y:
            return Grip.LEFT
        if near_r and in_y:
            return Grip.RIGHT
        # Kenarlarin hicbirine yakin degil ama cercevenin icinde: tasima.
        if rect.contains(pos):
            return Grip.MOVE
        return Grip.NONE

    def _apply_grip(self, pos: QPoint) -> None:
        delta = pos - self._anchor
        rect = QRect(self._rect_at_press)
        if self._grip == Grip.MOVE:
            rect.translate(delta)
            # Cerceve ekran disina tasmasin: goruntusu olmayan alan kirpilamaz.
            rect.moveLeft(max(0, min(rect.left(), self.width() - rect.width())))
            rect.moveTop(max(0, min(rect.top(), self.height() - rect.height())))
        else:
            if self._grip in (Grip.TOP_LEFT, Grip.LEFT, Grip.BOTTOM_LEFT):
                rect.setLeft(rect.left() + delta.x())
            if self._grip in (Grip.TOP_RIGHT, Grip.RIGHT, Grip.BOTTOM_RIGHT):
                rect.setRight(rect.right() + delta.x())
            if self._grip in (Grip.TOP_LEFT, Grip.TOP, Grip.TOP_RIGHT):
                rect.setTop(rect.top() + delta.y())
            if self._grip in (Grip.BOTTOM_LEFT, Grip.BOTTOM, Grip.BOTTOM_RIGHT):
                rect.setBottom(rect.bottom() + delta.y())
        self._rect = rect

    def _place_bar(self) -> None:
        """Paneli secimin altina (sigmiyorsa ustune) yerlestirir.

        Area acilinca panel uzuyor; `adjustSize` yeni boyu verdigi icin
        asagi tasma kontrolu acik/kapali her iki durumda da dogru calisiyor.
        """
        rect = self._rect.normalized()
        self._panel.adjustSize()
        x = rect.center().x() - self._panel.width() // 2
        y = rect.bottom() + 12
        if y + self._panel.height() > self.height():  # alta sigmiyor: ustune
            y = max(0, rect.top() - self._panel.height() - 12)
        x = max(0, min(x, self.width() - self._panel.width()))
        self._panel.move(x, y)
        self._panel.show()
        self._panel.raise_()

    def _update_mask(self) -> None:
        """Ayar fazinda tiklanabilir bolgeyi secim + cubukla sinirlar.

        Maske olmasa tam ekran pencere butun tiklamalari yutardi ve OCR+
        paneli acikken alttaki uygulamayla calisilamazdi. Secimin ICI de
        maskeye dahil: cerceve icinden tutup tasima oyle calisiyor.
        """
        if not self._session:
            self.clearMask()
            return
        rect = self._rect.normalized()
        region = QRegion(rect.adjusted(-GRIP_PX, -GRIP_PX, GRIP_PX, GRIP_PX))
        if self._panel.isVisible():
            region = region.united(QRegion(self._panel.geometry()))
        self.setMask(region)

    # ---- Qt olaylari ----

    def mousePressEvent(self, event) -> None:
        # Orta tus = iptal (Esc ile ayni). Secim F14 basiliyken yapiliyor,
        # el zaten farede: iptal icin klavyeye uzanmak gerekmesin.
        if event.button() == Qt.MouseButton.MiddleButton:
            self.close()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        self._anchor = pos
        self._grip = self._grip_at(pos)
        if self._grip == Grip.NONE:
            if self._session:
                return  # ayar fazinda maske disi zaten bize gelmez
            # Bos alana basildi: yeni secim baslar.
            self._picking = True
            self._rect = QRect(pos, pos)
            self._panel.hide()
        else:
            self._rect_at_press = QRect(self._rect.normalized())
            self._panel.hide()
            self._update_mask()
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        if self._picking:
            self._resolve_anchor()  # F14 ile secimde capa henuz cevrilmemis olabilir
            self._rect = QRect(self._anchor, pos)
            self.update()
            return
        if self._grip != Grip.NONE and event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_grip(pos)
            self._update_mask()
            self.update()
            return
        # Surukleme yok: imlec sekli tutamaca gore.
        grip = self._grip_at(pos)
        if grip == Grip.NONE:
            self.setCursor(
                Qt.CursorShape.ArrowCursor if self._session else Qt.CursorShape.CrossCursor
            )
        else:
            self.setCursor(QCursor(_CURSORS[grip]))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        adjusted = self._grip != Grip.NONE
        self._settle_pick()
        if self._rect.isEmpty():  # secim yok: `_settle_pick` pencereyi kapatti
            return
        if self._session and adjusted:
            # Alan degisti: ekrani temiz haliyle yeniden cekip paneli tazele.
            self._recapture(self._emit_rect_changed)

    def _emit_rect_changed(self, box: QRect) -> None:
        """Yeniden yakalama bitti: AYNI fiziksel dikdortgeni kirpip yolla."""
        image = self._crop_screen(box)
        if image is not None:
            self.rect_changed.emit(image)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        # FARENIN KOPYALA TUSU. F20 kaskadi kisa basimda `^c` gonderiyor
        # (keymap.build_cascades) ve o tus, secim penceresi ondeyken bize
        # geliyordu -- ama burada Ctrl+C'nin bir anlami yoktu, tus hicbir
        # sey yapmadan dusuyordu. Cubuktaki "Kopyala" dugmesi calisiyor,
        # farenin tusu calismiyordu; ikisi ayni isi yapmali.
        #
        # Metin kutusuna (Area adi, IFTTT metni) yazarken calismaz: Qt
        # olayi once odaktaki widget'a verir, QLineEdit Ctrl+C'yi kendi
        # yer ve buraya hic yukselmez -- ayrica bir kontrole gerek yok.
        if (
            event.key() == Qt.Key.Key_C
            and event.modifiers() == Qt.KeyboardModifier.ControlModifier
            and not self._rect.normalized().isEmpty()
        ):
            self._finish("copy")
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        rect = self._rect.normalized()
        painter = QPainter(self)

        if not self._session:
            if self._shot is None:
                return
            # Goruntu widget'in TAMAMINI kaplayacak sekilde ciziliyor: pencere
            # sanal masaustune birebir oturdugu icin bu 1:1 esleme demek,
            # Qt'nin dpr'sinden bagimsiz.
            painter.drawPixmap(self.rect(), self._shot)
            # Karartma YOK (kullanici istegi): dondurulmus goruntu oldugu
            # gibi duruyor, secimin disi da okunur kaliyor. Secimi cerceve
            # + ic dolgu (FILL) belirtir.
            if not rect.isEmpty():
                painter.fillRect(rect, FILL)

        if rect.isEmpty():
            painter.end()
            return

        if self._session:
            # Gorunmez dolgu: cercevenin ICI fareyi yakalasin (bkz.
            # SESSION_FILL). Boyanmazsa katmanli pencerede tiklama alta
            # gecer ve "ortasindan tutup tasima" calismaz.
            painter.fillRect(rect, SESSION_FILL)

        painter.setPen(QPen(BORDER, 1))
        painter.drawRect(rect)

        # Tutamaclar. Ilk surukleme sirasinda gosterilmez; cok kucuk secimde
        # ust uste binerler (AHK: GRIP_MIN).
        if not self._picking and min(rect.width(), rect.height()) >= GRIP_MIN:
            painter.setBrush(BORDER)
            for point in self._grip_points(rect):
                painter.drawRect(
                    point.x() - HANDLE_PX, point.y() - HANDLE_PX,
                    HANDLE_PX * 2, HANDLE_PX * 2,
                )

        if not self._session:
            sx, sy = self._scale()
            painter.setPen(QColor("#e6edf3"))
            painter.drawText(
                rect.left(),
                max(14, rect.top() - 6),
                f"{round(rect.width() * sx)} x {round(rect.height() * sy)}",
            )
        painter.end()

    @staticmethod
    def _grip_points(rect: QRect) -> tuple[QPoint, ...]:
        cx, cy = rect.center().x(), rect.center().y()
        return (
            rect.topLeft(), QPoint(cx, rect.top()), rect.topRight(),
            QPoint(rect.right(), cy), rect.bottomRight(), QPoint(cx, rect.bottom()),
            rect.bottomLeft(), QPoint(rect.left(), cy),
        )

    def closeEvent(self, event) -> None:
        """Kapanisi app.py'ye bildir: pencere acikken kisayollar susuyordu."""
        # Area kipinde kaydedilmemis is varsa once sorulur; "Vazgec"
        # denirse pencere ACIK KALIR -- Esc'e yanlislikla basmak yazilani
        # goturmesin.
        if not self._confirm_discard():
            event.ignore()
            return
        self._mode = "screen"
        self._apply_mode()
        self._session = False
        self._key_timer.stop()
        self._key_vk = 0
        self._key_origin = None
        self._shot = None  # ekran goruntusu bellekte bosuna durmasin
        self._panel.hide()
        self.clearMask()
        super().closeEvent(event)
        self.closed.emit()
