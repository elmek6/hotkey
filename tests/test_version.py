"""Yapim damgasi -- "elimdeki kopya hangi gunun kodu" sorusunun cevabi.

Damga once yalnizca son git islemesinin tarihiydi: kodu degistirip programi
yeniden baslatan hala DUNUN tarihini goruyordu, cunku islememisti.
"""

import re

from cascade import version


def _stamp(monkeypatch, git):
    version.build_stamp.cache_clear()
    monkeypatch.setattr(version, "_git", git)
    try:
        return version.build_stamp()
    finally:
        version.build_stamp.cache_clear()


def test_kirli_agac_YILDIZLA_biter(monkeypatch):
    """ASIL SORUN BUYDU: kaydedilmis ama islenmemis degisiklik."""

    def git(*args):
        return " M cascade/app.py" if args[0] == "status" else "0903_2259"

    stamp = _stamp(monkeypatch, git)
    assert stamp.endswith(version.DIRTY_MARK)
    assert not stamp.startswith("0903_2259")


def test_temiz_agac_ISLEME_tarihini_verir(monkeypatch):
    def git(*args):
        return "" if args[0] == "status" else "0903_2259"

    assert _stamp(monkeypatch, git) == "0903_2259"


def test_git_yoksa_kaynak_tarihine_duser(monkeypatch):
    """Kaynak kopyalanmis olabilir -- damga yine de bir sey soylesin."""
    stamp = _stamp(monkeypatch, lambda *_args: None)
    assert re.fullmatch(r"\d{4}_\d{4}", stamp)


def test_kaynak_damgasi_TUM_dosyalara_bakar():
    """version.py'ye dokunmayan degisiklik de damgayi kimildatmali."""
    assert re.fullmatch(r"\d{4}_\d{4}", version._source_stamp())


def test_full_version_surum_ve_damgayi_birlestirir(monkeypatch):
    version.build_stamp.cache_clear()
    monkeypatch.setattr(version, "_git", lambda *a: "" if a[0] == "status" else "0101_0000")
    try:
        assert version.full_version() == f"{version.VERSION}+0101_0000"
    finally:
        version.build_stamp.cache_clear()
