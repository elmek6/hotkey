"""Sistem tepsisi -- AHK'deki TraySetIcon + A_TrayMenu karsiligi.

Menu: Pause/Play (surumle birlikte) / Reload / Pause menu / Settings / Event monitor /
Copy last error / Exit. Metinler INGILIZCE -- AHK tepsi menusu de oyleydi,
aliskanlik bozulmasin.

Duraklat, AHK'nin `Suspend` komutunun karsiligi: hook yerinde kalir ama
hicbir tus yutulmaz, hicbir eylem calismaz. Hook'u sokup takmak yerine
bayrak kullanmanin sebebi, yeniden kurulan hook'un zincirin sonuna
dusmesi ve sira garantisinin kaybolmasi.

Simge dosyadan degil, cizilerek uretiliyor -- ne .ico dosyasi tasimak
gerekiyor ne de paketlemede kaynak gomme derdi var. Dort durumu var: calisiyor
(mavi), duraklatildi (gri), uyari var (sari), gercek hata var (kirmizi).

KIRMIZI PAHALI BIR RENKTIR. Once her WARNING+ kaydi kirmiziya boyuyordu ve
en cok goruleni "cift tiklama yutuldu" idi -- kendi log satiri bile "program
hatasi degil" diyen bir kayit. Simgeye bakan "keypilot coktu mu" diye
irkiliyor, sonra ariza farenin normal bir gunune bakiyordu. Artik esik
ERROR: WARNING sariya duser, kirmizi yalnizca gercekten bozulan bir sey
oldugunda yanar.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from keypilot.settings import Category, setting

BACKGROUND = QColor("#1f6feb")
PAUSED_BACKGROUND = QColor("#6e7681")
ERROR_BACKGROUND = QColor("#da3633")
WARN_BACKGROUND = QColor("#bb8009")
BAR = QColor("#ffffff")
#: Gelistirme modu (keypilot/dev.py) acikken simgenin cevresine cizilen
#: halka. ZEMIN DEGIL cerceve: zemin renkleri zaten dolu (duraklatildi /
#: hata / uyari) ve mor onlarin yerine gecseydi gelistirme modu hata
#: isaretini ORTERDI. Halka ayri bir kanal -- ikisi ayni anda gorunur.
DEV_RING = QColor("#a371f7")

#: Cift tiklama eylemleri. Ayara KIMLIK yazilir, menude ETIKET gorunur --
#: menu metnini degistirmek kayitli secimi bozmasin.
DOUBLE_CLICK_LABELS = {
    "pause": "Pause/Play",
    "restart": "Reload",
    "pause_dialog": "Pause menu",
    "settings": "Settings",
    "monitor": "Event monitor",
    "copy_error": "Copy last error",
    "show_log": "Show log",
}
#: settings.json'da duran eski (metin) degerler.
DOUBLE_CLICK_LEGACY = {label: name for name, label in DOUBLE_CLICK_LABELS.items()}

DOUBLE_CLICK = setting(
    "tray.doubleClick",
    "Tepsi simgesine cift tiklama",
    default="pause",
    choices=tuple(DOUBLE_CLICK_LABELS),
    labels=DOUBLE_CLICK_LABELS,
    legacy=DOUBLE_CLICK_LEGACY,
    category=Category.TRAY,
    tags="tepsi tray cift tiklama simge",
    desc=(
        "Sistem tepsisindeki simgeye cift tiklayinca ne olsun -- secenekler "
        "tepsi menusundeki maddelerin ayni. Tek tiklama Windows'un kendi isi "
        "(menuyu acar), ona karisilmiyor. Simge ISARETLI iken (kirmizi = hata, "
        "sari = uyari) bu ayar gecersiz: son hatalar penceresi acilir."
    ),
)


def make_icon(
    size: int = 64,
    paused: bool = False,
    error: bool = False,
    warn: bool = False,
    dev: bool = False,
) -> QIcon:
    """Kaskadi anlatan basit simge: saga dogru inen uc cubuk.

    Duraklatilmisken ayni sekil gri zeminde -- AHK'nin Suspend simgesi gibi,
    program calisiyor ama tuslara dokunmuyor demek. Sonra siddet sirasi:
    kirmizi (ERROR+, bir sey bozuldu), sari (WARNING, dikkat ama calisiyor).
    Duraklatma hepsinden oncelikli, cunku o an tuslarin neden olmedigini
    bilmek birikmis bir uyaridan daha acil.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    if paused:
        ground = PAUSED_BACKGROUND
    elif error:
        ground = ERROR_BACKGROUND
    elif warn:
        ground = WARN_BACKGROUND
    else:
        ground = BACKGROUND

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(ground))
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)

    painter.setBrush(QBrush(BAR))
    unit = size / 16.0
    for index in range(3):
        painter.drawRoundedRect(
            QRectF(
                unit * (3 + index * 1.6),
                unit * (3.2 + index * 3.6),
                unit * (9 - index * 1.6),
                unit * 2.2,
            ),
            unit * 1.1,
            unit * 1.1,
        )

    # Gelistirme modu: mor halka. Simge tepside 16 px'e inecegi icin
    # cizgi kalinligi oranli veriliyor ve dikdortgen yarim kalinlik iceri
    # cekiliyor -- yoksa halkanin disi kirpiliyor.
    if dev:
        stroke = size * 0.09
        pen = QPen(DEV_RING)
        pen.setWidthF(stroke)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = stroke / 2.0
        painter.drawRoundedRect(
            QRectF(inset, inset, size - stroke, size - stroke),
            size * 0.20,
            size * 0.20,
        )
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    def __init__(
        self,
        version: str,
        on_monitor: Callable[[], None],
        on_restart: Callable[[], None],
        on_exit: Callable[[], None],
        on_pause_dialog: Callable[[], None] = lambda: None,
        on_toggle_pause: Callable[[], None] = lambda: None,
        on_settings: Callable[[], None] = lambda: None,
        on_copy_error: Callable[[], None] = lambda: None,
        on_show_log: Callable[[], None] = lambda: None,
        on_show_errors: Callable[[], None] = lambda: None,
        parent=None,
    ) -> None:
        super().__init__(make_icon(), parent)
        self.version = version
        self.paused = False
        #: Gelistirme modu acik mi -- simgede mor halka, ipucunda etiket.
        #: Ayardan da gelebilir bayraktan da; tepsi ayrimi bilmiyor.
        self.dev = False
        self.error_count = 0
        #: Bunlarin kaci ERROR+ -- simgeyi KIRMIZI yapan sayi budur.
        self.severe_count = 0
        self.setToolTip(f"KeyPilot {version}")

        self._handlers = {
            "pause": on_toggle_pause,
            "restart": on_restart,
            "pause_dialog": on_pause_dialog,
            "settings": on_settings,
            "monitor": on_monitor,
            "copy_error": on_copy_error,
            "show_log": on_show_log,
        }
        #: Simge KIRMIZI ya da SARI iken cift tiklama bunu cagirir -- cift
        #: tiklama ayarindan bagimsiz. Isaretli simgeye tiklayan "ne oldu"
        #: diye bakiyor; o an Pause/Play yapmak istemiyor.
        self._on_show_errors = on_show_errors

        menu = QMenu()

        # AHK: Suspend.  Isaretlenebilir tek madde -- ayri "devam et" maddesi
        # koymak yerine kutucuk, cunku durumu da gostermesi gerekiyor. Surum
        # ayri bir baslik satirinda degil burada: menunun ilk satiri zaten
        # okunuyor, pasif bir baslik bir satiri bosa harciyordu.
        self.pause_action = self._add(menu, "", on_toggle_pause)
        self.pause_action.setCheckable(True)
        self._add(menu, "Reload", on_restart)
        # AHK menus.ahk `DialogPauseGui` (Pause & c / Pause & End): duraklat +
        # yeniden baslat + kaydetmeden yeniden baslat + cikis tek pencerede.
        # Tepsiden de acilsin -- Pause tusu olmayan klavyede tek yol buydu.
        self._add(menu, "Pause menu...", on_pause_dialog)
        menu.addSeparator()

        self._add(menu, "Settings...", on_settings)
        self._add(menu, "Event monitor...", on_monitor)
        self.error_action = self._add(menu, "", on_copy_error)
        self._add(menu, "Show log...", on_show_log)
        menu.addSeparator()
        self._add(menu, "Exit", on_exit)

        self._menu = menu  # GC'ye yem olmasin
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self.set_paused(False)
        self.set_error_count(0)

    @staticmethod
    def _add(menu: QMenu, text: str, slot: Callable[[], None]) -> QAction:
        action = QAction(text, menu)
        action.triggered.connect(lambda _checked=False: slot())
        menu.addAction(action)
        return action

    def _on_activated(self, reason) -> None:
        if reason != QSystemTrayIcon.ActivationReason.DoubleClick:
            return
        if self.error_count:
            self._on_show_errors()
            return
        name = str(DOUBLE_CLICK.get())
        self._handlers.get(name, self._handlers["pause"])()

    # ---- durum ----

    def set_paused(self, paused: bool) -> None:
        """Menu kutucugu + simge + arac ipucu tek yerden guncellenir."""
        self.paused = paused
        self.pause_action.setChecked(paused)
        self.pause_action.setText(
            f"Play  (v{self.version})" if paused else f"Pause  (v{self.version})"
        )
        self._refresh()

    def set_dev(self, active: bool) -> None:
        """Gelistirme modunu simgede goster.

        Neden gorunur olmali: mod, programin davranisini degistiriyor
        (nobetci calisir, log sisirir) ve komut satirindan da acilabiliyor
        -- yani ayar ekraninda KAPALI gorunurken acik olabilir. Boyle bir
        sey ekranda hicbir iz birakmadan durmamali.
        """
        if active == self.dev:
            return
        self.dev = active
        self._refresh()

    def set_error_count(self, count: int, severe: int = 0) -> None:
        """Kayit sayisi: menude sayi gorunur, simge renk degistirir.

        `severe` = bunlarin kaci ERROR+. Simge YALNIZCA o sayi sifirdan
        buyukken kirmizi; geri kalani (WARNING) sari. Bkz. dosya basi.
        """
        self.error_count = count
        self.severe_count = min(severe, count)
        self.error_action.setText(
            f"Copy last error  ({count})" if count else "Copy last error"
        )
        self.error_action.setEnabled(bool(count))
        self._refresh()

    def _refresh(self) -> None:
        self.setIcon(
            make_icon(
                paused=self.paused,
                error=bool(self.severe_count),
                warn=bool(self.error_count),
                dev=self.dev,
            )
        )
        tip = f"KeyPilot {self.version}"
        if self.dev:
            tip += " - GELISTIRME"
        if self.paused:
            tip += " - paused"
        # Arac ipucu de ayirir: "1 error" ile "1 warning" cok farkli iki haber.
        if self.severe_count:
            tip += f" - {self.severe_count} error"
        if self.error_count - self.severe_count:
            tip += f" - {self.error_count - self.severe_count} warning"
        self.setToolTip(tip)

    def notify(self, title: str, message: str, ms: int = 2500) -> None:
        """AHK: TrayTip"""
        self.showMessage(title, message, make_icon(), ms)
