"""Depo panelinin FLET surumu (fui/repository.py) -- suzgec ve kayit.

Flet calistirilmiyor: `_build` cagrilmadan panelin QT TARAFI suruluyor.
Zaten bolunme oradan geciyor -- depoya dokunan her satir ana thread'de
kosuyor (`ask_qt`), Flet tarafi yalnizca hazir demetleri ciziyor. Yani
burada test edilen sey panelin karar veren yarisi.

Qt surumunun testleri (`tests/test_repository_view.py`) AYNEN duruyor:
iki pencere de ayakta ve ayni depoyu okuyor.
"""

from __future__ import annotations

import pytest

from keypilot.fui.repository import TUMU, RepositoryPanel, result_label
from keypilot.repository import Repository, parse

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


class SahteOlay:
    """`ft.ControlEvent` yerine: panelin okudugu tek sey `control.value`."""

    def __init__(self, value: str) -> None:
        self.control = type("Kutu", (), {"value": value})()


@pytest.fixture
def panel(qapp, tmp_path):
    yol = tmp_path / "repository.md"
    yol.write_text(ORNEK, encoding="utf-8")
    panel = RepositoryPanel(Repository(yol))
    panel._reload()
    return panel


def _basliklar(panel: RepositoryPanel) -> list[str]:
    return [label for _uuid, label in panel._shown]


def _ara(panel: RepositoryPanel, metin: str) -> None:
    """Arama kutusu -- Flet olayi geldi, sonra Qt tarafi hesapladi."""
    panel._on_search(SahteOlay(metin))
    panel._recompute()


def _tikla(panel: RepositoryPanel, handler, *args) -> None:
    """Liste tiklamasi: durum Flet thread'inde degisir, hesap Qt'de kosar."""
    handler(*args)
    panel._recompute()


# ---- listeleme ----


def test_acilista_hepsi_listelenir(panel):
    assert _basliklar(panel) == ["doorbell (iot)", "kamera (iot)", "not"]
    assert panel._total == 3


def test_kategorisiz_kayit_parantezsiz_yazilir():
    assert result_label("not", "") == "not"
    assert result_label("doorbell", "iot") == "doorbell (iot)"


def test_kategori_listesinde_TUMU_YOK(panel):
    """`(tumu)` ETIKETLERDE: kategori tek secim, bos secim zaten 'hepsi'."""
    assert panel._categories == ("iot",)
    assert TUMU not in panel._categories


def test_etiketler_tekil_sirali_ve_TUMU_ustte(panel):
    assert panel._tag_rows == (TUMU, "tuya", "zigbee")


# ---- suzgecler ----


def test_arama_govdede_de_suzer(panel):
    _ara(panel, "rtsp")
    assert _basliklar(panel) == ["kamera (iot)"]


def test_kategori_suzgeci(panel):
    _tikla(panel, panel._on_category, "iot")
    assert len(_basliklar(panel)) == 2


def test_secili_kategoriye_tekrar_tiklamak_secimi_kaldirir(panel):
    """Qt'de `ToggleList` alt sinifi yapiyordu; burada iki satir."""
    _tikla(panel, panel._on_category, "iot")
    _tikla(panel, panel._on_category, "iot")
    assert panel._category == ""
    assert len(_basliklar(panel)) == 3


def test_coklu_etiket_HEPSINI_ister(panel):
    _tikla(panel, panel._on_tag, "tuya")
    assert len(_basliklar(panel)) == 2
    _tikla(panel, panel._on_tag, "zigbee")
    assert _basliklar(panel) == ["doorbell (iot)"]


def test_TUMU_etiket_secimini_bosaltir(panel):
    _tikla(panel, panel._on_tag, "tuya")
    _tikla(panel, panel._on_tag, TUMU)
    assert panel._tags == set()
    assert len(_basliklar(panel)) == 3


def test_etiket_listesi_BAGLAMDAN_gelir(panel):
    """Etiketler depodan degil, arama + kategori sonucundan toplaniyor:
    listede duran her etiket sonucu daraltir, hicbiri sifira dusurmez."""
    _ara(panel, "rtsp")
    assert panel._tag_rows == (TUMU, "tuya")


def test_baglamdan_dusen_etiketin_secimi_de_duser(panel):
    _tikla(panel, panel._on_tag, "zigbee")
    assert _basliklar(panel) == ["doorbell (iot)"]
    # "kamera"da zigbee yok: etiket listeden de secimden de duser.
    _ara(panel, "rtsp")
    assert panel._tags == set()
    assert _basliklar(panel) == ["kamera (iot)"]


def test_suzgecler_birlikte_calisir(panel):
    _ara(panel, "tuya")
    _tikla(panel, panel._on_category, "iot")
    _tikla(panel, panel._on_tag, "zigbee")
    assert _basliklar(panel) == ["doorbell (iot)"]


# ---- detay paneli ----


def test_secim_detaya_yuklenir(panel):
    panel._load_item("u-1")
    uuid, baslik, kategori, etiketler, metin = panel._detail
    assert (uuid, baslik, kategori, etiketler) == ("u-1", "doorbell", "iot", "tuya, zigbee")
    assert "two way audio" in metin


def test_yeni_kayit_diske_yazilir(panel):
    panel._current_uuid = ""
    panel._save_now("yeni kayit", "test", ["a", "b"], "govde")

    diskte = parse(panel.repo.path.read_text(encoding="utf-8"))
    yeni = next(item for item in diskte if item.title == "yeni kayit")
    assert yeni.category == "test"
    assert yeni.tags == ["a", "b"]
    assert yeni.text == "govde"


def test_yeni_kayit_suzgec_listelerini_tazeler(panel):
    panel._current_uuid = ""
    panel._save_now("x", "yenikategori", ["yenietiket"], "")
    assert "yenikategori" in panel._categories
    assert "yenietiket" in panel._tag_rows


def test_guncelleme_yeni_kayit_ACMAZ(panel):
    """Ayni uuid uzerine yazilmali; yoksa her kaydet bir kopya uretirdi."""
    panel._load_item("u-1")
    panel._save_now("doorbell v2", "iot", ["tuya"], "govde")

    diskte = parse(panel.repo.path.read_text(encoding="utf-8"))
    assert len(diskte) == 3
    assert [item for item in diskte if item.uuid == "u-1"][0].title == "doorbell v2"


def test_silme_kaydi_diskten_de_goturur(panel):
    panel._load_item("u-2")
    panel._delete_now()

    diskte = parse(panel.repo.path.read_text(encoding="utf-8"))
    assert [item.uuid for item in diskte] == ["u-1", "u-3"]
    assert panel._detail == ("", "", "", "", "")
    assert panel._current_uuid == ""


def test_disaridan_duzenleme_tazelemeyle_gelir(panel):
    """Depo Notepad'den de duzenlenebiliyor: "Diskten tazele" onun yolu."""
    panel.repo.path.write_text(
        ORNEK + "===\nuuid: u-4\ntitle: disaridan\n---\nelle eklendi\n",
        encoding="utf-8",
    )
    panel._reload()
    assert "disaridan" in _basliklar(panel)


def test_repo_nesnesi_app_ile_PAYLASILIR(panel):
    """Panel kendi kopyasini tutmuyor: `app.py`nin depo nesnesi ayni."""
    panel._current_uuid = ""
    panel._save_now("paylasim", "", [], "")
    assert any(item.title == "paylasim" for item in panel.repo.items)
