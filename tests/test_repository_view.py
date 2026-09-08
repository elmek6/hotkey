"""Repository penceresi (ui/repository_view.py).

Pencere gosterilmiyor; kurulup dogrudan surularak "hangi kayit listede,
detayda ne var, diske ne yazildi" soruluyor. AHK'de bu katman hic test
edilemiyordu -- suzgec mantigi GUI olaylarinin icindeydi.
"""

import pytest

from keypilot.repository import Item, Repository, parse
from keypilot.ui.repository_view import TUMU, RepositoryView

ORNEK = """===
uuid: u-1
title: doorbell
category: iot
tags: tuya, zigbee
---
tuya
two way audio
===
uuid: u-2
title: kamera
category: iot
tags: tuya
---
rtsp akisi
===
uuid: u-3
title: not
---
kategorisiz kayit
"""


@pytest.fixture
def view(qapp, tmp_path):
    yol = tmp_path / "repository.md"
    yol.write_text(ORNEK, encoding="utf-8")
    pencere = RepositoryView(Repository(yol))
    pencere.reload_from_disk()
    return pencere


def _basliklar(view: RepositoryView) -> list[str]:
    return [view.results.item(i).text() for i in range(view.results.count())]


def _liste(widget) -> list[str]:
    return [widget.item(i).text() for i in range(widget.count())]


# ---- listeleme ----


def test_acilista_hepsi_listelenir(view):
    assert len(_basliklar(view)) == 3
    assert view.status.text() == "3 / 3 kayit"


def test_kategori_listesinde_TUMU_YOK(view):
    """`(tumu)` etiketlere tasindi; kategoride bos secim ayni ise yariyor."""
    assert _liste(view.categories) == ["iot"]
    assert view.categories.selectedItems() == []


def test_etiketler_tekil_sirali_ve_TUMU_ustte(view):
    assert _liste(view.tags) == [TUMU, "tuya", "zigbee"]
    assert view.tags.item(0).isSelected()


def test_kategorisiz_kayit_parantezsiz_yazilir(view):
    assert "not" in _basliklar(view)
    assert "doorbell (iot)" in _basliklar(view)


# ---- suzgecler ----


def test_arama_govdede_de_suzer(view):
    view.search.setText("rtsp")
    assert _basliklar(view) == ["kamera (iot)"]


def test_kategori_suzgeci(view):
    view.categories.setCurrentRow(0)  # iot
    assert len(_basliklar(view)) == 2


def test_kategori_secimi_kalkinca_suzgec_kalkar(view):
    view.categories.setCurrentRow(0)
    view.categories.clearSelection()
    assert len(_basliklar(view)) == 3


def test_secili_kategoriye_tekrar_tiklamak_secimi_kaldirir(view):
    """`ToggleList`: fare ile suzgeci kaldirmanin tek yolu bu."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    view.categories.setCurrentRow(0)  # iot
    assert len(_basliklar(view)) == 2

    nokta = view.categories.visualItemRect(view.categories.item(0)).center()
    view.categories.mousePressEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(nokta),
            QPointF(view.categories.mapToGlobal(QPoint(nokta.x(), nokta.y()))),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert view.categories.selectedItems() == []
    assert len(_basliklar(view)) == 3


def test_coklu_etiket_HEPSINI_ister(view):
    """AHK `FilterByTags` matchAll: iki etiket secilince ikisini de
    tasiyan kalir -- 'tuya' iki kayitta, 'zigbee' yalniz birinde."""
    view.tags.item(1).setSelected(True)  # tuya
    assert len(_basliklar(view)) == 2
    view.tags.item(2).setSelected(True)  # + zigbee
    assert _basliklar(view) == ["doorbell (iot)"]


def test_suzgecler_birlikte_calisir(view):
    view.search.setText("tuya")
    view.categories.setCurrentRow(0)  # iot
    view.tags.item(2).setSelected(True)  # zigbee
    assert _basliklar(view) == ["doorbell (iot)"]


# ---- detay paneli ----


def test_secim_detaya_yuklenir(view):
    view.results.setCurrentRow(0)
    assert view.title_edit.text() == "doorbell"
    assert view.category_edit.text() == "iot"
    assert view.tags_edit.text() == "tuya, zigbee"
    assert view.text_edit.toPlainText() == "tuya\ntwo way audio"
    assert view.uuid_label.text() == "u-1"


def test_yeni_paneli_bosaltir(view):
    view.results.setCurrentRow(0)
    view.new_item()
    assert view.title_edit.text() == ""
    assert view.uuid_label.text() == "(yeni)"


# ---- kaydetme ----


def test_yeni_kayit_diske_yazilir(view):
    view.new_item()
    view.title_edit.setText("yeni kayit")
    view.category_edit.setText("test")
    view.tags_edit.setText("a, b")
    view.text_edit.setPlainText("govde")
    view.save_current()

    diskte = parse(view.repo.path.read_text(encoding="utf-8"))
    yeni = next(item for item in diskte if item.title == "yeni kayit")
    assert yeni.category == "test"
    assert yeni.tags == ["a", "b"]
    assert yeni.text == "govde"


def test_yeni_kayit_suzgec_listelerini_tazeler(view):
    view.new_item()
    view.title_edit.setText("x")
    view.category_edit.setText("yenikategori")
    view.tags_edit.setText("yenietiket")
    view.save_current()
    assert "yenikategori" in _liste(view.categories)
    assert "yenietiket" in _liste(view.tags)


def test_guncelleme_yeni_kayit_ACMAZ(view):
    """Ayni uuid uzerine yazilmali; yoksa her kaydet bir kopya uretirdi."""
    view.results.setCurrentRow(0)
    view.title_edit.setText("doorbell v2")
    view.save_current()

    diskte = parse(view.repo.path.read_text(encoding="utf-8"))
    assert len(diskte) == 3
    assert [item for item in diskte if item.uuid == "u-1"][0].title == "doorbell v2"


def test_baslik_zorunlu(view, monkeypatch):
    """AHK `_saveItem`: 'Title zorunlu!'. Uyari penceresi acilmadan
    test edilebilsin diye QMessageBox yakalaniyor."""
    from PySide6.QtWidgets import QMessageBox

    cagrildi: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kw: cagrildi.append(args[2])
    )
    view.new_item()
    view.text_edit.setPlainText("basliksiz")
    view.save_current()

    assert cagrildi  # uyari verildi
    assert len(parse(view.repo.path.read_text(encoding="utf-8"))) == 3  # yazilmadi


def test_govdedeki_ayrac_kayitla_birlikte_hayatta_kalir(view):
    """Pencereden girilen `===` govdeyi bolmemeli (repository.py kacisi)."""
    view.new_item()
    view.title_edit.setText("diff")
    view.text_edit.setPlainText("ustu\n===\n---\nalti")
    view.save_current()

    diskte = parse(view.repo.path.read_text(encoding="utf-8"))
    assert len(diskte) == 4
    assert next(i for i in diskte if i.title == "diff").text == "ustu\n===\n---\nalti"


# ---- silme ----


def test_silme_onay_isterse_siler(view, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    view.results.setCurrentRow(0)
    view.delete_current()
    assert len(parse(view.repo.path.read_text(encoding="utf-8"))) == 2


def test_silme_reddedilirse_dokunmaz(view, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
    )
    view.results.setCurrentRow(0)
    view.delete_current()
    assert len(parse(view.repo.path.read_text(encoding="utf-8"))) == 3


# ---- diskten tazeleme ----


def test_disaridan_duzenleme_tazelemeyle_gelir(view):
    """Dosya Notepad'den de duzenlenebiliyor; `Refresh` onu gormeli."""
    view.repo.path.write_text(
        ORNEK + "===\nuuid: u-4\ntitle: disaridan\n---\nx\n", encoding="utf-8"
    )
    view.reload_from_disk()
    assert "disaridan" in _basliklar(view)


def test_bos_depo_pencereyi_bozmaz(qapp, tmp_path):
    pencere = RepositoryView(Repository(tmp_path / "yok.md"))
    pencere.reload_from_disk()
    assert _basliklar(pencere) == []
    assert _liste(pencere.categories) == []
    assert _liste(pencere.tags) == [TUMU]


def test_bos_depoya_ilk_kayit_eklenir(qapp, tmp_path):
    repo = Repository(tmp_path / "yeni.md")
    pencere = RepositoryView(repo)
    pencere.reload_from_disk()
    pencere.title_edit.setText("ilk")
    pencere.save_current()
    assert repo.path.exists()
    assert [item.title for item in parse(repo.path.read_text(encoding="utf-8"))] == ["ilk"]


def test_repo_nesnesi_pencere_ile_paylasilir(view):
    """app.py tek `Repository` tutuyor; pencere onu DEGISTIRIYOR, kopyasini
    degil -- yoksa menuden acilan pencere ile veri katmani ayrisirdi."""
    view.new_item()
    view.title_edit.setText("paylasim")
    view.save_current()
    assert any(item.title == "paylasim" for item in view.repo.items)


def test_item_uuid_kendiliginden_uretilir():
    assert Item(title="x").uuid


# ---- etiketler baglamla daralir ----


def test_kategori_secince_etiketler_o_kategoriden_gelir(view):
    """`not` kaydi kategorisiz ve etiketsiz; `iot` secilince liste ayni
    kalir. Asil sinav: baska kategori secilince iot etiketleri DUSMELI."""
    view.new_item()
    view.title_edit.setText("push")
    view.category_edit.setText("git")
    view.tags_edit.setText("branch")
    view.save_current()

    view.categories.setCurrentRow(_liste(view.categories).index("git"))
    assert _liste(view.tags) == [TUMU, "branch"]

    view.categories.setCurrentRow(_liste(view.categories).index("iot"))
    assert _liste(view.tags) == [TUMU, "tuya", "zigbee"]


def test_arama_da_etiket_listesini_daraltir(view):
    view.search.setText("rtsp")  # yalniz `kamera`, etiketi `tuya`
    assert _liste(view.tags) == [TUMU, "tuya"]


def test_baglamdan_dusen_etiketin_secimi_de_duser(view):
    """Gorunmeyen bir etiket sonucu sessizce sifirda tutmamali."""
    view.tags.item(2).setSelected(True)  # zigbee
    assert _basliklar(view) == ["doorbell (iot)"]

    view.search.setText("rtsp")  # zigbee artik baglamda yok
    assert _liste(view.tags) == [TUMU, "tuya"]
    assert _basliklar(view) == ["kamera (iot)"]


def test_etiket_secimi_listeyi_daraltmaz(view):
    """Bir etiket secmek digerlerini listeden silmemeli -- yoksa secimi
    geri almak icin tiklanacak satir kalmazdi."""
    view.tags.item(1).setSelected(True)  # tuya
    assert _liste(view.tags) == [TUMU, "tuya", "zigbee"]
    view.tags.item(1).setSelected(False)
    assert len(_basliklar(view)) == 3


def test_etiket_secilince_TUMU_kalkar(view):
    view.tags.item(1).setSelected(True)  # tuya
    assert not view.tags.item(0).isSelected()


def test_TUMU_secilince_etiket_secimleri_kalkar(view):
    view.tags.item(1).setSelected(True)  # tuya
    view.tags.setCurrentRow(0)
    view.tags.item(0).setSelected(True)  # (tumu)
    assert not view.tags.item(1).isSelected()
    assert len(_basliklar(view)) == 3


def test_son_etiket_birakilinca_TUMU_geri_gelir(view):
    """Bos secim de suzgecsiz demek ama ekranda bunu soyleyen bir sey yok."""
    view.tags.item(1).setSelected(True)
    view.tags.item(1).setSelected(False)
    assert view.tags.item(0).isSelected()
