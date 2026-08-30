"""Ekran alani secimi -- F14 secim tusu (AHK screen_ocr.ahk'nin snip kismi).

Akis: `start()` ile tum ekranlarin DONDURULMUS goruntusu alinir ve uzeri
karartilmis tam ekran bir pencere acilir. Fare basilip surulerek alan
secilir; birakinca secim AYAR moduna gecer:

    * 8 tutamac (koseler + kenar ortalari) secimi yeniden boyutlandirir
    * ortadaki nokta cerceveyi komple tasir
    * secimin disina tiklamak yeni secim baslatir
    * yanindaki cubuktan islem secilir: Kopyala / Sakla / OCR / OCR+
    * Esc iptal eder

Goruntu ACILISTA donduruldugu icin kirpma her zaman gorunenle birebir --
pencereyi gizleyip yeniden yakalama oyunu yok. Islem secilince kirpilmis
goruntu `done(eylem, QImage)` sinyaliyle app.py'ye verilir; ne yapilacagi
(panoya koyma, diske yazma, OCR) bu pencerenin isi degil.
"""

from __future__ import annotations

from enum import IntEnum

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

HANDLE_PX = 5  # tutamac karesinin yarim kenari
GRIP_PX = 8  # tutamaca "isabet etti" sayilan mesafe
CENTER_PX = 7  # ortadaki tasima noktasinin yaricapi
MIN_SIZE = 4  # bundan kucuk secim tiklama sayilir, yok sayilir

VEIL = QColor(0, 0, 0, 110)  # secim disinin karartmasi
BORDER = QColor(0, 174, 255)
FILL = QColor(0, 174, 255, 26)


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
    CENTER = 9  # ortadaki nokta: komple tasima


_CURSORS = {
    Grip.TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
    Grip.BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
    Grip.TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
    Grip.BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
    Grip.TOP: Qt.CursorShape.SizeVerCursor,
    Grip.BOTTOM: Qt.CursorShape.SizeVerCursor,
    Grip.LEFT: Qt.CursorShape.SizeHorCursor,
    Grip.RIGHT: Qt.CursorShape.SizeHorCursor,
    Grip.CENTER: Qt.CursorShape.SizeAllCursor,
}

#: (etiket, eylem kimligi) -- app.py `done` sinyalinde bu kimligi alir.
ACTIONS = (
    ("\U0001f4cb Kopyala", "copy"),
    ("\U0001f4be Sakla", "save"),
    ("\U0001f524 OCR", "ocr"),
    ("\U0001f9e0 OCR+", "ocr_adv"),
)


class SnipOverlay(QWidget):
    """Tam ekran secim penceresi. Tek ornek app.py'de tutulur."""

    #: eylem kimligi ("copy" / "save" / "ocr" / "ocr_adv") + kirpilmis goruntu
    done = Signal(str, QImage)
    closed = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setMouseTracking(True)
        self._shot: QPixmap | None = None
        self._dpr = 1.0
        self._rect = QRect()  # secim, mantiksal pencere koordinati
        self._grip = Grip.NONE  # su an suruklenen tutamac
        self._anchor = QPoint()  # surukleme baslangici
        self._rect_at_press = QRect()
        self._picking = False  # ilk secim suruklemesi mi

        self._bar = QWidget(self)
        layout = QHBoxLayout(self._bar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        for label, action in ACTIONS:
            button = QPushButton(label, self._bar)
            button.clicked.connect(lambda _c=False, a=action: self._finish(a))
            layout.addWidget(button)
        cancel = QPushButton("✕", self._bar)
        cancel.clicked.connect(self.close)
        layout.addWidget(cancel)
        self._bar.setStyleSheet(
            "QWidget { background: #1f2328; border-radius: 6px; }"
            "QPushButton { background: #2d333b; color: #e6edf3; border: none;"
            "  padding: 6px 10px; border-radius: 4px; font-size: 13px; }"
            "QPushButton:hover { background: #444c56; }"
        )
        self._bar.hide()

    # ---- disari ----

    def start(self) -> None:
        """Ekrani dondurur ve secim modunda acilir."""
        virtual = QGuiApplication.primaryScreen().virtualGeometry()
        self._dpr = QGuiApplication.primaryScreen().devicePixelRatio()
        shot = QPixmap(int(virtual.width() * self._dpr), int(virtual.height() * self._dpr))
        painter = QPainter(shot)
        for screen in QGuiApplication.screens():
            geo = screen.geometry()
            painter.drawPixmap(
                int((geo.x() - virtual.x()) * self._dpr),
                int((geo.y() - virtual.y()) * self._dpr),
                screen.grabWindow(0),
            )
        painter.end()
        shot.setDevicePixelRatio(self._dpr)
        self._shot = shot

        self._rect = QRect()
        self._grip = Grip.NONE
        self._picking = False
        self._bar.hide()
        self.setGeometry(virtual)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.show()
        self.raise_()
        self.activateWindow()

    # ---- ic akis ----

    def _finish(self, action: str) -> None:
        rect = self._rect.normalized()
        if self._shot is None or rect.width() < MIN_SIZE or rect.height() < MIN_SIZE:
            return
        device = QRect(
            int(rect.x() * self._dpr),
            int(rect.y() * self._dpr),
            int(rect.width() * self._dpr),
            int(rect.height() * self._dpr),
        )
        image = self._shot.copy(device).toImage()
        image.setDevicePixelRatio(1.0)  # kaydedilen dosya gercek piksel
        self.close()
        self.done.emit(action, image)

    def _grip_at(self, pos: QPoint) -> Grip:
        rect = self._rect.normalized()
        if rect.isEmpty():
            return Grip.NONE
        if (pos - rect.center()).manhattanLength() <= CENTER_PX + 4:
            return Grip.CENTER
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
        return Grip.NONE

    def _apply_grip(self, pos: QPoint) -> None:
        delta = pos - self._anchor
        rect = QRect(self._rect_at_press)
        if self._grip == Grip.CENTER:
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
        rect = self._rect.normalized()
        self._bar.adjustSize()
        x = rect.center().x() - self._bar.width() // 2
        y = rect.bottom() + 12
        if y + self._bar.height() > self.height():  # alta sigmiyor: ustune
            y = max(0, rect.top() - self._bar.height() - 12)
        x = max(0, min(x, self.width() - self._bar.width()))
        self._bar.move(x, y)
        self._bar.show()
        self._bar.raise_()

    # ---- Qt olaylari ----

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        self._anchor = pos
        self._grip = self._grip_at(pos)
        if self._grip == Grip.NONE:
            # Bos alana basildi: yeni secim baslar.
            self._picking = True
            self._rect = QRect(pos, pos)
            self._bar.hide()
        else:
            self._rect_at_press = QRect(self._rect.normalized())
            self._bar.hide()
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        if self._picking:
            self._rect = QRect(self._anchor, pos)
            self.update()
            return
        if self._grip != Grip.NONE and event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_grip(pos)
            self.update()
            return
        # Surukleme yok: imlec sekli tutamaca gore.
        grip = self._grip_at(pos)
        if grip == Grip.NONE:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(QCursor(_CURSORS[grip]))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._picking = False
        self._grip = Grip.NONE
        rect = self._rect.normalized()
        if rect.width() < MIN_SIZE or rect.height() < MIN_SIZE:
            self._rect = QRect()  # tiklama: secim yok, beklemeye devam
        else:
            self._rect = rect
            self._place_bar()
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        if self._shot is None:
            return
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._shot)
        rect = self._rect.normalized()

        # Karartma: secim disindaki dort serit. Secimin ici dokunulmadan
        # kalir -- kullanici ne kirpacagini oldugu gibi gorur.
        if rect.isEmpty():
            painter.fillRect(self.rect(), VEIL)
        else:
            painter.fillRect(QRect(0, 0, self.width(), rect.top()), VEIL)
            painter.fillRect(
                QRect(0, rect.bottom() + 1, self.width(), self.height() - rect.bottom() - 1),
                VEIL,
            )
            painter.fillRect(QRect(0, rect.top(), rect.left(), rect.height()), VEIL)
            painter.fillRect(
                QRect(rect.right() + 1, rect.top(), self.width() - rect.right() - 1, rect.height()),
                VEIL,
            )
            painter.fillRect(rect, FILL)
            painter.setPen(QPen(BORDER, 1))
            painter.drawRect(rect)

            # Tutamaclar + ortadaki tasima noktasi (yalniz ayar modunda,
            # yani ilk surukleme bittikten sonra).
            if not self._picking:
                painter.setBrush(BORDER)
                for point in self._grip_points(rect):
                    painter.drawRect(
                        point.x() - HANDLE_PX, point.y() - HANDLE_PX,
                        HANDLE_PX * 2, HANDLE_PX * 2,
                    )
                painter.drawEllipse(rect.center(), CENTER_PX, CENTER_PX)

            # Boyut etiketi.
            label = f"{rect.width()} x {rect.height()}"
            painter.setPen(QColor("#e6edf3"))
            painter.drawText(rect.left(), max(14, rect.top() - 6), label)
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
        self._shot = None  # ekran goruntusu bellekte bosuna durmasin
        self._bar.hide()
        super().closeEvent(event)
        self.closed.emit()
