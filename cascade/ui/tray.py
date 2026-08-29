"""Sistem tepsisi -- AHK'deki TraySetIcon + A_TrayMenu karsiligi.

Menu: surum (baslik) / duraklat-devam / olay izleyici / yeniden baslat / cikis.

Duraklat, AHK'nin `Suspend` komutunun karsiligi: hook yerinde kalir ama
hicbir tus yutulmaz, hicbir eylem calismaz. Hook'u sokup takmak yerine
bayrak kullanmanin sebebi, yeniden kurulan hook'un zincirin sonuna
dusmesi ve sira garantisinin kaybolmasi.

Simge dosyadan degil, cizilerek uretiliyor -- ne .ico dosyasi tasimak
gerekiyor ne de paketlemede kaynak gomme derdi var.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

BACKGROUND = QColor("#1f6feb")
PAUSED_BACKGROUND = QColor("#6e7681")
BAR = QColor("#ffffff")


def make_icon(size: int = 64, paused: bool = False) -> QIcon:
    """Kaskadi anlatan basit simge: saga dogru inen uc cubuk.

    Duraklatilmisken ayni sekil gri zeminde -- AHK'nin Suspend simgesi gibi,
    program calisiyor ama tuslara dokunmuyor demek.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(PAUSED_BACKGROUND if paused else BACKGROUND))
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
        parent=None,
    ) -> None:
        super().__init__(make_icon(), parent)
        self.version = version
        self.setToolTip(f"cascade {version}")

        menu = QMenu()

        header = QAction(f"cascade {version}", menu)
        header.setEnabled(False)
        menu.addAction(header)
        menu.addSeparator()

        # AHK: Suspend.  Isaretlenebilir tek madde -- ayri "devam et" maddesi
        # koymak yerine kutucuk, cunku durumu da gostermesi gerekiyor.
        self.pause_action = self._add(menu, "Duraklat  (Pause)", on_toggle_pause)
        self.pause_action.setCheckable(True)
        menu.addSeparator()

        self._add(menu, "Olay izleyici...", on_monitor)
        menu.addSeparator()
        self._add(menu, "Yeniden baslat  (reload)", on_restart)
        self._add(menu, "Cikis  (exit)", on_exit)

        self._menu = menu  # GC'ye yem olmasin
        self.setContextMenu(menu)
        # Cift tiklama duraklat/devam. AHK'de tepsi simgesine cift tiklamak
        # scripti askiya aliyordu; en sik istenen sey o, izleyici degil.
        self.activated.connect(lambda reason: self._on_activated(reason, on_toggle_pause))

    @staticmethod
    def _add(menu: QMenu, text: str, slot: Callable[[], None]) -> QAction:
        action = QAction(text, menu)
        action.triggered.connect(lambda _checked=False: slot())
        menu.addAction(action)
        return action

    @staticmethod
    def _on_activated(reason, on_double_click: Callable[[], None]) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            on_double_click()

    def set_paused(self, paused: bool) -> None:
        """Menu kutucugu + simge + arac ipucu tek yerden guncellenir."""
        self.pause_action.setChecked(paused)
        self.pause_action.setText("Devam et  (Play)" if paused else "Duraklat  (Pause)")
        self.setIcon(make_icon(paused=paused))
        self.setToolTip(f"cascade {self.version}" + (" - duraklatildi" if paused else ""))

    def notify(self, title: str, message: str, ms: int = 2500) -> None:
        """AHK: TrayTip"""
        self.showMessage(title, message, make_icon(), ms)
