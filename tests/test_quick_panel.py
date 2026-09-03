"""CapsLock hizli paneli (ui/quick_panel.py).

Sabitlenen davranislar, port sirasinda kolay kaybolacak olanlar:

    * `wrap`     -- uc satirda keser, son satir "…" ile biter
    * 1-9        -- SUZULMUS listeyi sayar, ham listeyi degil
    * sag / sol  -- modlar arasinda gezer, sonuncudan basa doner
    * Ctrl+q     -- SECILI ogenin HAM metnini verir (etiketi degil)
    * saglayici  -- her acilista yeniden cagrilir (pano degismis olabilir)

Panel eylemi calistirmaz, kimligini yayar: testler sinyalleri topluyor.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from cascade.ui.quick_panel import QuickItem, QuickPanel, QuickTab, shortcut, wrap


def tus(panel: QuickPanel, key, modifiers=Qt.KeyboardModifier.NoModifier, text="") -> None:
    panel.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers, text))


@pytest.fixture
def panel(qapp):
    """Iki sekme: biri sabit, digeri her cagrida degisen (sayac)."""
    cagri = {"sayi": 0}

    def sayac() -> tuple[QuickItem, ...]:
        cagri["sayi"] += 1
        return (QuickItem(content=f"cagri {cagri['sayi']}", action="b.1"),)

    view = QuickPanel(
        (
            QuickTab(
                "Slot",
                lambda: (
                    QuickItem(content="alfa metni", action="a.1", label="alfa"),
                    QuickItem(content="beta metni", action="a.2", label="beta"),
                    QuickItem(content="gama metni", action="a.3", label="gama"),
                ),
            ),
            QuickTab("Pano", sayac),
        )
    )
    view.secilen: list[str] = []
    view.qr: list[str] = []
    view.chosen.connect(view.secilen.append)
    view.qr_requested.connect(view.qr.append)
    view.select_tab(0)
    return view


# ---- sarma ----


def test_wrap_kisa_metni_bolmez():
    assert wrap("kisa", 20) == ["kisa"]


def test_wrap_kelime_kelime_sarar():
    assert wrap("bir iki uc dort", 8) == ["bir iki", "uc dort"]


def test_wrap_uc_satirda_keser_ve_uc_nokta_koyar():
    lines = wrap(" ".join(["kelime"] * 40), 20)
    assert len(lines) == 3
    assert lines[-1].endswith("…")


def test_wrap_satira_sigmayan_tek_kelimeyi_boler():
    assert wrap("x" * 25, 10)[0] == "x" * 10


def test_onuncu_ogenin_kisayoli_sifir():
    assert [shortcut(n) for n in (1, 9, 10)] == ["1", "9", "0"]


# ---- secim ----


def test_rakam_ogeyi_secer_ve_paneli_kapatir(panel):
    tus(panel, Qt.Key.Key_2)
    assert panel.secilen == ["a.2"]
    assert not panel.isVisible()


def test_rakam_SUZULMUS_listeyi_sayar(panel):
    panel.search.setText("gama")
    tus(panel, Qt.Key.Key_1)  # suzgecte tek oge var, o da ucuncusu
    assert panel.secilen == ["a.3"]


def test_olmayan_rakam_bir_sey_secmez(panel):
    tus(panel, Qt.Key.Key_9)
    assert panel.secilen == []


def test_ok_tuslari_ve_enter(panel):
    tus(panel, Qt.Key.Key_Down)
    tus(panel, Qt.Key.Key_Return)
    assert panel.secilen == ["a.2"]


def test_asagi_sondan_basa_doner(panel):
    for _ in range(3):
        tus(panel, Qt.Key.Key_Down)
    tus(panel, Qt.Key.Key_Return)
    assert panel.secilen == ["a.1"]


# ---- sekmeler ----


def test_sag_ok_modu_degistirir(panel):
    tus(panel, Qt.Key.Key_Right)
    assert panel.tab.title == "Pano"


def test_sol_ok_geri_gider(panel):
    tus(panel, Qt.Key.Key_Left)
    assert panel.tab.title == "Pano"  # iki sekme: geri gitmek de Pano'ya cikar


def test_tab_sekmeler_arasinda_doner(panel):
    tus(panel, Qt.Key.Key_Tab)
    assert panel.tab.title == "Pano"
    tus(panel, Qt.Key.Key_Tab)
    assert panel.tab.title == "Slot"


def test_shift_tab_geri_gider(panel):
    tus(panel, Qt.Key.Key_Backtab)
    assert panel.tab.title == "Pano"


# ---- arama kutusu suzgeci (odak hep orada) ----


def kutu_tus(panel: QuickPanel, key, modifiers=Qt.KeyboardModifier.NoModifier, text="") -> None:
    """Tusu ARAMA KUTUSUNA gonderir -- gercekte odak orada duruyor."""
    QApplication.sendEvent(panel.search, QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers, text))


def test_kutudaki_tab_sekme_degistirir(panel):
    kutu_tus(panel, Qt.Key.Key_Tab, text="\t")
    assert panel.tab.title == "Pano"


def test_kutu_bosken_sag_ok_sekme_degistirir(panel):
    kutu_tus(panel, Qt.Key.Key_Right)
    assert panel.tab.title == "Pano"


def test_kutuda_yazi_varken_sag_ok_metinde_gezer(panel):
    panel.search.setText("ga")
    kutu_tus(panel, Qt.Key.Key_Right)
    assert panel.tab.title == "Slot"  # sekme DEGISMEDI


def test_kutudaki_rakam_ogeyi_secer(panel):
    kutu_tus(panel, Qt.Key.Key_2, text="2")
    assert panel.secilen == ["a.2"]
    assert panel.search.text() == ""  # rakam aramaya yazilmadi


def test_sekme_degisince_arama_temizlenir(panel):
    panel.search.setText("gama")
    panel.select_tab(1)
    assert panel.search.text() == ""


def test_saglayici_her_acilista_cagrilir(panel):
    panel.select_tab(1)
    ilk = panel.items[0].content
    panel.select_tab(1)
    assert panel.items[0].content != ilk


# ---- sayfalama ----


@pytest.fixture
def uzun(qapp):
    """Yirmi bes ogeli tek sekme -- uc sayfa (10 + 10 + 5)."""
    items = tuple(QuickItem(content=f"oge {i}", action=f"a.{i}") for i in range(1, 26))
    view = QuickPanel((QuickTab("Pano", lambda: items),))
    view.secilen: list[str] = []
    view.chosen.connect(view.secilen.append)
    view.select_tab(0)
    return view


def test_sayfa_basina_on_oge(uzun):
    assert len(uzun.items) == 10
    assert uzun.pages == 3


def test_son_satirda_asagi_sonraki_onluyu_yukler(uzun):
    for _ in range(10):  # 10. satirdan bir daha asagi
        tus(uzun, Qt.Key.Key_Down)
    assert uzun.page == 1
    tus(uzun, Qt.Key.Key_1)
    assert uzun.secilen == ["a.11"]  # kisayol ayni, icerik yeni onlu


def test_ilk_satirda_yukari_onceki_sayfanin_SONUNA_gider(uzun):
    tus(uzun, Qt.Key.Key_Up)
    assert uzun.page == 2  # basta yukari: son sayfaya doner
    tus(uzun, Qt.Key.Key_Return)
    assert uzun.secilen == ["a.25"]


def test_arama_sayfayi_basa_alir(uzun):
    uzun.go_page(2)
    uzun.search.setText("oge 1")
    assert uzun.page == 0


# ---- QR ----


def test_ctrl_q_secili_ogenin_HAM_metnini_verir(panel):
    tus(panel, Qt.Key.Key_Down)
    tus(panel, Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier, "q")
    assert panel.qr == ["beta metni"]  # etiket "beta" DEGIL


def test_bos_listede_ctrl_q_bos_metin_verir(panel):
    panel.search.setText("boyle bir sey yok")
    tus(panel, Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier, "q")
    assert panel.qr == [""]


# ---- arama ----


def test_arama_etikete_gore_suzer(panel):
    panel.search.setText("BE")  # buyuk/kucuk harf ayrimi yok
    assert [item.action for item in panel.items] == ["a.2"]


def test_esc_kapatir(panel):
    panel.show()
    tus(panel, Qt.Key.Key_Escape)
    assert not panel.isVisible()
