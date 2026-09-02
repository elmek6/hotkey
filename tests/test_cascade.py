"""Kaskad durum makinesi testleri.

AHK'de imkansiz olan sey: zamani uydurup basim turlerini dogrulamak.
Burada gercek klavye de, Windows da, bekleme de yok.
"""

import pytest

from cascade.core.builder import KeyBuilder, PressType, press_type
from cascade.core.cascade import (
    Beep,
    CascadeMachine,
    CloseMenu,
    OpenMenu,
    Phase,
    Run,
)

TAB = 0x09
ESCAPE = 0x1B
KEY_1, KEY_2, KEY_X = 0x31, 0x32, 0x58


def build_tab() -> CascadeMachine:
    """AHK cascadeTab() ile ayni sekil: kisa basim Tab yollar, orta basim menu acar."""
    definition = (
        KeyBuilder(TAB, short=350)
        .main_key(PressType.SHORT, "send_key:Tab")
        .main_key(PressType.MEDIUM, "menu:slots")
        .set_exit_on_press_type(PressType.SHORT)
        .combo(KEY_1, "Slot 1", "slot:1")
        .combo(KEY_2, "Slot 2", "slot:2")
        .named("Tab")
        .build()
    )
    return CascadeMachine({definition.key: definition})


def actions_of(result) -> list:
    return result[1]


# ---- basim turu siniflandirmasi (AHK getPressType birebir) ----


def test_press_type_iki_seviye():
    assert press_type(100, 350, None) == PressType.SHORT
    assert press_type(350, 350, None) == PressType.SHORT
    assert press_type(351, 350, None) == PressType.MEDIUM


def test_press_type_uc_seviye():
    assert press_type(350, 350, 800) == PressType.SHORT
    assert press_type(500, 350, 800) == PressType.MEDIUM
    assert press_type(799, 350, 800) == PressType.MEDIUM
    assert press_type(800, 350, 800) == PressType.LONG


# ---- temel akis ----


def test_kisa_basim_ana_eylemi_calistirir_ve_menu_acmaz():
    m = build_tab()
    swallow, acts = m.feed_key(TAB, True, 0.0)
    assert swallow is True
    assert acts == []

    swallow, acts = m.feed_key(TAB, False, 0.100)
    assert swallow is True
    assert acts == [Run("send_key:Tab", press=PressType.SHORT, key=TAB)]
    assert m.phase == Phase.IDLE


def test_orta_basim_menuyu_acar():
    m = build_tab()
    m.feed_key(TAB, True, 0.0)
    _, acts = m.feed_key(TAB, False, 0.500)

    assert acts[0] == Run("menu:slots", press=PressType.MEDIUM, key=TAB)
    assert isinstance(acts[1], OpenMenu)
    assert acts[1].items == (("1", "Slot 1"), ("2", "Slot 2"))
    assert m.phase == Phase.MENU


def test_menude_kombo_tusu_eylemi_calistirir_ve_kapatir():
    m = build_tab()
    m.feed_key(TAB, True, 0.0)
    m.feed_key(TAB, False, 0.500)

    swallow, acts = m.feed_key(KEY_2, True, 0.60)
    assert swallow is True
    assert isinstance(acts[0], CloseMenu)
    assert acts[1] == Run("slot:2", key=KEY_2, desc="Slot 2")
    assert m.phase == Phase.IDLE


def test_menude_escape_iptal_eder():
    m = build_tab()
    m.feed_key(TAB, True, 0.0)
    m.feed_key(TAB, False, 0.500)

    swallow, acts = m.feed_key(ESCAPE, True, 0.60)
    assert swallow is True
    assert acts == [CloseMenu()]
    assert m.phase == Phase.IDLE


def test_menude_tanimsiz_tus_biplar_ve_kapatir():
    """AHK: SoundBeep(1000, 100) sonra return."""
    m = build_tab()
    m.feed_key(TAB, True, 0.0)
    m.feed_key(TAB, False, 0.500)

    swallow, acts = m.feed_key(KEY_X, True, 0.60)
    assert swallow is True
    assert acts[0] == Beep(1000, 100)
    assert isinstance(acts[1], CloseMenu)
    assert m.phase == Phase.IDLE


def test_menu_zaman_asiminda_kapanir():
    m = build_tab()
    m.feed_key(TAB, True, 0.0)
    m.feed_key(TAB, False, 0.500)

    assert m.tick(10.0) == []  # 30 sn dolmadi
    assert m.tick(31.0) == [CloseMenu()]
    assert m.phase == Phase.IDLE


# ---- ana tus basiliyken yanci tus ----


def test_ana_tus_basiliyken_kombo_calisir_ve_ana_eylem_iptal_olur():
    """AHK: _checkCombo calisirsa mainKey hic cagrilmaz."""
    m = build_tab()
    m.feed_key(TAB, True, 0.0)

    swallow, acts = m.feed_key(KEY_1, True, 0.05)
    assert swallow is True
    assert acts == [Run("slot:1", key=KEY_1, desc="Slot 1")]

    swallow, acts = m.feed_key(TAB, False, 0.20)
    assert acts == []  # ana eylem calismadi
    assert m.phase == Phase.IDLE


def test_ana_tus_basiliyken_ilgisiz_tus_normal_akar():
    m = build_tab()
    m.feed_key(TAB, True, 0.0)
    swallow, acts = m.feed_key(KEY_X, True, 0.05)
    assert swallow is False  # yutulmaz, uygulamaya gider
    assert acts == []


def test_yutulan_tusun_birakilmasi_da_yutulur():
    """Down yutulup up birakilirsa tus sistemde 'basili kalir'. Klasik port hatasi."""
    m = build_tab()
    m.feed_key(TAB, True, 0.0)
    swallow_down, _ = m.feed_key(KEY_1, True, 0.05)
    swallow_up, _ = m.feed_key(KEY_1, False, 0.06)
    assert swallow_down is True
    assert swallow_up is True


def test_otomatik_tekrar_sureyi_bozmaz():
    m = build_tab()
    m.feed_key(TAB, True, 0.0)
    for tick in (0.05, 0.10, 0.15):
        swallow, acts = m.feed_key(TAB, True, tick)  # klavye tekrari
        assert swallow is True
        assert acts == []
    _, acts = m.feed_key(TAB, False, 0.200)
    assert acts == [Run("send_key:Tab", press=PressType.SHORT, key=TAB)]


# ---- bip esikleri ----


def test_uc_seviyede_bip_esikleri_bir_kez_calar():
    definition = (
        KeyBuilder(TAB, short=350, long=800)
        .main_key(PressType.SHORT, "send_key:Tab")
        .build()
    )
    m = CascadeMachine({TAB: definition})
    m.feed_key(TAB, True, 0.0)

    assert m.tick(0.20) == []
    assert m.tick(0.40) == [Beep(800, 50)]
    assert m.tick(0.50) == []  # ikinci kez calmaz
    assert m.tick(0.90) == [Beep(600, 50)]
    assert m.tick(1.20) == []


def test_iki_seviyede_bip_yok():
    m = build_tab()  # long_ms yok
    m.feed_key(TAB, True, 0.0)
    assert m.tick(5.0) == []


# ---- tek kaskad garantisi ----


def test_bir_kaskad_calisirken_ikincisi_baslamaz():
    """AHK'de bunu global `State.Busy` yapiyordu; burada `_phase` yapiyor:
    HELD iken baska bir kaskadin ana tusu tanimsiz tus gibi akip gider."""
    other = KeyBuilder(KEY_X, short=350).main_key(PressType.SHORT, "x").build()
    tab = KeyBuilder(TAB, short=350).main_key(PressType.SHORT, "tab").build()
    m = CascadeMachine({TAB: tab, KEY_X: other})

    assert m.feed_key(TAB, True, 0.0)[0] is True
    assert m.phase == Phase.HELD

    swallow, acts = m.feed_key(KEY_X, True, 1.0)
    assert swallow is False
    assert acts == []
    assert m.phase == Phase.HELD  # TAB kaskadi bozulmadi


def test_reset_durumu_temizler():
    m = build_tab()
    m.feed_key(TAB, True, 0.0)
    assert m.phase == Phase.HELD
    m.reset()
    assert m.phase == Phase.IDLE


# ---- tanimsiz tuslar ----


def test_tanimsiz_tus_hic_dokunulmaz():
    m = build_tab()
    assert m.feed_key(KEY_X, True, 0.0) == (False, [])
    assert m.feed_key(KEY_X, False, 0.1) == (False, [])
    assert m.phase == Phase.IDLE


def test_bilinmeyen_tus_adi_hata_verir():
    with pytest.raises(ValueError):
        KeyBuilder("boyle-bir-tus-yok")
