"""Radyal menu: model (core/radial.py) ve pencere (ui/radial_menu.py).

Pencere gosterilmeden suruluyor: `track(dx, dy)` fare hareketinin, `click()`
sol tikin yerine. Eylemler sahte `run` / `show_menu` ile toplaniyor;
imlec tasima (`QCursor.setPos`) kaydediliyor.
"""

import pytest

from keypilot.core.hot_vectors import Direction
from keypilot.core.radial import (
    CLOSE_R,
    EDGE_R,
    HOLE_R,
    INNER_R,
    OUTER_R,
    STEP_PX,
    Axis,
    AxisLock,
    RadialItem,
    RadialSpec,
    Zone,
    fit_center,
    hit,
    item_at,
)

MID_INNER = (HOLE_R + INNER_R) / 2
MID_OUTER = (INNER_R + OUTER_R) / 2


# ---- geometri ----


def test_delik_bosluk_ve_pembe():
    assert hit(0, 0).zone is Zone.HOLE
    assert hit(0, -(OUTER_R + 2)).zone is Zone.GAP
    assert hit(CLOSE_R, 0).zone is Zone.CLOSE
    assert hit(0, EDGE_R + 50).zone is Zone.CLOSE


@pytest.mark.parametrize(
    ("dx", "dy", "direction"),
    [
        (0, -MID_INNER, Direction.UP),
        (MID_INNER, 0, Direction.RIGHT),
        (0, MID_INNER, Direction.DOWN),
        (-MID_INNER, 0, Direction.LEFT),
        (-40, -60, Direction.UP),
    ],
)
def test_ic_halka_dort_yon(dx, dy, direction):
    where = hit(dx, dy)
    assert where.zone is Zone.DIRECTION
    assert where.direction is direction


@pytest.mark.parametrize(
    ("dx", "dy", "index"),
    [
        (0, -MID_OUTER, 0),  # 1 ustte
        (MID_OUTER, 0, 3),  # 4 sagda
        (0, MID_OUTER, 6),  # 7 altta
        (-MID_OUTER, 0, 9),  # 10 solda
        (-10, -MID_OUTER, 0),  # 1 dilimi ortanin iki yanina tasiyor
    ],
)
def test_dis_halka_saat_gibi(dx, dy, index):
    where = hit(dx, dy)
    assert where.zone is Zone.OUTER
    assert where.index == index


def test_item_at():
    ust = RadialItem("ust", "a")
    bir = RadialItem("1", "b")
    spec = RadialSpec({Direction.UP: ust}, (bir,))
    assert item_at(spec, hit(0, -MID_INNER)) is ust
    assert item_at(spec, hit(0, -MID_OUTER)) is bir
    assert item_at(spec, hit(MID_OUTER, 0)) is None
    assert item_at(spec, hit(0, 0)) is None


def test_kilit_adimlari_ve_kalan():
    lock = AxisLock(Axis.VERTICAL, anchor=0)
    assert lock.feed(-(STEP_PX - 1)) == 0
    assert lock.feed(-1) == 1  # birikim bir adima tamamlandi
    assert lock.feed(STEP_PX * 2) == -2
    assert lock.feed(0) == 0


def test_menu_ekrana_sigar():
    area = (0, 0, 1920, 1080)
    assert fit_center(500, 500, area) == (500, 500)
    assert fit_center(10, 1075, area) == (EDGE_R, 1080 - EDGE_R)


# ---- pencere ----

SES = RadialItem("Volume", lock=Axis.VERTICAL, step_up="up", step_down="down")
SISTEM = RadialItem("System", menu=(("x", "y"),))
UST = RadialItem("Paste", "paste")
SLOT1 = RadialItem("1", "slot1", hint="Slot 1")


@pytest.fixture
def menu(qapp, monkeypatch):
    from PySide6.QtGui import QCursor

    from keypilot.ui.radial_menu import RadialMenu

    calisan: list[str] = []
    menuler: list[tuple] = []
    tasima: list = []
    monkeypatch.setattr(QCursor, "setPos", staticmethod(lambda *a: tasima.append(a)))
    spec = RadialSpec({Direction.UP: UST, Direction.RIGHT: SISTEM, Direction.LEFT: SES}, (SLOT1,))
    pencere = RadialMenu(spec, calisan.append, menuler.append)
    pencere.show()
    pencere.calisan, pencere.menuler, pencere.tasima = calisan, menuler, tasima
    yield pencere
    pencere.close()


def _bekle(qapp):
    qapp.processEvents()


def test_ogeye_tiklayinca_calisir_ve_kapanir(menu, qapp):
    menu.track(0, -MID_OUTER)
    menu.click()
    _bekle(qapp)
    assert menu.calisan == ["slot1"]
    assert not menu.isVisible()


def test_alt_menulu_yon_klasik_menuyu_acar(menu, qapp):
    menu.track(MID_INNER, 0)
    menu.click()
    _bekle(qapp)
    assert menu.menuler == [SISTEM.menu]
    assert menu.calisan == []
    assert not menu.isVisible()


def test_delige_tiklamak_bir_sey_yapmaz(menu, qapp):
    menu.track(0, 0)
    menu.click()
    _bekle(qapp)
    assert menu.isVisible()
    assert menu.calisan == []


def test_pembeye_degince_kapanir(menu, qapp):
    menu.track(0, -MID_OUTER)
    menu.track(0, -(CLOSE_R + 3))
    _bekle(qapp)
    assert not menu.isVisible()
    assert menu.calisan == []


def test_kilitli_yon_dikey_hareketi_adima_cevirir(menu, qapp):
    menu.track(-MID_INNER, 0)
    assert menu.locked
    menu.track(-MID_INNER, -STEP_PX * 2)  # yukari iki adim
    menu.track(-MID_INNER, STEP_PX)  # asagi bir adim
    assert menu.calisan == ["up", "up", "down"]
    assert menu.tasima  # imlec kilit noktasina geri tasindi
    assert menu.isVisible()


def test_kilit_yatayda_serbest_ve_sektorden_cikinca_biter(menu, qapp):
    menu.track(-MID_INNER, 0)
    menu.track(-MID_INNER + 20, 0)
    assert menu.locked
    menu.track(0, 0)  # deligin icine
    assert not menu.locked
    menu.track(0, -STEP_PX * 3)
    assert menu.calisan == []


def test_kilitli_yone_tiklamak_yalniz_kapatir(menu, qapp):
    menu.track(-MID_INNER, 0)
    menu.click()
    _bekle(qapp)
    assert not menu.isVisible()
    assert menu.calisan == []
    assert not menu.locked


# ---- icerik ve baglanti ----


def test_deneme_icerigi():
    from keypilot import keymap
    from keypilot.commands import Cmd

    spec = keymap.RADIAL_MENU
    assert set(spec.directions) == set(Direction)
    assert spec.directions[Direction.LEFT].lock is Axis.VERTICAL
    assert len(spec.outer) == 12
    assert spec.outer[0].action == Cmd.Slot.PASTE_GROUP("/1")
    assert spec.outer[9].label == "0"
    assert Cmd.Menu.RADIAL == "menu.radial"
