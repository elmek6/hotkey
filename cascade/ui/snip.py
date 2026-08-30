"""Ekran alani secimi -- F14 surukleme (AHK screen_ocr.ahk'nin secim kismi).

Iki faz var, AHK ile ayni:

**1. Secim fazi.** Tum ekranlarin DONDURULMUS goruntusu alinir, uzeri
karartilir ve fare surukleyerek alan secilir. Orutu tiklamalari yutar, alttaki
uygulamaya kaza tiklamasi gitmez.

**2. Ayar fazi.** Secim birakilinca:

    * 8 tutamac (koseler + kenar ortalari) secimi yeniden boyutlandirir
    * ortadaki nokta cerceveyi komple tasir
    * secimin disina tiklamak yeni secim baslatir
    * yanindaki cubuktan islem secilir: Kopyala / Sakla / OCR / OCR+
    * Esc iptal eder

**Orutu neden yalniz 1. fazda** (AHK'deki ayni karar): OCR+ paneli acikken
cerceve ekranda KALIYOR ve kullanici alani yeniden ayarlayabiliyor. Bu sirada
ekrani karartmak hem altini gormeyi engellerdi hem de yakalama oncesi
gizlenecek pencere sayisini artirirdi. Ayar fazinda pencereye MASKE
uygulaniyor: yalniz cerceve halkasi, tutamaclar ve cubuk tikliyor, geri kalan
her sey alttaki uygulamaya geciyor.

**Yakalama neden tek cekim degil:** ilk OCR dondurulmus goruntuden yapilir
(orutu vardi, ekran temizdi). Ayar fazinda alan degistirilirse ekran YENIDEN
cekilir -- cerceve gizlenir, DWM'in temiz kareyi cizmesi icin `SETTLE_MS`
beklenir, sonra yakalanir. Beklenmezse cerceve goruntunun icine karisir ve
OCR onu da okumaya calisir (AHK'de de ayni tuzak vardi).
"""

from __future__ import annotations

from enum import IntEnum

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QRegion,
)
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

HANDLE_PX = 5  # tutamac karesinin yarim kenari
GRIP_PX = 8  # tutamaca "isabet etti" sayilan mesafe (AHK: GRAB_TOL)
CENTER_PX = 7  # ortadaki tasima noktasinin yaricapi
MIN_SIZE = 8  # bundan kucuk secim "yanlislikla tikladim" sayilir (AHK: MIN_SIZE)
GRIP_MIN = 44  # bu boyutun altinda tutamaclar ust uste biner: yalniz cerceve
SETTLE_MS = 70  # cerceve gizlendikten sonra DWM'in temiz kareyi cizme suresi

VEIL = QColor(0, 0, 0, 90)  # AHK: DIM_ALPHA 90
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
#: "ocr_adv" seciminde pencere KAPANMAZ, ayar fazinda kalir.
ACTIONS = (
    ("\U0001f4cb Kopyala", "copy"),
    ("\U0001f4be Sakla", "save"),
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
        self._shot: QPixmap | None = None
        self._dpr = 1.0
        self._rect = QRect()  # secim, mantiksal pencere koordinati
        self._grip = Grip.NONE  # su an suruklenen tutamac
        self._anchor = QPoint()  # surukleme baslangici
        self._rect_at_press = QRect()
        self._picking = False  # ilk secim suruklemesi mi
        self._session = False  # OCR+ acik: cerceve kalir, orutu kalkar

        self._bar = QWidget(self)
        layout = QHBoxLayout(self._bar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        for label, action in ACTIONS:
            button = QPushButton(label, self._bar)
            button.setCursor(Qt.CursorShape.ArrowCursor)
            button.clicked.connect(lambda _c=False, a=action: self._finish(a))
            layout.addWidget(button)
        cancel = QPushButton("✕", self._bar)
        cancel.setCursor(Qt.CursorShape.ArrowCursor)
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
        """Ekrani dondurur ve secim fazinda acilir."""
        self._session = False
        self._rect = QRect()
        self._grip = Grip.NONE
        self._picking = False
        self._bar.hide()
        self.clearMask()

        virtual = self._capture()
        self.setGeometry(virtual)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.show()
        self.raise_()
        self.activateWindow()

    def end_session(self) -> None:
        """OCR+ paneli kapandi: cerceveyi de kaldir."""
        if self._session:
            self.close()

    # ---- ekran yakalama ----

    def _capture(self) -> QRect:
        """Tum ekranlari tek bir pixmap'e alir; sanal masaustunu doner.

        Her ekran KENDI olcegiyle yakalanir ve HEDEF DIKDORTGENE cizilir.
        Boylece farkli DPI'li monitorler dogru boyutta birlesir: eskiden
        yakalanan pixmap'in kendi devicePixelRatio'su korundugu icin Qt onu
        MANTIKSAL boyutunda ciziyor, goruntu olcek kadar kuculuyordu
        ("her monitorde icerik unzoom gibi kuculuyor").
        """
        primary = QGuiApplication.primaryScreen()
        virtual = primary.virtualGeometry()
        self._dpr = primary.devicePixelRatio()

        shot = QPixmap(
            int(virtual.width() * self._dpr), int(virtual.height() * self._dpr)
        )
        shot.fill(Qt.GlobalColor.black)
        painter = QPainter(shot)
        for screen in QGuiApplication.screens():
            grab = screen.grabWindow(0)
            grab.setDevicePixelRatio(1.0)  # gercek piksel boyutunda cizilsin
            geometry = screen.geometry()
            target = QRectF(
                (geometry.x() - virtual.x()) * self._dpr,
                (geometry.y() - virtual.y()) * self._dpr,
                geometry.width() * self._dpr,
                geometry.height() * self._dpr,
            )
            painter.drawPixmap(target, grab, QRectF(grab.rect()))
        painter.end()
        shot.setDevicePixelRatio(self._dpr)
        self._shot = shot
        return virtual

    def _crop(self) -> QImage | None:
        """Secili alani kaynak pikselde kirpar."""
        rect = self._rect.normalized()
        if self._shot is None or rect.width() < MIN_SIZE or rect.height() < MIN_SIZE:
            return None
        device = QRect(
            int(rect.x() * self._dpr),
            int(rect.y() * self._dpr),
            int(rect.width() * self._dpr),
            int(rect.height() * self._dpr),
        )
        image = self._shot.copy(device).toImage()
        image.setDevicePixelRatio(1.0)  # kaydedilen dosya gercek piksel
        return image

    def _recapture(self, then) -> None:
        """Cerceveyi gizle, bir kare bekle, ekrani yeniden cek, geri goster.

        Ayar fazinda alan degistiginde gerekiyor: orutu kalkmis oldugu icin
        goruntunun uzerinde bizim cercevemiz duruyor ve kirpim ona bulasirdi.
        """
        self.hide()

        def grab() -> None:
            virtual = self._capture()
            self.setGeometry(virtual)
            self.show()
            self.raise_()
            self._update_mask()
            then()

        QTimer.singleShot(SETTLE_MS, grab)

    # ---- ic akis ----

    def _finish(self, action: str) -> None:
        image = self._crop()
        if image is None:
            return
        if action in KEEP_OPEN:
            # AHK ayar fazi: orutu kalkar, cerceve ekranda kalir, tiklamalar
            # cerceve disinda alttaki uygulamaya gecer.
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

    def _update_mask(self) -> None:
        """Ayar fazinda tiklanabilir bolgeyi cerceve + cubukla sinirlar.

        Maske olmasa tam ekran pencere butun tiklamalari yutardi ve OCR+
        paneli acikken alttaki uygulamayla calisilamazdi.
        """
        if not self._session:
            self.clearMask()
            return
        rect = self._rect.normalized()
        outer = rect.adjusted(-GRIP_PX, -GRIP_PX, GRIP_PX, GRIP_PX)
        inner = rect.adjusted(GRIP_PX, GRIP_PX, -GRIP_PX, -GRIP_PX)
        region = QRegion(outer)
        if inner.width() > 0 and inner.height() > 0:
            region = region.subtracted(QRegion(inner))
        center = rect.center()
        region = region.united(
            QRegion(
                center.x() - CENTER_PX, center.y() - CENTER_PX,
                CENTER_PX * 2, CENTER_PX * 2, QRegion.RegionType.Ellipse,
            )
        )
        if self._bar.isVisible():
            region = region.united(QRegion(self._bar.geometry()))
        self.setMask(region)

    # ---- Qt olaylari ----

    def mousePressEvent(self, event) -> None:
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
            self._bar.hide()
        else:
            self._rect_at_press = QRect(self._rect.normalized())
            self._bar.hide()
            self._update_mask()
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        if self._picking:
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
        self._picking = False
        self._grip = Grip.NONE
        rect = self._rect.normalized()
        if rect.width() < MIN_SIZE or rect.height() < MIN_SIZE:
            self._rect = QRect()  # tiklama: secim yok, beklemeye devam
            self._update_mask()
            self.update()
            return
        self._rect = rect
        self._place_bar()
        self._update_mask()
        self.update()
        if self._session and adjusted:
            # Alan degisti: ekrani temiz haliyle yeniden cekip paneli tazele.
            self._recapture(self._emit_rect_changed)

    def _emit_rect_changed(self) -> None:
        image = self._crop()
        if image is not None:
            self.rect_changed.emit(image)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        rect = self._rect.normalized()
        painter = QPainter(self)

        if not self._session:
            if self._shot is None:
                return
            painter.drawPixmap(0, 0, self._shot)
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
                    QRect(
                        rect.right() + 1, rect.top(),
                        self.width() - rect.right() - 1, rect.height(),
                    ),
                    VEIL,
                )
                painter.fillRect(rect, FILL)

        if rect.isEmpty():
            painter.end()
            return

        painter.setPen(QPen(BORDER, 1))
        painter.drawRect(rect)

        # Tutamaclar + ortadaki tasima noktasi. Ilk surukleme sirasinda
        # gosterilmez; cok kucuk secimde ust uste binerler (AHK: GRIP_MIN).
        if not self._picking and min(rect.width(), rect.height()) >= GRIP_MIN:
            painter.setBrush(BORDER)
            for point in self._grip_points(rect):
                painter.drawRect(
                    point.x() - HANDLE_PX, point.y() - HANDLE_PX,
                    HANDLE_PX * 2, HANDLE_PX * 2,
                )
            painter.drawEllipse(rect.center(), CENTER_PX, CENTER_PX)

        if not self._session:
            painter.setPen(QColor("#e6edf3"))
            painter.drawText(
                rect.left(), max(14, rect.top() - 6), f"{rect.width()} x {rect.height()}"
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
        self._session = False
        self._shot = None  # ekran goruntusu bellekte bosuna durmasin
        self._bar.hide()
        self.clearMask()
        super().closeEvent(event)
        self.closed.emit()
