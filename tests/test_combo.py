from keypilot.core.builder import PressType
from keypilot.core.combo import ComboTracker, Thresholds

LCTRL, LSHIFT, RALT = 0xA2, 0xA0, 0xA5
K, A, PAUSE, HOME = 0x4B, 0x41, 0x13, 0x24


def test_modifier_kombosu_metne_donusur():
    c = ComboTracker()
    assert c.key_down(LCTRL, 0.0) is None  # modifier tek basina kombo degil
    assert c.key_down(LSHIFT, 0.01) is None
    chord = c.key_down(K, 0.02)
    assert chord is not None
    assert chord.text == "LShift+LCtrl+K"
    assert chord.prefix is None


def test_sol_sag_modifier_ayri_kombo_uretir():
    sol = ComboTracker()
    sol.key_down(0xA2, 0.0)
    sag = ComboTracker()
    sag.key_down(0xA3, 0.0)
    assert sol.key_down(A, 0.01).text != sag.key_down(A, 0.01).text


def test_prefix_kombosu_ahk_sozdizimine_denk():
    """AHK'deki 'Pause & Home::' karsiligi."""
    c = ComboTracker()
    assert c.key_down(PAUSE, 0.0) is not None  # kendisi de bir chord uretir
    chord = c.key_down(HOME, 0.05)
    assert chord.prefix == PAUSE
    assert chord.text == "Pause & Home"


def test_prefix_olarak_kullanilan_tus_birakilinca_isaretlenir():
    """Prefix'in kendi basimi eyleme donusmemeli: was_prefix bunu soyler."""
    c = ComboTracker()
    c.key_down(PAUSE, 0.0)
    c.key_down(HOME, 0.05)
    c.key_up(HOME, 0.06)
    press = c.key_up(PAUSE, 0.10)
    assert press.was_prefix is True

    c.key_down(PAUSE, 1.0)
    assert c.key_up(PAUSE, 1.05).was_prefix is False


def test_basim_suresi_siniflandirmasi():
    c = ComboTracker(Thresholds(short_ms=200, long_ms=500))
    c.key_down(A, 0.0)
    assert c.key_up(A, 0.100).kind is PressType.SHORT
    c.key_down(A, 0.0)
    assert c.key_up(A, 0.250).kind is PressType.MEDIUM
    c.key_down(A, 0.0)
    assert c.key_up(A, 0.800).kind is PressType.LONG


def test_esik_sinirlari_ahk_ile_ayni():
    """AHK: duration <= short -> kisa, < long -> orta, digeri uzun."""
    c = ComboTracker(Thresholds(short_ms=200, long_ms=500))
    c.key_down(A, 0.0)
    assert c.key_up(A, 0.200).kind is PressType.SHORT  # tam sinir kisa sayilir
    c.key_down(A, 0.0)
    assert c.key_up(A, 0.201).kind is PressType.MEDIUM
    c.key_down(A, 0.0)
    assert c.key_up(A, 0.499).kind is PressType.MEDIUM
    c.key_down(A, 0.0)
    assert c.key_up(A, 0.500).kind is PressType.LONG


def test_otomatik_tekrar_isaretlenir_ve_sure_bozulmaz():
    c = ComboTracker()
    first = c.key_down(A, 0.0)
    again = c.key_down(A, 0.3)
    assert first.repeat is False
    assert again.repeat is True
    assert c.key_up(A, 1.0).ms == 1000.0  # ilk basim ani korunur


def test_gorulmeyen_basimin_birakilmasi_none_doner():
    c = ComboTracker()
    assert c.key_up(A, 1.0) is None


def test_reset_hayalet_tuslari_temizler():
    c = ComboTracker()
    c.key_down(LCTRL, 0.0)
    c.key_down(A, 0.01)
    assert c.held
    c.reset()
    assert c.held == ()
    assert c.key_down(A, 1.0).modifiers == ()
