"""Diske kayit. AHK'de bu bolum hic test edilemiyordu (gercek dosya + modal
hata pencereleri); burada tmp_path ile insansiz kosuyor."""

import orjson
import pytest

from cascade.core.clip_history import ClipEntry, ClipHistory
from cascade.store import ClipStore, JsonStore


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


def test_liste_yerine_baska_bicim_gelirse_bos_doner(store):
    store.save({"entries": "liste degil"})
    assert store.load_entries() == []


def test_tek_bozuk_kayit_dosyanin_tamamini_dusurmez(store):
    """Bir satir bozuksa o atlanir, digerleri kurtarilir."""
    store.save({"entries": [{"text": "iyi"}, {"yok": 1}, "duz metin", {"text": ""}]})
    assert [e.text for e in store.load_entries()] == ["iyi"]


# ---- veri kaybi korumasi ----


def test_okunandan_az_kayit_yazilmaz(store):
    """AHK'deki 'Asama 1' uyarisi: gecmis sadece buyur; azaldiysa bir yerde
    is ters gitmistir ve ustune yazmak hatayi kalicilastirir."""
    store.save_entries([entry("a"), entry("b"), entry("c")])
    store.load_entries()  # loaded_count = 3
    assert store.save_entries([entry("a")]) is False
    assert len(store.load_entries()) == 3


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
