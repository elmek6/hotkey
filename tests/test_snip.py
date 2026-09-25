"""Secim cubugunun klavye yolu (ui/snip.py).

Ekran yakalama offscreen surucude de calisiyor: `grab_virtual` Win32'den
gercek masaustunu aliyor, Qt'nin gorunur pencereye ihtiyaci yok.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from keypilot.ui.snip import Grip, SnipOverlay


def _ctrl_c(widget) -> None:
    QApplication.sendEvent(
        widget,
        QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier, "c"
        ),
    )


def _open_bar(qapp):
    """Secim yapilmis, islem cubugu acilmis bir orutu dondurur."""
    from keypilot.ui.snip import SnipOverlay

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
    from keypilot.ui.snip import SnipOverlay

    snip = SnipOverlay()
    snip.start()
    done: list[str] = []
    snip.done.connect(lambda action, _image: done.append(action))
    _ctrl_c(snip)
    assert done == []
    snip.close()


def test_ocr_hover_paneli_solda_metin_sagda_diller(qapp):
    snip = _open_bar(qapp)
    assert snip._ocr_expand is not None
    assert snip._ocr_preview_label is not None
    snip._show_ocr_expand()
    assert snip._ocr_expand.isVisible()
    labels = [child.text() for child in snip._ocr_expand.findChildren(QPushButton)]
    assert "En" in labels and "Tr" in labels and "De" in labels
    snip.close()


def _arrow(widget, key) -> None:
    QApplication.sendEvent(
        widget,
        QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier),
    )


def _click(widget, pos: QPoint) -> None:
    point = QPointF(pos)
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        point,
        point,
        point,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, press)
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        point,
        point,
        point,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, release)


def test_secim_bitince_orta_tutamac_varsayilan_ve_cizilir(qapp):
    snip = _open_bar(qapp)
    assert snip._selected_grip == Grip.MOVE
    grips = {grip for grip, _point in SnipOverlay._grip_handles(snip._rect)}
    assert Grip.MOVE in grips
    assert len(grips) == 9
    snip.close()


def test_yon_tuslari_ortayi_1px_kaydirir(qapp):
    snip = _open_bar(qapp)
    before = QRect(snip._rect)
    _arrow(snip, Qt.Key.Key_Right)
    assert snip._rect.left() == before.left() + 1
    assert snip._rect.width() == before.width()
    assert snip._rect.height() == before.height()
    snip.close()


def test_sol_tutamac_yalniz_yatay_yon_tuslari(qapp):
    snip = _open_bar(qapp)
    snip._selected_grip = Grip.LEFT
    snip._hover_grip = Grip.NONE
    before = QRect(snip._rect)
    _arrow(snip, Qt.Key.Key_Up)
    assert snip._rect == before
    _arrow(snip, Qt.Key.Key_Left)
    assert snip._rect.left() == before.left() - 1
    assert snip._rect.top() == before.top()
    snip.close()


def test_ust_tutamac_yalniz_dikey_yon_tuslari(qapp):
    snip = _open_bar(qapp)
    snip._selected_grip = Grip.TOP
    snip._hover_grip = Grip.NONE
    before = QRect(snip._rect)
    _arrow(snip, Qt.Key.Key_Right)
    assert snip._rect == before
    _arrow(snip, Qt.Key.Key_Up)
    assert snip._rect.top() == before.top() - 1
    snip.close()


def test_kenar_tutamacina_tiklamak_kipi_secer(qapp):
    snip = _open_bar(qapp)
    rect = snip._rect.normalized()
    _click(snip, QPoint(rect.left(), rect.center().y()))
    assert snip._selected_grip == Grip.LEFT
    snip.close()
