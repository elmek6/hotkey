"""Onek tusu durum makinesi. AHK'de bu mantik bloke eden KeyWait'in
icindeydi ve hic denenemiyordu."""

from cascade.core.prefix import Outcome, PrefixDef, PrefixTracker

CARET, F13, LBUTTON = 0xDC, 0x7C, 0x01


def make() -> PrefixTracker:
    return PrefixTracker(
        {
            CARET: PrefixDef(CARET, hold_action="menu.clip", hold_ms=350),
            F13: PrefixDef(F13),  # basili tutmasi yok
            LBUTTON: PrefixDef(LBUTTON, passthrough=True),
        }
    )


# ---- yutma ----


def test_normal_onek_yutulur():
    assert make().key_down(CARET, 0.0) is True


def test_gecirgen_onek_yutulmaz():
    """AHK `~`: LButton yutulursa hicbir yere tiklanamaz."""
    assert make().key_down(LBUTTON, 0.0) is False


def test_taninmayan_tus_yutulmaz():
    assert make().key_down(0x41, 0.0) is False


# ---- kisa basim / kombo ----


def test_kombosuz_kisa_basim_tap_doner():
    tracker = make()
    tracker.key_down(CARET, 0.0)
    assert tracker.key_up(CARET, 0.1) is Outcome.TAP


def test_kombo_yapilinca_tap_olmaz():
    tracker = make()
    tracker.key_down(CARET, 0.0)
    tracker.combo_used(CARET)
    assert tracker.key_up(CARET, 0.1) is Outcome.NOTHING


def test_gorulmemis_birakma_sessiz():
    """Baska proses keydown'i yutmus olabilir; hayalet TAP uretmemeli."""
    assert make().key_up(CARET, 0.1) is Outcome.NOTHING


# ---- basili tutma ----
#
# Esik BIRAKMA aninda olculuyor, tus basiliyken degil (eski `tick` gitti).
# Gerekcesi core/prefix.py `key_up`: jest yapmak esigi kolayca gectigi icin
# basiliyken tetiklenen menu jestin ortasinda aciliyordu.


def test_esik_gecilince_hold_doner():
    tracker = make()
    tracker.key_down(CARET, 0.0)
    assert tracker.key_up(CARET, 0.35) is Outcome.HOLD


def test_esik_altinda_tap_doner():
    tracker = make()
    tracker.key_down(CARET, 0.0)
    assert tracker.key_up(CARET, 0.2) is Outcome.TAP


def test_hold_sonrasi_ikinci_birakma_sessiz():
    """Basim tuketildi: ayni tusun hayalet birakmasi tekrar HOLD uretmemeli."""
    tracker = make()
    tracker.key_down(CARET, 0.0)
    assert tracker.key_up(CARET, 0.4) is Outcome.HOLD
    assert tracker.key_up(CARET, 0.9) is Outcome.NOTHING


def test_hold_tanimsizsa_uzun_basim_da_tap():
    """F13'un hold_action'i yok: ne kadar tutulursa tutulsun TAP."""
    tracker = make()
    tracker.key_down(F13, 0.0)
    assert tracker.key_up(F13, 5.1) is Outcome.TAP


def test_kombo_yapilmissa_hold_calismaz():
    tracker = make()
    tracker.key_down(CARET, 0.0)
    tracker.combo_used(CARET)
    assert tracker.key_up(CARET, 1.0) is Outcome.NOTHING


def test_otomatik_tekrar_sureyi_sifirlamaz():
    """Basili tutulan tus keydown'i tekrarlar; esik ILK basimdan olculur."""
    tracker = make()
    tracker.key_down(CARET, 0.0)
    tracker.key_down(CARET, 0.2)  # otomatik tekrar
    assert tracker.key_up(CARET, 0.36) is Outcome.HOLD


# ---- temizlik ----


def test_reset_hayalet_tusu_temizler():
    tracker = make()
    tracker.key_down(CARET, 0.0)
    tracker.reset()
    assert tracker.held == ()
    assert tracker.key_up(CARET, 9.0) is Outcome.NOTHING
