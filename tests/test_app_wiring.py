"""Cascade kurulum testi -- `__init__` bastan sona kosuyor mu.

Bolme sirasinda `self.slot_store` satiri kayboldu ve program acilista
patladi; birim testleri bunu goremezdi cunku denetleyiciler tek tek
kuruluyordu. Burada GERCEK kurulum yapiliyor, yalniz iki sey degistiriliyor:

  * HookThread -- sahte. Gercegi makinenin butun klavyesini dinler.
  * on_start   -- bos. Disk okumasi ve tepsi balonu testin isi degil.

Kalan her sey (pencereler, denetleyiciler, eylem kayitlari, zamanlayicilar)
programdaki gibi kuruluyor.
"""

from __future__ import annotations

import pytest

from cascade import app as app_module


class FakeHook:
    def __init__(self, *args, **kwargs) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


@pytest.fixture
def cascade(qapp, monkeypatch):
    monkeypatch.setattr(app_module, "HookThread", FakeHook)
    monkeypatch.setattr(app_module.Cascade, "on_start", lambda self: None)
    instance = app_module.Cascade(qapp)
    yield instance
    instance._shutdown()


def test_construction_binds_every_part(cascade):
    for name in ("clip", "slots", "slot_store", "dispatcher", "machine", "incognito"):
        assert getattr(cascade, name) is not None, f"kurulumda eksik: {name}"


def test_menu_actions_are_registered(cascade):
    """Menulerde gecen her eylem kimliginin bir kosucusu olmali."""
    for action in (
        "clip.paste",
        "clip.filter",
        "clip.images",
        "slot.paste",
        "slot.paste_group",
        "slots.save",
        "slots.search",
        "menu.slots",
        "menu.base_slots",
        "menu.side_slots",
        "incognito.open",
    ):
        assert action in cascade.runner.handlers, f"kayitsiz eylem: {action}"


def test_menus_can_be_built(cascade):
    """Menu kurgusu gercek depolarla uretilebiliyor mu (cagri patlamasin)."""
    assert cascade.slots.menu_spec()
    assert cascade.slots.side_menu_spec()
    assert cascade.clip.menu_items()


def test_kapanista_hata_aboneligi_birakilir(cascade):
    """`logs.errors` MODUL DUZEYINDE tek ornek: kapanan Cascade abone
    kalirsa olu nesnesine hata akmaya devam eder -- ve o nesne kritik
    hatada modal pencere aciyor. Testleri kilitleyen tam olarak buydu.
    """
    from cascade import logs

    assert cascade._error_sub in logs.errors._subs
    cascade._shutdown()
    assert cascade._error_sub not in logs.errors._subs


def test_kritik_hatalar_tek_pencerede_toplanir(cascade, monkeypatch):
    """Acilista uc dosya birden bozuk cikabilir. Kayitlar biriktirilip TEK
    pencerede gosteriliyor; ERROR hic pencere acmiyor."""
    acilan: list[list[str]] = []
    monkeypatch.setattr(
        type(cascade),
        "_flush_critical",
        lambda self: acilan.append(list(self._critical_pending)),
    )
    cascade._on_error_logged("CRITICAL", "slots.json bozuk")
    cascade._on_error_logged("CRITICAL", "profiles.json bozuk")
    cascade._on_error_logged("ERROR", "sadece rozet")

    assert cascade._critical_pending == ["slots.json bozuk", "profiles.json bozuk"]
    assert cascade._critical_scheduled  # bir sonraki olay turuna birakildi
    cascade._flush_critical()
    assert acilan == [["slots.json bozuk", "profiles.json bozuk"]]
