"""Gelistirme modu salteri -- keypilot/dev.py.

Burada sinanan sey davranis degil KARAR: hangi kaynak hangisini yeniyor,
yanlis yazilmis bir anahtar ne yapiyor, zorlama kullanicinin ayarina
dokunuyor mu. Uctu de sessizce yanlis calisabilecek turden -- "gelistirme
modu acik sanmistim" ile "kapali sanmistim" ayni kolaylikta oluyor ve
ikisi de log'a bakmadan fark edilmiyor.
"""

from __future__ import annotations

import pytest

from keypilot import dev
from keypilot.settings import Category


@pytest.fixture
def ayarlar():
    """Ayarlari test sonunda eski haline dondurur -- SETTINGS tek ornek."""
    mode, ms = dev.DEV_MODE.get(), dev.HOOK_WATCHDOG_MS.get()
    yield
    dev.DEV_MODE.set(mode)
    dev.HOOK_WATCHDOG_MS.set(ms)


def zorla(monkeypatch, mode, ms) -> None:
    monkeypatch.setattr(dev, "OVERRIDE", dev.Override(mode=mode, hook_ms=ms, source="test"))


# ---- gramer: bayrak acar/kapar, ayrinti anahtar=deger ----


def test_bayrak_acar_anahtar_ayrinti_verir(monkeypatch):
    monkeypatch.setattr(dev.sys, "argv", ["main.py", "--dev", "hook=300"])
    over = dev._from_argv()
    assert (over.mode, over.hook_ms) == (True, 300)
    assert over.problems == ()


def test_yalin_bayrak_yalnizca_acar(monkeypatch):
    """Nobetci araligi ayardan gelir -- bayrak onu kendiliginden kurmaz."""
    monkeypatch.setattr(dev.sys, "argv", ["main.py", "--dev"])
    assert dev._from_argv() == dev.Override(mode=True, source=dev.FLAG)


def test_baska_bayrakta_duruyor(monkeypatch):
    """`--dev hook=300 --supervised` dogru bolunmeli."""
    monkeypatch.setattr(dev.sys, "argv", ["main.py", "--dev", "--supervised", "hook=300"])
    assert dev._from_argv().hook_ms is None, "sonraki bayragin ardindaki parca bize ait degil"


def test_anlasilmayan_anahtar_sessizce_yutulmaz(monkeypatch):
    """Yazim hatasi log'da gorunmeli: "hook=300 yazdim ama calismadi" olmasin."""
    monkeypatch.setattr(dev.sys, "argv", ["main.py", "--dev", "hok=300", "hook=abc"])
    over = dev._from_argv()
    assert over.hook_ms is None
    assert len(over.problems) == 2
    monkeypatch.setattr(dev, "OVERRIDE", over)
    assert dev.problems() == over.problems, "acilista uyari olarak yazilmali"


# ---- kaynak sirasi ----


def test_komut_satiri_ortam_degiskenini_yener(monkeypatch):
    monkeypatch.setattr(dev.sys, "argv", ["main.py", "--dev", "hook=900"])
    monkeypatch.setenv(dev.ENV_VAR, "hook=300")
    over = dev._override()
    assert (over.hook_ms, over.source) == (900, dev.FLAG)


def test_ortam_degiskeninin_VARLIGI_acar(monkeypatch):
    monkeypatch.setattr(dev.sys, "argv", ["main.py"])
    monkeypatch.setenv(dev.ENV_VAR, "hook=300")
    over = dev._override()
    assert (over.mode, over.hook_ms, over.source) == (True, 300, dev.ENV_VAR)


def test_bayrak_yoksa_zorlama_yok(monkeypatch):
    monkeypatch.setattr(dev.sys, "argv", ["main.py", "--supervised"])
    monkeypatch.delenv(dev.ENV_VAR, raising=False)
    assert dev._override().mode is None


def test_bayraklar_cocuga_aynen_gecer(monkeypatch):
    """Reload edince gelistirme modu kapanmamali (app.restart bunu tasiyor)."""
    monkeypatch.setattr(dev.sys, "argv", ["main.py", "--dev", "hook=300", "--supervised"])
    assert dev.argv_flags() == ["--dev", "hook=300"]


# ---- ayarla iliski ----


def test_zorlama_ayari_yener_ve_ayara_YAZMAZ(monkeypatch, ayarlar):
    """Bayrak bir CALISMAYI baglar; kullanicinin settings.json'ina degmez."""
    dev.DEV_MODE.set(False)
    zorla(monkeypatch, True, 1500)
    assert dev.enabled()
    assert dev.hook_watchdog_ms() == 1500
    assert dev.DEV_MODE.get() is False, "ayar degeri degismemeli"


def test_ana_salter_kapaliyken_alt_ayar_okunmaz(monkeypatch, ayarlar):
    """Salterin butun anlami bu: alt ayar acik kalsa bile susmali."""
    zorla(monkeypatch, None, None)
    dev.DEV_MODE.set(False)
    dev.HOOK_WATCHDOG_MS.set(2000)
    assert dev.hook_watchdog_ms() == 0
    dev.DEV_MODE.set(True)
    assert dev.hook_watchdog_ms() == 2000


def test_nobetci_araligi_dogrulaniyor(ayarlar):
    """0=yok,500-60000 ms."""
    assert dev.HOOK_WATCHDOG_MS.set(0) == ""
    assert dev.HOOK_WATCHDOG_MS.set(2000) == ""
    assert dev.HOOK_WATCHDOG_MS.set(50) != "", "cok kucuk deger reddedilmeli"
    assert dev.HOOK_WATCHDOG_MS.set(90_000) != "", "cok buyuk deger reddedilmeli"


def test_gelistirme_kategorisi_en_ustte():
    """Bolum ayar ekraninin EN USTUNDE dursun.

    Ayri bir sira listesi YOK: sira KAYIT sirasi ve `main.py` `keypilot.dev`i
    ilk import ediyor. Bu yuzden test ayri bir surecte kosuyor -- ayni
    surecte baska testler keypilot modullerini coktan import etmis olur ve
    kayit sirasi onlarin izini tasir. Sinanan sey gercek acilis yolu.
    """
    import subprocess
    import sys

    probe = "import main; from keypilot.settings import SETTINGS; print(SETTINGS.categories[0])"
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == Category.DEVELOPMENT


# ---- tek seferlik kapatma: "Reload (dev off)" ----


def test_isaret_bir_sonraki_calismayi_KAPALI_baslatir(monkeypatch, tmp_path):
    """Gozetmen altinda cocugun komut satirina dokunamiyoruz.

    "Reload" bekci programini calistiriyor, o da kendi komut satirini
    (icinde `--dev`) kullaniyor -- yani bayragi silmek mumkun degil.
    Sonraki calismaya not birakmanin tek yolu disk.
    """
    monkeypatch.setattr(dev, "OFF_ONCE_FILE", tmp_path / ".dev-off")
    monkeypatch.setattr(dev.sys, "argv", ["main.py", "--dev"])

    assert dev._override().mode is True  # bayrak: acik

    dev.request_off_once()
    over = dev._override()
    assert over.mode is False  # isaret bayragi YENIYOR
    assert "dev off" in over.source


def test_isaret_TEK_SEFERLIK_tuketiliyor(monkeypatch, tmp_path):
    """Ikinci acilista mod yine bayragin/ayarin dedigi gibi olmali."""
    monkeypatch.setattr(dev, "OFF_ONCE_FILE", tmp_path / ".dev-off")
    monkeypatch.setattr(dev.sys, "argv", ["main.py", "--dev"])

    dev.request_off_once()
    assert dev._override().mode is False
    assert not (tmp_path / ".dev-off").exists()  # tuketildi
    assert dev._override().mode is True


def test_kapatma_zorlamasi_log_satirinda_dogru_yazilir(monkeypatch):
    zorla(monkeypatch, mode=False, ms=None)
    assert "kapali" in dev.override_note()
