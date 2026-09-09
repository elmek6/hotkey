"""Ayar ekraninin FLET surumu (fui/settings.py).

Flet calistirilmiyor: `_build` cagrilmadan panelin QT TARAFI suruluyor --
ayar defterine dokunan her satir zaten ana thread'de kosuyor (`ask_qt`),
Flet tarafi yalnizca hazir kartlari ciziyor. Adim 9/11/12'de kurulan
kalibin ayni.

Gercek kayit defteri yerine kucuk bir tane kuruluyor (Qt surumunun
testleri de oyle yapiyor): test ayar EKLEMESIN, gercek ayarlarin degeri
testten etkilenmesin.
"""

from __future__ import annotations

import pytest

from keypilot.fui import settings as fui_settings
from keypilot.fui.settings import (
    ALL_LABEL,
    THEME_NOTE,
    SettingsPanel,
    card_of,
    category_rows,
    choice_rows,
    current_choice,
    status_text,
    value_text,
)
from keypilot.settings import Category, Registry, Setting, between


@pytest.fixture
def defter(monkeypatch):
    """Kucuk bir kayit defteri -- modulun gordugu `SETTINGS` bu olur."""
    registry = Registry()
    monkeypatch.setattr(fui_settings, "SETTINGS", registry)
    return registry


def kur(registry: Registry, *items: Setting) -> None:
    for item in items:
        registry.register(item)


@pytest.fixture
def panel(qapp, defter):
    """Uc tipli kucuk bir ayar kumesi: enum, sayi ve iki bool."""
    kur(
        defter,
        Setting(
            "app.theme",
            "Tema",
            default="system",
            choices=("system", "light", "dark"),
            labels={"system": "Sistem", "light": "Acik", "dark": "Koyu"},
            category=Category.GENERAL,
            tags="renk",
        ),
        Setting(
            "mouse.delay",
            "Fare gecikmesi",
            default=8,
            category=Category.MOUSE,
            validate=between(1, 9),
        ),
        Setting("tray.tips", "Ipuclari", default=True, category=Category.TRAY),
        Setting(
            "dev.verbose",
            "Ayrinti log",
            default=False,
            category=Category.DEVELOPMENT,
            desc="",
        ),
        Setting("gizli.olan", "Gizli", default=1, category=Category.TRAY, hidden=True),
    )
    instance = SettingsPanel()
    instance._recompute()
    return instance


def _kartlar(panel: SettingsPanel) -> list[str]:
    return [card.key for card in panel._state.cards]


def _kart(panel: SettingsPanel, key: str):
    return next(card for card in panel._state.cards if card.key == key)


# ---- saf metin yardimcilari ----


def test_status_text_qt_ile_ayni():
    assert status_text(26, 3) == "26 ayar, 3 degismis"


def test_value_text_varsayilanda_bos():
    item = Setting("a.b", "A", default=8)
    assert value_text(item) == ""


def test_value_text_degismisse_degeri_yazar():
    item = Setting("a.b", "A", default=8)
    item.set(5)
    assert value_text(item) == "5"


def test_bool_secenekleri_acik_kapali():
    item = Setting("a.b", "A", default=True)
    assert choice_rows(item) == (("true", "acik", True), ("false", "kapali", False))
    assert current_choice(item) == "true"


def test_bool_varsayilani_kapaliysa_isaret_orada():
    item = Setting("a.b", "A", default=False)
    assert choice_rows(item) == (("true", "acik", False), ("false", "kapali", True))


def test_enum_secenekleri_etiketli():
    item = Setting(
        "a.b", "A", default="light", choices=("light", "dark"), labels={"light": "Acik"}
    )
    assert choice_rows(item) == (("light", "Acik", True), ("dark", "dark", False))
    assert current_choice(item) == "light"


# ---- kart goruntusu ----


def test_kart_tipi_ve_aciklamasi():
    item = Setting("a.b", "A", default=8, desc="aciklama")
    card = card_of(item)
    assert (card.kind, card.desc, card.default) == ("int", "aciklama", "8")


def test_aciklamasiz_kartta_anahtar_gorunur():
    """Qt: `item.desc or item.key` -- kartin ikinci satiri bos kalmasin."""
    assert card_of(Setting("a.b", "A", default=8)).desc == "a.b"


def test_bilgi_hucresi_araliktan_geliyor():
    item = Setting("a.b", "A", default=8, validate=between(1, 9, "ms"))
    assert card_of(item).info == "1-9 ms"


def test_gecersiz_deger_bilgi_hucresine_dusmuyorsa_gerekce_yazilir():
    """Bilgisi OLMAYAN ayarda ret gerekcesi o bos hucreye dusuyor."""
    item = Setting("a.b", "A", default="x")
    assert card_of(item, "Gecersiz deger: A").info == "Gecersiz deger: A"


def test_bilgi_varsa_gerekce_hucreyi_ezmez():
    item = Setting("a.b", "A", default=8, validate=between(1, 9))
    assert card_of(item, "1-9 arasi olmali").info == "1-9"


# ---- kategori listesi ----


def test_kategori_sirasi_ayrac_ve_tumu(panel):
    rows = category_rows()
    assert rows[-1].label.startswith(ALL_LABEL)
    assert rows[-2].key == Category.DEVELOPMENT  # ayracin ALTINDA
    assert rows[-3].separator
    assert Category.DEVELOPMENT not in [row.key for row in rows[:-2]]


def test_kategori_sayaci_gizliyi_saymaz(panel):
    rows = {row.key: row.label for row in category_rows()}
    assert rows[Category.TRAY] == "Sistem tepsisi (1)"  # gizli ayar sayilmiyor


def test_tumu_sayaci_gorunur_ayar_sayisi(panel):
    assert category_rows()[-1].label == f"{ALL_LABEL} (4)"


# ---- suzgec ----


def test_acilista_hepsi_listelenir(panel):
    assert _kartlar(panel) == ["app.theme", "mouse.delay", "tray.tips", "dev.verbose"]
    assert panel._state.status == "4 ayar, 0 degismis"


def test_gizli_ayar_listede_yok(panel):
    assert "gizli.olan" not in _kartlar(panel)


def test_arama_ad_ve_etikette(panel):
    panel._query = "renk"
    panel._recompute()
    assert _kartlar(panel) == ["app.theme"]


def test_arama_boslukla_ve(panel):
    panel._query = "fare gecikmesi"
    panel._recompute()
    assert _kartlar(panel) == ["mouse.delay"]


def test_kategori_suzgeci(panel):
    panel._category = Category.MOUSE
    panel._recompute()
    assert _kartlar(panel) == ["mouse.delay"]


def test_arama_kategori_suzgecini_kaldirir(panel):
    """AHK ile ayni karar: arama varken kategori suzgeci devre disi."""
    panel._category = Category.MOUSE
    panel._query = "tema"
    panel._recompute()
    assert panel._category == ""
    assert _kartlar(panel) == ["app.theme"]


def test_kategori_basligi_yalniz_suzgecsiz_listede(panel):
    assert [card.group for card in panel._state.cards if card.group]
    panel._category = Category.MOUSE
    panel._recompute()
    assert all(not card.group for card in panel._state.cards)


def test_baslik_kategori_degisince_dusuyor(panel):
    """Kayit sirasi kategoriye gore DEGIL: baslik her degisimde tekrar
    yaziliyor (Qt surumunun ayni davranisi)."""
    gruplar = [card.group for card in panel._state.cards]
    assert gruplar == ["Genel", "Fare", "Sistem tepsisi", "GELISTIRME"]


# ---- deger degistirme ----


def test_menuden_secim_ayari_yazar(panel, defter):
    panel._apply_choice("app.theme", "dark")
    assert defter.by_key["app.theme"].get() == "dark"
    assert _kart(panel, "app.theme").choice == "dark"
    assert _kart(panel, "app.theme").changed


def test_bool_secimi_metinden_cozuluyor(panel, defter):
    panel._apply_choice("tray.tips", "false")
    assert defter.by_key["tray.tips"].get() is False


def test_tema_degisince_uyari_yaziliyor(panel):
    """Flet panelleri koyu sabit -- kullanici sebebini aramasin."""
    panel._apply_choice("app.theme", "dark")
    assert panel._state.note == THEME_NOTE


def test_baska_ayarda_uyari_yok(panel):
    panel._apply_choice("tray.tips", "false")
    assert panel._state.note == ""


def test_yazilan_sayi_ayari_yazar(panel, defter):
    panel._apply_typed("mouse.delay", "5")
    assert defter.by_key["mouse.delay"].get() == 5
    assert _kart(panel, "mouse.delay").text == "5"


def test_gecersiz_sayi_ayari_degistirmez(panel, defter):
    panel._apply_typed("mouse.delay", "999")
    assert defter.by_key["mouse.delay"].get() == 8
    assert panel._state.invalid["mouse.delay"] == "1-9 arasi olmali"
    assert _kart(panel, "mouse.delay").invalid


def test_gecersiz_degerden_sonra_gecerli_deger_temizler(panel):
    panel._apply_typed("mouse.delay", "999")
    panel._apply_typed("mouse.delay", "3")
    assert panel._state.invalid == {}
    assert not _kart(panel, "mouse.delay").invalid


def test_bos_kutu_varsayilana_doner(panel, defter):
    """Qt: BOS = varsayilan -- kutu varsayilandayken zaten bos duruyor."""
    panel._apply_typed("mouse.delay", "3")
    panel._apply_typed("mouse.delay", "")
    assert defter.by_key["mouse.delay"].get() == 8
    assert _kart(panel, "mouse.delay").text == ""


def test_sifirlama_dugmesi(panel, defter):
    panel._apply_typed("mouse.delay", "3")
    panel._reset_one("mouse.delay")
    assert defter.by_key["mouse.delay"].get() == 8
    assert not _kart(panel, "mouse.delay").changed


def test_sifirlama_gecersiz_isaretini_kaldirir(panel):
    panel._apply_typed("mouse.delay", "999")
    panel._reset_one("mouse.delay")
    assert panel._state.invalid == {}


def test_tanimsiz_anahtar_dusurmez(panel):
    panel._apply_choice("yok.boyle", "x")
    panel._apply_typed("yok.boyle", "5")
    panel._reset_one("yok.boyle")


def test_degisiklik_alt_satiri_tazeler(panel):
    panel._apply_typed("mouse.delay", "3")
    assert panel._state.status == "4 ayar, 1 degismis"


def test_degisiklik_listeyi_yeniden_kurmaz(panel):
    """Qt'deki kural: kart kendini tazeliyor, liste ayakta kaliyor."""
    onceki = _kartlar(panel)
    panel._apply_typed("mouse.delay", "3")
    assert _kartlar(panel) == onceki


def test_tek_kart_tazelenirken_baslik_korunur(panel):
    """Kart yerine yenisi geciyor; kategori basligi onun uzerindeydi."""
    onceki = _kart(panel, "mouse.delay").group
    panel._apply_typed("mouse.delay", "3")
    assert _kart(panel, "mouse.delay").group == onceki


# ---- toplu islem ----


def test_tumu_varsayilana(panel, defter):
    panel._apply_typed("mouse.delay", "3")
    panel._apply_choice("tray.tips", "false")
    panel._reset_all_now()
    assert defter.by_key["mouse.delay"].get() == 8
    assert defter.by_key["tray.tips"].get() is True
    assert panel._state.status == "4 ayar, 0 degismis"


def test_toplu_sifirlama_tema_degismediyse_uyari_yok(panel):
    panel._apply_typed("mouse.delay", "3")
    panel._reset_all_now()
    assert panel._state.note == ""


def test_toplu_sifirlama_temayi_geri_alirsa_uyariyor(panel):
    panel._apply_choice("app.theme", "dark")
    panel._reset_all_now()
    assert panel._state.note == THEME_NOTE


def test_toplu_sifirlama_gecersizleri_temizler(panel):
    panel._apply_typed("mouse.delay", "999")
    panel._reset_all_now()
    assert panel._state.invalid == {}


# ---- disk ----


def test_kapanista_kaydediyor(panel, defter, tmp_path, monkeypatch):
    """Qt: `closeEvent` -- ekran acikken her degisiklikte yazilmiyor."""
    hedef = tmp_path / "settings.json"
    monkeypatch.setattr(fui_settings.paths, "SETTINGS", hedef)
    panel._apply_typed("mouse.delay", "3")
    assert not hedef.exists()
    # `Registry.save` yalniz KIRLIYKEN yaziyor. Bayragi `Setting.set`
    # koyuyor ama GERCEK deftere (`settings.SETTINGS` modul degiskeni),
    # test defterine degil -- bu testte elle konuyor.
    defter.dirty = True
    panel._save()
    assert '"mouse.delay": 3' in hedef.read_text(encoding="utf-8")


def test_json_ac_once_diske_yazar(panel, defter, tmp_path, monkeypatch):
    hedef = tmp_path / "settings.json"
    monkeypatch.setattr(fui_settings.paths, "SETTINGS", hedef)
    acilan: list = []
    monkeypatch.setattr(fui_settings.subprocess, "Popen", acilan.append)
    panel._apply_typed("mouse.delay", "3")
    panel._open_json_now()
    assert hedef.exists()
    assert acilan == [["notepad.exe", str(hedef)]]
