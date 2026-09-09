"""Profil yoneticisinin FLET surumu (fui/profiles.py) -- liste ve kayit.

Flet calistirilmiyor: `_build` cagrilmadan panelin QT TARAFI suruluyor.
Bolunme zaten oradan geciyor -- `ShortcutStore`a dokunan her satir ana
thread'de kosuyor (`ask_qt`), Flet tarafi yalnizca hazir demetleri
ciziyor. Yani burada test edilen sey panelin karar veren yarisi
(`tests/test_fui_repository.py` ile ayni kalip).

Qt surumunun testleri (`tests/test_profiles_view.py`) AYNEN duruyor:
iki pencere de ayakta ve ayni depoyu okuyor.
"""

from __future__ import annotations

import codecs

import orjson
import pytest

from keypilot.app_shorts import ShortcutStore
from keypilot.fui.profiles import (
    YENI,
    ProfilesPanel,
    read_strokes,
    rule_text,
    stroke_hint,
)

ORNEK = {
    "projectName": "ProfileManager",
    "profiles": [
        {
            "profileName": "Chrome",
            "className": "Chrome_WidgetWin_1",
            "title": "Google Chrome",
            "shortCuts": [
                {
                    "shortCutName": "Closed tab",
                    "keyDescription": "son sekmeyi ac",
                    "keyStrokes": ["^+t"],
                },
                {"shortCutName": "Yaz", "keyDescription": "", "keyStrokes": ["merhaba"]},
            ],
        },
        {
            "profileName": "Firefox",
            "className": "MozillaWindowClass",
            "title": "Mozilla Firefox",
            "shortCuts": [],
        },
    ],
}


@pytest.fixture
def panel(qapp, tmp_path):
    (tmp_path / "profiles.json").write_bytes(codecs.BOM_UTF8 + orjson.dumps(ORNEK))
    panel = ProfilesPanel(ShortcutStore(tmp_path))
    # `open()` Flet'e dokunmuyor: yalnizca diskten okuyup Qt tarafinin
    # demetlerini kuruyor, sonra `_show` cagriliyor -- sayfa olmadigi icin
    # `engine.start()` isterdi, o yuzden ayni sira ELLE kuruluyor.
    panel.store.load()
    panel._refresh_profiles()
    panel._select_profile(0)
    return panel


def _diskten(panel: ProfilesPanel) -> dict:
    return orjson.loads(panel.store.path.read_bytes().lstrip(codecs.BOM_UTF8))


# ---- listeleme ----


def test_profiller_listelenir(panel):
    assert panel._profiles == ("Chrome", "Firefox")
    assert panel._status == "2 profil, 2 aksiyon"


def test_acilista_ilk_profil_secili(panel):
    assert panel._profile_index == 0
    assert panel._profile_fields == ("Chrome", "Chrome_WidgetWin_1", "Google Chrome")
    assert panel._actions == ("Closed tab", "Yaz")


def test_ada_gore_acilis(qapp, tmp_path):
    (tmp_path / "profiles.json").write_bytes(codecs.BOM_UTF8 + orjson.dumps(ORNEK))
    panel = ProfilesPanel(ShortcutStore(tmp_path))
    panel.store.load()
    panel._refresh_profiles()
    panel._select_profile(panel._named("Firefox"))
    assert panel._profile_fields[0] == "Firefox"


def test_bilinmeyen_ad_secilmez(panel):
    assert panel._named("YokBoyleBirSey") == YENI


def test_profil_secimi_sag_sutunu_BOSALTIR(panel):
    """Qt: `_on_profile` sonunda `new_action` -- baska profilin aksiyonu
    sag sutunda asili kalmamali."""
    panel._load_action(0)
    assert panel._action_fields[0] == "Closed tab"
    panel._select_profile(1)
    assert panel._action_index == YENI
    assert panel._action_fields == ("", "", "", "")


def test_aksiyon_secimi_detayi_doldurur(panel):
    panel._load_action(0)
    assert panel._action_fields == ("Closed tab", "son sekmeyi ac", "", "^+t")


# ---- saf yardimcilar (Flet de ekran da gerekmiyor) ----


def test_kural_metni_iki_kosulu_da_soyler():
    metin = rule_text("Chrome_WidgetWin_1", "Google")
    assert "TAM olarak `Chrome_WidgetWin_1`" in metin
    assert "`Google` GECEN" in metin


def test_bos_profil_kurali_uyarir():
    assert "HER pencereye uyar" in rule_text("", "")


def test_stroke_ipucu_kisayol_ile_metni_ayirir():
    ipucu = stroke_hint("^+t\nmerhaba")
    assert "`^+t` → kisayol" in ipucu
    assert "`merhaba` → duz metin" in ipucu


def test_bos_kutuda_ipucu_yok():
    assert stroke_hint("   \n\n") == ""


def test_bos_satirlar_elenir():
    assert read_strokes(" ^+t \n\n  merhaba  \n") == ("^+t", "merhaba")


# ---- profil kaydi ----


def test_yeni_profil_diske_yazilir(panel):
    panel._new_profile()
    panel._save_profile("Notepad", "Notepad", "Not Defteri")

    diskte = _diskten(panel)["profiles"]
    assert [p["profileName"] for p in diskte] == ["Chrome", "Firefox", "Notepad"]
    assert panel._profile_index == 2
    assert panel._profiles[-1] == "Notepad"


def test_profil_guncelleme_yeni_kayit_ACMAZ(panel):
    panel._save_profile("Chrome v2", "Chrome_WidgetWin_1", "Google Chrome")
    diskte = _diskten(panel)["profiles"]
    assert len(diskte) == 2
    assert diskte[0]["profileName"] == "Chrome v2"


def test_kayit_kurali_tazeler(panel):
    panel._save_profile("Chrome", "YeniSinif", "")
    assert "`YeniSinif`" in panel._rule


def test_profil_silinir(panel):
    panel._delete_profile()
    diskte = _diskten(panel)["profiles"]
    assert [p["profileName"] for p in diskte] == ["Firefox"]
    assert panel._profile_index == YENI
    assert panel._profile_fields == ("", "", "")


def test_kaydetme_kanca_cagirir(panel):
    """`app.py` `bind_profile_keys`: yeni atanan tus kayit defterine
    tutturulmali, yoksa program yeniden baslayana kadar olu kalir."""
    cagrildi: list[int] = []
    panel.keys_changed = lambda: cagrildi.append(1)
    panel._save_profile("Chrome", "Chrome_WidgetWin_1", "Google Chrome")
    assert cagrildi == [1]


# ---- aksiyon kaydi ----


def test_yeni_aksiyon_eklenir(panel):
    panel._new_action()
    panel._save_action("Yeni", "aciklama", "^s")

    aksiyonlar = _diskten(panel)["profiles"][0]["shortCuts"]
    assert [a["shortCutName"] for a in aksiyonlar] == ["Closed tab", "Yaz", "Yeni"]
    assert aksiyonlar[-1]["keyStrokes"] == ["^s"]
    assert panel._action_index == 2


def test_cok_satirli_tuslar_ayri_dizi_olur(panel):
    panel._new_action()
    panel._save_action("Coklu", "", "^+t\n\nmerhaba\n")
    aksiyonlar = _diskten(panel)["profiles"][0]["shortCuts"]
    assert aksiyonlar[-1]["keyStrokes"] == ["^+t", "merhaba"]


def test_aksiyon_guncelleme_kopya_uretmez(panel):
    panel._load_action(0)
    panel._save_action("Closed tab v2", "", "^+t")
    aksiyonlar = _diskten(panel)["profiles"][0]["shortCuts"]
    assert len(aksiyonlar) == 2
    assert aksiyonlar[0]["shortCutName"] == "Closed tab v2"


def test_yakalanan_kisayol_kayitta_KORUNUR(panel):
    """Kisayol Qt tarafinda yakalanip `_action_fields`e yaziliyor;
    `Kaydet` kutulardan yalniz UC alani okuyor, dorduncusu buradan."""
    panel._load_action(0)
    ad, aciklama, _tus, dizi = panel._action_fields
    panel._action_fields = (ad, aciklama, "Ctrl+Shift+K", dizi)
    panel._save_action(ad, aciklama, dizi)
    # Dosyadaki alan adi `hotKey` ve YALNIZCA doluyken yaziliyor
    # (app_shorts.save; bos alan dosyayi AHK'nin yazdigindan ayirirdi).
    assert _diskten(panel)["profiles"][0]["shortCuts"][0]["hotKey"] == "Ctrl+Shift+K"


def test_profilsiz_aksiyon_kaydedilemez(panel):
    panel._new_profile()
    panel._save_action("Sahipsiz", "", "^s")
    # Hicbir profile yazilmadi ve dosya degismedi.
    diskte = _diskten(panel)["profiles"]
    assert [len(p["shortCuts"]) for p in diskte] == [2, 0]


def test_aksiyon_silinir(panel):
    panel._load_action(0)
    panel._delete_action()
    aksiyonlar = _diskten(panel)["profiles"][0]["shortCuts"]
    assert [a["shortCutName"] for a in aksiyonlar] == ["Yaz"]
    assert panel._action_index == YENI
    assert panel._action_fields == ("", "", "", "")


def test_aksiyon_asagi_tasinir(panel):
    """Sira F13 menusundeki siradir, onemli (Qt: `move_action`)."""
    panel._load_action(0)
    panel._move_action(1)
    aksiyonlar = _diskten(panel)["profiles"][0]["shortCuts"]
    assert [a["shortCutName"] for a in aksiyonlar] == ["Yaz", "Closed tab"]
    assert panel._action_index == 1
    assert panel._actions == ("Yaz", "Closed tab")


def test_sinirdan_disari_tasima_yok_sayilir(panel):
    panel._load_action(0)
    panel._move_action(-1)
    aksiyonlar = _diskten(panel)["profiles"][0]["shortCuts"]
    assert [a["shortCutName"] for a in aksiyonlar] == ["Closed tab", "Yaz"]
    assert panel._action_index == 0


def test_yazilan_dosya_BOM_ve_anahtar_adlarini_korur(panel):
    """Dosya AHK ile PAYLASILIYOR: bicim bozulursa oteki taraf okuyamaz."""
    panel._save_profile("Chrome", "Chrome_WidgetWin_1", "Google Chrome")
    ham = panel.store.path.read_bytes()
    assert ham.startswith(codecs.BOM_UTF8)
    veri = orjson.loads(ham.lstrip(codecs.BOM_UTF8))
    assert veri["projectName"] == "ProfileManager"
    assert set(veri["profiles"][0]) >= {"profileName", "className", "title", "shortCuts"}


def test_depo_nesnesi_app_ile_PAYLASILIR(panel):
    """Panel kendi kopyasini tutmuyor: `app.py`nin `shorts` nesnesi ayni."""
    panel._new_profile()
    panel._save_profile("Paylasim", "", "")
    assert any(p.name == "Paylasim" for p in panel.store.profiles)
