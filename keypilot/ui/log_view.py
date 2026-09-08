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
Detayi olan satirin zemini farkli ve asagi oku var; satiri secince detay
ALT PANELDE aciliyor.

Kaynak: bellekteki `ErrorStore` degil DOSYA. Depo yalnizca son 50 WARNING+
kaydi tutuyor; dosyada gecmis de, sistem satirlari da var. Dosya
degistiyse (mtime) yeniden okunuyor -- pencere acikken hata olusursa
listeye kendiliginden dusuyor.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
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

#: Detay tasiyan satirin `tur` sutunundaki simge.
DETAIL_ICON = "▾"  # ▾


class LogView(QWidget):
    """Tepsi menusu / hata rozeti -> "log". Tek ornek app.py'de tutuluyor."""

    COLUMNS = ["tarih", "saat", "sev", "▾", "kaynak", "mesaj"]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KeyPilot - log")
        self.resize(980, 620)

        self._rows: tuple[logs.LogLine, ...] = ()
        self._shown: list[logs.LogLine] = []
        self._stamp: tuple[float, int] | None = None  # (mtime, boyut)

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)

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
        # Uzun mesaj satiri IKIYE bolmesin: log listesinde satir yuksekligi
        # sabit kalmali, tam metin zaten alt panelde.
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.table.doubleClicked.connect(lambda _index: self._copy_row())

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(mono)
        self.detail.setPlaceholderText("detay yok -- ▾ isaretli satirlarda dolar")

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

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
        log_layout.addWidget(split, 1)
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

    def _render(self) -> None:
        detail_bg = self.detail_bg()
        self._shown = [row for row in self._rows if self._matches(row)]
        self.table.setRowCount(len(self._shown))
        for index, row in enumerate(self._shown):
            has_detail = bool(row.detail)
            cells = (
                row.date,
                row.time,
                row.icon,  # dosyadaki simgenin ayni
                # Detayi olan kayitta ASAGI OKU: alt panelde bakilacak bir
                # sey oldugu listeden gorunsun.
                DETAIL_ICON if has_detail else "",
                row.source,
                row.message,
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if row.level in ("ERROR", "CRITICAL"):
                    item.setForeground(ERROR_COLOR)
                if has_detail:
                    item.setBackground(detail_bg)
                self.table.setItem(index, column, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._update_status()
        if self._shown:
            self.table.scrollToBottom()

    def _update_status(self) -> None:
        errors = sum(1 for row in self._rows if row.is_problem)
        line = (
            f"{len(self._shown)} / {len(self._rows)} kayit  ·  "
            f"{errors} hata-uyari  ·  {paths.LOG}"
        )
        self.status.setText(line)

    def _selected(self) -> logs.LogLine | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._shown):
            return self._shown[row]
        return None

    def _show_detail(self) -> None:
        """Alt panel YALNIZCA detay tasiyan kayitta doluyor.

        Onceden basligi ve mesaji da yaziyordu: detaysiz bir satir secince
        alt panel ustteki satirin aynisini tekrar ediyor, "detay yok" demek
        icin ekranin ucte birini kullaniyordu.
        """
        row = self._selected()
        self.detail.setPlainText(row.detail if row is not None else "")

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
        self.detail.clear()
        self.reload(force=True)

    # ---- Qt ----

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt adi
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt adi
        self._timer.stop()
        super().hideEvent(event)
