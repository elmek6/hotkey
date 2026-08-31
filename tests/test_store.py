"""Diske kayit. AHK'de bu bolum hic test edilemiyordu (gercek dosya + modal
hata pencereleri); burada tmp_path ile insansiz kosuyor."""

import orjson
import pytest

from cascade.core.clip_history import ClipEntry, ClipHistory
from cascade.store import ClipStore, JsonStore, SlotStore


@pytest.fixture
def store(tmp_path):
    return ClipStore(directory=tmp_path)


def entry(text: str, count: int = 1) -> ClipEntry:
    return ClipEntry(text=text, first_ts=1.0, last_ts=2.0, count=count)


# ---- gidis donus ----


def test_yazilan_okunur(store):
    items = [entry("bir"), entry("iki", count=3)]
    assert store.save_entries(items)
    okunan = ClipStore(directory=store.path.parent).load_entries()
    assert [e.text for e in okunan] == ["bir", "iki"]
    assert okunan[1].count == 3


def test_dosya_yoksa_bos_liste(store):
    assert store.load_entries() == []
    assert not store.path.exists()


def test_max_items_kadar_yazar(tmp_path):
    store = ClipStore(directory=tmp_path, max_items=2)
    store.save_entries([entry("a"), entry("b"), entry("c")])
    assert [e.text for e in store.load_entries()] == ["a", "b"]


# ---- bozuk dosya ----


def test_bozuk_dosya_yedeklenir_ve_program_devam_eder(store):
    """AHK: backupOnError. Silmiyoruz -- icinde kurtarilabilir veri olabilir."""
    store.path.write_bytes(b"{ bu json degil")
    assert store.load_entries() == []
    yedekler = list(store.path.parent.glob("*.bozuk-*"))
    assert len(yedekler) == 1
    assert yedekler[0].read_bytes() == b"{ bu json degil"


def test_surum_uyusmazligi_bozuk_sayilir(store):
    store.path.write_bytes(orjson.dumps({"version": 99, "entries": []}))
    assert store.load_entries() == []
    assert list(store.path.parent.glob("*.surum-*"))


def test_yarim_kalan_kayit_okunani_dusurmez(store):
    """Dosyanin sonu kirpilmissa okunabilen kayitlar kurtarilir; dosya
    yedeklenir ama yerinde de kalir (kopya)."""
    store.save_entries([entry("iyi"), entry("yarim")])
    raw = store.path.read_bytes()
    store.path.write_bytes(raw[:-4])
    assert [e.text for e in store.load_entries()] == ["iyi"]
    assert list(store.path.parent.glob("*.bozuk-*"))
    assert store.path.exists()


def test_isaretci_bozulursa_okuma_orada_durur(store):
    """`~` (0x7E) bicimin tek saglamasi -- AHK de burada kesiyordu."""
    store.save_entries([entry("iyi"), entry("bozuk")])
    raw = bytearray(store.path.read_bytes())
    ikinci = ClipStore.HEADER.size + ClipStore.RECORD.size + 1 + len("iyi")
    raw[ikinci + ClipStore.RECORD.size] = 0x41  # `~` yerine `A`
    store.path.write_bytes(bytes(raw))
    assert [e.text for e in store.load_entries()] == ["iyi"]


# ---- AHK ile bicim uyumu ----


def test_baslik_ahk_bicimiyle_ayni(store):
    """AHK `_readRecords`: [u32 sayi][u64 baslangic ms][u32 surum][u32 bos]."""
    store.save_entries([entry("bir"), entry("iki")])
    sayi, _baslangic, surum, ayrilmis = ClipStore.HEADER.unpack_from(
        store.path.read_bytes(), 0
    )
    assert (sayi, surum, ayrilmis) == (2, 2, 0)


def test_ahk_nin_yazdigi_dosya_okunur(store):
    """Elle AHK bicimi kurup okuyoruz: kayit = [u64 ts][u16 count][u32 len]~metin."""
    metin = b"merhaba"
    ham = ClipStore.HEADER.pack(1, 1_700_000_000_000, 2, 0)
    ham += ClipStore.RECORD.pack(1_700_000_000_000, 5, len(metin)) + b"~" + metin
    store.path.write_bytes(ham)
    okunan = store.load_entries()
    assert [(e.text, e.count) for e in okunan] == [("merhaba", 5)]
    assert not list(store.path.parent.glob("*.bozuk-*"))


def test_baslangic_tarihi_korunur(store):
    """AHK: 'ne okuduysan onu yaz' -- gecmisin baslangic tarihi kaybolmasin."""
    store.path.write_bytes(ClipStore.HEADER.pack(0, 1_234_567_890_000, 2, 0))
    store.load_entries()
    store.save_entries([entry("a")])
    baslangic = ClipStore.HEADER.unpack_from(store.path.read_bytes(), 0)[1]
    assert baslangic == 1_234_567_890_000


# ---- slots.json: clip_slot.ahk bicimi ----


def test_slot_dosyasi_yoksa_on_bos_slot(tmp_path):
    store = SlotStore(directory=tmp_path)
    store.load()
    slots = store.slots()
    assert len(slots) == 10
    assert slots[0].name == "Slot 1"
    assert slots[0].content == ""


def test_slot_gidis_donus_ve_bom(tmp_path):
    store = SlotStore(directory=tmp_path)
    store.load()
    store.slots()[2].content = "icerik"
    assert store.save()
    assert store.path.read_bytes().startswith(b"\xef\xbb\xbf")  # AHK BOM ile yaziyor

    tekrar = SlotStore(directory=tmp_path)
    tekrar.load()
    assert tekrar.slots()[2].content == "icerik"


def test_ahk_slot_dosyasi_okunur_ve_gruplar_bozulmaz(tmp_path):
    """Dokunmadigimiz gruplar geri yazarken aynen kalmali."""
    ahk = {
        "defaultGroupName": "x",
        "groups": [
            {"groupName": "", "values": [{"content": "a", "name": "Slot 1"}]},
            {"groupName": "x", "values": [{"content": "b", "name": "isim"}]},
        ],
    }
    store = SlotStore(directory=tmp_path)
    store.path.write_bytes(b"\xef\xbb\xbf" + orjson.dumps(ahk))
    store.load()
    assert store.default_group == "x"
    assert store.groups["x"][0].content == "b"
    store.save()

    data = orjson.loads(store.path.read_bytes().lstrip(b"\xef\xbb\xbf"))
    assert data["defaultGroupName"] == "x"
    assert data["groups"][0]["groupName"] == ""  # bos grup HER ZAMAN once
    assert data["groups"][1]["values"] == [{"content": "b", "name": "isim"}]


# ---- veri kaybi korumasi ----


def test_diskteki_fazlalik_korunur(store):
    """AHK `_save` birlestirmesi: bellekteki liste diskten kisa olabilir
    (bellek siniri daha dusuk); diskteki fazlalar arkaya eklenir."""
    store.save_entries([entry("a"), entry("b"), entry("c")])
    store.load_entries()
    assert store.save_entries([entry("a")])
    assert [e.text for e in store.load_entries()] == ["a", "b", "c"]


def test_okunandan_az_kayit_yazilmaz(store):
    """AHK'deki 'Asama 1' uyarisi: gecmis sadece buyur; azaldiysa bir yerde
    is ters gitmistir ve ustune yazmak hatayi kalicilastirir.

    Birlestirme devredeyken bu ancak dosya elden kayarsa olur -- burada
    dosyayi disaridan siliyoruz."""
    store.save_entries([entry("a"), entry("b"), entry("c")])
    store.load_entries()  # loaded_count = 3
    store.path.unlink()
    assert store.save_entries([entry("a")]) is False
    assert not store.path.exists()


def test_bilerek_temizleme_korumayi_gecer(store):
    store.save_entries([entry("a"), entry("b")])
    store.load_entries()
    assert store.clear()
    assert store.load_entries() == []


def test_esit_sayida_kayit_yazilabilir(store):
    store.save_entries([entry("a"), entry("b")])
    store.load_entries()
    assert store.save_entries([entry("a"), entry("c")])


# ---- atomik yazma ----


def test_yarim_tmp_dosyasi_birakilmaz(store):
    store.save_entries([entry("a")])
    assert not list(store.path.parent.glob("*.tmp"))


def test_taban_sinif_surum_alanini_koyar(tmp_path):
    class Deneme(JsonStore):
        filename = "deneme.json"
        version = 7

    s = Deneme(directory=tmp_path)
    s.save({"x": 1})
    data = orjson.loads(s.path.read_bytes())
    assert data["version"] == 7
    assert data["x"] == 1
    assert "saved_at" in data
    assert s.load()["x"] == 1


# ---- ClipHistory ile birlikte ----


def test_gecmise_yuklenince_sira_korunur(store):
    store.save_entries([entry("yeni"), entry("eski")])
    history = ClipHistory()
    assert history.load(store.load_entries()) == 2
    assert history.get(1).text == "yeni"
    assert history.last_text == "yeni"


def test_yuklemede_tekrar_eden_metin_bir_kez_girer():
    history = ClipHistory()
    assert history.load([entry("ayni"), entry("ayni"), entry("baska")]) == 2


# ---- grup yonetimi (AHK: clip_slot.ahk addGroup/deleteGroup/setDefaultGroup) ----


def _slot_store(tmp_path):
    from cascade.store import SlotStore

    store = SlotStore(directory=tmp_path)
    store.load()
    return store


def test_grup_eklenir_ve_on_bos_slotla_acilir(tmp_path):
    store = _slot_store(tmp_path)
    assert store.add_group("is") is True
    assert store.add_group("is") is False  # ayni ad ikinci kez eklenmez
    assert store.group_names() == ["is"]
    assert len(store.slots("is")) == 10
    assert all(not slot.content for slot in store.slots("is"))


def test_yan_grup_secimi_diske_yazilir(tmp_path):
    from cascade.store import SlotStore

    store = _slot_store(tmp_path)
    store.add_group("is")
    assert store.set_default_group("is") is True
    assert store.set_default_group("yok") is False  # olmayan grup secilmez

    tekrar = SlotStore(directory=tmp_path)
    tekrar.load()
    assert tekrar.default_group == "is"


def test_grup_silinince_yan_grup_secimi_bosa_duser(tmp_path):
    store = _slot_store(tmp_path)
    store.add_group("is")
    store.set_default_group("is")
    assert store.delete_group("is") is True
    assert store.default_group == ""
    assert store.group_names() == []
    # Varsayilan (adsiz) grup silinemez -- AHK'de de oyle.
    assert store.delete_group("") is False


def test_slot_adi_ve_icerigi_yazilir(tmp_path):
    from cascade.store import SlotStore

    store = _slot_store(tmp_path)
    assert store.set_slot_name("", 3, "  fan ow  ") is True
    assert store.set_slot_content("", 3, "M106 O1 S60") is True
    assert store.set_slot_name("", 99, "olmaz") is False

    tekrar = SlotStore(directory=tmp_path)
    tekrar.load()
    slot = tekrar.slots("")[2]
    assert (slot.name, slot.content) == ("fan ow", "M106 O1 S60")


def test_bos_ad_verilince_slot_varsayilan_adina_doner(tmp_path):
    store = _slot_store(tmp_path)
    store.set_slot_name("", 4, "   ")
    assert store.slots("")[3].name == "Slot 4"


def test_olmayan_grubu_okumak_grup_yaratmaz(tmp_path):
    """Grup acmak `add_group`in isi. Eskiden `slots()` icindeki `setdefault`
    yuzunden, dosyada `defaultGroupName` var olmayan bir grubu gosterdiginde
    (elle duzenleme ya da AHK tarafinda silinmis grup) o ad on bos slotla
    uyduruluyor ve ilk `save()` onu DISKE yaziyordu."""
    import orjson

    from cascade.store import BOM, SlotStore

    store = _slot_store(tmp_path)
    store.add_group("is")

    assert store.slots("yok-boyle-bir-grup") == []
    assert store.group_names() == ["is"]
    assert store.set_slot_content("yok-boyle-bir-grup", 1, "x") is False
    assert store.set_slot_name("yok-boyle-bir-grup", 1, "x") is False

    store.set_slot_content("", 1, "yazmayi tetikle")
    yazilan = orjson.loads((tmp_path / "slots.json").read_bytes().lstrip(BOM))
    assert [g["groupName"] for g in yazilan["groups"]] == ["", "is"]

    # Varsayilan (adsiz) grup istisna: `load` cagrilmadan da kullanilabilir.
    assert len(SlotStore(directory=tmp_path / "yeni").slots("")) == 10


def test_dizgi_olmayan_slot_alani_bos_sayilir(tmp_path):
    """`"content": null` gecen bir dosyada `str()` slotu "None" METNIYLE
    dolduruyordu: slot dolu gorunuyor ve o metin yapistirilabiliyordu."""
    import orjson

    from cascade.store import BOM, SlotStore

    (tmp_path / "slots.json").write_bytes(
        BOM
        + orjson.dumps(
            {
                "defaultGroupName": "",
                "groups": [
                    {
                        "groupName": "",
                        "values": [
                            {"content": None, "name": None},
                            {"content": 5, "name": 7},
                            {"content": "gercek", "name": "Ad"},
                        ],
                    }
                ],
            }
        )
    )
    slotlar = SlotStore(directory=tmp_path).load()[""]
    assert (slotlar[0].name, slotlar[0].content) == ("", "")
    assert (slotlar[1].name, slotlar[1].content) == ("", "")
    assert (slotlar[2].name, slotlar[2].content) == ("Ad", "gercek")
