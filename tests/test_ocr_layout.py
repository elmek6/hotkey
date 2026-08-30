"""OCR ciktisinin dizilmesi. AHK'de bu mantik hic test edilemiyordu --
gercek ekran ve gercek motor gerekiyordu. Burada girdi sadece kelime
kutulari oldugu icin motorsuz test edilebiliyor.
"""

from cascade.core.ocr_layout import (
    LayoutMode,
    Word,
    column_index,
    column_splits,
    escape_separator,
    group_rows,
    layout,
    separator_from_text,
    separator_label,
    unescape_separator,
)


def w(text: str, x: float, y: float, width: float = 40, height: float = 20) -> Word:
    return Word(text=text, x=x, y=y, w=width, h=height)


#: Iki kolonlu tablo: solda ad, sagda miktar. Arada 200 px bosluk.
TABLE_WORDS = [
    w("Elma", 20, 20), w("12", 300, 20), w("adet", 345, 20),
    w("Armut", 20, 60), w("7", 300, 60), w("adet", 345, 60),
    w("Kiraz", 20, 100), w("45", 300, 100), w("adet", 345, 100),
]
TABLE_LINES = ["Elma", "Armut", "Kiraz", "12 adet", "7 adet", "45 adet"]


def test_duz_metin_motorun_satirlarini_verir():
    result = layout(TABLE_WORDS, TABLE_LINES, LayoutMode.PLAIN)
    assert result.text == "\n".join(TABLE_LINES)
    assert result.columns == 1


def test_tablo_bicimi_satirlari_ayracla_birlestirir():
    """Duz metinde karisan ad/miktar ciftleri tabloda dogru eslesir."""
    result = layout(TABLE_WORDS, TABLE_LINES, LayoutMode.TABLE, separator="\t")
    assert result.text == "Elma\t12 adet\nArmut\t7 adet\nKiraz\t45 adet"
    assert result.columns == 2
    assert result.rows == 3


def test_ayrac_degisince_cikti_degisir():
    result = layout(TABLE_WORDS, TABLE_LINES, LayoutMode.TABLE, separator=",")
    assert result.text.splitlines()[0] == "Elma,12 adet"


def test_kolon_bicimi_kolonlari_alt_alta_yazar():
    """Iki sutunlu makale duzeni: once sol kolon, sonra sag kolon."""
    result = layout(TABLE_WORDS, TABLE_LINES, LayoutMode.COLUMNS)
    assert result.text == "Elma\nArmut\nKiraz\n\n12 adet\n7 adet\n45 adet"


def test_tek_kolonlu_metin_duz_metne_duser():
    words = [w("bir", 10, 10), w("iki", 55, 10), w("uc", 100, 10)]
    result = layout(words, ["bir iki uc"], LayoutMode.TABLE)
    assert result.text == "bir iki uc"
    assert "kolon ayraci yok" in result.info


def test_kolon_esigi_elle_verilince_kullanilir():
    """Buyuk esik kolonlari birlestirir: 200 px bosluk 500 esigini gecemez."""
    result = layout(TABLE_WORDS, TABLE_LINES, LayoutMode.TABLE, gutter=500)
    assert "kolon ayraci yok" in result.info


def test_kucuk_esik_kelime_aralarini_kolon_sanir():
    result = layout(TABLE_WORDS, TABLE_LINES, LayoutMode.TABLE, gutter=5)
    assert result.columns > 2  # kelime aralari da bolme noktasi oldu


def test_bos_kelime_listesi_duz_metne_duser():
    result = layout([], ["bir seyler"], LayoutMode.TABLE)
    assert result.text == "bir seyler"
    assert result.info == "kelime yok"


# ---- yardimcilar ----


def test_kolon_bolme_noktasi_boslugun_ortasi():
    words = [w("a", 0, 0, width=50), w("b", 250, 0, width=50)]
    splits = column_splits(words, gutter_min=100)
    assert splits == [150.0]  # 50 ile 250 arasi, ortasi


def test_ust_uste_binen_kutular_tek_kolon_sayilir():
    words = [w("a", 0, 0, width=100), w("b", 50, 0, width=100)]
    assert column_splits(words, gutter_min=10) == []


def test_satir_gruplama_y_merkezine_gore():
    words = [w("a", 0, 0), w("b", 60, 3), w("c", 0, 100)]
    rows = group_rows(words, row_eps=10)
    assert [[word.text for word in row] for row in rows] == [["a", "b"], ["c"]]


def test_satirdaki_kelimeler_soldan_saga_sirali():
    rows = group_rows([w("sag", 200, 0), w("sol", 10, 0)], row_eps=10)
    assert [word.text for word in rows[0]] == ["sol", "sag"]


def test_kolon_indeksi():
    assert column_index(10, [100, 200]) == 0
    assert column_index(150, [100, 200]) == 1
    assert column_index(250, [100, 200]) == 2


# ---- ayrac kacislari ----


def test_gorunmez_karakterler_yazilabilir_hale_gelir():
    assert escape_separator("\t") == "\\t"
    assert unescape_separator("\\t") == "\t"
    assert unescape_separator("\\s") == " "


def test_ters_boluler_kacista_bozulmaz():
    """`\\\\t` TAB olmamali -- AHK'deki ayni tuzak."""
    assert unescape_separator("\\\\t") == "\\t"


def test_ayrac_etiketi_ve_geri_cevrimi():
    assert separator_label("\t") == "Tab"
    assert separator_from_text("Tab") == "\t"
    assert separator_from_text(",  Virgul") == ","
    # Listede olmayan ayrac: etiketten geri okunabilmeli
    label = separator_label(" ~ ")
    assert separator_from_text(label) == " ~ "
