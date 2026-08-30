"""Dispatcher'in yutma karari: onek tusu, kombo ve geri gonderme.

Dispatcher dogrudan kuruluyor (hook thread'i yok, Qt yok); karar veren
metotlar dogrudan cagriliyor. Test ettigimiz sey tam olarak hook
callback'inin icinde calisan kod.
"""

import queue

from cascade.core.cascade import CascadeMachine
from cascade.core.gesture import GestureTracker
from cascade.core.hotkey import HotkeyTable
from cascade.core.keynames import VK_WHEEL_UP, register_name
from cascade.dispatch import Dispatcher

F13, F14, CARET, ONE = 0x7C, 0x7D, 0xDC, 0x31
LBUTTON, F16 = 0x01, 0x7F


def make_dispatcher() -> Dispatcher:
    register_name(CARET, "Caret")
    table = (
        HotkeyTable()
        .add("F13", "tip:F13", "ipucu")
        .add("F13 & F14", "tip:kombo", "kombo")
        .add("F13 & WheelUp", "send_key:#NumpadAdd", "buyut")
        .add("Caret & 1", "send_key:^v", "yapistir")
        .add("~LButton & F16", "send_key:^v", "tikla + yapistir")
        .prefix("Caret", hold_action="menu.clip", hold_ms=350)
    )
    return Dispatcher(
        machine=CascadeMachine(),
        hotkeys=table,
        # Bos jest izleyicisi: `has()` her tusa False der, yani jest yolu
        # kapali. Jestin kendi testleri tests/test_gesture.py icinde.
        gestures=GestureTracker(),
        actions=queue.Queue(),
        seen=queue.Queue(),
        menu_open=lambda: False,
    )


def feed(box: Dispatcher, vk: int, down: bool, t: float, momentary: bool = False):
    """key_filter / mouse_filter'in ortak yarisi: tracker + tablo."""
    return box._dispatch(vk, down, t, momentary)


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


# ---- `~` gecirgen onek: fare dugmesi ----


def test_gecirgen_onek_yutulmaz():
    """LButton yutulsaydi hicbir yere tiklayamazdik. AHK: ~LButton & F16"""
    box = make_dispatcher()
    assert feed(box, LBUTTON, True, 0.0) == (False, [])


def test_gecirgen_onek_uzerine_kombo_calisir():
    box = make_dispatcher()
    feed(box, LBUTTON, True, 0.0)
    combo = feed(box, F16, True, 0.05)
    assert combo[0] is True  # F16 yutulur, LButton yutulmaz
    assert actions(combo) == ["send_key:^v"]


def test_gecirgen_onek_birakilinca_geri_gonderilmez():
    """Yutmadik ki geri verelim -- tik zaten uygulamaya gitti."""
    box = make_dispatcher()
    feed(box, LBUTTON, True, 0.0)
    feed(box, F16, True, 0.05)
    feed(box, F16, False, 0.06)
    assert feed(box, LBUTTON, False, 0.10) == (False, [])


def test_kombosuz_gecirgen_onek_sessiz_kalir():
    box = make_dispatcher()
    feed(box, LBUTTON, True, 0.0)
    assert feed(box, LBUTTON, False, 0.05) == (False, [])


# ---- basili tutma ----


def test_basili_tutma_esikte_calisir():
    """AHK cascadeCaret: kisa basim `^` yazar, basili tutma menu acar."""
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    assert box.tick(0.2) == []  # esik 350 ms
    assert box.tick(0.4) == [(CARET, "menu.clip")]


def test_basili_tutma_bir_kez_calisir():
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    box.tick(0.4)
    assert box.tick(0.5) == []


def test_basili_tutmadan_sonra_caret_yazilmaz():
    """Menu acildiktan sonra tusu birakinca `^` ekrana dusmemeli."""
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    box.tick(0.4)
    assert actions(feed(box, CARET, False, 0.5)) == []


def test_kombo_yapilinca_basili_tutma_calismaz():
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    feed(box, ONE, True, 0.05)
    assert box.tick(0.6) == []


# ---- tekerlek ----


def test_tekerlek_onek_uzerinde_calisir():
    box = make_dispatcher()
    feed(box, F13, True, 0.0)
    wheel = feed(box, VK_WHEEL_UP, True, 0.05, momentary=True)
    assert wheel[0] is True
    assert actions(wheel) == ["send_key:#NumpadAdd"]


def test_tekerlek_basili_kalmaz():
    """Birakma olayi olmadigi icin elle temizlenmezse sonraki tuslara onek
    olurdu."""
    box = make_dispatcher()
    feed(box, F13, True, 0.0)
    feed(box, VK_WHEEL_UP, True, 0.05, momentary=True)
    assert VK_WHEEL_UP not in box.tracker.held
    assert VK_WHEEL_UP not in box._hk_swallowed


def test_tekerlek_kombosu_onegin_kendi_eylemini_iptal_eder():
    box = make_dispatcher()
    feed(box, F13, True, 0.0)
    feed(box, VK_WHEEL_UP, True, 0.05, momentary=True)
    assert actions(feed(box, F13, False, 0.20)) == []
