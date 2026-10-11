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

    Izgara kumesi (ikonlar + sayac sutunu) ~50 px yer istiyor; `_open_bar`in
    kucuk dikdortgeninde kenara kirpilip resize tutamacinin bolgesine
    dusuyor ve oradaki oncelik kurali onu hakli olarak bloke ediyor.
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


def test_sayac_bandi_esit_boler(qapp):
    """Fusion 360 "repeat": sayi KAC CIZGI oldugunu soyler, kac parca degil."""
    snip = _grid_session(qapp)
    snip._grid_count = 1
    assert snip._even_cuts(0.0, 1.0) == pytest.approx([0.5])
    snip._grid_count = 2
    assert snip._even_cuts(0.0, 1.0) == pytest.approx([1 / 3, 2 / 3])
    snip._grid_count = 3
    assert snip._even_cuts(0.0, 1.0) == pytest.approx([0.25, 0.5, 0.75])
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


def test_ikon_kumesi_kenara_yakin_cizgide_secimin_icinde_kalir(qapp):
    """Kume rect'i tasarsa maske onu kirpiyor (silik/kesik gorunum)."""
    snip = _grid_session(qapp)
    snip._grid_rows = [0.0]
    rect = snip._rect.normalized()
    for _icon, center, half in snip._line_icon_specs("row", 0, rect.center()):
        assert rect.left() <= center.x() - half and center.x() + half <= rect.right()
        assert rect.top() <= center.y() - half and center.y() + half <= rect.bottom()
    snip.close()


def test_imlec_cizgiden_ikonlara_giderken_kume_kapanmaz(qapp):
    """Cizgiyle ikonlar arasindaki olu bant kumeyi dusuruyor, ikonlar
    tiklanamadan kayboluyordu."""
    snip = _grid_session(qapp)
    snip._grid_rows = [0.5]
    rect = snip._rect.normalized()
    x = rect.center().x()
    y = round(rect.top() + 0.5 * rect.height())
    _move(snip, QPoint(x, y))
    assert snip._line_hover == ("row", 0)

    # Cizgiden ikona DIK yuruyus -- imlecin gercekte izledigi yol.
    target = next(c for i, c, _h in snip._line_icon_specs("row", 0, QPoint(x, y)) if i == "up")
    step = -1 if target.y() < y else 1
    for cursor_y in range(y, target.y() + step, step):
        _move(snip, QPoint(x, cursor_y))
        assert snip._line_hover == ("row", 0), f"y={cursor_y} kumeyi dusurdu"
    assert snip._icon_hover == "up"
    snip.close()


def test_sayac_oklari_kumeyi_kapatmaz_ve_bire_kadar_iner(qapp):
    snip = _grid_session(qapp)
    snip._grid_rows = [0.5]
    snip._line_hover = ("row", 0)
    snip._handle_icon_click("inc")
    assert snip._grid_count == 2
    assert snip._line_hover == ("row", 0)  # pes pese basilabilsin diye acik kalir
    snip._handle_icon_click("dec")
    snip._handle_icon_click("dec")
    assert snip._grid_count == 1
    assert not snip._local_splits  # sayac cizgi basmaz, yalnizca sayiyi tutar
    snip.close()


def test_yon_ikonu_sayac_kadar_yerel_kesme_basar(qapp):
    """3 -> hucreyi dortte bir noktalarindan kesen 3 kisa dikey cizgi."""
    snip = _grid_session(qapp)
    snip._grid_rows = [0.5]
    snip._line_hover = ("row", 0)
    snip._line_hover_pos = snip._rect.normalized().center()
    snip._grid_count = 3
    snip._handle_icon_click("up")
    assert [split.pos for split in snip._local_splits] == pytest.approx([0.25, 0.5, 0.75])
    # Uzunluk komsu SATIR bandi: ust kenardan hover'daki cizgiye kadar.
    assert {(s.axis, s.start, s.end) for s in snip._local_splits} == {("v", 0.0, 0.5)}
    snip.close()
