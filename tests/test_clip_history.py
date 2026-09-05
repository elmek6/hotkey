from keypilot.core.clip_history import ClipHistory
from keypilot.core.state import ClipboardMode, ClipboardState


def test_kopyalanan_metin_basa_girer():
    h = ClipHistory()
    h.add("bir", 1.0)
    h.add("iki", 2.0)
    assert [e.text for e in h.entries] == ["iki", "bir"]
    assert len(h) == 2


def test_ayni_metin_ust_uste_kaydedilmez():
    """AHK: lastClip kontrolu -- sayaci bile artirmaz."""
    h = ClipHistory()
    h.add("bir", 1.0)
    assert h.add("bir", 2.0) is None
    assert len(h) == 1
    assert h.entries[0].count == 1


def test_eski_kayit_tekrar_kopyalanirsa_basa_tasinir_sayac_artar():
    h = ClipHistory()
    h.add("bir", 1.0)
    h.add("iki", 2.0)
    entry = h.add("bir", 3.0)
    assert entry is not None
    assert [e.text for e in h.entries] == ["bir", "iki"]
    assert entry.count == 2
    assert entry.first_ts == 1.0 and entry.last_ts == 3.0
    assert len(h) == 2  # yeni kayit acilmadi


def test_bos_metin_alinmaz():
    h = ClipHistory()
    assert h.add("", 1.0) is None
    assert len(h) == 0


def test_buyuk_metin_alinmaz():
    """AHK: maxByteSize. Olcu karakter degil UTF-8 bayti."""
    h = ClipHistory(max_bytes=10)
    assert h.add("a" * 11, 1.0) is None
    assert h.add("ş" * 6, 1.0) is None  # 12 bayt
    assert h.add("ş" * 5, 1.0) is not None  # 10 bayt


def test_liste_dolunca_en_eski_duser():
    h = ClipHistory(max_items=3)
    for index in range(5):
        h.add(f"metin {index}", float(index))
    assert [e.text for e in h.entries] == ["metin 4", "metin 3", "metin 2"]


def test_get_bir_tabanli():
    """AHK'deki history[1] ile ayni numaralandirma."""
    h = ClipHistory()
    h.add("bir", 1.0)
    h.add("iki", 2.0)
    assert h.get(1).text == "iki"
    assert h.get(2).text == "bir"
    assert h.get(0) is None
    assert h.get(3) is None


def test_preview_satirlari_tek_satira_indirir():
    h = ClipHistory()
    entry = h.add("  ilk satir\n\tikinci   satir  ", 1.0)
    assert entry.preview == "ilk satir ikinci satir"
    assert entry.text == "  ilk satir\n\tikinci   satir  "  # ham metin bozulmaz


def test_temizle():
    h = ClipHistory()
    h.add("bir", 1.0)
    h.clear()
    assert len(h) == 0
    assert h.last_text == ""


# ---- durum (AHK: State.Clipboard) ----


def test_varsayilan_mod_gecmis():
    state = ClipboardState()
    assert state.is_history()
    assert state.mode is ClipboardMode.HISTORY


def test_mod_degisimi():
    state = ClipboardState()
    state.set_mem_slots()
    assert state.is_mem_slots() and not state.is_history()
    state.set_none()
    assert state.is_none()
