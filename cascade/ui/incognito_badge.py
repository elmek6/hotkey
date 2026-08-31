"""Incognito penceresi -- AHK `incognito.ahk` `_showBadge()` portu.

Bu pencere hem gosterge hem kumanda: incognito acikken gorev cubugunda
durur, boylece "acik kaldi mi?" sorusu hic sorulmaz. Kisayolun tek isi bu
pencereyi acmak; mod pencere acilinca devreye girer, kapanana kadar acik
kalir.

  * `show_badge()` pencereyi one getirir; gorev cubugu butonu hep kalir.
  * Gorev cubugundan geri acilinca liste tazelenir (AHK `_onBadgeSize`).
  * Pencereyi KAPATMAK incognito'yu kapatir -- capraz, Escape ve "Kapat"
    dugmesi ayni sey. Kapanis uzun surdugu icin dugme aninda devre disi
    kalir ve isi zamanlayiciya devreder (AHK `_closeFromBadge`).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cascade.incognito import Incognito

MASK = "🏴‍☠️"  # korsan bayragi -- gorev cubugu simgesi


def make_icon(size: int = 64) -> QIcon:
    """Simgeyi emojiden ciziyoruz: pakete .ico dosyasi tasimamak icin."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    font = QFont()
    font.setPointSizeF(size * 0.72)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, MASK)
    painter.end()
    return QIcon(pixmap)



class IncognitoBadge(QWidget):
    def __init__(self, incognito: Incognito, on_close: Callable[[], None]) -> None:
        super().__init__()
        self.incognito = incognito
        self._on_close = on_close
        self._closing = False

        self.setWindowTitle(f"{MASK} Incognito")
        self.setWindowIcon(make_icon())
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)

        self.info = QLabel()
        self.list = QListWidget()
        self.list.setMinimumSize(320, 220)

        self.deep = QCheckBox("Derin izler (klasor + program gecmisi — yavaslatir)")
        self.deep.setChecked(incognito.deep_mode)
        self.deep.clicked.connect(self._on_deep)

        self.vlc = QCheckBox("VLC")
        self.vlc.setChecked(incognito.cover_vlc)
        self.vlc.clicked.connect(lambda on: setattr(incognito, "cover_vlc", bool(on)))

        self.restore = QCheckBox("Kapanista geri yukle")
        self.restore.setChecked(incognito.restore_on_close)
        self.restore.clicked.connect(
            lambda on: setattr(incognito, "restore_on_close", bool(on))
        )

        audit = QPushButton("🔍 Denetle")
        audit.clicked.connect(self._show_audit)
        refresh = QPushButton("🔄 Yenile")
        refresh.clicked.connect(self.refresh)
        self.close_button = QPushButton("🔒 Kapat")
        self.close_button.clicked.connect(self._close_incognito)

        checks = QHBoxLayout()
        checks.addWidget(self.vlc)
        checks.addWidget(self.restore)
        checks.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addWidget(audit)
        buttons.addWidget(refresh)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.info)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.deep)
        layout.addLayout(checks)
        layout.addLayout(buttons)

        self.refresh()

    # ---- gosterim ----

    def show_badge(self) -> None:
        """Kisayoldan cagrilir: pencereyi one getirir."""
        self.refresh()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def refresh(self) -> None:
        """AHK `_refreshBadgeList`: bilgi satiri + kilitli dosya adlari."""
        self.info.setText(
            f"Donduruldu: {self.incognito.locked_count} jump list dosyasi"
            f"   ·   {len(self.incognito.stores)}/{len(self.incognito.all_stores)}"
            " iz deposu"
        )
        self.list.clear()
        self.list.addItems(self.incognito.locked_names())

    def changeEvent(self, event) -> None:
        """Gorev cubugundan geri acilinca listeyi tazele (AHK `_onBadgeSize`)."""
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange and not self.isMinimized():
            self.refresh()

    # ---- eylemler ----

    def _on_deep(self, on: bool) -> None:
        self.incognito.set_deep_mode(on)
        # set_deep_mode mesgulken hicbir sey yapmaz; kutu gercek durumu gostersin.
        self.deep.setChecked(self.incognito.deep_mode)
        self.refresh()

    def _show_audit(self) -> None:
        """AHK `_showAudit`. Kapsam HER ZAMAN yazilir: "iz yok" ile "zaten
        kapsam disi" birbirine karismasin."""
        lines = self.incognito.audit()
        if lines:
            message = "Oturumda olusan izler — kapanista geri alinacak:\n\n" + "\n".join(
                lines
            )
        else:
            message = (
                "Oturum basindan beri yeni iz olusmadi.\n\n"
                "(Onleme katmani calisiyor demektir.)"
            )
        deep = (
            " (derin izler ACIK)"
            if self.incognito.deep_mode
            else " (derin izler kapali — klasor/program gecmisi kapsam disi)"
        )
        message += (
            f"\n──────────\nKapsam: {len(self.incognito.stores)} / "
            f"{len(self.incognito.all_stores)} depo{deep}"
        )
        QMessageBox.information(self, "Incognito denetim", message)

    def _close_incognito(self) -> None:
        """Kapanis uzun surer (geri yukleme): dugme aninda oluyor gorunsun,
        is bir sonraki olay turuna kalsin -- AHK'de de `SetTimer(-10)`."""
        if self._closing:
            return
        self._closing = True
        self.close_button.setEnabled(False)
        self.close_button.setText("Kapaniyor…")
        QTimer.singleShot(10, self._on_close)

    def closeEvent(self, event) -> None:
        """Capraz da Escape de "incognito'yu kapat" demek (AHK ile ayni).

        Pencereyi kapatan zaten kapanis akisiysa (app tarafi) engellenmez.
        """
        if self._closing or not self.incognito.active:
            super().closeEvent(event)
            return
        event.ignore()
        self._close_incognito()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
