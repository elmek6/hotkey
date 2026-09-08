"""Log penceresi -- log.txt'yi listeler, secili kaydin detayini gosterir.

Neden var: hatalar `QMessageBox` ile gosteriliyordu ve her kaydin metnine
traceback yapisiktir. Mesaj kutusu icerige gore buyur, kaydirma cubugu
yoktur; birkac hata birikince pencere ekrani asiyor, kapatma dugmesi
disarida kaliyordu.

Is bolumu (kullanicinin karari):

  * TEK hata olustugunda -- eskisi gibi ipucu / kritik hata kutusu.
  * BIRIKMIS hata varsa -- bu pencere. "Hepsini tek kutuya sigdir" yanlis
    olan seydi.

Liste KRONOLOJIK ve gruplamasiz: burasi bir log sayfasi, rapor degil.
Seviye sutununda dosyadakiyle AYNI renkli simge duruyor (logs.LEVEL_ICONS).
Detayi olan satirin zemini farkli ve mesajinin sonunda `▾` var; SATIRA
tiklayinca detay altinda aciliyor (ikinci tik kapatiyor).

Detay neden sabit alt panel DEGIL: panel pencerenin ucte birini her zaman
tutuyordu -- detaysiz satirdayken bos, detayli satirdayken de listeden
kopuk. Acilir satir yeri yalnizca bakilan kayit icin harciyor ve traceback
ait oldugu satirin hemen altinda duruyor. Maliyeti de kucuk: acik olan her
kayit icin BIR widget kuruluyor, kapalilar icin hicbir sey.

Kaynak: bellekteki `ErrorStore` degil DOSYA. Depo yalnizca son 50 WARNING+
kaydi tutuyor; dosyada gecmis de, sistem satirlari da var. Dosya
degistiyse (mtime) yeniden okunuyor -- pencere acikken hata olusursa
listeye kendiliginden dusuyor.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from keypilot import logs, paths
from keypilot.ui import place

#: Listede gosterilen en fazla kayit -- en yenilerden geriye.
MAX_ROWS = 2000

#: Dosya degisti mi diye bakma araligi. Ayristirma 512 KB'lik dosyada
#: milisaniyeler suruyor ama gereksizse hic yapilmiyor: yalniz mtime
#: degisince yeniden okunuyor.
POLL_MS = 1500

#: Filtre kutusunda yazma bittikten sonra cizime kadar beklenen sure.
FILTER_MS = 150

#: Hata satirinin yazi rengi (`@` isaretli kayitlar).
ERROR_COLOR = QColor("#e5534b")

#: DETAYI OLAN satirin zemini. Ayri renk, cunku "asagida bakilacak bir sey
#: var mi" sorusu listeye bakinca cevaplanmali -- ok simgesi tek basina
#: kucuk kaliyor. IKI renk: program koyu temada da calisiyor (theme.py) ve
#: sabit acik sari koyu palette goz ciplatirdi.
DETAIL_BG = QColor("#fff3cd")
DETAIL_BG_DARK = QColor("#3d3419")

#: Detayi olan kaydin mesajinin SONUNA konan simge: "devami var, tikla".
#: Once ayri bir OK SUTUNUYDU -- tek karakterlik icerige gore 15 piksele
#: iniyordu: ne goze carpiyor ne de tiklanabiliyordu. Uc nokta da denendi;
#: metin gibi okunuyor, simge gibi durmuyordu.
DETAIL_MARK = "▾"

#: Acilan detay kutusunun en fazla kac satir yer kaplayacagi. Ustu kutunun
#: KENDI kaydirma cubuguna dusuyor: 200 satirlik bir traceback listeyi
#: tumuyle asagi itmesin, acilan satir hep ekranda kalsin.
MAX_DETAIL_LINES = 16

#: Kutunun metin disi payi: belge kenar boslugu (ustte + altta 4 px) ve
#: bir tutam nefes. Yatay kaydirma cubugu AYRICA ekleniyor -- traceback
#: satirlari uzun, cubuk cogu zaman cikiyor ve metnin son satirini
#: orterdi.
DETAIL_PAD = 10


class LogView(QWidget):
    """Tepsi menusu / hata rozeti -> "log". Tek ornek app.py'de tutuluyor."""

    COLUMNS = ["tarih", "saat", "sev", "kaynak", "mesaj"]
    #: Genisleyen (ve detay satirinin yayildigi) sutun: mesaj.
    MESSAGE_COLUMN = 4

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KeyPilot - log")
        self.resize(980, 620)

        self._rows: tuple[logs.LogLine, ...] = ()
        self._shown: list[logs.LogLine] = []
        self._stamp: tuple[float, int] | None = None  # (mtime, boyut)
        #: ACIK detaylar. Kayitlar degerle karsilastiriliyor (`LogLine`
        #: donmus bir dataclass), yani dosya yeniden okununca acik satir
        #: acik kaliyor -- nesneler yeni olsa da.
        self._open: set[logs.LogLine] = set()
        #: Tablo satiri -> kayit. Detay satirlarinda `None`: liste artik
        #: birebir `_shown` degil, aralarina acilmis kutular giriyor.
        self._row_map: list[logs.LogLine | None] = []

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._mono = mono

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("filtre: metin, kaynak ya da seviye (ornek: magnifier)")
        self.filter.setClearButtonEnabled(True)
        # Cizim GECIKMELI: her tusa basista 2000 satir yeniden kuruluyordu.
        # Yazma bitince bir kez ciziyoruz (ui/array_filter.py ile ayni fikir).
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(FILTER_MS)
        self._filter_timer.timeout.connect(self._render)
        self.filter.textChanged.connect(lambda _text: self._filter_timer.start())

        # Gunluk soru "ne patladi", ayrinti satirlari onu bogar. Kutu
        # isaretliyken yalniz `@` satirlari kaliyor.
        self.only_errors = QCheckBox("Yalniz hata/uyari")
        self.only_errors.stateChanged.connect(lambda _state: self._render())

        top = QHBoxLayout()
        top.addWidget(self.filter, 1)
        top.addWidget(self.only_errors)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setFont(mono)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        # Uzun mesaj satiri IKIYE bolmesin: liste satirlari sabit yukseklikte
        # kalmali, tam metin zaten acilan kutuda.
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(
            self.MESSAGE_COLUMN, QHeaderView.ResizeMode.Stretch
        )
        # Detayli satirda TEK tik acar/kapatir. Cift tik eski isini yapiyor
        # (satiri kopyalar): iki tik acip kapatiyor, satir yerinde kaliyor.
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.doubleClicked.connect(lambda _index: self._copy_row())

        self.status = QLabel()
        self.status.setFont(mono)

        refresh = QPushButton("Yenile")
        refresh.clicked.connect(lambda: self.reload(force=True))
        copy_row = QPushButton("Satiri kopyala")
        copy_row.clicked.connect(self._copy_row)
        open_file = QPushButton("Dosyayi ac")
        open_file.clicked.connect(self._open_file)
        clear = QPushButton("Log temizle")
        clear.clicked.connect(self._clear)

        bar = QHBoxLayout()
        bar.addWidget(self.status, 1)
        bar.addWidget(refresh)
        bar.addWidget(copy_row)
        bar.addWidget(open_file)
        bar.addWidget(clear)

        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        log_layout.addLayout(top)
        log_layout.addWidget(self.table, 1)
        log_layout.addLayout(bar)

        # Tani sayaclari AYRI SEKMEDE: log listesinin altinda dururken hem
        # yer isgal ediyor hem de her satir degisiminde goz oraya kayiyordu.
        # Bakilma sikligi da farkli -- bunlar arada bir sorulan sayilar.
        self.stats = QTableWidget(0, 2)
        self.stats.setHorizontalHeaderLabels(["olcum", "deger"])
        self.stats.setFont(mono)
        self.stats.verticalHeader().setVisible(False)
        self.stats.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats.setWordWrap(False)
        self.stats.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        self.tabs = QTabWidget()
        self.tabs.addTab(log_page, "Log")
        self.tabs.addTab(self.stats, "Durum")

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)

        # Pencere KAPALIYKEN maliyet sifir olmali: zamanlayici yalniz
        # gorunurken calisiyor (bkz. showEvent / hideEvent).
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(lambda: self.reload())

    # ---- disari acilan ----

    def show_log(self) -> None:
        """Pencereyi acar/one getirir ve dosyayi tazeler."""
        self.reload(force=True)
        self.show()
        if self.isMinimized():
            self.showNormal()
        place.center_on_cursor_screen(self)
        self.raise_()
        self.activateWindow()

    def set_stats(self, rows: list[tuple[str, str]]) -> None:
        """"Durum" sekmesini doldurur -- (olcum, deger) ciftleri.

        Bu sayilar eski "son hatalar" kutusundaki hook/olay sayaclariydi
        (app._diagnostics dolduruyor); pencere onlarin da yeni evi.
        """
        self.stats.setRowCount(len(rows))
        for index, (name, value) in enumerate(rows):
            self.stats.setItem(index, 0, QTableWidgetItem(name))
            self.stats.setItem(index, 1, QTableWidgetItem(value))
        self.stats.resizeColumnsToContents()
        self.stats.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def reload(self, force: bool = False) -> None:
        """Dosya degistiyse yeniden okur. `force` ise her halukarda."""
        stamp = self._file_stamp()
        if not force and stamp == self._stamp:
            return
        self._stamp = stamp
        self._rows = logs.read_log(limit=MAX_ROWS)
        self._render()

    # ---- ic ----

    @staticmethod
    def _file_stamp() -> tuple[float, int] | None:
        try:
            info = paths.LOG.stat()
        except OSError:
            return None
        return (info.st_mtime, info.st_size)

    def _matches(self, row: logs.LogLine) -> bool:
        if self.only_errors.isChecked() and not row.is_problem:
            return False
        needle = self.filter.text().strip().lower()
        if not needle:
            return True
        return needle in f"{row.level} {row.source} {row.thread} {row.message}".lower()

    def detail_bg(self) -> QColor:
        """Detayli satirin zemini -- yururlukteki paletten secilir."""
        base = self.palette().base().color()
        return DETAIL_BG_DARK if base.lightness() < 128 else DETAIL_BG

    def _render(self, scroll_end: bool = True) -> None:
        detail_bg = self.detail_bg()
        self._shown = [row for row in self._rows if self._matches(row)]
        self._row_map = []
        # Once SIFIRLA: eski acilmis kutular (cell widget) ve birlestirilmis
        # hucreler yeni cizimde yerinde kalmasin.
        self.table.clearSpans()
        self.table.setRowCount(0)
        opened = [row for row in self._shown if row.detail and row in self._open]
        self.table.setRowCount(len(self._shown) + len(opened))
        line = 0
        for row in self._shown:
            has_detail = bool(row.detail)
            is_open = has_detail and row in self._open
            cells = (
                row.date,
                row.time,
                row.icon,  # dosyadaki simgenin ayni
                row.source,
                # "Devami var" simgesi MESAJIN SONUNDA: ayri bir sutun bir
                # karakter genisliginde kaliyor, hem gorunmuyor hem de
                # tiklanamiyordu. Simge metnin bittigi yerde duruyor --
                # okuyan zaten oraya bakiyor.
                f"{row.message} {DETAIL_MARK}" if has_detail else row.message,
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if row.level in ("ERROR", "CRITICAL"):
                    item.setForeground(ERROR_COLOR)
                if has_detail:
                    item.setBackground(detail_bg)
                self.table.setItem(line, column, item)
            self._row_map.append(row)
            line += 1
            if is_open:
                self._row_map.append(None)
                self.table.setSpan(line, 0, 1, len(self.COLUMNS))
                # Sondaki bos satirlar KIRPILIYOR: log kaydinin arkasinda
                # kalan bosluk kutuyu bir avuc bos satir kadar sisiriyordu.
                detail = row.detail.strip("\n")
                box = self._detail_box(detail)
                self.table.setCellWidget(line, 0, box)
                self.table.setRowHeight(line, self._detail_height(box, detail))
                line += 1
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(
            self.MESSAGE_COLUMN, QHeaderView.ResizeMode.Stretch
        )
        self._update_status()
        if self._shown and scroll_end:
            self.table.scrollToBottom()

    def _detail_box(self, text: str) -> QPlainTextEdit:
        """Satirin altina acilan detay kutusu.

        Kaydirma KENDI icinde (satirmiyor): traceback'in girintisi ve satir
        uzunlugu anlam tasiyor, sarmalanmis bir yigin izi okunmuyor.
        """
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        box.setFont(self._mono)
        box.setFrameShape(QFrame.Shape.NoFrame)
        box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # Zemin, ustundeki kaydin zemininin ayni: kutunun KIME ait oldugu
        # renkten anlasilsin.
        box.setStyleSheet(f"QPlainTextEdit {{ background: {self.detail_bg().name()}; }}")
        return box

    def _detail_height(self, box: QPlainTextEdit, text: str) -> int:
        """Kutunun yuksekligi -- KUTUNUN KENDI yazi tipinden.

        Once `self._mono`dan olculuyordu; o fontun boy verilmemis hali
        (19 px satir) ile kutuya uygulanmis hali (14 px) farkli, yani her
        acilan kutunun altinda bir avuc bos satir kaliyordu.
        """
        lines = min(len(text.splitlines()) or 1, MAX_DETAIL_LINES)
        bar = box.horizontalScrollBar().sizeHint().height()
        return lines * box.fontMetrics().lineSpacing() + DETAIL_PAD + bar

    def _on_cell_clicked(self, row: int, _column: int) -> None:
        """Detayli satira tiklama detayi acar/kapatir.

        Yalnizca ok sutunu degil SATIRIN HER YERI: ok sutunu bir karakter
        genisliginde ve isabet ettirmesi zor -- "tiklayinca acilmiyor"
        sikayetinin sebebi buydu. Cift tiklama (satiri kopyala) bundan
        etkilenmiyor: iki tik acip kapatiyor, satir bulundugu halde kaliyor.
        """
        record = self._row_map[row] if 0 <= row < len(self._row_map) else None
        if record is None or not record.detail:
            return
        if record in self._open:
            self._open.discard(record)
        else:
            self._open.add(record)
        # Bakilan yer kacmasin: acma/kapama sonrasi liste sonuna atlanmiyor
        # ve kaydirma konumu geri konuyor.
        offset = self.table.verticalScrollBar().value()
        self._render(scroll_end=False)
        self.table.verticalScrollBar().setValue(offset)

    def _update_status(self) -> None:
        errors = sum(1 for row in self._rows if row.is_problem)
        line = (
            f"{len(self._shown)} / {len(self._rows)} kayit  ·  "
            f"{errors} hata-uyari  ·  {paths.LOG}"
        )
        self.status.setText(line)

    def _selected(self) -> logs.LogLine | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._row_map):
            return self._row_map[row]
        return None

    def _copy_row(self) -> None:
        row = self._selected()
        if row is None:
            return
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(row.text)

    def _open_file(self) -> None:
        import subprocess

        try:
            paths.ensure_files_dir()
            paths.LOG.touch(exist_ok=True)
            subprocess.Popen(["notepad.exe", str(paths.LOG)])  # noqa: S603, S607
        except OSError:
            logs.log.exception("log dosyasi acilamadi")

    def _clear(self) -> None:
        """Dosyayi bosaltir. Onay SART: geri donusu yok."""
        answer = QMessageBox.question(
            self,
            "Log temizle",
            f"{paths.LOG}\n\nDosyanin icerigi silinsin mi? Geri alinamaz.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        logs.clear_log()
        logs.errors.clear()
        self._open.clear()
        self.reload(force=True)

    # ---- Qt ----

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt adi
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt adi
        self._timer.stop()
        super().hideEvent(event)
