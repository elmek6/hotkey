from keypilot.core.keynames import MODIFIER_VKS, key_name, vk_from_name


def test_sol_sag_modifier_ayrimi():
    assert key_name(0xA0) == "LShift"
    assert key_name(0xA1) == "RShift"
    assert key_name(0xA2) != key_name(0xA3)
    assert {0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5} <= MODIFIER_VKS


def test_fonksiyon_ve_harf_tuslari():
    assert key_name(0x70) == "F1"
    assert key_name(0x87) == "F24"
    assert key_name(0x41) == "A"
    assert key_name(0x30) == "0"


def test_bilinmeyen_vk_extended_bayragini_tasir():
    assert key_name(0xFF, 0x45, extended=False) == "VKFFSC045"
    assert key_name(0xFF, 0x45, extended=True) == "VKFFSC145"


def test_isimden_vk_cozumleme_buyuk_kucuk_harf_duyarsiz():
    assert vk_from_name("lshift") == 0xA0
    assert vk_from_name("XButton2") == 0x06
    assert vk_from_name("yok-boyle-bir-tus") is None
