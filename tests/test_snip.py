"""Secim cubugunun klavye yolu (ui/snip.py).

Ekran yakalama offscreen surucude de calisiyor: `grab_virtual` Win32'den
gercek masaustunu aliyor, Qt'nin gorunur pencereye ihtiyaci yok.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLineEdit


def _ctrl_c(widget) -> None:
    QApplication.sendEvent(
        widget,
        QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier, "c"
        ),
    )


def _open_bar(qapp):
    """Secim yapilmis, islem cubugu acilmis bir orutu dondurur."""
    from cascade.ui.snip import SnipOverlay

    snip = SnipOverlay()
    snip.start()
    snip._rect = QRect(QPoint(10, 10), QPoint(120, 90))
    snip._settle_pick()
    return snip


def test_farenin_kopyala_tusu_cubuktaki_dugmeyle_ayni_isi_yapar(qapp):
    """F20 kaskadi kisa basimda `^c` gonderiyor. Secim penceresi ondeyken
    o tus bize geliyor ama Ctrl+C'nin burada bir anlami yoktu: cubuktaki
    "Kopyala" dugmesi calisirken farenin tusu hicbir sey yapmiyordu."""
    snip = _open_bar(qapp)
    done: list[str] = []
    snip.done.connect(lambda action, _image: done.append(action))
    _ctrl_c(snip)
    assert done == ["copy"]
    snip.close()


def test_metin_kutusunda_yazarken_secimi_kopyalamaz(qapp):
    """Area adi / IFTTT metni yazarken Ctrl+C metni kopyalamali.

    Qt olayi once odaktaki widget'a verir; QLineEdit Ctrl+C'yi kendi yer ve
    orutuye hic yukselmez -- burada dogrulanan sey tam olarak bu.
    """
    snip = _open_bar(qapp)
    done: list[str] = []
    snip.done.connect(lambda action, _image: done.append(action))
    box = QLineEdit(snip)
    box.setText("deneme")
    box.selectAll()
    _ctrl_c(box)
    assert done == []
    snip.close()


def test_secim_yokken_kopyalama_calismaz(qapp):
    """Bos cerceve: kirpilacak bir sey yok, tus uygulamaya gitsin."""
    from cascade.ui.snip import SnipOverlay

    snip = SnipOverlay()
    snip.start()
    done: list[str] = []
    snip.done.connect(lambda action, _image: done.append(action))
    _ctrl_c(snip)
    assert done == []
    snip.close()
