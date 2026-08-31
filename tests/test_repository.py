"""Kod parcasi deposunun METIN bicimi (cascade/repository.py).

Bicimin tek isi elle okunup elle duzenlenebilmek; bu yuzden testlerin agirligi
"bozuk/garip girdi ne oluyor" tarafinda. AHK tarafinda bu katman hic test
edilemiyordu, dosya okuma GUI'nin icindeydi.
"""

from cascade.repository import Item, Repository, dump, parse

ORNEK = """===
uuid: 05/11/2025_00:45_1692013593
title: doorbell
category: iot
tags: tuya, zigbee
---
tuya
two way audio
===
uuid: 09/11/2025_00:10_2035557495
title: zigbeeeee
---
IR + RF learn 433 833 2,4
BT
"""


# ---- okuma ----


def test_iki_kayit_okunur():
    items = parse(ORNEK)
    assert [item.title for item in items] == ["doorbell", "zigbeeeee"]


def test_alanlar_dogru_ayrisir():
    item = parse(ORNEK)[0]
    assert item.uuid == "05/11/2025_00:45_1692013593"
    assert item.category == "iot"
    assert item.tags == ["tuya", "zigbee"]
    assert item.text == "tuya\ntwo way audio"


def test_bos_alanlar_bos_kalir():
    item = parse(ORNEK)[1]
    assert item.category == ""
    assert item.tags == []


def test_uuid_yoksa_uretilir():
    item = parse("===\ntitle: x\n---\ngovde\n")[0]
    assert item.uuid  # bos birakilmaz


def test_bos_metin_bos_liste():
    assert parse("") == []
    assert parse("\n\n") == []


# ---- gidis-donus ----


def test_yaz_oku_ayni_kalir():
    once = parse(ORNEK)
    sonra = parse(dump(once))
    assert [(i.uuid, i.title, i.category, i.tags, i.text) for i in once] == [
        (i.uuid, i.title, i.category, i.tags, i.text) for i in sonra
    ]


def test_govdedeki_ayrac_kaydi_bolmez():
    """Asil sebep bu: govde bir KOD PARCASI, icinde `---` ve `===` gecebilir.
    Ayrac govdeden ayirt edilemezse iki kayit sessizce birlesir."""
    item = Item(title="diff", text="ustu\n---\n===\nalti")
    okunan = parse(dump([item]))
    assert len(okunan) == 1
    assert okunan[0].text == "ustu\n---\n===\nalti"


def test_cok_satirli_govde_korunur():
    item = Item(title="kod", text="satir1\n\nsatir3\n")
    assert parse(dump([item]))[0].text == "satir1\n\nsatir3"


def test_govdesiz_kayit_gecerli():
    items = parse("===\ntitle: bos\n---\n")
    assert len(items) == 1 and items[0].text == ""


def test_bilinmeyen_anahtar_korunur():
    """Bir surum, tanimini bilmedigi alani SILMEMELI."""
    items = parse("===\ntitle: x\nyeni_alan: deger\n---\ngovde\n")
    assert items[0].extra == {"yeni_alan": "deger"}
    assert "yeni_alan: deger" in dump(items)


# ---- bozuk girdi ----


def test_basliksiz_kayit_atlanir_digerleri_kalir():
    """Elle duzenlenen dosyada tek hata butun depoyu dusurmemeli."""
    items = parse("===\ncategory: yok\n---\ngovde\n===\ntitle: saglam\n---\nx\n")
    assert [item.title for item in items] == ["saglam"]


def test_anahtarsiz_satir_atlanir():
    items = parse("===\ntitle: x\nbu satirda iki nokta yok\n---\ngovde\n")
    assert items[0].title == "x"


# ---- sorgular ----


def _depo() -> Repository:
    repo = Repository(path=None)  # type: ignore[arg-type]  # diske dokunmuyoruz
    repo.items = parse(ORNEK)
    return repo


def test_arama_govdede_de_bakar():
    assert [item.title for item in _depo().search("two way")] == ["doorbell"]


def test_arama_harf_duyarsiz():
    assert len(_depo().search("DOORBELL")) == 1


def test_bos_arama_hepsini_verir():
    assert len(_depo().search("")) == 2


def test_etiket_suzgeci_hepsini_ister():
    repo = _depo()
    assert len(repo.filter_tags(["tuya"])) == 1
    assert repo.filter_tags(["tuya", "olmayan"]) == []


def test_kategori_suzgeci():
    assert [item.title for item in _depo().filter_category("iot")] == ["doorbell"]


def test_kategori_ve_etiket_listeleri_tekil_ve_sirali():
    repo = _depo()
    assert repo.categories == ["iot"]
    assert repo.tags == ["tuya", "zigbee"]


# ---- degistirme ----


def test_guncelle_ve_sil():
    repo = _depo()
    uuid = repo.items[0].uuid
    assert repo.update(uuid, "yeni", "kat", "metin", ["a"]) is True
    assert repo.get(uuid).title == "yeni"  # type: ignore[union-attr]
    assert repo.delete(uuid) is True
    assert repo.get(uuid) is None
    assert repo.delete(uuid) is False  # ikinci silme bir sey bulmaz


def test_diske_yaz_oku(tmp_path):
    yol = tmp_path / "repository.md"
    repo = Repository(yol)
    repo.items = parse(ORNEK)
    assert repo.save() is True

    tekrar = Repository(yol)
    assert tekrar.load() is True
    assert [item.title for item in tekrar.items] == ["doorbell", "zigbeeeee"]


def test_dosya_yoksa_bos_depo(tmp_path):
    repo = Repository(tmp_path / "yok.md")
    assert repo.load() is False
    assert repo.items == []
