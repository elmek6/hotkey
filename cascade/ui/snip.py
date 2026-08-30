"""Ekran alani secimi -- F14 surukleme (AHK screen_ocr.ahk'nin secim kismi).

Iki faz var, AHK ile ayni:

**1. Secim fazi.** Tum ekranlarin DONDURULMUS goruntusu alinir, uzeri
karartilir ve fare surukleyerek alan secilir. Orutu tiklamalari yutar, alttaki
uygulamaya kaza tiklamasi gitmez.

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
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from cascade.win32.screen import grab_virtual

HANDLE_PX = 4  # tutamac karesinin yarim kenari
GRIP_PX = 8  # tutamaca "isabet etti" sayilan mesafe (AHK: GRAB_TOL)
MIN_SIZE = 8  # bundan kucuk secim "yanlislikla tikladim" sayilir (AHK: MIN_SIZE)
GRIP_MIN = 44  # bu boyutun altinda tutamaclar ust uste biner: yalniz cerceve
SETTLE_MS = 70  # cerceve gizlendikten sonra DWM'in temiz kareyi cizme suresi

VEIL = QColor(0, 0, 0, 90)  # AHK: DIM_ALPHA 90
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

#: (etiket, eylem kimligi) -- app.py `done` sinyalinde bu kimligi alir.
#: "ocr_adv" seciminde pencere KAPANMAZ, ayar fazinda kalir.
ACTIONS = (
    ("\U0001f4cb Kopyala", "copy"),
    ("\U0001f4be Sakla", "save"),
    ("\U0001f5bc️ Gorsellere ekle", "clip_image"),
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
        self._bar.hide()
        self.clearMask()
        self._capture()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.show()
        # SIRA ONEMLI: yerlestirme show()'dan SONRA. Once cagrilirsa Qt
        # pencereyi kendi hesapladigi geometriyle gosterip uzerine yaziyor.
        self._place()
        self.raise_()
        self.activateWindow()
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
        """Secim suruklemesi bitti: cok kucukse iptal, degilse cubugu ac."""
        self._picking = False
        self._grip = Grip.NONE
        rect = self._rect.normalized()
        if rect.width() < MIN_SIZE or rect.height() < MIN_SIZE:
            self._rect = QRect()
            self._update_mask()
            self.update()
            return
        self._rect = rect
        self._place_bar()
        self._update_mask()
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
        self._bar.hide()
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
        if self._rect.isEmpty():  # tiklama: secim yok, beklemeye devam
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
        self._session = False
        self._key_timer.stop()
        self._key_vk = 0
        self._key_origin = None
        self._shot = None  # ekran goruntusu bellekte bosuna durmasin
        self._bar.hide()
        self.clearMask()
        super().closeEvent(event)
        self.closed.emit()
