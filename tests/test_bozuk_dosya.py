"""BOZUK DOSYA sonrasi ne oluyor -- uctan uca.

Uc ayri soru var ve ucu ayri katmanda cevaplaniyor:

    1. dosya yedeklenip yenisi kuruluyor mu   store.py        (bu dosya)
    2. tepsi simgesi kirmizi oluyor mu        logs -> tray    (bu dosya)
    3. kullaniciya bir sey soyleniyor mu      app._on_error_logged

Ucuncu adimin kapsami DAR ve bilerek oyle: ekrana modal pencere ancak
CRITICAL'da cikiyor. Bozuk bir veri dosyasi ERROR seviyesinde -- program
calismaya devam edebiliyor, kullaniciyi durdurmak orantisiz olurdu.
Asagidaki `test_bozuk_dosya_dialog_ACMAZ` bunu bilincli bir karar olarak
sabitliyor: davranis degisirse test duser ve kimse kazara degistirmez.
"""

import logging

import orjson
import pytest

from cascade import logs
from cascade.store import ClipStore, JsonStore, SlotStore

BOZUK = b"{ bu json degil ]]"


# ---- 1. yedekle + yenisini kur ----


def test_bozuk_slots_yedeklenir(tmp_path):
    yol = tmp_path / "slots.json"
    yol.write_bytes(BOZUK)

    store = SlotStore(tmp_path)
    store.load()

    yedekler = list(tmp_path.glob("slots.json.bozuk-*"))
    assert len(yedekler) == 1
    assert yedekler[0].read_bytes() == BOZUK  # icerik KAYBOLMAZ


def test_bozuk_slots_yerine_calisir_varsayilan_gelir(tmp_path):
    (tmp_path / "slots.json").write_bytes(BOZUK)
    store = SlotStore(tmp_path)
    gruplar = store.load()
    assert list(gruplar) == [""]
    assert len(gruplar[""]) == 10  # AHK initializeDefaultGroups


def test_yedekten_sonra_yeni_dosya_diske_yazilir(tmp_path):
    """Yedekleme dosyayi TASIYOR (kopyalamiyor): eski ad bosalir ve
    program kaydedince yerine gecerli bir dosya yazilir."""
    yol = tmp_path / "slots.json"
    yol.write_bytes(BOZUK)

    store = SlotStore(tmp_path)
    store.load()
    assert not yol.exists()  # tasindi

    store.save()
    assert yol.exists()
    veri = orjson.loads(yol.read_bytes().lstrip(b"\xef\xbb\xbf"))
    assert veri["groups"][0]["groupName"] == ""


def test_json_degil_ama_gecerli_json_de_yedeklenir(tmp_path):
    """`[1,2,3]` gecerli JSON ama beklenen bicim DEGIL -- ayri gerekce
    (`bicim`), cunku "okunamadi" ile "yanlis sey" farkli arizalar."""
    (tmp_path / "slots.json").write_bytes(b"[1, 2, 3]")
    SlotStore(tmp_path).load()
    assert list(tmp_path.glob("slots.json.bicim-*"))


def test_bozuk_pano_deposu_da_yedeklenir(tmp_path):
    """Ayni koruma pano gecmisinde de var (ikili bicim, ayri okuyucu)."""
    yol = tmp_path / ClipStore.filename
    yol.write_bytes(b"BOZUKBOZUK" * 10)
    store = ClipStore(tmp_path)
    assert store.load_entries() == []
    assert list(tmp_path.glob(ClipStore.filename + ".*"))


def test_bozuk_dosya_istisna_firlatmaz(tmp_path):
    """Acilista tek bir bozuk dosya PROGRAMI ACILMAZ HALE GETIRMEMELI."""
    for isim in ("slots.json", "profiles.json"):
        (tmp_path / isim).write_bytes(BOZUK)
    SlotStore(tmp_path).load()
    JsonStore(tmp_path / "profiles.json").load()  # patlamamali


# ---- 2. tepsi simgesi ----


@pytest.fixture
def hata_kaydi():
    """`logs.errors` handler'ini kok logger'a takar.

    Uygulamada bunu `logs.setup()` yapiyor; test o kurulumun tamamini
    (dosya, Qt kopru, stderr) istemedigi icin yalniz ilgilendigimiz
    handler'i takip cikariyoruz.
    """
    root = logging.getLogger()
    once_subs = list(logs.errors._subs)
    takili = logs.errors in root.handlers
    if not takili:
        root.addHandler(logs.errors)
    seviye = root.level
    root.setLevel(logging.INFO)
    yield logs.errors
    logs.errors._subs[:] = once_subs
    if not takili:
        root.removeHandler(logs.errors)
    root.setLevel(seviye)


def test_bozuk_dosya_hata_kaydi_uretir(tmp_path, hata_kaydi, caplog):
    """Zincirin ilk halkasi: bozulma ERROR seviyesinde log'a dusmeli --
    tepsi rozeti bu kayda abone."""
    gorulen: list[tuple[str, str]] = []
    hata_kaydi.subscribe(lambda level, text: gorulen.append((level, text)))

    (tmp_path / "slots.json").write_bytes(BOZUK)
    with caplog.at_level(logging.WARNING):
        SlotStore(tmp_path).load()

    seviyeler = {level for level, _ in gorulen}
    assert "ERROR" in seviyeler
    assert any("okunamadi" in text for _, text in gorulen)


def test_hata_sayaci_simgeyi_kirmizi_yapar(qapp):
    """Zincirin ikinci halkasi: sayac artinca simge KIRMIZI zemine geciyor.

    Simgenin kendisi cizim; renk karsilastirmasi icin ayni boyutta iki
    goruntu uretip piksel okuyoruz -- "sarili mi" degil "gercekten farkli
    mi" sorusunu soruyor.
    """
    from cascade.ui.tray import ERROR_BACKGROUND, make_icon

    boyut = 64
    normal = make_icon(boyut).pixmap(boyut, boyut).toImage()
    hatali = make_icon(boyut, error=True).pixmap(boyut, boyut).toImage()

    kose = (boyut // 2, 4)  # ust kenar ortasi: zemin, cubuk degil
    assert normal.pixelColor(*kose) != hatali.pixelColor(*kose)
    assert hatali.pixelColor(*kose).name() == ERROR_BACKGROUND.name()


def test_duraklatma_hatadan_oncelikli(qapp):
    """Ikisi birdense duraklatma gosteriliyor: o an ne oldugunu bilmek
    daha onemli (ui/tray.make_icon)."""
    from cascade.ui.tray import make_icon

    boyut = 64
    kose = (boyut // 2, 4)
    duraklatilmis = make_icon(boyut, paused=True).pixmap(boyut, boyut).toImage()
    ikisi = make_icon(boyut, paused=True, error=True).pixmap(boyut, boyut).toImage()
    assert duraklatilmis.pixelColor(*kose) == ikisi.pixelColor(*kose)


# ---- 3. kullaniciya bildirim ----


def test_bozuk_dosya_CRITICAL_uretir(tmp_path, hata_kaydi):
    """Bozulma = VERI KAYBI: kullanici fark etmeden devam etmemeli.

    Once ERROR seviyesindeydi ve yalniz tepsi rozetiyle haber veriliyordu;
    rozet sessiz bir sinyal, kullanici slotlarinin sifirlandigini ancak
    F14'e basinca goruyordu. `store.backup_file` artik CRITICAL yaziyor ve
    `app._on_error_logged` bu seviyede modal pencere aciyor.
    """
    seviyeler: list[str] = []
    hata_kaydi.subscribe(lambda level, _text: seviyeler.append(level))

    (tmp_path / "slots.json").write_bytes(BOZUK)
    SlotStore(tmp_path).load()

    assert "CRITICAL" in seviyeler


def test_kritik_mesaj_ne_oldugunu_soyler(tmp_path, hata_kaydi):
    """Pencerede gorunecek metin: hangi dosya, yedek nerede, ne yapildi."""
    mesajlar: list[str] = []
    hata_kaydi.subscribe(
        lambda level, text: mesajlar.append(text) if level == "CRITICAL" else None
    )

    (tmp_path / "slots.json").write_bytes(BOZUK)
    SlotStore(tmp_path).load()

    (mesaj,) = mesajlar
    assert "slots.json" in mesaj
    assert "bozuk-" in mesaj  # yedegin adi
    assert "varsayilan" in mesaj  # yerine ne kuruldu


def test_saglam_dosya_kritik_uretmez(tmp_path, hata_kaydi):
    """Yanlis pozitif olmasin: normal acilis sessiz gecmeli."""
    seviyeler: list[str] = []
    hata_kaydi.subscribe(lambda level, _text: seviyeler.append(level))

    store = SlotStore(tmp_path)
    store.load()
    store.save()
    SlotStore(tmp_path).load()

    assert "CRITICAL" not in seviyeler


def _sahte_cascade(monkeypatch, acilan: list):
    """`__init__` calistirmadan Cascade: hook, tepsi, pencere kurulmasin."""
    from PySide6.QtWidgets import QMessageBox

    from cascade.app import Cascade

    class SahteKutu:
        def __init__(self, *a, **kw):
            pass

        def setText(self, text):
            acilan.append(text)

        def setInformativeText(self, text):
            acilan.append(text)

        def setDetailedText(self, text):
            pass

        def exec(self):
            acilan.append("<ACILDI>")

    monkeypatch.setattr(QMessageBox, "__new__", lambda cls, *a, **kw: SahteKutu())

    sahte = Cascade.__new__(Cascade)
    sahte._critical_open = False
    sahte._critical_pending = []
    sahte._critical_scheduled = False
    sahte._error_count = 0
    sahte.tray = type(
        "T", (), {"set_error_count": lambda s, n: None, "notify": lambda s, *a: None}
    )()
    sahte.tip = type("P", (), {"show_html": lambda s, *a: None})()
    return sahte


def test_ARDISIK_uc_kritik_hata_TEK_pencere_acar(qapp, monkeypatch):
    """ASIL SORUN BUYDU.

    `on_start` uc depoyu sirayla okuyor. Uc dosya birden bozuksa her biri
    kendi penceresini aciyordu ve kullanici arka arkaya uc kez "Tamam"a
    basiyordu. Ust uste acilmayi engelleyen bayrak burada ise yaramiyor:
    cagrilar IC ICE degil ARDISIK -- ilk pencere kapanmadan ikinci hata
    zaten olusmuyor. Cozum pencereyi bir sonraki olay turuna birakmak.
    """
    acilan: list[str] = []
    sahte = _sahte_cascade(monkeypatch, acilan)

    for isim in ("slots.json", "profiles.json", "clipboards.bin"):
        sahte._on_error_logged("CRITICAL", f"{isim} bozuk: yedeklendi")

    assert acilan == []  # HENUZ acilmadi: olay turu bekleniyor
    sahte._flush_critical()

    assert acilan.count("<ACILDI>") == 1
    metin = " ".join(acilan)
    assert "3 kritik hata" in metin
    for isim in ("slots.json", "profiles.json", "clipboards.bin"):
        assert isim in metin  # hicbiri yutulmadi


def test_tek_kritik_hata_sayi_yazmaz(qapp, monkeypatch):
    acilan: list[str] = []
    sahte = _sahte_cascade(monkeypatch, acilan)
    sahte._on_error_logged("CRITICAL", "slots.json bozuk: yedeklendi")
    sahte._flush_critical()
    assert acilan.count("<ACILDI>") == 1
    assert "kritik hata:" not in " ".join(acilan)  # "1 kritik hata:" demiyor


def test_pencere_acikken_gelen_hata_YUTULMAZ(qapp, monkeypatch):
    """Toplamayi eklerken hata GIZLEMEYELIM: pencere acikken dusen kayit
    kuyrukta kalmali ve pencere kapaninca gosterilmeli."""
    acilan: list[str] = []
    sahte = _sahte_cascade(monkeypatch, acilan)

    sahte._critical_open = True  # pencere acik
    sahte._on_error_logged("CRITICAL", "acikken dusen hata")
    sahte._flush_critical()
    assert acilan == []  # ustune pencere acilmadi
    assert sahte._critical_pending  # ama kayit DURUYOR

    sahte._critical_open = False  # pencere kapandi
    sahte._flush_critical()
    assert acilan.count("<ACILDI>") == 1
    assert "acikken dusen hata" in " ".join(acilan)


def test_ERROR_pencere_acmaz(qapp, monkeypatch):
    acilan: list[str] = []
    sahte = _sahte_cascade(monkeypatch, acilan)
    sahte._on_error_logged("ERROR", "sadece rozet")
    sahte._flush_critical()
    assert acilan == []
