"""Fare jesti. AHK'de bu hic test edilemiyordu -- tanima gercek fare
hareketine ve cizim tahtasina bagliydi. Burada koordinat disaridan verilir."""

from cascade.core.gesture import Direction, GestureTracker

F13, F14 = 0x7C, 0x7D


def tracker(step: float = 60.0) -> GestureTracker:
    t = GestureTracker(step_px=step)
    t.register(F13, Direction.UP, "ses+")
    t.register(F13, Direction.DOWN, "ses-")
    t.register(F13, Direction.LEFT, "onceki")
    t.register(F13, Direction.RIGHT, "sonraki")
    return t


# ---- yon algilama ----


def test_esigi_gecmeden_jest_uretilmez():
    t = tracker()
    t.start(F13, 500, 500)
    assert t.move(540, 500) == []  # 40 px, esik 60
    assert not t.fired(F13)


def test_dort_ana_yon():
    beklenen = {
        (500, 400): (Direction.UP, "ses+"),
        (500, 600): (Direction.DOWN, "ses-"),
        (400, 500): (Direction.LEFT, "onceki"),
        (600, 500): (Direction.RIGHT, "sonraki"),
    }
    for (x, y), (direction, action) in beklenen.items():
        t = tracker()
        t.start(F13, 500, 500)
        events = t.move(x, y)
        assert len(events) == 1
        assert events[0].direction is direction
        assert events[0].action == action
        assert events[0].steps == 1


def test_kademe_sayisi_mesafeyle_artar():
    """'Sesi kac kademe artiracak' -- geri donus degeri bu."""
    t = tracker()
    t.start(F13, 500, 500)
    events = t.move(500, 500 - 180)  # 3 adim
    assert events[0].steps == 3


def test_ard_arda_hareket_kaldigi_yerden_sayar():
    """Capa tuketilen kadar ileri tasiniyor: yavas hareket de adim uretir."""
    t = tracker()
    t.start(F13, 500, 500)
    assert t.move(500, 460) == []  # 40 px -- henuz yok
    events = t.move(500, 420)  # toplam 80 px -> 1 adim
    assert len(events) == 1 and events[0].steps == 1
    events = t.move(500, 350)  # kalan 20 + 70 = 90 -> 1 adim daha
    assert len(events) == 1 and events[0].steps == 1


def test_eksen_kilitlenir():
    """Kilitlemezsek hafif capraz hareket sirayla iki yon uretir ve ses hem
    acilip hem kisilirdi."""
    t = tracker()
    t.start(F13, 500, 500)
    t.move(500, 400)  # yukari kilitlendi
    assert t.move(700, 400) == []  # saga gitmek artik adim uretmiyor
    events = t.move(700, 300)
    assert events[0].direction is Direction.UP


def test_geri_hareket_adim_uretmez():
    t = tracker()
    t.start(F13, 500, 500)
    t.move(500, 400)
    assert t.move(500, 500) == []


def test_tanimsiz_yon_kilitlemez():
    """Yalniz yukari tanimliysa saga surmek jesti baslatmamali."""
    t = GestureTracker(step_px=60.0)
    t.register(F13, Direction.UP, "ses+")
    t.start(F13, 500, 500)
    assert t.move(700, 500) == []
    assert t.move(500, 300)  # yukari hala calisiyor


# ---- yasam dongusu ----


def test_tanimsiz_onek_izlenmez():
    t = tracker()
    t.start(F14, 500, 500)
    assert not t.watching
    assert t.move(500, 300) == []


def test_izleme_bayragi_sicak_yolu_kapatir():
    """watching kapaliyken fare hareketi hic islenmez."""
    t = tracker()
    assert not t.watching
    t.start(F13, 500, 500)
    assert t.watching
    t.stop(F13)
    assert not t.watching


def test_stop_jest_yapildiysa_true_doner():
    """True donunce cagiran ne menu acar ne tusu geri gonderir."""
    t = tracker()
    t.start(F13, 500, 500)
    t.move(500, 400)
    assert t.stop(F13) is True


def test_stop_hareketsiz_birakmada_false_doner():
    t = tracker()
    t.start(F13, 500, 500)
    t.move(510, 500)
    assert t.stop(F13) is False


def test_reset_hayalet_durumu_temizler():
    t = tracker()
    t.start(F13, 500, 500)
    t.reset()
    assert not t.watching
