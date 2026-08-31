"""Pencereleri CALISILAN monitorun ortasina acar.

Tek kural: pencere, imlecin o an bulundugu ekranin calisma alaninda
(gorev cubugu haric) ortalanir. Elle koordinat hesabi, DPI cevrimi,
Win32 cagrisi yok -- Qt bu iki monitorlu %135 olcekli duzende dogru
sonuc veriyor, olculerek dogrulandi.

`availableGeometry` ile sinirlamak sart: ekrandan buyuk bir pencereyi
ortalamak onu yarim disarida birakirdi.
"""

from __future__ import annotations

from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QWidget


def center_on_cursor_screen(widget: QWidget) -> None:
    """Imlecin oldugu ekranda ortalar; ekrandan buyukse kucultup sigdirir."""
    app = QApplication.instance()
    if app is None:
        return
    screen = app.screenAt(QCursor.pos()) or app.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry()
    widget.resize(min(widget.width(), area.width()), min(widget.height(), area.height()))
    frame = widget.frameGeometry()
    frame.moveCenter(area.center())
    widget.move(frame.topLeft())
