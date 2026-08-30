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

AHK'deki DIL ve GRI TON kutulari burada YOK. AHK'nin OCR sarmalayicisi
ikisini de acikca istiyordu; Windows.Media.Ocr'in kendi API'si istemiyor:
dili `try_create_from_user_profile_languages` kullanicinin Windows dil
listesinden secer, gri tonlama da bizim tarafta sabit uygulanan bir on
isleme. Kullaniciya soruldugunda dogru cevabi olmayan iki kutuydu.

Hangi degisiklik neyi tetikler (AHK'deki maliyet ayrimi):

    bicim / ayrac / kolon esigi  ->  OCR GEREKMEZ, kelime kutulari yeniden
                                     dizilir (core/ocr_layout.py)
    olcek                        ->  yeniden OCR, ama ekran TEKRAR CEKILMEZ
                                     -- app.py elindeki kirpimi kullanir

Secim cercevesi bu panel acikken ekranda KALIR (ui/snip.py ayar fazi):
alan yeniden ayarlanabilir, panel kendini tazeler.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from cascade.core.ocr_layout import (
    SEPARATORS,
    LayoutMode,
    Word,
    layout,
    separator_from_text,
    separator_label,
)

#: AHK: GUTTERS -- kolon esigi icin hazir secenekler (duzenlenebilir kutu).
GUTTERS = ("Otomatik", "20px", "40px", "80px", "150px")

MODES = (
    ("Duz metin", LayoutMode.PLAIN),
    ("Kolonlu", LayoutMode.COLUMNS),
    ("Tablo (ayracli)", LayoutMode.TABLE),
)


class OcrView(QWidget):
    """Tek ornek app.py'de tutulur; her sonucta ayni pencere tazelenir."""

    #: "Kopyala" -- panoya yazmayi app.py yapar (pano gecmisine de dussun)
    copy_text = Signal(str)
    #: olcek degisti: yeniden OCR gerekiyor (yeni olcek)
    reocr_requested = Signal(int)
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

        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._edit = QPlainTextEdit()
        self._edit.setFont(mono)
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._info = QLabel("")
        self._info.setStyleSheet("color: #8b949e;")

        # ---- denetimler ----
        self._mode = QComboBox()
        for label, _mode in MODES:
            self._mode.addItem(label)
        self._mode.currentIndexChanged.connect(self._relayout)

        # Duzenlenebilir: listeden secilebilir ya da elle yazilabilir
        # (AHK'deki ComboBox + "Ozel..." satirinin karsiligi; burada kutu
        # zaten yazilabilir oldugu icin ayri bir "Ozel..." satiri gerekmiyor).
        self._sep = QComboBox()
        self._sep.setEditable(True)
        for label, _real in SEPARATORS:
            self._sep.addItem(label)
        self._sep.setToolTip("Kacislar:  \\t = TAB   \\n = satir sonu   \\s = bosluk")
        self._sep.currentTextChanged.connect(self._relayout)

        self._scale = QComboBox()
        for value in (1, 2, 3, 4):
            self._scale.addItem(f"{value}x", value)
        self._scale.setCurrentIndex(1)  # AHK varsayilani: 2
        self._scale.currentIndexChanged.connect(self._on_reocr_setting)

        self._gutter = QComboBox()
        self._gutter.setEditable(True)
        for value in GUTTERS:
            self._gutter.addItem(value)
        self._gutter.setToolTip("Kolon ayraci sayilacak en kucuk bos dikey serit")
        self._gutter.currentTextChanged.connect(self._relayout)

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

        copy_button = QPushButton("\U0001f4cb Kopyala")
        copy_button.setDefault(True)
        copy_button.clicked.connect(lambda: self.copy_text.emit(self._edit.toPlainText()))
        close_button = QPushButton("Kapat")
        close_button.clicked.connect(self.close)

        bottom = QHBoxLayout()
        bottom.addWidget(self._info, 1)
        bottom.addWidget(copy_button)
        bottom.addWidget(close_button)
        bottom.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignBottom)

        root = QVBoxLayout(self)
        root.addLayout(grid)
        root.addWidget(self._edit, 1)
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

    def busy(self, message: str = "okunuyor...") -> None:
        self._info.setText(message)

    @property
    def scale(self) -> int:
        return int(self._scale.currentData() or 2)

    # ---- ic akis ----

    def _on_reocr_setting(self) -> None:
        """Olcek degisti: yeniden OCR gerekiyor."""
        if self._loading:
            return
        self.busy()
        self.reocr_requested.emit(self.scale)

    def _relayout(self) -> None:
        """Bicim / ayrac / kolon esigi: OCR gerekmez, kutular yeniden dizilir."""
        if self._loading:
            return
        mode = MODES[max(0, self._mode.currentIndex())][1]
        separator = separator_from_text(self._sep.currentText())
        result = layout(
            list(self._words), list(self._lines), mode, separator, self._gutter_px()
        )
        self._edit.setPlainText(result.text)
        # Ayrac yalniz tablo biciminde is goruyor; digerlerinde kapatiliyor
        # ki kullanici bosuna oynamasin (AHK'de de pasifti).
        self._sep.setEnabled(mode is LayoutMode.TABLE)
        self._gutter.setEnabled(mode is not LayoutMode.PLAIN)
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

    def set_separator(self, value: str) -> None:
        self._loading = True
        self._sep.setCurrentText(separator_label(value))
        self._loading = False

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        self.closed.emit()
