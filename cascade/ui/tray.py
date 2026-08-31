"""Sistem tepsisi -- AHK'deki TraySetIcon + A_TrayMenu karsiligi.

Menu: Pause/Play (surumle birlikte) / Reload / Settings / Event monitor /
Copy last error / Exit. Metinler INGILIZCE -- AHK tepsi menusu de oyleydi,
aliskanlik bozulmasin.

Duraklat, AHK'nin `Suspend` komutunun karsiligi: hook yerinde kalir ama
hicbir tus yutulmaz, hicbir eylem calismaz. Hook'u sokup takmak yerine
bayrak kullanmanin sebebi, yeniden kurulan hook'un zincirin sonuna
dusmesi ve sira garantisinin kaybolmasi.

Simge dosyadan degil, cizilerek uretiliyor -- ne .ico dosyasi tasimak
gerekiyor ne de paketlemede kaynak gomme derdi var. Uc durumu var: calisiyor
(mavi), duraklatildi (gri), hata var (kirmizi). Hata rengi tek gorunur
uyari: hatalar log'a ve bellege yaziliyordu ama disariya hic yansimiyordu.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from cascade.settings import Category, setting

BACKGROUND = QColor("#1f6feb")
PAUSED_BACKGROUND = QColor("#6e7681")
ERROR_BACKGROUND = QColor("#da3633")
BAR = QColor("#ffffff")

#: Cift tiklama eylemleri. Ayara KIMLIK yazilir, menude ETIKET gorunur --
#: menu metnini degistirmek kayitli secimi bozmasin.
DOUBLE_CLICK_LABELS = {
    "pause": "Pause/Play",
    "restart": "Reload",
    "settings": "Settings",
    "monitor": "Event monitor",
    "copy_error": "Copy last error",
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
        "(menuyu acar), ona karisilmiyor."
    ),
)


def make_icon(size: int = 64, paused: bool = False, error: bool = False) -> QIcon:
    """Kaskadi anlatan basit simge: saga dogru inen uc cubuk.

    Duraklatilmisken ayni sekil gri zeminde -- AHK'nin Suspend simgesi gibi,
    program calisiyor ama tuslara dokunmuyor demek. Hata varsa kirmizi;
    duraklatma daha oncelikli, cunku o an ne oldugunu bilmek daha onemli.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    if paused:
        ground = PAUSED_BACKGROUND
    elif error:
        ground = ERROR_BACKGROUND
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
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    def __init__(
        self,
        version: str,
        on_monitor: Callable[[], None],
        on_restart: Callable[[], None],
        on_exit: Callable[[], None],
        on_toggle_pause: Callable[[], None] = lambda: None,
        on_settings: Callable[[], None] = lambda: None,
        on_copy_error: Callable[[], None] = lambda: None,
        parent=None,
    ) -> None:
        super().__init__(make_icon(), parent)
        self.version = version
        self.paused = False
        self.error_count = 0
        self.setToolTip(f"cascade {version}")

        self._handlers = {
            "pause": on_toggle_pause,
            "restart": on_restart,
            "settings": on_settings,
            "monitor": on_monitor,
            "copy_error": on_copy_error,
        }

        menu = QMenu()

        # AHK: Suspend.  Isaretlenebilir tek madde -- ayri "devam et" maddesi
        # koymak yerine kutucuk, cunku durumu da gostermesi gerekiyor. Surum
        # ayri bir baslik satirinda degil burada: menunun ilk satiri zaten
        # okunuyor, pasif bir baslik bir satiri bosa harciyordu.
        self.pause_action = self._add(menu, "", on_toggle_pause)
        self.pause_action.setCheckable(True)
        self._add(menu, "Reload", on_restart)
        menu.addSeparator()

        self._add(menu, "Settings...", on_settings)
        self._add(menu, "Event monitor...", on_monitor)
        self.error_action = self._add(menu, "", on_copy_error)
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

    def set_error_count(self, count: int) -> None:
        """Hata sayisi: simge kirmizi olur, menude sayi gorunur."""
        self.error_count = count
        self.error_action.setText(
            f"Copy last error  ({count})" if count else "Copy last error"
        )
        self.error_action.setEnabled(bool(count))
        self._refresh()

    def _refresh(self) -> None:
        self.setIcon(make_icon(paused=self.paused, error=bool(self.error_count)))
        tip = f"cascade {self.version}"
        if self.paused:
            tip += " - paused"
        if self.error_count:
            tip += f" - {self.error_count} error"
        self.setToolTip(tip)

    def notify(self, title: str, message: str, ms: int = 2500) -> None:
        """AHK: TrayTip"""
        self.showMessage(title, message, make_icon(), ms)
