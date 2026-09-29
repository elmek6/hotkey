"""Slot penceresi (ui/slots_view.py).

Pencere gosterilmiyor; kurulup dogrudan suruluyor ve "hangi sekme var, diske
ne yazildi" soruluyor. Dosya her testte `tmp_path` altinda, gercek
`Files/slots.json`a dokunulmuyor.
"""

import orjson
import pytest
from PySide6.QtWidgets import (
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QStyleOptionViewItem,
)

from keypilot.store import BOM, DEFAULT_GROUP, MASK, SLOTS_PER_GROUP, SlotStore
from keypilot.ui.slots_view import MAIN_TAB, SIDE_MARK, VALUE_COLUMN, SlotsView


def _dosya(yol, groups: list[dict], default: str = "") -> None:
    payload = {"defaultGroupName": default, "groups": groups}
    (yol / "slots.json").write_bytes(BOM + orjson.dumps(payload))


def _grup(ad: str, icerikler: dict[int, str] | None = None) -> dict:
    icerikler = icerikler or {}
    return {
        "groupName": ad,
        "values": [
            {"content": icerikler.get(i, ""), "name": f"Slot {i}"}
            for i in range(1, SLOTS_PER_GROUP + 1)
        ],
    }


@pytest.fixture
def view(qapp, tmp_path):
    _dosya(
        tmp_path,
        [_grup("", {1: "bir", 2: "a\r\nb"}), _grup("is", {3: "uc"}), _grup("ev")],
        default="ev",
    )
    pencere = SlotsView(SlotStore(tmp_path))
    pencere.reload()
    return pencere


def _etiketler(view: SlotsView) -> list[str]:
    return [view.tabs.tabText(i) for i in range(view.tabs.count())]


def _diskteki(tmp_path) -> dict:
    return orjson.loads((tmp_path / "slots.json").read_bytes().lstrip(BOM))


def _sayfa(view: SlotsView, grup: str):
    return next(page for page in view.pages() if page.group == grup)


def _editor(sayfa, slot: int):
    """Deger hucresinin editorunu delegenin kendisiyle kurar (tik yerine)."""
    index = sayfa.model().index(slot - 1, VALUE_COLUMN)
    delegate = sayfa.itemDelegate()
    editor = delegate.createEditor(sayfa.viewport(), QStyleOptionViewItem(), index)
    delegate.setEditorData(editor, index)
    return editor, index


# ---- listeleme ----


def test_sekme_sirasi_ana_grup_ilk_ve_yan_grup_isaretli(view):
    assert _etiketler(view) == [MAIN_TAB, "is", f"{SIDE_MARK}ev"]
    assert MAIN_TAB == "@"


def test_her_sekmede_on_satir_ve_tus_numaralari(view):
    for page in view.pages():
        assert page.rowCount() == SLOTS_PER_GROUP
        assert [page.key(i) for i in range(1, 11)] == [*"123456789", "0"]


def test_icerik_satirlara_dolar(view):
    ana = _sayfa(view, DEFAULT_GROUP)
    assert ana.value(1) == "bir"
    assert _sayfa(view, "is").value(3) == "uc"


def test_acilista_diskten_okur(view, tmp_path):
    _dosya(tmp_path, [_grup("", {1: "yeni"})])
    view.open()
    view.close()
    assert view.pages()[0].value(1) == "yeni"
    assert _etiketler(view) == [MAIN_TAB]


# ---- kaydetme ----


def test_baslangicta_kirli_degil(view):
    assert not view.is_dirty()
    assert view.save_button.styleSheet() == ""


def test_degisiklik_kaydet_dugmesini_isaretler(view):
    view.pages()[0].set_value(5, "x")
    assert view.is_dirty()
    assert view.save_button.styleSheet() != ""


def test_eski_haline_donunce_kirli_kalmaz(view):
    sayfa = view.pages()[0]
    sayfa.set_value(1, "baska")
    sayfa.set_value(1, "bir")
    assert not view.is_dirty()


def test_yalniz_degisen_slot_yazilir(view, tmp_path):
    sayfa = _sayfa(view, "is")
    sayfa.set_value(5, "bes")
    sayfa.set_name(5, "besinci")
    view.save()

    disk = _diskteki(tmp_path)
    is_grubu = next(g for g in disk["groups"] if g["groupName"] == "is")
    assert is_grubu["values"][4] == {"content": "bes", "name": "besinci"}
    assert not view.is_dirty()
    assert view.save_button.styleSheet() == ""


def test_crlf_iceren_dokunulmamis_slot_aynen_kalir(view, tmp_path):
    view.pages()[0].set_value(6, "alti")
    view.save()

    ana = _diskteki(tmp_path)["groups"][0]
    assert ana["values"][1]["content"] == "a\r\nb"
    assert ana["values"][5]["content"] == "alti"


def test_degisiklik_yoksa_dosyaya_dokunulmaz(view, tmp_path):
    once = (tmp_path / "slots.json").read_bytes()
    view.save()
    assert (tmp_path / "slots.json").read_bytes() == once


def test_kaydetmeden_once_disk_tazelenir(view, tmp_path):
    """F14'ten bu arada yazilan slot ezilmemeli."""
    diger = SlotStore(tmp_path)
    diger.load()
    diger.set_slot_content("", 9, "f14ten")

    view.pages()[0].set_value(1, "pencereden")
    view.save()

    ana = _diskteki(tmp_path)["groups"][0]
    assert ana["values"][0]["content"] == "pencereden"
    assert ana["values"][8]["content"] == "f14ten"
    assert view.pages()[0].value(9) == "f14ten"


def test_sifre_slotu_maskeli_ve_duzenlenebilir(view, tmp_path):
    sayfa = view.pages()[0]
    sayfa.set_value(10, "parola")
    assert sayfa.item(9, VALUE_COLUMN).text() == MASK
    assert sayfa.item(9, VALUE_COLUMN).toolTip() == ""
    editor, _index = _editor(sayfa, 10)
    assert isinstance(editor, QLineEdit)
    assert editor.echoMode() == QLineEdit.EchoMode.Password
    view.save()
    assert _diskteki(tmp_path)["groups"][0]["values"][9]["content"] == "parola"


def test_hucre_tek_satir_ipucu_tam_icerik(view):
    item = view.pages()[0].item(1, VALUE_COLUMN)
    assert item.text() == "a b"
    assert item.toolTip() == "a<br>b"


def test_editor_cok_satirli_ve_degismeden_kapaninca_yazmaz(view, tmp_path):
    sayfa = view.pages()[0]
    editor, index = _editor(sayfa, 2)
    assert isinstance(editor, QPlainTextEdit)
    assert editor.toPlainText() == "a\nb"
    sayfa.itemDelegate().setModelData(editor, sayfa.model(), index)
    assert sayfa.value(2) == "a\r\nb"
    assert not view.is_dirty()


def test_editorde_degisen_deger_hucreye_ve_diske_gecer(view, tmp_path):
    sayfa = view.pages()[0]
    editor, index = _editor(sayfa, 2)
    editor.setPlainText("a\nb\nc")
    sayfa.itemDelegate().setModelData(editor, sayfa.model(), index)
    assert view.is_dirty()
    view.save()
    assert _diskteki(tmp_path)["groups"][0]["values"][1]["content"] == "a\nb\nc"


# ---- gruplar ----


def _ad_ver(monkeypatch, ad: str, ok: bool = True) -> None:
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (ad, ok)))


def _cevap(monkeypatch, cevap) -> list:
    sorulan: list = []

    def soru(*args, **kwargs):
        sorulan.append(args)
        return cevap

    monkeypatch.setattr(QMessageBox, "question", staticmethod(soru))
    return sorulan


def test_yeni_grup_acilir_yan_grup_secilir_ve_sekmesi_gosterilir(view, tmp_path, monkeypatch):
    _ad_ver(monkeypatch, "  proje ")
    view.new_group()

    assert _etiketler(view) == [MAIN_TAB, "is", "ev", f"{SIDE_MARK}proje"]
    assert view.current_group() == "proje"
    assert [view.pages()[-1].value(i) for i in range(1, 11)] == [""] * SLOTS_PER_GROUP
    disk = _diskteki(tmp_path)
    assert disk["defaultGroupName"] == "proje"
    assert [g["groupName"] for g in disk["groups"]] == ["", "is", "ev", "proje"]


def test_var_olan_grup_yeniden_acilmaz(view, tmp_path, monkeypatch):
    _ad_ver(monkeypatch, "is")
    uyarilar: list = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: uyarilar.append(a)))
    view.new_group()
    assert uyarilar
    assert _etiketler(view) == [MAIN_TAB, "is", f"{SIDE_MARK}ev"]
    assert _diskteki(tmp_path)["defaultGroupName"] == "ev"


def test_yeni_grup_vazgecilirse_bir_sey_olmaz(view, tmp_path, monkeypatch):
    once = (tmp_path / "slots.json").read_bytes()
    _ad_ver(monkeypatch, "x", ok=False)
    view.new_group()
    assert (tmp_path / "slots.json").read_bytes() == once


def test_grup_silme_onay_sorar_ve_siler(view, tmp_path, monkeypatch):
    sorulan = _cevap(monkeypatch, QMessageBox.StandardButton.Yes)
    view.tabs.setCurrentIndex(2)  # ev: secili yan grup
    view.delete_group()

    assert sorulan
    assert _etiketler(view) == [MAIN_TAB, "is"]
    assert view.current_group() == DEFAULT_GROUP
    disk = _diskteki(tmp_path)
    assert [g["groupName"] for g in disk["groups"]] == ["", "is"]
    assert disk["defaultGroupName"] == ""


def test_grup_silme_reddedilirse_kalir(view, tmp_path, monkeypatch):
    _cevap(monkeypatch, QMessageBox.StandardButton.No)
    view.tabs.setCurrentIndex(1)
    view.delete_group()
    assert _etiketler(view) == [MAIN_TAB, "is", f"{SIDE_MARK}ev"]


def test_ana_grup_silinemez(view, tmp_path, monkeypatch):
    sorulan = _cevap(monkeypatch, QMessageBox.StandardButton.Yes)
    view.tabs.setCurrentIndex(0)
    assert not view.delete_button.isEnabled()
    view.delete_group()
    assert not sorulan
    assert _diskteki(tmp_path)["groups"][0]["groupName"] == ""
    view.tabs.setCurrentIndex(1)
    assert view.delete_button.isEnabled()


def test_grup_islemi_kaydedilmemis_degisikligi_dusurur(view, tmp_path, monkeypatch):
    view.pages()[0].set_value(1, "kaydedilmedi")
    assert view.is_dirty()
    _ad_ver(monkeypatch, "yeni")
    view.new_group()

    assert not view.is_dirty()
    assert view.save_button.styleSheet() == ""
    assert _diskteki(tmp_path)["groups"][0]["values"][0]["content"] == "bir"


def test_yan_grup_secimi_isareti_diskle_ayni(view, tmp_path, monkeypatch):
    """Isaret F14'ten degisen secimi de gosterir (acilista diskten okunur)."""
    diger = SlotStore(tmp_path)
    diger.load()
    diger.set_default_group("is")
    view.open()
    view.close()
    assert _etiketler(view) == [MAIN_TAB, f"{SIDE_MARK}is", "ev"]


# ---- baglanti ----


def test_backtick_menusunde_madde_var():
    from keypilot import keymap
    from keypilot.commands import Cmd

    assert Cmd.Slots.EDITOR == "slots.editor"
    assert ("s: Slot duzenle", Cmd.Slots.EDITOR) in keymap.SYS_COMMANDS_MENU


# ---- iki pencere ----


@pytest.fixture
def pencereler(qapp, tmp_path):
    from keypilot.ui.slots_view import SlotsWindows

    _dosya(tmp_path, [_grup("", {1: "bir"}), _grup("is")])
    ikili = SlotsWindows(SlotStore(tmp_path))
    yield ikili
    ikili.close()


def test_en_fazla_iki_pencere_acilir(pencereler):
    from keypilot.ui.slots_view import MAX_WINDOWS

    for _ in range(MAX_WINDOWS + 1):
        pencereler.open()
    assert MAX_WINDOWS == 2
    assert [view.isVisible() for view in pencereler.views] == [True, True]
    assert pencereler.views[1].windowTitle().endswith("(2)")


def test_kaydedince_temiz_diger_pencere_tazelenir(pencereler):
    birinci, ikinci = pencereler.views
    pencereler.open()
    pencereler.open()
    birinci.pages()[0].set_value(2, "iki")
    birinci.save()
    assert ikinci.pages()[0].value(2) == "iki"


def test_kaydedilmemis_degisikligi_olan_pencere_tazelenmez(pencereler, tmp_path):
    birinci, ikinci = pencereler.views
    pencereler.open()
    pencereler.open()
    ikinci.pages()[0].set_value(3, "uc")
    birinci.pages()[0].set_value(2, "iki")
    birinci.save()

    assert ikinci.pages()[0].value(3) == "uc"
    assert ikinci.is_dirty()
    ikinci.save()
    ana = _diskteki(tmp_path)["groups"][0]["values"]
    assert (ana[1]["content"], ana[2]["content"]) == ("iki", "uc")


def test_grup_islemi_diger_pencereye_yansir(pencereler, monkeypatch):
    birinci, ikinci = pencereler.views
    pencereler.open()
    pencereler.open()
    _ad_ver(monkeypatch, "yeni")
    birinci.new_group()
    assert _etiketler(ikinci) == [MAIN_TAB, "is", f"{SIDE_MARK}yeni"]
