"""app_shorts.py -- AHK `findProfileByWindow` kurallarinin karsiligi."""

from __future__ import annotations

import codecs

from cascade.app_shorts import ShortcutStore, stroke_kind

SAMPLE = (
    '{"projectName":"ProfileManager","profiles":['
    '{"className":"Chrome_WidgetWin_1","profileName":"vs","title":"Visual Studio Code",'
    '"shortCuts":[{"keyDescription":"","keyStrokes":["abc"],"shortCutName":"ac1"}]},'
    '{"className":"Chrome_WidgetWin_1","profileName":"Chrome","title":"Google Chrome",'
    '"shortCuts":[{"keyDescription":"geri ac","keyStrokes":["^+t"],'
    '"shortCutName":"Closed tab"}]},'
    '{"className":"","profileName":"Her yerde","title":"README","shortCuts":[]}]}'
)


def _store(tmp_path, text: str = SAMPLE, bom: bool = True) -> ShortcutStore:
    data = text.encode("utf-8")
    (tmp_path / "profiles.json").write_bytes(codecs.BOM_UTF8 + data if bom else data)
    store = ShortcutStore(directory=tmp_path)
    store.load()
    return store


def test_bom_lu_dosya_okunur(tmp_path):
    """AHK dosyanin basina BOM koyuyor; orjson BOM'u reddeder."""
    assert [p.name for p in _store(tmp_path).profiles] == ["vs", "Chrome", "Her yerde"]


def test_sinif_tam_baslik_parca_eslesir(tmp_path):
    store = _store(tmp_path)
    found = store.find("Chrome_WidgetWin_1", "Yeni sekme - Google Chrome")
    assert found is not None
    assert found.name == "Chrome"


def test_ilk_eslesen_kazanir(tmp_path):
    """Ayni sinifta iki profil var; dosyadaki sira belirleyici."""
    store = _store(tmp_path)
    found = store.find("Chrome_WidgetWin_1", "app.py - Visual Studio Code")
    assert found is not None
    assert found.name == "vs"


def test_bos_sinif_her_pencereye_uyar(tmp_path):
    store = _store(tmp_path)
    found = store.find("NotepadClass", "README.md - Notepad")
    assert found is not None
    assert found.name == "Her yerde"


def test_basliksiz_pencere_eslesmez(tmp_path):
    """AHK: `if (title == "") return false`."""
    assert _store(tmp_path).find("Chrome_WidgetWin_1", "") is None


def test_bozuk_dosya_programi_durdurmaz(tmp_path):
    store = _store(tmp_path, "{bozuk", bom=False)
    assert store.profiles == []
    assert list(tmp_path.glob("profiles.json.bozuk-*"))


def test_kisayol_indeksle_bulunur(tmp_path):
    store = _store(tmp_path)
    shortcut = store.shortcut("Chrome", 0)
    assert shortcut is not None
    assert shortcut.strokes == ("^+t",)
    assert store.shortcut("Chrome", 5) is None
    assert store.shortcut("yok", 0) is None


def test_stroke_kind():
    """`^+t` kisayol, `abc` metin -- AHK'nin tek Send'inin ikiye ayrilmasi."""
    assert stroke_kind("^+t") == "key"
    assert stroke_kind("{Enter}") == "key"
    assert stroke_kind("abc") == "text"
