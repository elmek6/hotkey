"""Pano gorsel gecmisi penceresi -- clip_image_dialog.ahk portu.

Sol: 64x64 thumb'li liste (diskten HAM okunur, PNG cozme yok).
Sag: secili kaydin onizlemesi -- tekerlekle zoom, surukleyerek kaydirma.

Kullanim (AHK ile ayni):

    ok tuslari / tik    gez              Ctrl/Shift + tik   coklu secim
    cift tik            panoya al        tekerlek           zoom
    sol tus surukle     kaydir           Esc                kapat

CANLI LISTE: yeni gorseller listeye kendiliginden girer. Depo her
degisiklikte `rev` sayacini artiriyor; pencere onu yokluyor (AHK: _poll).
Secim satir no ile degil SLOT ile tasindigi icin tazeleme onu bozmaz.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cascade.imgstore import THUMB_SIZE, ClipImageStore, ImageRecord, thumb_to_image
from cascade.store import _from_ahk_ms

log = logging.getLogger("cascade.clipimages")

POLL_MS = 900  # AHK: POLL_MS -- depo degisikligi yoklama sikligi
ZOOM_STEP = 1.25
ZOOM_MIN = 0.05
ZOOM_MAX = 8.0


def _format_ts(ms: int) -> str:
    """AHK `_formatTs`: yerel epoch ms -> okunur tarih."""
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(_from_ahk_ms(ms)).strftime("%d.%m.%Y %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


class _Preview(QWidget):
    """Onizleme yuzeyi: zoom + kaydirma.

    Gorsel kutuya SIGIYORSA 1:1 gosterilir, sigmiyorsa sigdirilir (AHK'deki
    ayni kural) -- kucuk gorseller bosuna buyutulup bulaniklasmasin.

    **1:1 GERCEKTEN 1:1.** Qt'de cizim mantiksal koordinatta; ekran %150
    olcekliyse (dpr 1.5) mantiksal boyda cizilen gorsel donanimda 1.5 kat
    buyutulur ve ince cizgiler bozulur. O yuzden hedef dikdortgen hep
    `dpr`'ye BOLUNEREK veriliyor: zoom 1.0'da bir goruntu pikseli bir ekran
    pikseli. Buyutmede yumusatma da KAPALI (nearest): 2x'te piksel dorde
    bolunmeli, bulanmamali.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._pixmap: QPixmap | None = None
        self._zoom = 1.0
        self._fit_zoom = 1.0
        self._pan = QPoint()
        self._drag_from: QPoint | None = None

    def set_image(self, image: QImage | None) -> None:
        self._pixmap = QPixmap.fromImage(image) if image is not None else None
        self.reset_view()

    def reset_view(self) -> None:
        self._fit_zoom = self._compute_fit()
        self._zoom = self._fit_zoom
        self._pan = QPoint()
        self.update()

    def toggle_fit(self) -> None:
        """AHK: _toggleFit -- 1:1 ile sigdirilmis gorunum arasinda gider gelir.

        Su an 1:1'de isek sigdirmaya, degilsek 1:1'e geciyoruz. Gorsel zaten
        kutuya sigiyorsa fit == 1.0 olur ve dugme is yapmaz.
        """
        at_one_to_one = abs(self._zoom - 1.0) < 1e-6
        self._zoom = self._fit_zoom if at_one_to_one else 1.0
        self._pan = QPoint()
        self.update()

    def _dpr(self) -> float:
        """Ekranin piksel orani. Cizim mantiksal, goruntu gercek pikselde."""
        return self.devicePixelRatioF() or 1.0

    def _compute_fit(self) -> float:
        if self._pixmap is None or self._pixmap.isNull():
            return 1.0
        dpr = self._dpr()
        ratio = min(
            self.width() * dpr / self._pixmap.width(),
            self.height() * dpr / self._pixmap.height(),
        )
        return min(1.0, ratio)  # sigiyorsa buyutme, 1:1 birak

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        was_fit = abs(self._zoom - self._fit_zoom) < 1e-6
        self._fit_zoom = self._compute_fit()
        if was_fit:  # kullanici zoom yapmadiysa sigdirmayi koru
            self._zoom = self._fit_zoom

    def wheelEvent(self, event) -> None:
        if self._pixmap is None:
            return
        step = ZOOM_STEP if event.angleDelta().y() > 0 else 1 / ZOOM_STEP
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, self._zoom * step))
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is None:
            return
        pos = event.position().toPoint()
        self._pan += pos - self._drag_from
        self._drag_from = pos
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1b1f24"))
        if self._pixmap is None or self._pixmap.isNull():
            painter.setPen(QColor("#6e7681"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "onizleme yok")
            return
        dpr = self._dpr()
        width = max(1, round(self._pixmap.width() * self._zoom / dpr))
        height = max(1, round(self._pixmap.height() * self._zoom / dpr))
        x = (self.width() - width) // 2 + self._pan.x()
        y = (self.height() - height) // 2 + self._pan.y()
        # Kucultmede yumusatma iyi, buyutmede kotu: 1:1 ve ustu keskin kalsin.
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform, self._zoom < 1.0
        )
        painter.drawPixmap(QRect(x, y, width, height), self._pixmap)

    @property
    def zoom(self) -> float:
        return self._zoom


class ClipImages(QWidget):
    """Gorsel gecmisi penceresi. Tek ornek app.py'de tutulur."""

    #: kayit panoya alindi -- ipucu gostermeyi app.py yapar
    copied = Signal(str)
    closed = Signal()

    def __init__(self, store: ClipImageStore) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("\U0001f5bc️ Pano Gorselleri")
        self.store = store
        self._items: list[ImageRecord] = []
        self._seen_rev = -1

        self.list = QTreeWidget()
        self.list.setColumnCount(5)
        self.list.setHeaderLabels(["Son kullanim", "Boyut", "KB", "×", "Ilk kayit"])
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setIconSize(QSize(THUMB_SIZE, THUMB_SIZE))
        # Ctrl/Shift ile coklu secim -- toplu silme icin (AHK: -Multi yok)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.currentItemChanged.connect(lambda *_: self._on_select())
        self.list.itemDoubleClicked.connect(lambda *_: self.copy_selected())

        self.preview = _Preview()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.list)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([430, 620])

        buttons = QHBoxLayout()
        for label, slot in (
            ("\U0001f4cb Panoya Al", self.copy_selected),
            ("\U0001f5d1️ Sil", self.delete_selected),
            ("1:1 / sigdir", self.preview.toggle_fit),
            ("\U0001f4be PNG Kaydet", self.export_selected),
            ("Kapat", self.close),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)

        self.info = QLabel("")
        self.stats = QLabel("")
        self.stats.setStyleSheet("color: #6e7681; font-size: 11px;")

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.info)
        layout.addWidget(self.stats)
        self.resize(1080, 640)

        # AHK: SetTimer(pollBound, POLL_MS) -- depo degisikligini yokla.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    # ---- disari ----

    def open(self) -> None:
        self.reload()
        self.show()
        self.raise_()
        self.activateWindow()
        self._timer.start(POLL_MS)

    def reload(self) -> None:
        """Listeyi depodan tazeler. Secim SLOT ile korunur, satir no ile degil
        -- yeni kayit girince secim kaymasin (AHK'deki ayni karar)."""
        selected = self._current_slot()
        self._items = self.store.records()
        self._seen_rev = self.store.rev

        self.list.clear()
        for record in self._items:
            item = QTreeWidgetItem(
                [
                    _format_ts(record.ts),
                    f"{record.w}x{record.h}",
                    str(round(record.dat_size / 1024)),
                    str(record.count) if record.count > 1 else "",
                    _format_ts(record.created_ts),
                ]
            )
            thumb = self.store.read_thumb(record.slot)
            if thumb is not None:
                image = thumb_to_image(thumb)
                pixmap = QPixmap.fromImage(
                    QImage(
                        image.tobytes(), THUMB_SIZE, THUMB_SIZE,
                        THUMB_SIZE * 4, QImage.Format.Format_RGBA8888,
                    ).copy()
                )
                item.setIcon(0, pixmap)
            item.setData(0, Qt.ItemDataRole.UserRole, record.slot)
            self.list.addTopLevelItem(item)

        for column in range(5):
            self.list.resizeColumnToContents(column)
        self.list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)

        self._restore_selection(selected)
        self._refresh_stats()

    # ---- secim ----

    def _current_slot(self) -> int | None:
        item = self.list.currentItem()
        return None if item is None else item.data(0, Qt.ItemDataRole.UserRole)

    def _selected_slots(self) -> list[int]:
        return [
            item.data(0, Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()
        ]

    def _restore_selection(self, slot: int | None) -> None:
        if not self._items:
            self.preview.set_image(None)
            self.info.setText("")
            return
        row = 0
        if slot is not None:
            for index, record in enumerate(self._items):
                if record.slot == slot:
                    row = index
                    break
        self.list.setCurrentItem(self.list.topLevelItem(row))

    def _on_select(self) -> None:
        slot = self._current_slot()
        if slot is None:
            self.preview.set_image(None)
            self.info.setText("")
            return
        png = self.store.read_png(slot)
        if png is None:
            self.preview.set_image(None)
            self.info.setText("kayit okunamadi")
            return
        image = QImage()
        image.loadFromData(png, "PNG")
        self.preview.set_image(image)
        self._update_info(slot)

    def _update_info(self, slot: int) -> None:
        record = next((r for r in self._items if r.slot == slot), None)
        if record is None:
            return
        parts = [
            f"{record.w}x{record.h} px",
            f"{record.dat_size / 1024:.0f} KB",
            f"#{record.id}",
        ]
        if record.count > 1:
            parts.append(f"{record.count} kez kopyalandi")
        parts.append(f"ilk: {_format_ts(record.created_ts)}")
        self.info.setText("   ·   ".join(parts))

    def _refresh_stats(self) -> None:
        """AHK: _refreshStats -- secim/zoom ile DEGISMEZ, o yuzden ayri."""
        count, total_bytes, copies = self.store.stats()
        self.stats.setText(
            f"{count} gorsel   ·   {total_bytes / (1024 * 1024):.1f} MB   ·   "
            f"{copies} kopyalama"
        )

    # ---- eylemler ----

    def copy_selected(self) -> None:
        slot = self._current_slot()
        if slot is None:
            return
        png = self.store.read_png(slot)
        if png is None:
            self.copied.emit("")
            return
        image = QImage()
        image.loadFromData(png, "PNG")
        QGuiApplication.clipboard().setImage(image)
        self.store.touch(slot)
        self.copied.emit(f"{image.width()}x{image.height()}")

    def delete_selected(self) -> None:
        """AHK: toplu silmede onay sorulur, tekli silme onaysiz."""
        slots = self._selected_slots()
        if not slots:
            return
        # Onay kutusu acikken yoklama listeyi degistirmesin.
        self._timer.stop()
        try:
            if len(slots) > 1:
                answer = QMessageBox.question(
                    self,
                    "Toplu silme",
                    f"{len(slots)} gorsel silinecek.\nEmin misiniz?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            if self.store.delete_many(slots):
                self.reload()
                if not self._items:
                    self.close()
        finally:
            if self.isVisible():
                self._seen_rev = self.store.rev
                self._timer.start(POLL_MS)

    def export_selected(self) -> None:
        slot = self._current_slot()
        if slot is None:
            return
        record = next((r for r in self._items if r.slot == slot), None)
        if record is None:
            return
        target, _filter = QFileDialog.getSaveFileName(
            self, "PNG olarak kaydet", f"clip_{record.id}.png", "PNG (*.png)"
        )
        if not target:
            return
        if not target.lower().endswith(".png"):
            target += ".png"
        if self.store.export_to(slot, target):
            self.copied.emit(f"kaydedildi: {target}")

    # ---- canli tazeleme ----

    def _poll(self) -> None:
        if self.store.rev != self._seen_rev:
            self.reload()

    # ---- olaylar ----

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        if event.key() == Qt.Key.Key_Delete:
            self.delete_selected()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)
        self.closed.emit()


# TODO(AHK): clip_image_dialog.ahk'nin surukleyip disari birakma yolu
#     (ole_drag_source.ahk) port edilmedi -- listedeki gorseli baska bir
#     uygulamaya surukleme. Qt'nin surukleme modeli tamamen ayri.
# TODO(AHK): AHK'de onizleme fare tekerlegi/tiklamasi GLOBAL hotkey ile
#     yakalaniyordu (pencere aktifken). Burada widget olaylari kullaniliyor;
#     davranis ayni ama pencere odakta degilken tekerlek calismaz.
