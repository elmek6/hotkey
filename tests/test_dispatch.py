"""main.py'nin yutma karari: onek tusu, kombo ve geri gonderme.

Cascade nesnesi kurulmuyor (o hook thread'i baslatirdi); karar veren iki
metot dogrudan cagriliyor. Test ettigimiz sey tam olarak hook callback'inin
icinde calisan kod.
"""

from types import SimpleNamespace

import main
from cascade.core.combo import ComboTracker
from cascade.core.hotkey import HotkeyTable
from cascade.core.keynames import register_name
from cascade.win32.hook import KeyEvent

F13, F14, CARET, ONE = 0x7C, 0x7D, 0xDC, 0x31


def make_dispatcher() -> SimpleNamespace:
    register_name(CARET, "Caret")
    table = (
        HotkeyTable()
        .add("F13", "tip:F13", "ipucu")
        .add("F13 & F14", "tip:kombo", "kombo")
        .add("Caret & 1", "send_key:^v", "yapistir")
    )
    box = SimpleNamespace(
        tracker=ComboTracker(),
        hotkeys=table,
        _hk_swallowed=set(),
        _prefix_used={},
    )
    box._hotkey_up = lambda event: main.Cascade._hotkey_up(box, event)
    return box


def feed(box: SimpleNamespace, vk: int, down: bool, t: float):
    """_key_filter'in kaskad disi yarisi: tracker + tablo."""
    if down:
        chord = box.tracker.key_down(vk, t)
    else:
        box.tracker.key_up(vk, t)
        chord = None
    event = KeyEvent(
        vk=vk, scan=0, down=down, extended=False, injected=False,
        ours=False, time_ms=0, t=t,
    )
    return main.Cascade._hotkey_key(box, event, chord)


def actions(result) -> list[str]:
    return [a.action for a in result[1]]


def test_onek_tusu_basildiginda_yutulur_eylem_ertelenir():
    box = make_dispatcher()
    swallow, acts = feed(box, F13, True, 0.0)
    assert swallow is True
    assert acts == []  # F13'un kendi eylemi daha calismaz


def test_onek_tusu_tek_basina_birakilinca_kendi_eylemi_calisir():
    box = make_dispatcher()
    feed(box, F13, True, 0.0)
    result = feed(box, F13, False, 0.1)
    assert result[0] is True  # keyup da yutulur
    assert actions(result) == ["tip:F13"]


def test_kombo_yapilinca_onegin_kendi_eylemi_calismaz():
    """AHK'de de F13 & F14 sonrasi sade F13 tetiklenmez."""
    box = make_dispatcher()
    feed(box, F13, True, 0.0)
    combo = feed(box, F14, True, 0.05)
    assert combo[0] is True
    assert actions(combo) == ["tip:kombo"]

    feed(box, F14, False, 0.06)
    release = feed(box, F13, False, 0.10)
    assert actions(release) == []


def test_caret_tek_basina_kalirsa_geri_gonderilir():
    """`^` yutuldu ama komboya donusmedi: kullanici `^` yazabilmeli."""
    box = make_dispatcher()
    assert feed(box, CARET, True, 0.0)[0] is True
    result = feed(box, CARET, False, 0.08)
    assert actions(result) == ["send_key:Caret"]


def test_caret_ile_bir_yapistirir_ve_caret_yazilmaz():
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    combo = feed(box, ONE, True, 0.05)
    assert combo[0] is True
    assert actions(combo) == ["send_key:^v"]

    feed(box, ONE, False, 0.06)
    release = feed(box, CARET, False, 0.10)
    assert actions(release) == []  # geri gonderme YOK, `^` ekrana yazilmaz


def test_baglanmamis_tusa_dokunulmaz():
    box = make_dispatcher()
    assert feed(box, 0x41, True, 0.0) == (False, [])  # A tusu


def test_onek_basiliyken_baglanmamis_tus_serbest():
    """`^` basiliyken 2'ye basmak: tanim yok, tus alttaki uygulamaya gider."""
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    assert feed(box, 0x32, True, 0.05) == (False, [])


def test_otomatik_tekrar_eylemi_cogaltmaz():
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    first = feed(box, ONE, True, 0.05)
    repeat = feed(box, ONE, True, 0.10)  # tus basili kaldi
    assert actions(first) == ["send_key:^v"]
    assert actions(repeat) == []
    assert repeat[0] is True  # yutma devam eder
