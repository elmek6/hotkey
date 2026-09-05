"""array_filter.ahk'nin arama mantigi. AHK'de pencere acmadan tek bir
eslesme bile denenemiyordu; ayrildigi icin artik denenebiliyor."""

from keypilot.core.filter import (
    FilterItem,
    FilterMode,
    Query,
    apply,
    wild_to_regex,
)

ITEMS = (
    FilterItem(name="1", content="SELECT id\nFROM users"),
    FilterItem(name="2", content="merhaba Dunya"),
    FilterItem(name="3", content="C:\\DEPO-1\\FIXED"),
)


def names(result):
    return tuple(item.name for item in result.items)


# ---- duz metin ----


def test_bos_arama_listeyi_oldugu_gibi_verir():
    assert apply(ITEMS, Query()).items == ITEMS


def test_metin_modu_icerikte_arar():
    assert names(apply(ITEMS, Query("dunya"))) == ("2",)


def test_metin_modu_varsayilan_olarak_buyuk_kucuk_harf_ayirmaz():
    assert names(apply(ITEMS, Query("DUNYA"))) == ("2",)


def test_case_kutusu_isaretliyken_ayirir():
    assert names(apply(ITEMS, Query("DUNYA", case_sensitive=True))) == ()
    assert names(apply(ITEMS, Query("Dunya", case_sensitive=True))) == ("2",)


def test_isimde_de_arar():
    """AHK: InStr(slot["name"], ...) || InStr(slot["content"], ...)"""
    assert names(apply(ITEMS, Query("3"))) == ("3",)


# ---- joker ----


def test_joker_satir_sonunu_asar():
    """AHK'de `s` (DOTALL) bayragi eklenmesinin sebebi: pano kayitlari cok
    satirli, onsuz SELECT*FROM eslesmezdi."""
    query = Query("SELECT*FROM", mode=FilterMode.WILD)
    assert names(apply(ITEMS, query)) == ("1",)


def test_joker_soru_isareti_tek_karakter():
    query = Query("Dun?a", mode=FilterMode.WILD)
    assert names(apply(ITEMS, query)) == ("2",)


def test_joker_modunda_nokta_joker_degildir():
    """Kacirma sirasi ters olsaydi kullanicinin yazdigi `.` de joker olurdu."""
    assert wild_to_regex("a.c") == r"a\.c"
    assert wild_to_regex("a*c") == r"a.*c"
    assert names(apply(ITEMS, Query("m.rhaba", mode=FilterMode.WILD))) == ()


def test_joker_cipa_koymaz():
    """Alt-dize semantigi: desen metnin ortasinda da eslesir."""
    assert names(apply(ITEMS, Query("id*users", mode=FilterMode.WILD))) == ("1",)


# ---- regexp ----


def test_regexp_modu_deseni_aynen_alir():
    query = Query(r"^SELECT", mode=FilterMode.REGEX)
    assert names(apply(ITEMS, query)) == ("1",)


def test_regexp_modunda_dotall_eklenmez():
    """Bayragi kullanici kendi yazar -- AHK'deki karar."""
    assert names(apply(ITEMS, Query("id.FROM", mode=FilterMode.REGEX))) == ()
    assert names(apply(ITEMS, Query("(?s)id.FROM", mode=FilterMode.REGEX))) == ("1",)


def test_bozuk_desen_sessizce_sifir_donmez():
    """Baslikta '(desen?)' yazabilmek icin isaretlenir: 'kayit mi yok, desen
    mi bozuk' ayirt edilebilsin."""
    result = apply(ITEMS, Query("[unclosed", mode=FilterMode.REGEX))
    assert result.items == ()
    assert result.pattern_error is True


def test_gecerli_arama_hata_bayragi_kaldirmaz():
    assert apply(ITEMS, Query("dunya")).pattern_error is False
