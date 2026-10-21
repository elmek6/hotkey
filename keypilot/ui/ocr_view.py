"""Gelismis OCR paneli -- screen_ocr.ahk'nin sonuc paneli.

Basit OCR metni dogrudan panoya koyar; bu panel ise metni GOSTERIR ve
AYARLARI barindirir. AHK'deki kural aynen korundu: **tum ayarlar burada,
menude yalniz eylemler var.**

Denetimler:

    bicim        duz metin / kolonlu / tablo (ayracli)
    ayrac        tablo bicimindeki hucre ayraci -- duzenlenebilir kutu,
                 `\\t` ve `\\n` kacislariyla gorunmez karakter de yazilir
    olcek        OCR oncesi buyutme (kucuk fontlar icin)
    kolon esigi  kolon ayraci sayilacak en kucuk bos dikey serit

Dil dugmeleri (En / Tr / De) ustte; paket yoksa motor sessizce Ingilizceye
doner. Gri tonlama arayuzde yok -- on isleme olarak sabit uygulanir.

Hangi degisiklik neyi tetikler (AHK'deki maliyet ayrimi):

    bicim / ayrac / kolon esigi  ->  OCR GEREKMEZ, kelime kutulari yeniden
                                     dizilir (core/ocr_layout.py)
    olcek                        ->  yeniden OCR, ama ekran TEKRAR CEKILMEZ
                                     -- app.py elindeki kirpimi kullanir
    Yenile                       ->  ekran TEKRAR CEKILIR, ayni alan bastan
                                     okunur (alttaki sayfa degismis olabilir)

Secim cercevesi bu panel acikken ekranda KALIR (ui/snip.py ayar fazi):
alan yeniden ayarlanabilir, panel kendini tazeler.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizeGrip,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from keypilot import theme
from keypilot.core.ocr_layout import (
    SEPARATORS,
    Grid,
    LayoutMode,
    Word,
    grid_cells,
    join_rows,
    layout,
    separator_from_text,
)
from keypilot.win32.ocr import DEFAULT_SCALE, OCR_LANGUAGES

#: AHK: GUTTERS -- kolon esigi icin hazir secenekler (duzenlenebilir kutu).
GUTTERS = ("Otomatik", "20px", "40px", "80px", "150px")


#: Hucre tablosunun en cok kolonu: basliklar A..Z. Bundan genis izgara
#: gercek bir kullanimda yok; gelirse duz metin gosterilir.
MAX_TABLE_COLUMNS = 26


def column_label(index: int) -> str:
    """0 -> A, 25 -> Z. Z'den sonrasi ValueError (bkz. MAX_TABLE_COLUMNS)."""
    if not 0 <= index < MAX_TABLE_COLUMNS:
        raise ValueError(f"kolon basligi A..Z disinda: {index}")
    return chr(ord("A") + index)


MODES = (
    ("Duz metin", LayoutMode.PLAIN),
    ("Kolonlu", LayoutMode.COLUMNS),
    ("Tablo (ayracli)", LayoutMode.TABLE),
    ("Izgara (cizdigim)", LayoutMode.GRID),
)

#: Dil dugmesinin uzerine gelince secilmesi icin beklenen sure. Sifir
#: olursa dugmelerin uzerinden gecmek bile pes pese OCR tetikler.
LANGUAGE_HOVER_MS = 220


class CellTable(QTableWidget):
    """Hucre tablosu: Ctrl+C secili hucreleri kopyalar (Qt kendiliginden yapmaz)."""

    copy_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_requested.emit()
            return
        super().keyPressEvent(event)


class OcrView(QWidget):
    """Tek ornek app.py'de tutulur; her sonucta ayni pencere tazelenir."""

    #: "Kopyala" -- panoya yazmayi app.py yapar (pano gecmisine de dussun)
    copy_text = Signal(str)
    #: olcek degisti: yeniden OCR gerekiyor (yeni olcek)
    reocr_requested = Signal(int)
    #: dil dugmesi: yeniden OCR, ayni kirpim
    language_requested = Signal(str)
    #: "Yenile" -- ekran TEKRAR CEKILIP ayni alan yeniden okunsun. Olcek
    #: degisiminden farki bu: orada elimizdeki kirpim yeniden okunuyor,
    #: burada altta duran sayfa degismis olabilecegi icin taze kare gerek.
    refresh_requested = Signal()
    closed = Signal()

    def __init__(self) -> None:
        # Tool DEGIL Window: gorev cubugunda yer alsin ve kenarlarindan
        # serbestce boyutlandirilabilsin. Ustte kalir cunku secim cercevesi
        # de ustte -- altina duserse panel kaybolurdu.
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowTitle("\U0001f9e0 OCR sonucu")

        self._words: tuple[Word, ...] = ()
        self._lines: tuple[str, ...] = ()
        self._ms = 0.0
        self._loading = False  # denetimleri programla doldururken sinyal yutar
        #: Secim cercevesinde cizilen izgara (ui/snip.py -> app.py -> burasi).
        self._grid = Grid()
        #: Uzerine gelinen dil dugmesi: hemen degil, kisa bir beklemeden
        #: sonra secilir (bkz. LANGUAGE_HOVER_MS).
        self._hover_language = ""
        self._language_hover = QTimer(self)
        self._language_hover.setSingleShot(True)
        self._language_hover.setInterval(LANGUAGE_HOVER_MS)
        self._language_hover.timeout.connect(self._on_language_hover)

        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._edit = QPlainTextEdit()
        self._edit.setFont(mono)
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        # Izgara kipinde duz metin kutusu hucreleri gostermiyor (birlesik
        # hucre, bos hucre, hizasi): onun yerine gercek bir hucre tablosu.
        # Hucreler duzenlenebilir -- OCR hatasi kopyalamadan once duzeltilir.
        self._table = CellTable()
        self._table.setFont(mono)
        self._table.setWordWrap(False)
        # Serbest secim: surukleyerek dikdortgen, Ctrl ile tek tek, basliga
        # tiklayarak satir/kolon, kose ile hepsi.
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self._table.copy_requested.connect(lambda: self.copy_text.emit(self._copy_text()))
        self._stack = QStackedWidget()
        self._stack.addWidget(self._edit)
        self._stack.addWidget(self._table)

        self._info = QLabel("")
        theme.muted(self._info)

        # ---- denetimler ----
        self._mode = QComboBox()
        for label, _mode in MODES:
            self._mode.addItem(label)
        # OCR+ cerceveye cizgi cekmek icin acilir: varsayilan biçim izgara.
        self._mode.setCurrentIndex(
            next(i for i, (_label, mode) in enumerate(MODES) if mode is LayoutMode.GRID)
        )
        self._mode.currentIndexChanged.connect(self._relayout)

        # Duzenlenebilir: listeden secilebilir ya da elle yazilabilir
        # (AHK'deki ComboBox + "Ozel..." satirinin karsiligi; burada kutu
        # zaten yazilabilir oldugu icin ayri bir "Ozel..." satiri gerekmiyor).
        self._sep = QComboBox()
        self._sep.setEditable(True)
        for label, _real in SEPARATORS:
            self._sep.addItem(label)
        # Hizali bosluk listenin basinda ama varsayilan eskisi gibi TAB kalir.
        self._sep.setCurrentIndex(max(0, self._sep.findText("Tab")))
        self._sep.setToolTip("Kacislar:  \\t = TAB   \\n = satir sonu   \\s = bosluk")
        self._sep.currentTextChanged.connect(self._relayout)

        self._scale = QComboBox()
        for value in (1, 2, 3, 4):
            self._scale.addItem(f"{value}x", value)
        # Varsayilan motorun sabitinden geliyor: basit OCR ile OCR+ ayni
        # buyutmeyi kullansin, biri degisince oteki geride kalmasin.
        self._scale.setCurrentIndex(max(0, self._scale.findData(DEFAULT_SCALE)))
        self._scale.currentIndexChanged.connect(self._on_reocr_setting)

        self._gutter = QComboBox()
        self._gutter.setEditable(True)
        for value in GUTTERS:
            self._gutter.addItem(value)
        self._gutter.setToolTip("Kolon ayraci sayilacak en kucuk bos dikey serit")
        self._gutter.currentTextChanged.connect(self._relayout)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Dil"))
        self._lang_buttons: dict[str, QPushButton] = {}
        for label, language in OCR_LANGUAGES:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolTip(f"{label} -- uzerine gelmek secmeye yeter")
            button.clicked.connect(
                lambda _checked=False, lang=language: self._on_language(lang)
            )
            # Uzerine gelince SECILIR: tiklamak zorunda kalmadan dil
            # denemek icin. Tiklama da calismaya devam eder (beklemesiz).
            button.installEventFilter(self)
            self._lang_buttons[language] = button
            lang_row.addWidget(button)
        lang_row.addStretch(1)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        for column, (label, widget) in enumerate(
            (
                ("Bicim", self._mode),
                ("Ayrac", self._sep),
                ("Olcek", self._scale),
                ("Kolon esigi", self._gutter),
            )
        ):
            grid.addWidget(QLabel(label), 0, column * 2)
            grid.addWidget(widget, 0, column * 2 + 1)
        grid.setColumnStretch(8, 1)

        refresh_button = QPushButton("\U0001f504 Yenile")
        refresh_button.setToolTip("Ayni alani ekrandan tekrar oku")
        refresh_button.clicked.connect(self._on_refresh)
        copy_button = QPushButton("\U0001f4cb Kopyala")
        copy_button.setDefault(True)
        copy_button.setToolTip(
            "Kutuda NE GORUNUYORSA onu kopyalar. Tabloda hucre secildiyse "
            "YALNIZ secili hucreleri (Ctrl+C ile ayni)"
        )
        copy_button.clicked.connect(lambda: self.copy_text.emit(self._copy_text()))
        excel_button = QPushButton("\U0001f4d7 Excel")
        excel_button.setToolTip(
            "Secili bicimden BAGIMSIZ olarak TAB ayracli tablo kopyalar -- "
            "Excel'e sutun sutun yapisir"
        )
        excel_button.clicked.connect(lambda: self.copy_text.emit(self.excel_text()))
        close_button = QPushButton("Kapat")
        close_button.clicked.connect(self.close)

        bottom = QHBoxLayout()
        bottom.addWidget(self._info, 1)
        bottom.addWidget(refresh_button)
        bottom.addWidget(excel_button)
        bottom.addWidget(copy_button)
        bottom.addWidget(close_button)
        bottom.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignBottom)

        root = QVBoxLayout(self)
        root.addLayout(lang_row)
        root.addLayout(grid)
        root.addWidget(self._stack, 1)
        root.addLayout(bottom)
        self.setMinimumSize(420, 260)
        self.resize(620, 460)

    # ---- disari ----

    def show_result(self, words: tuple[Word, ...], lines: tuple[str, ...], ms: float) -> None:
        """Yeni OCR sonucu geldi: kutulari sakla, secili bicimle diz."""
        self._words, self._lines, self._ms = words, lines, ms
        self._relayout()
        self.show()
        self.raise_()
        self.activateWindow()

    def set_grid(
        self,
        rows: tuple[float, ...],
        cols: tuple[float, ...],
        size: QSize,
    ) -> None:
        """Cercevede cizilen izgara degisti (ui/snip.py `grid_changed`).

        OCR tekrar KOSMAZ: eldeki kelime kutulari yeni cizgilere gore
        dagitiliyor, o yuzden yalniz yeniden dizim yapiliyor.
        """
        self._grid = Grid(rows, cols, float(size.width()), float(size.height()))
        self._relayout()

    def excel_text(self) -> str:
        """TAB ayracli tablo -- ekranda hangi bicim secili olursa olsun.

        "Kopyala" GORUNENI verir (duz metin de olabilir), bu dugme ise her
        zaman sutunlu: izgara cizilmisse ona gore, cizilmemisse otomatik
        kolon bulmayla. Boylece ayni pencere hem serbest metin hem de
        Excel'e hazir tablo uretebiliyor.
        """
        if self._table_shown():
            return join_rows(self._table_cells(), "	")
        mode = LayoutMode.GRID if self._grid.drawn else LayoutMode.TABLE
        return layout(
            list(self._words), list(self._lines), mode, "\t", self._gutter_px(), self._grid
        ).text

    def _table_shown(self) -> bool:
        return self._stack.currentWidget() is self._table

    def _table_cells(self) -> list[list[str]]:
        """Tablodaki (duzenlenmis olabilecek) hucre metinleri."""
        rows = []
        for row in range(self._table.rowCount()):
            cells = []
            for column in range(self._table.columnCount()):
                item = self._table.item(row, column)
                cells.append(item.text() if item is not None else "")
            rows.append(cells)
        return rows

    def _copy_text(self) -> str:
        """Kutuda/tabloda NE GORUNUYORSA: tablo secili ayracla birlestirilir.

        Tabloda hucre secildiyse yalniz onlar: secimin sinirlayici
        dikdortgeni alinir, secilmemis hucreler bos kalir (hiza bozulmaz).
        """
        if not self._table_shown():
            return self._edit.toPlainText()
        cells = self._table_cells()
        picked = {(index.row(), index.column()) for index in self._table.selectedIndexes()}
        if picked:
            rows = [row for row, _ in picked]
            cols = [column for _, column in picked]
            cells = [
                [cells[r][c] if (r, c) in picked else "" for c in range(min(cols), max(cols) + 1)]
                for r in range(min(rows), max(rows) + 1)
            ]
        return join_rows(cells, separator_from_text(self._sep.currentText()))

    def _fill_table(self, cells: list[list[str]]) -> None:
        """Izgara hucrelerini tabloya dok (sutunlar A, B, C...)."""
        table = self._table
        table.clear()
        table.setRowCount(len(cells))
        table.setColumnCount(len(cells[0]))
        table.setHorizontalHeaderLabels([column_label(i) for i in range(len(cells[0]))])
        for row, row_cells in enumerate(cells):
            for column, text in enumerate(row_cells):
                table.setItem(row, column, QTableWidgetItem(text))
        table.resizeColumnsToContents()
        table.resizeRowsToContents()

    def busy(self, message: str = "okunuyor...") -> None:
        self._info.setText(message)

    @property
    def scale(self) -> int:
        return int(self._scale.currentData() or DEFAULT_SCALE)

    # ---- ic akis ----

    def select_language(self, language: str) -> None:
        """Secili dil dugmesini isaretler; bos = hicbiri."""
        for tag, button in self._lang_buttons.items():
            button.setChecked(tag == language)

    def _on_language(self, language: str) -> None:
        self._language_hover.stop()  # tiklama bekleyen hover'i gecersiz kilar
        self.select_language(language)
        self.busy()
        self.language_requested.emit(language)

    def eventFilter(self, watched, event) -> bool:
        """Dil dugmesinin uzerine gelmek onu secer (kisa beklemeden sonra)."""
        for language, button in self._lang_buttons.items():
            if watched is not button:
                continue
            if event.type() == QEvent.Type.Enter:
                self._hover_language = language
                self._language_hover.start()
            elif event.type() == QEvent.Type.Leave and self._hover_language == language:
                self._hover_language = ""
                self._language_hover.stop()
            break
        return super().eventFilter(watched, event)

    def _on_language_hover(self) -> None:
        """Bekleme doldu: hala ayni dugmenin uzerindeysek o dile gec."""
        language = self._hover_language
        if language and not self._lang_buttons[language].isChecked():
            self._on_language(language)

    def _on_reocr_setting(self) -> None:
        """Olcek degisti: yeniden OCR gerekiyor."""
        if self._loading:
            return
        self.busy()
        self.reocr_requested.emit(self.scale)

    def _on_refresh(self) -> None:
        """Ayni alani ekrandan tekrar oku -- app.py snip.refresh()e baglar."""
        self.busy()
        self.refresh_requested.emit()

    def _relayout(self) -> None:
        """Bicim / ayrac / kolon esigi: OCR gerekmez, kutular yeniden dizilir."""
        if self._loading:
            return
        mode = MODES[max(0, self._mode.currentIndex())][1]
        separator = separator_from_text(self._sep.currentText())
        result = layout(
            list(self._words), list(self._lines), mode, separator, self._gutter_px(), self._grid
        )
        items = [word for word in self._words if word.text.strip()]
        cells = (
            grid_cells(items, self._grid, self._gutter_px())
            if mode is LayoutMode.GRID and self._grid.drawn and items
            else []
        )
        if cells and len(cells[0]) <= MAX_TABLE_COLUMNS:
            self._fill_table(cells)
            self._stack.setCurrentWidget(self._table)
        else:
            self._edit.setPlainText(result.text)
            self._stack.setCurrentWidget(self._edit)
        # Ayrac hucreleri ayiran kiplerde is goruyor; digerlerinde kapatiliyor
        # ki kullanici bosuna oynamasin (AHK'de de pasifti).
        self._sep.setEnabled(mode in (LayoutMode.TABLE, LayoutMode.GRID))
        # Kolon esigi kolonu TAHMIN eden kiplerin ayari: izgarada cizgiler
        # zaten belli, esigin hicbir etkisi olmaz.
        self._gutter.setEnabled(mode in (LayoutMode.COLUMNS, LayoutMode.TABLE))
        self._info.setText(
            f"{result.info}  ·  {len(result.text)} karakter  ·  {self._ms:.0f} ms"
        )

    def _gutter_px(self) -> int:
        """Kutudaki metni piksele cevirir; "Otomatik" ya da sacma deger -> 0."""
        text = self._gutter.currentText().strip().lower().removesuffix("px").strip()
        try:
            return max(0, int(float(text)))
        except ValueError:
            return 0

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        self.closed.emit()
