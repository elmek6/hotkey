"""Fare jesti. AHK'de bu hic test edilemiyordu -- tanima gercek fare
hareketine ve cizim tahtasina bagliydi. Burada girdi delta olarak verilir.

Girdinin delta olmasinin sebebi: jest sirasinda imlec donduruluyor
(dispatch.py hareket olayini yutuyor), yani mutlak konum akmiyor. Her olay yalniz o
darbenin ne kadar ittigini soyluyor.
"""

from cascade.core.gesture import Direction, GestureTracker

F13, F14 = 0x7C, 0x7D


def tracker(step: float = 60.0) -> GestureTracker:
    t = GestureTracker(step_px=step)
    t.register(F13, Direction.UP, "ses+", "ses ac")
    t.register(F13, Direction.DOWN, "ses-")
    t.register(F13, Direction.LEFT, "onceki")
    t.register(F13, Direction.RIGHT, "sonraki")
    return t


# ---- yon algilama ----


def test_esigi_gecmeden_jest_uretilmez():
    t = tracker()
    t.start(F13)
    assert t.move(40, 0) == []  # 40 px, esik 60
    assert not t.fired(F13)


def test_dort_ana_yon():
    beklenen = {
        (0, -100): (Direction.UP, "ses+"),
        (0, 100): (Direction.DOWN, "ses-"),
        (-100, 0): (Direction.LEFT, "onceki"),
        (100, 0): (Direction.RIGHT, "sonraki"),
    }
    for (dx, dy), (direction, action) in beklenen.items():
        t = tracker()
        t.start(F13)
        events = t.move(dx, dy)
        assert len(events) == 1
        assert events[0].direction is direction
        assert events[0].action == action
        assert events[0].steps == 1


def test_kademe_sayisi_mesafeyle_artar():
    """'Sesi kac kademe artiracak' -- geri donus degeri bu."""
    t = tracker()
    t.start(F13)
    assert t.move(0, -180)[0].steps == 3


def test_kucuk_darbeler_birikir():
    """Delta girdisinde her olay kucuk: birikmezse hic adim uretilmezdi."""
    t = tracker()
    t.start(F13)
    for _ in range(5):
        t.move(0, -10)  # toplam 50, henuz esik altinda
    assert t.status(F13).direction is None
    events = t.move(0, -10)  # 60 -> kilitlendi ve 1 adim
    assert len(events) == 1 and events[0].steps == 1


def test_tuketilmeyen_mesafe_sonraki_adima_sayar():
    t = tracker()
    t.start(F13)
    assert t.move(0, -80)[0].steps == 1  # 20 px artiyor
    events = t.move(0, -40)  # 20 + 40 = 60 -> bir adim daha
    assert len(events) == 1 and events[0].steps == 1


def test_eksen_kilitlenir():
    """Kilitlemezsek hafif capraz hareket sirayla iki yon uretir ve ses hem
    acilip hem kisilirdi."""
    t = tracker()
    t.start(F13)
    t.move(0, -100)  # yukari kilitlendi
    assert t.move(200, 0) == []  # saga gitmek artik adim uretmiyor
    assert t.move(0, -100)[0].direction is Direction.UP


def test_geri_hareket_adim_uretmez():
    t = tracker()
    t.start(F13)
    t.move(0, -100)
    assert t.move(0, 100) == []


def test_tanimsiz_yon_kilitlemez():
    """Yalniz yukari tanimliysa saga surmek jesti baslatmamali."""
    t = GestureTracker(step_px=60.0)
    t.register(F13, Direction.UP, "ses+")
    t.start(F13)
    assert t.move(200, 0) == []
    assert t.move(-200, -200)  # yukari hala calisiyor


# ---- geri bildirim ----


def test_status_kilitlenmeden_once_mesafe_verir():
    t = tracker()
    t.start(F13)
    t.move(0, -30)
    status = t.status(F13)
    assert status.direction is None
    assert status.distance == 30
    assert "bekliyor" in status.text


def test_status_kilitten_sonra_yon_mesafe_kademe_verir():
    t = tracker()
    t.start(F13)
    t.move(0, -150)  # 2 adim (120), 30 px artik
    status = t.status(F13)
    assert status.direction is Direction.UP
    assert status.steps == 2
    assert status.distance == 150
    assert "yukari" in status.text and "2 kademe" in status.text
    assert "ses ac" in status.text  # tanimin aciklamasi da yaziyor


def test_status_izlenmeyen_tusta_none():
    assert tracker().status(F13) is None


# ---- yasam dongusu ----


def test_tanimsiz_onek_izlenmez():
    t = tracker()
    t.start(F14)
    assert not t.watching
    assert t.move(0, -200) == []


def test_izleme_bayragi_sicak_yolu_kapatir():
    """watching kapaliyken fare hareketi hic islenmez."""
    t = tracker()
    assert not t.watching
    t.start(F13)
    assert t.watching
    t.stop(F13)
    assert not t.watching


def test_stop_jest_yapildiysa_true_doner():
    """True donunce cagiran ne menu acar ne tusu geri gonderir."""
    t = tracker()
    t.start(F13)
    t.move(0, -100)
    assert t.stop(F13) is True


def test_stop_hareketsiz_birakmada_false_doner():
    t = tracker()
    t.start(F13)
    t.move(10, 0)
    assert t.stop(F13) is False


def test_reset_hayalet_durumu_temizler():
    t = tracker()
    t.start(F13)
    t.reset()
    assert not t.watching
