"""script_state.ahk'nin BusyModule portunun testleri.

ScriptInfo / MouseState / ClipboardMode testleri devre disi -- o siniflar da
state.py'nin altinda yorumda duruyor.
"""

from cascade.core.state import Busy, BusyLevel


def test_busy_seviyeleri():
    busy = Busy()
    assert busy.is_free()
    busy.set_active("kaskad")
    assert busy.is_active() and busy.caller == "kaskad"
    busy.set_combo("kombo")
    assert busy.is_combo() and busy.level == BusyLevel.COMBO
    busy.set_free()
    assert busy.is_free() and busy.caller == ""


def test_claim_serbestken_alir_mesgulken_almaz():
    """AHK'de `isFree()` sonra `setActive()` iki adimdi; burada tek adim."""
    busy = Busy()
    assert busy.claim("ilk") is True
    assert busy.claim("ikinci") is False
    assert busy.caller == "ilk"
    busy.set_free()
    assert busy.claim("ucuncu") is True
