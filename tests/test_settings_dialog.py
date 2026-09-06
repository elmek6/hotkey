"""Ayar ekrani: her ayar bir KART, deger nesnenin kendisi.

Once tablo vardi ve deger bir hucre metniydi: degistirmek icin once satiri
sec, sonra cift tikla, acilan diyalogda degistir. Testler o zincirin yerine
gecen davranisi olcuyor -- tek tiklamada acilan menu, yerinde yazilan sayi,
reddedilen degerin kutuda kalmasi.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

from keypilot.settings import Registry, Setting, between
from keypilot.ui import settings_dialog
from keypilot.ui.settings_dialog import ALL_LABEL, SettingCard, SettingsDialog


@pytest.fixture
def defter(monkeypatch):
    """Gercek kayit defteri yerine kucuk bir tane -- test ayar eklemesin."""
    registry = Registry()
    monkeypatch.setattr(settings_dialog, "SETTINGS", registry)
    return registry


def _kur(registry: Registry, *items: Setting) -> None:
    for item in items:
        registry.register(item)


#: Kurulan pencereler burada duruyor. Test bittiginde yerel degisken
#: dusuyor, Python nesneyi topluyor ve Qt tarafi bir sonraki testin
#: ortasinda cokuyordu (access violation) -- oturum boyunca canli tut.
_CANLI: list = []


def _dialog() -> SettingsDialog:
    dialog = SettingsDialog()
    _CANLI.append(dialog)
    return dialog


def _kart(item: Setting) -> SettingCard:
    card = SettingCard(item)
    _CANLI.append(card)
    return card


def test_tumu_en_sonda(qapp, defter):
    _kur(
        defter,
        Setting("a.bir", "Bir", default=True, category="mouse"),
        Setting("b.iki", "Iki", default=True, category="tray"),
    )
    dialog = _dialog()
    rows = [dialog.categories.item(i).text() for i in range(dialog.categories.count())]
    assert rows[-1].startswith(ALL_LABEL)
    assert ALL_LABEL not in rows[0]
    # Acilista secili olan "Tümü": hicbir kategori suzulmus gelmemeli.
    assert dialog.categories.currentRow() == len(rows) - 1
    assert len(dialog.cards) == 2


def test_gizli_ayar_listede_yok(qapp, defter):
    _kur(
        defter,
        Setting("a.gorunur", "Gorunur", default=True, category="mouse"),
        Setting("a.gizli", "Gizli", default=True, category="mouse", hidden=True),
    )
    dialog = _dialog()
    assert [card.item.key for card in dialog.cards] == ["a.gorunur"]
    # Arama da bulmamali: acilamayan satiri gostermek daha kafa karistirici.
    dialog.search.setText("gizli")
    assert dialog.cards == []


def test_tek_ayari_gizli_kategori_hic_listelenmez(qapp, defter):
    _kur(
        defter,
        Setting("a.gorunur", "Gorunur", default=True, category="mouse"),
        Setting("b.gizli", "Gizli", default=True, category="tray", hidden=True),
    )
    dialog = _dialog()
    rows = [dialog.categories.item(i).text() for i in range(dialog.categories.count())]
    assert len(rows) == 3  # mouse + ayirici + Tümü, tray yok


def test_kartta_ad_deger_ve_aciklama_var(qapp):
    item = Setting("a.bool", "Bool", default=False, category="mouse", desc="ne yapar")
    card = _kart(item)
    assert card.name.text() == "Bool"
    assert card.desc.text() == "ne yapar"
    assert isinstance(card.value, QPushButton)  # deger NESNE, metin degil


def test_acik_kapali_da_menuden_secilir(qapp):
    """bool ayri bir tip degil: iki elemanli bir secenek listesi gibi."""
    item = Setting("a.bool", "Bool", default=False, category="mouse")
    card = _kart(item)
    assert card.value.text() == "kapali"

    actions = card.menu().actions()
    assert [a.text() for a in actions] == ["acik", "kapali"]
    assert [a.isChecked() for a in actions] == [False, True]  # secili: kapali
    assert [a.font().bold() for a in actions] == [False, True]  # varsayilan: kapali

    actions[0].trigger()
    assert item.get() is True
    assert card.value.text() == "acik"


def test_enum_menusunde_secili_tikli_varsayilan_kalin(qapp):
    item = Setting(
        "a.enum",
        "Enum",
        default="bir",
        category="mouse",
        choices=("bir", "iki", "uc"),
        labels={"bir": "Bir", "iki": "Iki", "uc": "Uc"},
    )
    item.set("iki")
    card = _kart(item)
    assert card.value.text() == "Iki"

    # Menu ACILMADAN denetleniyor: `exec` modal dongu, testte donmez.
    actions = card.menu().actions()
    assert [a.text() for a in actions] == ["Bir", "Iki", "Uc"]
    assert [a.isChecked() for a in actions] == [False, True, False]  # secili: iki
    assert [a.font().bold() for a in actions] == [True, False, False]  # varsayilan: bir

    actions[2].trigger()
    assert item.get() == "uc"
    assert card.value.text() == "Uc"


def test_sayi_kutuya_yazilarak_degisir(qapp):
    item = Setting("a.sayi", "Sayi", default=10, category="mouse")
    card = _kart(item)
    assert isinstance(card.value, QLineEdit)

    card.value.setText("42")
    card.value.editingFinished.emit()
    assert item.get() == 42
    assert card.value.text() == "42"


def test_ortadaki_bilgi_gecerli_araligi_yazar(qapp):
    """Aralik dogrulayicidan turetiliyor, elle yazilmiyor."""
    card = _kart(
        Setting("a.sayi", "Sayi", default=10, category="mouse", validate=between(0, 50, "px"))
    )
    assert card.info.text() == "0 - 50 px".replace(" - ", "-")
    # Duz aralik olmayan ayarda kisa bilgi elle veriliyor.
    elle = _kart(
        Setting("a.ms", "Ms", default=0, category="mouse", info="0=yok 500-60000ms")
    )
    assert elle.info.text() == "0=yok 500-60000ms"
    # Bilgisi olmayan ayarda hucre bos ara olarak duruyor.
    assert _kart(Setting("a.duz", "Duz", default=1, category="mouse")).info.text() == ""


def test_gecersiz_degerde_ayni_yazi_KIRMIZI_yanar(qapp):
    """Yazdigin yerinde kalir; ortadaki aralik kirmizi olur."""
    item = Setting(
        "a.sayi", "Sayi", default=10, category="mouse", validate=between(1, 9)
    )
    card = _kart(item)
    assert card.info.text() == "1-9"
    assert card.info.styleSheet() == ""

    card.value.setText("333")
    card.value.editingFinished.emit()
    assert item.get() == 10  # ayar DEGISMEDI
    assert card.value.text() == "333"  # ama yazdigi silinmedi
    assert card.invalid is True
    assert card.info.text() == "1-9"  # yazi ayni, rengi degisti
    assert settings_dialog.INVALID_COLOR in card.info.styleSheet()

    card.value.setText("5")  # duzeltince kirmizi kalkar
    card.value.editingFinished.emit()
    assert item.get() == 5
    assert card.info.styleSheet() == ""


def test_bilgisi_olmayan_ayarda_ret_gerekcesi_ortada_gorunur(qapp):
    """Bos hucre isi gorsun -- baska soyleyecek yer yok."""
    item = Setting(
        "a.sayi",
        "Sayi",
        default=10,
        category="mouse",
        validate=lambda value: "cok buyuk" if value > 100 else "",
    )
    card = _kart(item)
    card.value.setText("500")
    card.value.editingFinished.emit()
    assert card.info.text() == "cok buyuk"
    assert settings_dialog.INVALID_COLOR in card.info.styleSheet()


def test_uc_tip_de_ayni_satir_sablonunu_kullanir(qapp):
    """Sablon: ad | bilgi | deger. Deger sutunu tiplerde ayni yerde."""
    kartlar = [
        _kart(Setting("a.bool", "Bool", default=True, category="mouse")),
        _kart(Setting("a.enum", "Enum", default="x", choices=("x", "y"), category="mouse")),
        _kart(Setting("a.sayi", "Sayi", default=1, category="mouse")),
    ]
    for card in kartlar:
        assert card.info.parent() is card  # hucre HER tipte var
        # Hiza KUTUDA: sayi kartinda kutu degeri sarar, menulu tipte
        # dugmenin kendisidir -- genislik ucunde de ayni.
        assert card.box.width() == settings_dialog.VALUE_WIDTH


def test_hicbir_yerde_ipucu_yok(qapp):
    """Tooltip katmani kaldirildi: gosterdigi her sey zaten ekranda."""
    item = Setting(
        "a.sayi", "Sayi", default=10, category="mouse", validate=between(0, 50, "px")
    )
    card = _kart(item)
    assert card.value.toolTip() == ""
    assert card.info.toolTip() == ""
    assert card.name.toolTip() == ""


def test_varsayilan_disi_deger_kalin_yazilir(qapp, defter):
    """Isaret ADIN degil DEGERIN uzerinde: goz degerler sutununu tariyor."""
    item = Setting("a.sayi", "Sayi", default=10, category="mouse")
    _kur(defter, item)
    dialog = _dialog()
    card = dialog.cards[0]
    assert card.value.font().bold() is False
    assert card.name.font().bold() is False

    card.value.setText("42")
    card.value.editingFinished.emit()
    assert card.value.font().bold() is True
    assert card.name.font().bold() is False  # ad hep normal

    card.value.setText("10")
    card.value.editingFinished.emit()
    assert card.value.font().bold() is False


def test_kategorilerle_tumu_arasinda_ayirici_var(qapp, defter):
    """"Tümü" bir kategori DEGIL, suzgeci kaldirmak."""
    _kur(defter, Setting("a.bir", "Bir", default=True, category="mouse"))
    dialog = _dialog()
    rows = dialog.categories.count()
    assert rows == 3  # mouse + ayirici + Tümü
    ayirici = dialog.categories.item(rows - 2)
    assert ayirici.flags() == Qt.ItemFlag.NoItemFlags  # secilemez
    assert dialog.categories.itemWidget(ayirici) is not None


def test_durum_satiri_degisen_sayisini_sayar(qapp, defter):
    item = Setting("a.sayi", "Sayi", default=10, category="mouse")
    _kur(defter, item, Setting("a.bool", "Bool", default=True, category="mouse"))
    dialog = _dialog()
    assert dialog.status.text() == "2 ayar, 0 degismis"

    dialog.cards[0].value.setText("42")
    dialog.cards[0].value.editingFinished.emit()
    assert dialog.status.text() == "2 ayar, 1 degismis"

    # Reddedilen deger durum satirinda gerekceyi gosterir.
    dialog.cards[0].value.setText("abc")
    dialog.cards[0].value.editingFinished.emit()
    assert "Gecersiz" in dialog.status.text()


def test_sifirlama_dugmesi_kutunun_icinde_varsayilani_geri_yazar(qapp):
    """Kartin saginda ayri bir dugme hizayi bozuyordu; yeri kutunun ici."""
    item = Setting("a.sayi", "Sayi", default=10, category="mouse")
    card = _kart(item)
    # Hep gorunur ama varsayilandayken PASIF: dondurecek bir sey yok.
    assert card.reset_action.isEnabled() is False

    card.value.setText("42")
    card.value.editingFinished.emit()
    assert card.reset_action.isEnabled() is True

    card.reset_action.click()
    assert item.get() == 10
    assert card.value.text() == ""  # varsayilanda kutu BOS: sagdaki silik 10 yeter
    assert card.reset_action.isEnabled() is False


def test_kutuyu_bosaltmak_varsayilana_dondurur(qapp):
    """Bos = varsayilan. Kutu varsayilandayken zaten bos duruyor; yazdigini
    silmek gorunuse uyan bir geri alma olmali, ret mesaji degil."""
    item = Setting("a.sayi", "Sayi", default=10, category="mouse")
    card = _kart(item)
    card.value.setText("42")
    card.value.editingFinished.emit()
    assert item.get() == 42

    card.value.setText("   ")
    card.value.editingFinished.emit()
    assert item.get() == 10
    assert card.value.text() == ""
    assert card.invalid is False


def test_menu_dugmesinde_sifirlama_yok(qapp):
    """Yalniz yazi kutusunda: menude varsayilan zaten KALIN gorunuyor."""
    card = _kart(Setting("a.bool", "Bool", default=True, category="mouse"))
    assert card.reset_action is None
    assert card.default is None
    assert card.box is card.value  # menulu tipte dugmenin kendisi kutudur


def test_kutuda_silik_varsayilan_yazili(qapp):
    """Sayi kutusunun ICINDE: deger | sifirlama | silik varsayilan."""
    item = Setting("a.sayi", "Sayi", default=10, category="mouse")
    card = _kart(item)
    assert card.default.text() == "10"
    # Ucu de AYNI kutunun icinde -- sutun genisligi degismiyor.
    assert card.value.parent() is card.box
    assert card.reset_action.parent() is card.box
    assert card.default.parent() is card.box

    card.value.setText("42")
    card.value.editingFinished.emit()
    assert card.default.text() == "10"  # varsayilan degismez


def test_tumu_gorunumunde_kategori_basliklari_var(qapp, defter):
    """Suzgec yokken kartlar kategoriye gore basliklaniyor; tek kategoriye
    bakarken ayni basligi tekrarlamak gurultu olurdu."""
    _kur(
        defter,
        Setting("a.bir", "Bir", default=True, category="mouse"),
        Setting("a.iki", "Iki", default=True, category="mouse"),
        Setting("b.bir", "Uc", default=True, category="macro"),
    )
    dialog = _dialog()
    adlar = [label.text() for label in dialog.holder.findChildren(QLabel, "group")]
    assert len(adlar) == 2  # iki kategori, her biri BIR kez

    dialog._category = "mouse"
    dialog._refresh()
    assert dialog.holder.findChildren(QLabel, "group") == []
