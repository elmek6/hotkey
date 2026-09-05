"""Profil yoneticisi penceresi (ui/profiles_view.py).

AHK `showManagerGui` port edilmemisti; duzenleme dogrudan profiles.json'dan
yapiliyordu. Bu testler hem pencereyi hem de yeni eklenen `ShortcutStore.save`
yolunu kapsiyor -- dosya AHK ile PAYLASILDIGI icin bicimin bozulmamasi kritik.
"""

import codecs

import orjson
import pytest

from keypilot.app_shorts import ShortcutStore
from keypilot.ui.profiles_view import ProfilesView

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
def view(qapp, tmp_path):
    (tmp_path / "profiles.json").write_bytes(codecs.BOM_UTF8 + orjson.dumps(ORNEK))
    pencere = ProfilesView(ShortcutStore(tmp_path))
    pencere.open()
    pencere.hide()
    return pencere


def _diskten(view: ProfilesView) -> dict:
    return orjson.loads(view.store.path.read_bytes().lstrip(codecs.BOM_UTF8))


def _liste(widget) -> list[str]:
    return [widget.item(i).text() for i in range(widget.count())]


# ---- listeleme ----


def test_profiller_listelenir(view):
    assert _liste(view.profile_list) == ["Chrome", "Firefox"]
    assert view.status.text() == "2 profil, 2 aksiyon"


def test_acilista_ilk_profil_secili(view):
    """AHK hicbir seyi secmiyor ve pencere bos aciliyordu."""
    assert view.name_edit.text() == "Chrome"
    assert _liste(view.action_list) == ["Closed tab", "Yaz"]


def test_ada_gore_acilis(qapp, tmp_path):
    (tmp_path / "profiles.json").write_bytes(codecs.BOM_UTF8 + orjson.dumps(ORNEK))
    pencere = ProfilesView(ShortcutStore(tmp_path))
    pencere.open("Firefox")
    pencere.hide()
    assert pencere.name_edit.text() == "Firefox"


def test_aksiyon_secimi_detayi_doldurur(view):
    view.action_list.setCurrentRow(0)
    assert view.action_name.text() == "Closed tab"
    assert view.action_desc.text() == "son sekmeyi ac"
    assert view.strokes_edit.toPlainText() == "^+t"


# ---- eslesme kurali gorunur mu ----


def test_kural_metni_iki_kosulu_da_soyler(view):
    metin = view.rule.text()
    assert "Chrome_WidgetWin_1" in metin
    assert "Google Chrome" in metin


def test_bos_profil_kurali_uyarir(view):
    """Sinif da baslik da bossa profil HER pencereye uyar ve sonrakileri
    golgeler -- bu, dosyaya bakarak fark edilmesi zor bir tuzak."""
    view.new_profile()
    view.name_edit.setText("bos")
    view.save_profile()
    assert "HER pencereye uyar" in view.rule.text()


def test_stroke_ipucu_kisayol_ile_metni_ayirir(view):
    """`abc` ile `^+t` arasindaki fark dosyada gorunmuyordu."""
    view.strokes_edit.setPlainText("^+t\nmerhaba")
    ipucu = view.stroke_hint.text()
    assert "`^+t` → kisayol" in ipucu
    assert "`merhaba` → duz metin" in ipucu


# ---- profil yazma ----


def test_yeni_profil_diske_yazilir(view):
    view.new_profile()
    view.name_edit.setText("Notepad")
    view.class_edit.setText("Notepad")
    view.title_edit.setText("Not Defteri")
    view.save_profile()

    isimler = [p["profileName"] for p in _diskten(view)["profiles"]]
    assert isimler == ["Chrome", "Firefox", "Notepad"]


def test_profil_guncelleme_yeni_kayit_ACMAZ(view):
    view.profile_list.setCurrentRow(0)
    view.title_edit.setText("Chromium")
    view.save_profile()

    profiller = _diskten(view)["profiles"]
    assert len(profiller) == 2
    assert profiller[0]["title"] == "Chromium"


def test_profil_adi_zorunlu(view, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    uyari: list = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: uyari.append(a))
    view.new_profile()
    view.save_profile()
    assert uyari
    assert len(_diskten(view)["profiles"]) == 2


def test_profil_silinir(view, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    view.profile_list.setCurrentRow(1)
    view.delete_profile()
    assert [p["profileName"] for p in _diskten(view)["profiles"]] == ["Chrome"]


# ---- aksiyon yazma ----


def test_yeni_aksiyon_eklenir(view):
    view.profile_list.setCurrentRow(1)  # Firefox, aksiyonu yok
    view.new_action()
    view.action_name.setText("Yeni sekme")
    view.strokes_edit.setPlainText("^t")
    view.save_action()

    firefox = _diskten(view)["profiles"][1]
    assert [s["shortCutName"] for s in firefox["shortCuts"]] == ["Yeni sekme"]
    assert firefox["shortCuts"][0]["keyStrokes"] == ["^t"]


def test_cok_satirli_tuslar_ayri_dizi_olur(view):
    """AHK `StrSplit(..., "\\n", "\\r")`: her satir bir Send."""
    view.profile_list.setCurrentRow(1)
    view.new_action()
    view.action_name.setText("uclu")
    view.strokes_edit.setPlainText("^a\n\n  ^c  \n{Enter}")
    view.save_action()

    strokes = _diskten(view)["profiles"][1]["shortCuts"][0]["keyStrokes"]
    assert strokes == ["^a", "^c", "{Enter}"]  # bos satir elendi, bosluk kirpildi


def test_aksiyon_guncelleme_kopya_uretmez(view):
    view.action_list.setCurrentRow(0)
    view.action_name.setText("Closed tab v2")
    view.save_action()

    kisayollar = _diskten(view)["profiles"][0]["shortCuts"]
    assert len(kisayollar) == 2
    assert kisayollar[0]["shortCutName"] == "Closed tab v2"


def test_aksiyon_adi_zorunlu(view, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    uyari: list = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: uyari.append(a))
    view.new_action()
    view.strokes_edit.setPlainText("^t")
    view.save_action()
    assert uyari
    assert len(_diskten(view)["profiles"][0]["shortCuts"]) == 2


def test_profilsiz_aksiyon_kaydedilemez(view, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    uyari: list = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: uyari.append(a))
    view.new_profile()  # profil secili degil
    view.action_name.setText("x")
    view.save_action()
    assert uyari


def test_aksiyon_silinir(view, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    view.action_list.setCurrentRow(0)
    view.delete_action()
    assert [s["shortCutName"] for s in _diskten(view)["profiles"][0]["shortCuts"]] == [
        "Yaz"
    ]


# ---- sira ----


def test_aksiyon_asagi_tasinir(view):
    """Sira F13 menusundeki siradir, yani gorunur bir sonuc."""
    view.action_list.setCurrentRow(0)
    view.move_action(1)
    assert [s["shortCutName"] for s in _diskten(view)["profiles"][0]["shortCuts"]] == [
        "Yaz",
        "Closed tab",
    ]
    assert view.action_list.currentRow() == 1  # secim tasinan ogeyle gitti


def test_sinirdan_disari_tasima_yok_sayilir(view):
    view.action_list.setCurrentRow(0)
    view.move_action(-1)
    assert [s["shortCutName"] for s in _diskten(view)["profiles"][0]["shortCuts"]] == [
        "Closed tab",
        "Yaz",
    ]


# ---- dosya bicimi (AHK ile PAYLASILIYOR) ----


def test_yazilan_dosya_BOM_ve_anahtar_adlarini_korur(view):
    view.new_profile()
    view.name_edit.setText("x")
    view.save_profile()

    ham = view.store.path.read_bytes()
    assert ham.startswith(codecs.BOM_UTF8)  # AHK FileIO.writeText boyle yaziyor
    veri = orjson.loads(ham.lstrip(codecs.BOM_UTF8))
    assert veri["projectName"] == "ProfileManager"
    assert set(veri["profiles"][0]) == {"profileName", "className", "title", "shortCuts"}
    assert set(veri["profiles"][0]["shortCuts"][0]) == {
        "shortCutName",
        "keyDescription",
        "keyStrokes",
    }


def test_yaz_oku_dongusu_veriyi_degistirmez(qapp, tmp_path):
    yol = tmp_path / "profiles.json"
    yol.write_bytes(codecs.BOM_UTF8 + orjson.dumps(ORNEK))
    store = ShortcutStore(tmp_path)
    store.load()
    assert store.save()

    tekrar = ShortcutStore(tmp_path)
    tekrar.load()
    assert [(p.name, p.class_name, p.title) for p in tekrar.profiles] == [
        (p.name, p.class_name, p.title) for p in store.profiles
    ]
    assert orjson.loads(yol.read_bytes().lstrip(codecs.BOM_UTF8)) == ORNEK


def test_yazma_yarim_kalirsa_eski_dosya_yerinde_kalir(view, monkeypatch):
    """`.tmp` + `os.replace`: AHK dosyayi tek parca yaziyordu."""
    import keypilot.app_shorts as modul

    monkeypatch.setattr(
        modul.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk dolu"))
    )
    onceki = view.store.path.read_bytes()
    assert view.store.save() is False
    assert view.store.path.read_bytes() == onceki
    assert not list(view.store.path.parent.glob("*.tmp"))  # gecici dosya temizlendi
