"""Secim cubugunun klavye yolu (ui/snip.py).

Ekran yakalama offscreen surucude de calisiyor: `grab_virtual` Win32'den
gercek masaustunu aliyor, Qt'nin gorunur pencereye ihtiyaci yok.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from keypilot.ui.snip import Grip, SnipAction, SnipOverlay


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


def test_eylem_kimligi_bicimi():
    """app.py `_on_snip_done` dil secili OCR'yi `partition(":")` ile ayiriyor."""
    assert SnipAction.COPY == "copy"
    assert SnipAction.OCR("de") == "ocr:de"


# ---- OCR+ izgarasi (ui/snip.py: cetvel, cizgi ikonlari, sayac) --------------


def _grid_session(qapp):
    """Ayar fazindaki orutu: OCR+ oturumu acik, GERCEKCI boyutta cerceve.

    `_open_bar`in kucuk dikdortgeninde cetvel seridi ve resize tutamaclari
    ic ice giriyor; izgara kurallari ancak gercek bir secim boyutunda
    anlamli olculuyor.
    """
    snip = SnipOverlay()
    snip.start()
    snip._rect = QRect(QPoint(100, 100), QPoint(600, 500))
    snip._settle_pick()
    snip._session = True
    snip._update_mask()
    return snip


def _move(widget, pos: QPoint) -> None:
    point = QPointF(pos)
    QApplication.sendEvent(
        widget,
        QMouseEvent(
            QEvent.Type.MouseMove,
            point,
            point,
            point,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def _drag(widget, start: QPoint, end: QPoint) -> None:
    """Bas, surukle, birak -- sol tus basili hareketle."""
    _click_press(widget, start)
    point = QPointF(end)
    QApplication.sendEvent(
        widget,
        QMouseEvent(
            QEvent.Type.MouseMove,
            point,
            point,
            point,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    _click_release(widget, end)


def _click_press(widget, pos: QPoint) -> None:
    point = QPointF(pos)
    QApplication.sendEvent(
        widget,
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            point,
            point,
            point,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def _click_release(widget, pos: QPoint) -> None:
    point = QPointF(pos)
    QApplication.sendEvent(
        widget,
        QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            point,
            point,
            point,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def test_cetvele_tiklamak_cizgi_ekler(qapp):
    """Ust serit dikey, sol serit yatay cizgi birakir (cetvel kurali)."""
    snip = _grid_session(qapp)
    rect = snip._rect.normalized()
    top = snip._top_ruler_rect(rect)
    _move(snip, QPoint(rect.center().x(), top.center().y()))
    _click(snip, QPoint(rect.center().x(), top.center().y()))
    assert snip._grid_cols == pytest.approx([0.5], abs=0.01)
    assert not snip._grid_rows

    left = snip._left_ruler_rect(rect)
    _move(snip, QPoint(left.center().x(), rect.center().y()))
    _click(snip, QPoint(left.center().x(), rect.center().y()))
    assert snip._grid_rows == pytest.approx([0.5], abs=0.01)
    snip.close()


def test_cetveldeki_x_cizgiyi_siler(qapp):
    """Tutamac cizginin HIZASINDA cikar; uzerindeyken ekleme onizlemesi
    gosterilmez -- tiklama silme olur, ekleme degil."""
    snip = _grid_session(qapp)
    snip._grid_rows = [0.25, 0.75]
    rect = snip._rect.normalized()
    left = snip._left_ruler_rect(rect)
    on_handle = QPoint(left.center().x(), snip._line_pos(rect, "row", 0))

    _move(snip, on_handle)
    assert snip._del_hover == ("row", 0)

    _click(snip, on_handle)
    assert snip._grid_rows == pytest.approx([0.75])  # digeri yerinde kaldi
    snip.close()


def test_cetvelde_bos_yere_tiklamak_silmez_ekler(qapp):
    snip = _grid_session(qapp)
    snip._grid_rows = [0.25]
    rect = snip._rect.normalized()
    left = snip._left_ruler_rect(rect)
    empty = QPoint(left.center().x(), snip._line_pos(rect, "row", 0) + 40)

    _move(snip, empty)
    assert snip._del_hover is None
    _click(snip, empty)
    assert len(snip._grid_rows) == 2
    snip.close()


def test_cizgi_tutulup_suruklenir_secim_oynamaz(qapp):
    snip = _grid_session(qapp)
    snip._grid_rows = [0.25]
    rect = QRect(snip._rect.normalized())
    y = snip._line_pos(rect, "row", 0)
    _move(snip, QPoint(rect.center().x(), y))
    assert snip._line_hover == ("row", 0)

    _drag(snip, QPoint(rect.center().x(), y), QPoint(rect.center().x(), y + 80))
    assert snip._grid_rows[0] == pytest.approx(0.25 + 80 / rect.height(), abs=0.01)
    assert snip._rect.normalized() == rect  # cerceve kendisi kimildamadi
    assert snip._line_drag is None
    snip.close()


def test_kenara_oturan_cizgi_resize_tutamacini_calmaz(qapp):
    """Cizgi tam kenara denk gelirse o kenardan boyutlandirma olmeli degil:
    tutamac her zaman izgara hover'indan once gelir."""
    snip = _grid_session(qapp)
    snip._grid_rows = [0.0]  # ust kenarin uzerinde duran cizgi
    rect = snip._rect.normalized()
    _move(snip, QPoint(rect.center().x(), rect.top()))
    assert snip._hover_grip == Grip.TOP
    assert snip._line_hover is None
    snip.close()


def test_silme_tutamaclari_kendi_seridinde_durur(qapp):
    """Yatay cizgininki sol seritte, dikeyinki ust seritte."""
    snip = _grid_session(qapp)
    snip._grid_rows = [0.4]
    snip._grid_cols = [0.6]
    rect = snip._rect.normalized()
    for band, strip in (("h", snip._left_ruler_rect(rect)), ("v", snip._top_ruler_rect(rect))):
        handles = snip._delete_handles(rect, band)
        assert len(handles) == 1
        _kind, _index, center = handles[0]
        assert strip.contains(center)
    snip.close()


