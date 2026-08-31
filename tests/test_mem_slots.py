"""Hafiza bloklari penceresi (ui/mem_slots.py) -- AHK `memory_slots.ahk`.

Pencerenin testi yoktu; asagidakiler AHK aslindan DOGRULANMIS davranislari
sabitliyor (`_AutoHotKey/Lib/memory_slots.ahk`), ozellikle port sirasinda
kolay kaybolacak olanlari:

    * `_autoFillSlot` -- ilk bos bloga yazar, doluysa 1'in USTUNE yazar
      (2,3 diye donmez; AHK'de de oyle)
    * `_isClipInSlots` -- ayni metin ikinci kez dusmez, kutu acikken duser
    * `slotsLength` -- SONDAN geriye ilk dolu blok; aradaki bosluk sayilir
    * `_makePreview` -- bos icerik "(Bos)" yazar
    * `smartPaste` -- yalniz ORTA tus siradakine gecer, kombo yerinde kalir

Pencere panoyu kendisi yazmaz, sinyal gonderir: testler sinyalleri
topluyor, Win32'ye hic dokunulmuyor.
"""

from __future__ import annotations

import pytest

from cascade.ui.mem_slots import SLOT_COUNT, MemSlots, preview


class Kayit:
    """Pencerenin disariya yaydigi sinyalleri toplar."""

    def __init__(self) -> None:
        self.pasted: list[tuple[str, bool]] = []
        self.copied: list[tuple[str, bool]] = []
        self.tips: list[str] = []
        self.grabs = 0
        self.fkeys: list[bool] = []


@pytest.fixture
def pencere(qapp):
    view = MemSlots()
    log = Kayit()
    view.paste_text.connect(lambda t, p: log.pasted.append((t, p)))
    view.copy_text.connect(lambda t, p: log.copied.append((t, p)))
    view.tip.connect(log.tips.append)
    view.grab_clip.connect(lambda: setattr(log, "grabs", log.grabs + 1))
    view.fkeys_toggled.connect(log.fkeys.append)
    yield view, log
    view.close()


def hucreler(view: MemSlots) -> list[str]:
    return [view.slot_table.item(row, 1).text() for row in range(SLOT_COUNT)]


# ---- acilis ----


def test_acilista_bloklar_bos_gecmis_aktif(pencere):
    """AHK: start() -- gecmis yuklu gelir ve AKTIF liste gecmistir."""
    view, _ = pencere
    view.start(["g1", "g2", "g3"])
    assert view.blocks == [""] * SLOT_COUNT
    assert view.history == ["g1", "g2", "g3"]
    assert view.hist_index == 1
    assert view._slots_active is False


def test_gecmis_on_kayitta_kirpilir(pencere):
    view, _ = pencere
    view.start([f"h{i}" for i in range(20)])
    assert len(view.history) == SLOT_COUNT
    assert view.hist_table.rowCount() == SLOT_COUNT


def test_bos_gecmisle_acilis_cokmez(pencere):
    view, _ = pencere
    view.start([])
    assert view.history == []
    assert view.hist_index == 1


def test_bloklar_yeniden_acilista_korunur(pencere):
    """AHK pencereyi her acilista bosaltiyordu; bizde BILEREK korunuyor --
    temizlemek isteyen "Slotlari temizle" dugmesini kullanir."""
    view, _ = pencere
    view.start([])
    view.on_clip("kalici")
    view.close()
    view.start(["yeni"])
    assert view.blocks[0] == "kalici"
    assert hucreler(view)[0] == "kalici"


# ---- pano -> blok (AHK: _autoFillSlot) ----


def test_pano_ilk_bos_bloga_duser(pencere):
    view, _ = pencere
    view.start([])
    view.on_clip("alpha")
    view.on_clip("beta")
    assert view.blocks[:3] == ["alpha", "beta", ""]
    assert view.slot_index == 2
    assert view._slots_active is True  # AHK: ilk kopyalamada slotlar secili


def test_bos_pano_yok_sayilir(pencere):
    view, _ = pencere
    view.start([])
    view.on_clip("")
    assert view.blocks == [""] * SLOT_COUNT


def test_ayni_metin_ikinci_kez_dusmez(pencere):
    """AHK: _isClipInSlots. "Veri tekrarini kabul et" kutusu bunu kapatir."""
    view, _ = pencere
    view.start([])
    view.on_clip("alpha")
    view.on_clip("alpha")
    assert view.blocks[:2] == ["alpha", ""]

    view.allow_repeat.setChecked(True)
    view.on_clip("alpha")
    assert view.blocks[:2] == ["alpha", "alpha"]


def test_bloklar_dolunca_birincinin_ustune_yazilir(pencere):
    """AHK `_autoFillSlot`: slotsLength == 10 iken index 1'e SABITLENIR --
    2,3 diye donmez. Port bunu birebir tasiyor."""
    view, _ = pencere
    view.start([])
    for index in range(1, SLOT_COUNT + 3):
        view.on_clip(f"v{index}")
    assert view.blocks[0] == f"v{SLOT_COUNT + 2}"
    assert view.blocks[1:] == [f"v{i}" for i in range(2, SLOT_COUNT + 1)]
    assert view.slot_index == 1


# ---- F1..F10 (app.py cagirir) ----


def test_kisa_basim_blogu_yapistirir(pencere):
    view, log = pencere
    view.start([])
    view.on_clip("alpha")
    view.paste_slot(1)
    assert log.pasted == [("alpha", False)]


def test_kisa_basim_bos_blokta_yalniz_uyarir(pencere):
    view, log = pencere
    view.start([])
    view.paste_slot(2)
    assert log.pasted == []
    assert "bos" in log.tips[-1]


def test_kisa_basim_sinir_disi_indekste_cokmez(pencere):
    view, log = pencere
    view.start([])
    view.paste_slot(0)
    view.paste_slot(SLOT_COUNT + 1)
    assert log.pasted == []


def test_orta_basim_gecmisi_yapistirir(pencere):
    view, log = pencere
    view.start(["g1", "g2"])
    view.paste_history(2)
    assert log.pasted == [("g2", False)]
    assert view._slots_active is False


def test_orta_basim_olmayan_gecmiste_uyarir(pencere):
    view, log = pencere
    view.start(["g1"])
    view.paste_history(9)
    assert log.pasted == []
    assert "yok" in log.tips[-1]


def test_uzun_basim_once_kopyalama_ister(pencere):
    """AHK `SendInput("^c") + ClipWait` yerine: `grab_clip` yayilir, gelen
    ILK metin bekleyen bloga yazilir."""
    view, log = pencere
    view.start([])
    view.save_slot(7)
    assert log.grabs == 1
    assert view._pending_slot == 7

    view.on_clip("yedinciye")
    assert view.blocks[6] == "yedinciye"
    assert view._pending_slot is None
    assert view.slot_index == 7


def test_uzun_basim_sinir_disi_indekste_kopyalama_istemez(pencere):
    view, log = pencere
    view.start([])
    for index in (0, SLOT_COUNT + 1, -3):
        view.save_slot(index)
    assert log.grabs == 0
    assert view._pending_slot is None


# ---- akilli yapistirma (AHK: smartPaste) ----


def test_orta_tus_siradaki_kayda_gecer(pencere):
    view, log = pencere
    view.start([])
    view.on_clip("a")
    view.on_clip("b")
    view.select_slot(1)
    view.smart_paste(middle=True)
    assert view.slot_index == 2
    view.smart_paste(middle=True)
    assert view.slot_index == 1  # AHK: sondan basa doner
    assert [text for text, _ in log.pasted] == ["a", "b"]


def test_kombo_yolu_secimi_yerinde_birakir(pencere):
    """AHK ayrimi: orta tus gezdirir, tus kombosu gezdirmez."""
    view, log = pencere
    view.start([])
    view.on_clip("a")
    view.on_clip("b")
    view.select_slot(1)
    view.smart_paste(middle=False)
    assert view.slot_index == 1
    assert log.pasted == [("a", False)]


def test_orta_tus_kutusu_kapaliyken_fare_yolu_susar(pencere):
    view, log = pencere
    view.start([])
    view.on_clip("a")
    view.select_slot(1)
    view.middle_paste.setChecked(False)
    view.smart_paste(middle=True)
    assert log.pasted == []
    # Kutu yalniz FARE yolunu kapatir; kombo calismaya devam eder.
    view.smart_paste(middle=False)
    assert log.pasted == [("a", False)]


def test_pencere_kapaliyken_akilli_yapistirma_sessiz(pencere):
    """Orta tus her yerde calisan bir tus; yalniz bu pencere acikken
    anlam kazanmali."""
    view, log = pencere
    view.start([])
    view.on_clip("a")
    view.hide()
    view.smart_paste(middle=True)
    assert log.pasted == []


# ---- temizleme ----


def test_temizle_bloklari_ve_hucreleri_bosaltir(pencere):
    view, _ = pencere
    view.start([])
    view.on_clip("a")
    view.clear_slots()
    assert view.blocks == [""] * SLOT_COUNT
    assert hucreler(view) == [""] * SLOT_COUNT


def test_temizle_bekleyen_kopyalama_istegini_dusurur(pencere):
    """Regresyon: "uzun basim + temizle" sirasindan sonra gelen kopyalama
    temizlenmis bloga sessizce doluyordu. AHK'de bu ara durum yoktu
    (pano orada `ClipWait` ile BLOKE okunuyordu)."""
    view, _ = pencere
    view.start([])
    view.save_slot(3)
    view.clear_slots()
    assert view._pending_slot is None

    view.on_clip("sonra")
    assert view.blocks[0] == "sonra"  # bekleyen blok 3'e degil, ilk bosa
    assert view.blocks[2] == ""


# ---- ters cevirme (baslik seridine tiklama) ----


def test_bloklari_ters_cevirme_yalniz_dolu_kismi_dondurur(pencere):
    """AHK `_reverseSlotsOrder`: `slotsLength` kadarini cevirir, gerisi
    yerinde kalir."""
    view, _ = pencere
    view.start([])
    for text in ("a", "b", "c"):
        view.on_clip(text)
    view._reverse_slots()
    assert view.blocks[:3] == ["c", "b", "a"]
    assert view.blocks[3:] == [""] * (SLOT_COUNT - 3)
    assert view.slot_index == 1


def test_gecmisi_ters_cevirme(pencere):
    view, _ = pencere
    view.start(["g1", "g2", "g3"])
    view._reverse_history()
    assert view.history == ["g3", "g2", "g1"]
    assert view.hist_index == 1


# ---- kapanis ----


def test_kapanista_fkeys_birakilir(pencere):
    """AHK `_destroy`: F1..F10 kaskadlari pencere ile birlikte sokulur."""
    view, log = pencere
    view.start([])
    view.fkeys.setChecked(True)
    log.fkeys.clear()
    kapandi: list[int] = []
    view.closed.connect(lambda: kapandi.append(1))

    view.close()
    assert log.fkeys == [False]
    assert kapandi == [1]


# ---- yardimcilar ----


def test_onizleme(pencere):
    """AHK `_makePreview`: satir sonlari bosluga iner, bos icerik "(Bos)"."""
    assert preview("") == "(Bos)"
    assert preview("   ") == "(Bos)"
    assert preview("a\nb  c") == "a b c"
    assert preview("x" * 70).endswith("...")
    assert len(preview("x" * 70)) <= 63


def test_surukleme_KISALTILMIS_degil_TAM_icerigi_tasir(pencere):
    """AHK `OleDragSource`: tabloda onizleme yazar, surukleme tam metni
    tasir. `_slot` / `_history_text` surukleme kaynagi."""
    view, _ = pencere
    view.start(["kisa"])
    uzun = "y" * 200
    view.on_clip(uzun)
    assert view.slot_table.item(0, 1).text() != uzun  # tabloda kisaltilmis
    assert view._slot(1) == uzun  # surukleme tam
    assert view._history_text(1) == "kisa"
    assert view._history_text(0) == ""  # sinir disi -> bos, cokme yok
    assert view._history_text(99) == ""
