"""Makro denetleyicisi -- pencere ile veri katmani arasindaki bag.

Oynatma ayri thread'de kostugu icin testler `finished` sinyalini bekliyor;
gercek `send.py` cagrilmasin diye oynatici tumuyle sahte.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from keypilot import macro
from keypilot.macro_ctl import MacroController
from keypilot.win32.hook import KeyEvent, MouseEvent


@pytest.fixture(autouse=True)
def files_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(macro.paths, "FILES", tmp_path)
    monkeypatch.setattr(macro.paths, "ensure_files_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def ctl(qapp):
    controller = MacroController()
    yield controller
    controller.shutdown()
    controller.view.close()


def key(vk: int, down: bool = True) -> KeyEvent:
    return KeyEvent(
        vk=vk, scan=0, down=down, extended=False, injected=False, ours=False, time_ms=0, t=0.0
    )


def mouse(message: int) -> MouseEvent:
    return MouseEvent(
        message=message, x=5, y=5, data=0, injected=False, ours=False, time_ms=0, t=0.0
    )


@dataclass
class Sahte:
    """`macro.Player` yerine gecer -- gercek girdi gonderilmesin."""

    oynatilan: list

    def play(self, events, repeat=1):
        self.oynatilan.extend(events)
        return len(self.oynatilan)


def test_kayit_dosyaya_yazilir(ctl, files_dir):
    ctl.start_record(1, macro.KEY)
    ctl.feed(key(65))
    ctl.feed(key(65, down=False))
    ctl.stop(1, "deneme")
    assert macro.read(macro.slot_path(1)) == ("deneme", ctl.recorder.events)
    assert "2 olay" in ctl.view.status


def test_esc_kaydi_bitirip_yazar(ctl, files_dir):
    """Kaydedici kendini durdurunca denetleyici diske yazmali."""
    ctl.view.name = "esc"
    ctl.start_record(1, macro.KEY)
    ctl.feed(key(65))
    ctl.feed(key(macro.VK_ESCAPE))
    assert not ctl.recorder.recording
    assert macro.slot_path(1).exists()
    assert [e["vk"] for e in macro.read(macro.slot_path(1))[1]] == [65]


def test_key_modunda_fare_beslemesi_yok_sayilir(ctl):
    ctl.start_record(1, macro.KEY)
    ctl.feed(mouse(0x0201))
    assert ctl.recorder.events == []


def test_hybrid_modunda_fare_kaydedilir(ctl):
    ctl.start_record(1, macro.HYBRID)
    ctl.feed(mouse(0x0201))
    assert [e["e"] for e in ctl.recorder.events] == ["mouse"]


def test_kayit_yokken_besleme_bedava(ctl):
    ctl.feed(key(65))
    assert ctl.recorder.events == []


def test_bos_slot_oynatilmaz(ctl, files_dir):
    ctl.play(2)
    assert "bos" in ctl.view.status.lower()


def test_oynatma_bitince_durum_tazelenir(ctl, files_dir, qapp, monkeypatch):
    oynatilan: list = []
    monkeypatch.setattr(macro, "Player", lambda **_kwargs: Sahte(oynatilan))
    macro.write(macro.slot_path(1), [{"dt": 0, "e": "key", "vk": 65, "down": True}], "x")

    ctl.play(1)
    assert ctl._thread is not None
    ctl._thread.join(timeout=2)
    qapp.processEvents()
    assert [e["vk"] for e in oynatilan] == [65]
    assert "Bitti" in ctl.view.status


def test_esc_oynatmayi_keser(ctl, files_dir, monkeypatch):
    """Oynatma sirasinda klavye kullanicinin elinden ciktigi icin panik
    tusu KAYIT kapaliyken de is gormeli."""
    monkeypatch.setattr(macro, "Player", lambda **_kwargs: Sahte([]))
    macro.write(macro.slot_path(1), [{"dt": 0, "e": "key", "vk": 65, "down": True}], "x")
    ctl.play(1)
    ctl._stop.clear()  # thread bitmis olabilir; kesme yolunu tek basina sina
    monkeypatch.setattr(ctl, "_playing", lambda: True)
    ctl.feed(key(macro.VK_ESCAPE))
    assert ctl._stop.is_set()


def test_eylem_kaydi(ctl, monkeypatch):
    kayitli: dict = {}

    class Runner:
        def register(self, name, fn):
            kayitli[name] = fn

    ctl.register(Runner())
    assert "macro.recorder" in kayitli
    # Panel Flet'te: `open` gercekte bir Flet thread'i (ve `flet.exe`)
    # baslatiyor. Testin sordugu sey pencerenin ACILDIGI, o yuzden motor
    # susturuluyor ve ana thread'deki gorunurluk bayragina bakiliyor.
    monkeypatch.setattr(ctl.view._engine, "start", lambda: None)
    kayitli["macro.recorder"](None)
    assert ctl.view.visible


def test_dispatcher_yolundan_gelen_fare_kaydedilir(ctl):
    """GERCEK yol: hook -> Dispatcher -> `seen` kuyrugu -> ctl.feed.

    `feed`e elle `MouseEvent` vermek yolu sinamiyordu: dispatch.py o
    kuyruga cevrilmis `MouseSeen` koyuyor. Cevrilmis bicim eskiden
    `isinstance(event, MouseEvent)` suzgecine takilmiyordu ve "Yalniz
    fare" kaydi BOS dosya cikiyordu.
    """
    import queue

    from keypilot.core.cascade import CascadeMachine
    from keypilot.core.hot_vectors import HotVectors
    from keypilot.core.hotkey import HotkeyTable
    from keypilot.dispatch import Dispatcher

    seen: queue.Queue = queue.Queue()
    dispatcher = Dispatcher(
        machine=CascadeMachine(),
        hotkeys=HotkeyTable(),
        gestures=HotVectors(),
        actions=queue.Queue(),
        seen=seen,
        menu_open=lambda: False,
    )
    # ard arda gelen sahte tik yutulmasin
    dispatcher.bounce_guard_left = False
    dispatcher.bounce_guard_middle = False

    ctl.start_record(1, macro.HYBRID)
    dispatcher.mouse_filter(mouse(0x0201))  # WM_LBUTTONDOWN
    dispatcher.mouse_filter(mouse(0x0202))  # WM_LBUTTONUP
    while not seen.empty():
        ctl.feed(seen.get_nowait()[0])

    assert [event["e"] for event in ctl.recorder.events] == ["mouse", "mouse"]
