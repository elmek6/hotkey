"""F13 profil menusunun BICIMI (app.py `_shortcut_*`).

Menu gosterilmiyor -- spec demeti kurulup okunuyor. Buradaki sorular
duzenin kendisiyle ilgili: bakim maddeleri ana menuye sizmis mi, alt menu
basligi on plandaki pencereyi soyluyor mu, hedefi olmayan madde tiklanabilir
kalmis mi.
"""

from __future__ import annotations

import pytest

from keypilot import app as app_module
from keypilot.app_shorts import AppProfile, ShortCut
from keypilot.ui.menu import DISABLED
from tests.test_app_wiring import FakeHook

VSCODE = AppProfile(
    name="VSCode",
    class_name="Chrome_WidgetWin_1",
    title="Visual Studio Code",
    shortcuts=(ShortCut(name="format", strokes=("^!f",)),),
)
BOS = AppProfile(name="Bos", class_name="BosClass")


@pytest.fixture
def keypilot(qapp, monkeypatch):
    monkeypatch.setattr(app_module, "HookThread", FakeHook)
    monkeypatch.setattr(app_module.KeyPilot, "on_start", lambda self: None)
    instance = app_module.KeyPilot(qapp)
    instance.shorts.profiles = [VSCODE, BOS]
    yield instance
    instance._shutdown()


def _pencere(monkeypatch, class_name: str, title: str) -> None:
    monkeypatch.setattr(app_module, "foreground_window", lambda: 1)
    monkeypatch.setattr(app_module, "window_class", lambda _h: class_name)
    monkeypatch.setattr(app_module, "window_title", lambda _h: title)


def _etiketler(rows) -> list[str]:
    return [row[0] for row in rows if row is not None]


def _madde(rows, prefix: str):
    return next(row for row in rows if row is not None and row[0].startswith(prefix))


# ---- ana menu ----


def test_ana_menude_yalniz_calistirilacak_maddeler_var(keypilot, monkeypatch):
    """"Profili duzenle" ve "Profil ekle" ana menuden alt menuye tasindi."""
    _pencere(monkeypatch, "Chrome_WidgetWin_1", "x - Visual Studio Code")
    items = keypilot._shortcut_menu_items()
    assert [row[1] for row in items] == ["shorts.play:VSCode/0"]


def test_profil_yoksa_ana_menuye_HICBIR_SEY_eklenmez(keypilot, monkeypatch):
    _pencere(monkeypatch, "Notepad", "Adsiz - Not Defteri")
    assert keypilot._shortcut_menu_items() == ()


# ---- alt menu basligi ----


def test_baslik_eslesen_profilin_adini_tasir(keypilot, monkeypatch):
    _pencere(monkeypatch, "Chrome_WidgetWin_1", "x - Visual Studio Code")
    title, _rows = keypilot._shortcut_manager_item()
    assert title == "Profil (VSCode)"


def test_baslik_profil_yokken_ekle_der(keypilot, monkeypatch):
    _pencere(monkeypatch, "Notepad", "Adsiz - Not Defteri")
    title, _rows = keypilot._shortcut_manager_item()
    assert title == "Profil (ekle)"


# ---- bakim maddeleri ----


def test_ekle_maddesi_sinif_adini_tasir(keypilot, monkeypatch):
    _pencere(monkeypatch, "Notepad", "Adsiz - Not Defteri")
    _title, rows = keypilot._shortcut_manager_item()
    label, action, *rest = _madde(rows, "Profil ekle")
    assert label == "Profil ekle (Notepad)"
    assert action == "shorts.add:Notepad"
    assert DISABLED not in rest


def test_sinifsiz_pencerede_ekle_maddesi_SOLUK(keypilot, monkeypatch):
    _pencere(monkeypatch, "", "")
    _title, rows = keypilot._shortcut_manager_item()
    label, action, *rest = _madde(rows, "Profil ekle")
    assert label == "Profil ekle"
    assert action == ""
    assert DISABLED in rest


def test_duzenle_maddesi_eslesen_profili_hedefler(keypilot, monkeypatch):
    _pencere(monkeypatch, "Chrome_WidgetWin_1", "x - Visual Studio Code")
    _title, rows = keypilot._shortcut_manager_item()
    label, action, *rest = _madde(rows, "Profil duzenle")
    assert label == "Profil duzenle (VSCode)"
    assert action == "shorts.manage:VSCode"
    assert DISABLED not in rest


def test_duzenle_profil_yokken_de_CALISIR(keypilot, monkeypatch):
    """Duzenle hicbir zaman soluk degil: argumansiz `shorts.manage` genel
    yonetici penceresini aciyor, yani hedefsiz kalmiyor."""
    _pencere(monkeypatch, "Notepad", "Adsiz - Not Defteri")
    _title, rows = keypilot._shortcut_manager_item()
    label, action, *rest = _madde(rows, "Profil duzenle")
    assert (label, action) == ("Profil duzenle", "shorts.manage")
    assert DISABLED not in rest


def test_profiles_json_duzenle_maddesi_KALKTI(keypilot, monkeypatch):
    _pencere(monkeypatch, "Notepad", "Adsiz - Not Defteri")
    _title, rows = keypilot._shortcut_manager_item()
    assert not any(row and "shorts.edit" in str(row[1]) for row in rows)


# ---- profil listesi ----


def test_her_profil_kendi_alt_menusunde_kalir(keypilot, monkeypatch):
    _pencere(monkeypatch, "Chrome_WidgetWin_1", "x - Visual Studio Code")
    _title, rows = keypilot._shortcut_manager_item()
    etiketler = _etiketler(rows)
    assert any(label.startswith("VSCode") for label in etiketler)
    assert any(label.startswith("Bos") for label in etiketler)


def test_kisayolsuz_profil_duzenlemeye_gotururur(keypilot, monkeypatch):
    _pencere(monkeypatch, "Notepad", "Adsiz - Not Defteri")
    _title, rows = keypilot._shortcut_manager_item()
    bos = _madde(rows, "Bos")
    assert bos[1] == (("(kisayol yok)", "shorts.manage:Bos"),)


def test_ekle_ve_duzenle_ayracin_altinda(keypilot, monkeypatch):
    _pencere(monkeypatch, "Notepad", "Adsiz - Not Defteri")
    _title, rows = keypilot._shortcut_manager_item()
    ayrac = rows.index(None)
    assert [row[0] for row in rows[ayrac + 1 :]] == ["Profil ekle (Notepad)", "Profil duzenle"]
