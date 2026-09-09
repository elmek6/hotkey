"""Ipucu panelinin SAF parcalari -- Flet de ekran da gerekmiyor.

Adim 9'da baslayan kalip (`tests/test_fui_repository.py`): panelin Qt
tarafi surulur, Flet calistirilmaz. Ipucunda bolunme daha da net, cunku
isin cogu saf fonksiyon:

    parse         HTML -> bicimli parcalar (cagiran kirk yerin dagarcigi)
    window_size   icerige gore pencere olcusu
    place         imlecin yanina, FIZIKSEL -> MANTIKSAL piksel cevrimiyle

`place` gercek ekrani sorguluyor, o yuzden olcek ve calisma alani
yamaniyor: test makinesinin monitorune bagli kalmasin.
"""

from __future__ import annotations

import pytest

from keypilot.fui import tip


def duz(body: str) -> str:
    return tip.text_of(tip.parse(body))


# -- parse ------------------------------------------------------------------


def test_duz_metin_oldugu_gibi():
    assert duz("merhaba") == "merhaba"


def test_kalin_isaretleniyor():
    parcalar = tip.parse("bir <b>iki</b> uc")
    assert [(p.text, p.bold) for p in parcalar] == [
        ("bir ", False),
        ("iki", True),
        (" uc", False),
    ]


def test_satir_sonu():
    assert duz("bir<br>iki") == "bir\niki"


def test_renk_span_dan_geliyor():
    parcalar = tip.parse("<span style='color:#8b949e;'>soluk</span>")
    assert [(p.text, p.color) for p in parcalar] == [("soluk", "#8b949e")]


def test_kacis_dizileri_cozuluyor():
    """`&nbsp;` ipucularinda ayrac olarak kullaniliyor (app.py acilis karti)."""
    assert duz("a &nbsp;&middot;&nbsp; b") == "a \xa0\xb7\xa0 b"
    assert duz("&lt;b&gt;") == "<b>"


def test_bilinmeyen_etiket_ATILIYOR_metin_kaliyor():
    """Ipucu bir metin kutusu: tanimadigi bir etiket yuzunden BOS
    gorunmesi en kotu sonuc olurdu."""
    assert duz("<table><tr><td>hucre</td></tr></table>") == "hucre"


def test_kapanmamis_etiket_PATLATMIYOR():
    assert duz("<b>kalin") == "kalin"


def test_fazla_kapanis_PATLATMIYOR():
    """Yigin taban bicimin altina inmemeli."""
    assert duz("</b></span>metin</div>") == "metin"


def test_ayni_bicimli_parcalar_BIRLESIYOR():
    """Az parca az `TextSpan` demek (bkz. cizim maliyeti)."""
    assert len(tip.parse("bir <x>iki</x> uc")) == 1


def test_bastaki_sondaki_bos_satir_atiliyor():
    assert duz("<br>metin<br>") == "metin"


def test_gercek_ipucu_govdesi():
    """`app.py` acilis karti -- kullanilan butun dagarcik tek metinde."""
    parcalar = tip.parse(
        "✅ <b>KeyPilot</b> &nbsp;·&nbsp; is<br>"
        "<span style='color:#8b949e;'>version</span> 1.2.3"
    )
    assert tip.text_of(parcalar) == "✅ KeyPilot \xa0·\xa0 is\nversion 1.2.3"
    assert [p.text for p in parcalar if p.bold] == ["KeyPilot"]
    assert [p.text for p in parcalar if p.color == "#8b949e"] == ["version"]


# -- window_size ------------------------------------------------------------


def test_olcu_icerikle_BUYUYOR():
    kisa = tip.window_size(tip.parse("kisa"))
    uzun = tip.window_size(tip.parse("cok daha uzun bir ipucu metni burada"))
    assert uzun[0] > kisa[0]


def test_satir_sayisi_BOYU_buyutuyor():
    tek = tip.window_size(tip.parse("bir"))
    uc = tip.window_size(tip.parse("bir<br>iki<br>uc"))
    assert uc[1] > tek[1]


def test_resim_yer_kapliyor():
    # Alt sinirin (120 piksel) ustunde bir metin: eklemenin gorulmesi icin.
    govde = tip.parse("gorsel kaydedildi 1920x1080")
    resimsiz = tip.window_size(govde)
    resimli = tip.window_size(govde, has_image=True)
    assert resimli[0] == resimsiz[0] + tip.THUMB + tip.GAP
    assert resimli[1] >= 2 * tip.PAD + tip.THUMB


def test_olcunun_TAVANI_var():
    """Pencere ekrandan buyuk olursa yerlestirme hesabi anlamsizlasir."""
    genislik, yukseklik = tip.window_size(tip.parse("x" * 5000 + "<br>x" * 500))
    assert genislik == tip.MAX_WIDTH
    assert yukseklik == tip.MAX_HEIGHT


def test_bos_govde_de_bir_olcu_veriyor():
    assert tip.window_size(()) == (120, 48)


# -- place ------------------------------------------------------------------


@pytest.fixture
def ekran(monkeypatch):
    """1920x1027 calisma alani, olcek 1.25 -- bu makinede olculen 1.10
    degil bilerek baska bir sayi: cevrimin GERCEKTEN yapildigi gorulsun."""
    monkeypatch.setattr(tip.screen, "dpi_scale_at", lambda x, y: 1.25)
    monkeypatch.setattr(tip.screen, "work_area_at", lambda x, y: (0, 0, 1920, 1027))


def test_imlecin_SAG_ALTINA(ekran):
    # (400, 300) fiziksel + 18 kayma, 1.25'e bolunmus.
    assert tip.place(200, 60, (400, 300)) == (334, 254)


def test_sag_kenarda_ICE_CEKILIYOR(ekran):
    genislik = 300
    x, _y = tip.place(genislik, 60, (1900, 500))
    assert x == round(1920 / 1.25 - genislik - 4)


def test_alt_kenarda_YUKARI_CEKILIYOR(ekran):
    yukseklik = 80
    _x, y = tip.place(300, yukseklik, (500, 1020))
    assert y == round(1027 / 1.25 - yukseklik - 4)


def test_olcek_bilinmiyorsa_HAM_koordinat(monkeypatch):
    """`dpi_scale_at` 1.0 dondurdugunde (Windows 8 oncesi ya da cagri
    basarisiz) ipucu yanlis yerde acilabilir ama ACILIR."""
    monkeypatch.setattr(tip.screen, "dpi_scale_at", lambda x, y: 1.0)
    monkeypatch.setattr(tip.screen, "work_area_at", lambda x, y: (0, 0, 1920, 1027))
    assert tip.place(200, 60, (400, 300)) == (418, 318)


def test_ikinci_monitor_NEGATIF_koordinat(monkeypatch):
    """Soldaki monitor negatif koordinatta; kutu oraya da sigmali."""
    monkeypatch.setattr(tip.screen, "dpi_scale_at", lambda x, y: 1.0)
    monkeypatch.setattr(tip.screen, "work_area_at", lambda x, y: (-1920, 0, 0, 1080))
    x, _y = tip.place(200, 60, (-1900, 100))
    assert x == -1882


# -- denetim agaci ----------------------------------------------------------
#
# BU TESTLER BIR HATADAN DOGDU. Ilk surumde `ft.border.all` ve
# `ft.padding.symmetric` yaziliydi; dogrusu `ft.Border.all` ve
# `ft.Padding.symmetric`. Saf fonksiyonlarin 21 testi geciyordu ama panel
# EKRANDA aciliyordu ve Flet "module has no attribute" diye dusuyordu --
# yani yanlis Flet API'si ancak GERCEK PENCEREDE gorunuyordu.
#
# Asagidakiler denetimleri KURUYOR (Flet calistirmadan, ekran olmadan):
# yanlis bir ad ya da imza artik burada patliyor. Yeni panel yazacak olana:
# bu ucuz ve kalibi budur.


class SahtePencere:
    """`page.window` yerine: ne atandigini tutar, dogrulamaz."""


class SahteSayfa:
    """`ft.Page` yerine. Panel `_build` icinde yalnizca su alanlara
    dokunuyor; gercek `Page` bir oturum istiyor, burada gerekmiyor."""

    def __init__(self) -> None:
        self.window = SahtePencere()
        self.controls: list = []
        self.title = ""
        self.bgcolor = None
        self.padding = None

    def update(self) -> None:
        pass


def test_build_denetimleri_KURULUYOR(qapp):
    """Yanlis Flet API'si (ft.border.all gibi) burada patlar."""
    panel = tip.TipPanel()
    sayfa = SahteSayfa()
    panel._build(sayfa)
    assert sayfa.controls, "kutu sayfaya eklenmedi"
    assert sayfa.window.frameless is True
    assert sayfa.window.skip_task_bar is True
    assert sayfa.window.always_on_top is True


def test_metin_icerigi_kuruluyor(qapp):
    panel = tip.TipPanel()
    panel._pieces = tip.parse("<b>kalin</b> ve <span style='color:#8b949e;'>soluk</span>")
    denetimler = panel._content()
    assert len(denetimler) == 1
    assert [span.text for span in denetimler[0].spans] == ["kalin", " ve ", "soluk"]


def test_resimli_icerik_kuruluyor(qapp):
    """`ft.Image` kodlanmis bayt istiyor -- `png_bytes`in ciktisi."""
    panel = tip.TipPanel()
    panel._pieces = tip.parse("gorsel")
    panel._thumb = b"sahte-png"
    satir = panel._content()[0]
    assert satir.controls[0].src == b"sahte-png"


def test_menu_icerigi_kuruluyor(qapp):
    """Rozet bir `Container` (ft.Padding.symmetric) -- Qt'de hucre zeminiydi."""
    panel = tip.TipPanel()
    panel._menu = True
    panel._title = "Pano gecmisi"
    panel._rows = (("1", "ilk"), ("2", "ikinci <span style='color:#8b949e;'>x4</span>"))
    panel._footer = "Esc  iptal"
    denetimler = panel._content()
    # baslik + iki satir + dipnot
    assert len(denetimler) == 4
    rozet = denetimler[1].controls[0]
    assert rozet.content.value == "1"
    assert rozet.bgcolor == tip.BADGE_BG


def test_menusuz_ve_menulu_olcu_ikisi_de_hesaplaniyor(qapp):
    """`_arm` ekrana dokunmadan olcu ve yer hesabini yapiyor; ikisi de
    ANA THREAD'de kosuyor (Win32 cagrilari)."""
    panel = tip.TipPanel()
    panel.show_html("<b>bir</b><br>iki", 0)
    metin_olcusu = panel._size
    panel.show_menu("baslik", (("1", "ilk"), ("2", "ikinci")), ms=0)
    assert panel._size != metin_olcusu
    assert panel._size[1] > metin_olcusu[1]  # menude daha cok satir


# -- olculen tuzaklar -------------------------------------------------------
#
# Ikisi de `probes/tip.py` ile OLCULDU ve ikisi de sessizce bozuluyordu:
# program calisiyor, hata yok, yalnizca pencere yanlis davraniyor. Bu
# yuzden testleri var.


def test_movable_AYARLANMIYOR(qapp):
    """`window.movable = False` `window.visible = False`i BOZUYOR.

    OLCULDU (probes/tip.py, bayrak bayrak): o ayar konunca ipucu bir daha
    KAPANMIYOR -- `hide()` cagriliyor, `IsWindowVisible` hala True.
    Kaybedilen bir sey yok (pencere cercevesiz, suruklenecek baslik
    cubugu yok), ama geri eklenirse ipucu ekranda asili kalir.
    """
    panel = tip.TipPanel()
    sayfa = SahteSayfa()
    panel._build(sayfa)
    assert not hasattr(sayfa.window, "movable"), (
        "window.movable ayarlanmis -- bu ayar gizlemeyi bozuyor"
    )


def test_gorev_cubugundan_gizleme_BIR_KEZ(qapp, monkeypatch):
    """`skip_task_bar` OLCULDU ve ISLEMIYOR; is Win32'ye dusuyor.

    Bayrak pencere GIZLIYKEN konmali, yani her gosterimden ONCE deneniyor
    -- ama tuttuktan sonra bir daha degil.
    """
    panel = tip.TipPanel()
    cagrilar: list[tuple[int, bool]] = []
    monkeypatch.setattr(tip.win, "find_window", lambda **_kwargs: 0x1234)
    monkeypatch.setattr(
        tip.win,
        "set_tool_window",
        lambda hwnd, on: (cagrilar.append((hwnd, on)), True)[1],
    )
    panel.show_html("bir", 0)
    panel.show_html("iki", 0)
    panel.show_html("uc", 0)
    assert cagrilar == [(0x1234, True)]


def test_pencere_yoksa_SONRAKI_gosterimde_yeniden_deneniyor(qapp, monkeypatch):
    """`flet.exe` daha ayaga kalkmadiysa tutamak yok; vazgecilmemeli."""
    panel = tip.TipPanel()
    bulunan = [0, 0, 0xABCD]
    denemeler: list[int] = []

    def sahte_bul(**_kwargs):
        return bulunan.pop(0) if bulunan else 0xABCD

    def sahte_ayarla(hwnd, on):
        denemeler.append(hwnd)
        return True

    monkeypatch.setattr(tip.win, "find_window", sahte_bul)
    monkeypatch.setattr(tip.win, "set_tool_window", sahte_ayarla)
    panel.show_html("bir", 0)
    panel.show_html("iki", 0)
    panel.show_html("uc", 0)
    panel.show_html("dort", 0)
    assert denemeler == [0xABCD]
