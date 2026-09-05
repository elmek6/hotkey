"""QR sablonlari -- pencereyi degil, metne cevirme kuralini sinar.

Kritik yer wifi kacisi: kacirilmazsa parolanin icindeki `;` dizgiyi
bolerek telefonun yanlis aga baglanmasina yol aciyor.
"""

from __future__ import annotations

import pytest

from keypilot import qr


def build(key: str, **values: str) -> str:
    return qr.template(key).build(values)


def test_metin_oldugu_gibi_gecer():
    assert build("text", text="merhaba") == "merhaba"


@pytest.mark.parametrize(
    ("girdi", "beklenen"),
    [
        ("example.com", "https://example.com"),
        ("http://example.com", "http://example.com"),
        ("https://example.com", "https://example.com"),
        ("", ""),
    ],
)
def test_link_semasi_tamamlanir(girdi, beklenen):
    assert build("link", url=girdi) == beklenen


def test_wifi_bicimi():
    assert (
        build("wifi", ssid="EvAgi", password="parola", security="WPA", hidden="0")
        == "WIFI:T:WPA;S:EvAgi;P:parola;H:false;;"
    )


def test_wifi_ozel_karakterler_kacirilir():
    """`;` ve `:` kacirilmazsa alanlar bolunur."""
    assert build("wifi", ssid="Ev;Agi", password="a:b", security="WPA") == (
        "WIFI:T:WPA;S:Ev\\;Agi;P:a\\:b;H:false;;"
    )


def test_wifi_parolasiz_ag_parola_alani_yazmaz():
    assert build("wifi", ssid="Misafir", password="x", security="nopass") == (
        "WIFI:T:nopass;S:Misafir;H:false;;"
    )


def test_wifi_ssid_yoksa_kare_uretilmez():
    """Yarim wifi karesi telefonu bos baglanti diyaloguna sokuyor."""
    assert build("wifi", ssid="", password="parola") == ""


def test_gizli_ag_bayragi():
    assert build("wifi", ssid="Ag", security="nopass", hidden="1").endswith("H:true;;")


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("https://x.com", "link"),
        ("www.x.com", "link"),
        ("WIFI:T:WPA;S:a;;", "wifi"),
        ("duz metin", "text"),
    ],
)
def test_sablon_tahmini(metin, beklenen):
    assert qr.guess_template(metin) == beklenen


def test_bos_icerik_kare_uretmez():
    assert qr.png_bytes("") == b""
    assert qr.version_of("") == 0


def test_mikro_qr_uretilmez():
    """Kisa icerikte segno mikro kare seciyor; telefonlar onu okumuyor."""
    assert qr.version_of("kisa") >= 1


def test_png_uretilir():
    data = qr.png_bytes("deneme")
    assert data.startswith(b"\x89PNG")
