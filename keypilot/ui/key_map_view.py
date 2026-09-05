"""Kisayol haritasi -- hangi tus kimde, catisma var mi.

Once filtreli liste (ui/array_filter.py) kullaniliyordu ama o pencere PANO
GECMISI icin yapilmis: tek satir metin gosterir, secince yapistirir. Burada
sorulan soru baska -- "F4 bosta mi, degilse kim tutuyor" -- ve cevabi
SUTUNLU bir tablo istiyor: sahip, tus, aciklama, eylem yan yana durmali ki
goz tarayabilsin.

Sutun sirasi bilerek `sahip | tus | aciklama | eylem`: liste sahibe gore
gruplu okunuyor ("alanlarimin tuslari neler"), tusa gore arama zaten filtre
kutusunun isi.

Catisan tuslar ustte ve kirmizi: `HotkeyTable.match` en ozgul tanimi secip
otekini sessizce yutuyor, yani catisma normalde HIC belli olmuyor. Bu
pencerenin asil varlik sebebi o.

Sistem tuslari (keymap.py'deki sabit tablo) aciklamasiz gelebilir --
onlarin ne yaptigi zaten bilinir; buradaki isleri BOS DEGIL, DOLU
olduklarini gostermek: yeni bir kisayol atanirken cakismasin.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

#: Sahip oneki -> okunur ad. Kayit defterinde sahip `area:kur#0` gibi
#: makine adidir; listede insana gore yaziliyor.
OWNER_LABELS = {
    "keymap": "sistem",
    "keypilot": "kaskad",
    "area": "alan",
    "profile": "profil",
    "macro": "makro",
}

CONFLICT_BG = QColor("#5a1e22")
SYSTEM_FG = QColor("#8b949e")


def owner_label(owner: str) -> str:
    """`area:kur#0` -> `alan · kur#0`; bilinmeyen onek oldugu gibi kalir."""
    head, sep, tail = owner.partition(":")
    name = OWNER_LABELS.get(head, head)
    return f"{name} · {tail}" if sep else name


class KeyMapView(QWidget):
    """Kisayol tablosu. `show_rows` ile doldurulur, tek ornek app.py'de."""

    #: Pencere kapandi. app.py bunu dinleyip `ui_open`i indiriyor: pencere
    #: acikken dusuk seviye hook susturuluyor ve sinyal olmadan bir daha
    #: ACILMIYORDU -- kapattiktan sonra F13/F14/`´` dahil hicbir
    #: kisayol calismiyordu. Ayni kalip array_filter'da da var.
    closed = Signal()

    COLUMNS = ("Sahip", "Tus", "Aciklama", "Eylem")

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("Kisayol haritasi")
        self.resize(920, 560)
        self._rows: tuple[tuple[str, str, str, str, bool], ...] = ()

        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("ara: tus, sahip, eylem...")
        self._search.textChanged.connect(self._apply)
        top.addWidget(self._search)
        # Sistem tuslari listenin dortte ucunu kapliyor; kullanicinin kendi
        # attigi kisayollari gormek istedigi an bu kutu isini goruyor.
        self._only_mine = QCheckBox("yalniz benim atadiklarim", self)
        self._only_mine.toggled.connect(self._apply)
        top.addWidget(self._only_mine)
        self._conflicts_only = QCheckBox("yalniz catisanlar", self)
        self._conflicts_only.toggled.connect(self._apply)
        top.addWidget(self._conflicts_only)
        outer.addLayout(top)

        self._table = QTableWidget(0, len(self.COLUMNS), self)
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        header = self._table.horizontalHeader()
        for index, mode in enumerate((
            QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.Stretch,
            QHeaderView.ResizeMode.ResizeToContents,
        )):
            header.setSectionResizeMode(index, mode)
        outer.addWidget(self._table)

        self._status = QLabel("", self)
        self._status.setStyleSheet("color: #8b949e;")
        outer.addWidget(self._status)

        self.setStyleSheet(
            "QWidget { background: #0d1117; color: #e6edf3; font-size: 12px; }"
            "QLineEdit { background: #161b22; border: 1px solid #30363d;"
            "  border-radius: 4px; padding: 5px 8px; }"
            "QTableWidget { background: #0d1117; gridline-color: #21262d;"
            "  alternate-background-color: #11161d; }"
            "QHeaderView::section { background: #161b22; color: #8b949e;"
            "  border: none; border-bottom: 1px solid #30363d; padding: 6px; }"
        )

    def show_rows(self, rows: tuple[tuple[str, str, str, str, bool], ...]) -> None:
        """(sahip, tus, aciklama, eylem, catisiyor_mu) satirlarini gosterir."""
        self._rows = rows
        self._apply()
        self.show()
        self.raise_()
        self.activateWindow()
        self._search.setFocus()

    def keyPressEvent(self, event) -> None:
        """Esc kapatir -- oteki pencerelerle ayni davranis."""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        self.closed.emit()

    def _apply(self) -> None:
        query = self._search.text().strip().lower()
        rows = [
            row for row in self._rows
            if (not query or query in " ".join(row[:4]).lower())
            and (not self._conflicts_only.isChecked() or row[4])
            and (not self._only_mine.isChecked() or not row[0].startswith(("keymap", "keypilot")))
        ]
        # Catisanlar once: pencerenin asil derdi onlar.
        rows.sort(key=lambda row: (not row[4], row[0], row[1]))

        # Siralama KAPATILIYOR: acikken satir eklemek Qt'de satirlari
        # arasina serpistiriyor ve tablo karisiyor.
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for index, (owner, key, desc, action, clash) in enumerate(rows):
            system = owner.startswith(("keymap", "keypilot"))
            for column, text in enumerate((owner_label(owner), key, desc, action)):
                item = QTableWidgetItem(text)
                if clash:
                    item.setBackground(CONFLICT_BG)
                elif system:
                    # Sistem satirlari soluk: burada olma sebepleri
                    # okunmak degil, tusun DOLU oldugunu gostermek.
                    item.setForeground(SYSTEM_FG)
                self._table.setItem(index, column, item)
        self._table.setSortingEnabled(True)

        clashes = sum(1 for row in rows if row[4])
        self._status.setText(
            f"{len(rows)} / {len(self._rows)} kisayol"
            + (f"  —  ⚠ {clashes} catisma" if clashes else "  —  catisma yok")
        )
