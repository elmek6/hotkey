"""ClipController testleri -- app.py'den ayrilan pano mantigi.

Depolar tmp_path'e kuruluyor: gercek `Files/` klasoruna dokunulmuyor.
"""

from __future__ import annotations

import pytest

from cascade.clip_ctl import ClipController
from cascade.core.state import ClipboardMode


class Recorder:
    def __init__(self) -> None:
        self.tips: list[str] = []
        self.tip_menus: list[tuple] = []
        self.menus: list[tuple] = []
        self.filters: list[tuple] = []
        self.keys: list[str] = []
        self.mem: list[str] = []


@pytest.fixture
def clip(qapp, tmp_path):
    log = Recorder()
    ctl = ClipController(
        tip_html=lambda body, ms: log.tips.append(body),
        tip_menu=lambda title, items, footer="", ms=0: log.tip_menus.append((title, items)),
        show_menu=log.menus.append,
        show_filter=lambda items, title: log.filters.append((items, title)),
        send_key=log.keys.append,
        to_mem_slots=log.mem.append,
        directory=tmp_path,
    )
    yield ctl, log
    ctl.close()


def test_copied_text_enters_history(clip):
    ctl, log = clip
    ctl.on_text("merhaba")
    assert [entry.text for entry in ctl.history.entries] == ["merhaba"]
    assert log.tips  # kopyalanan sey ipucunda gosterildi


def test_mem_slots_mode_bypasses_history(clip):
    ctl, log = clip
    ctl.state.set_mem_slots()
    ctl.on_text("bloga gitsin")
    assert log.mem == ["bloga gitsin"]
    assert len(ctl.history) == 0


def test_history_off_records_nothing(clip):
    ctl, _ = clip
    ctl.state.set_mode(ClipboardMode.NONE)
    ctl.on_text("kayitsiz")
    assert len(ctl.history) == 0


def test_paste_history_index_is_one_based(clip):
    ctl, log = clip
    ctl.on_text("bir")
    ctl.on_text("iki")
    ctl.paste_history("1")
    # En son kopyalanan listenin basinda: 1 -> "iki"
    assert ctl.history.get(1).text == "iki"
    assert log.tips[-1]


def test_paste_history_missing_index_warns(clip):
    ctl, log = clip
    ctl.paste_history("7")
    assert "kayit yok" in log.tips[-1]


def test_filter_items_carry_content(clip):
    ctl, log = clip
    ctl.on_text("aranacak")
    ctl.show_filter()
    items, title = log.filters[-1]
    assert title == "Pano gecmisi"
    assert items[0].content == "aranacak"


def test_empty_history_opens_no_list(clip):
    ctl, log = clip
    ctl.show_filter()
    ctl.show_menu()
    ctl.show_history()
    assert not log.filters
    assert not log.menus
    assert not log.tip_menus
    assert all("bos" in tip for tip in log.tips)


def test_menu_items_have_search_row(clip):
    ctl, _ = clip
    ctl.on_text("kayit")
    items = ctl.menu_items()
    assert items[0] == ("Search on history", "clip.filter")
    assert items[2][1] == "clip.paste:1"


def test_disk_round_trip(clip):
    ctl, _ = clip
    ctl.on_text("diske yazilacak")
    assert ctl.save()
    assert ctl.store.path.exists()

    ctl.history.clear()
    assert ctl.load() == 1
    assert ctl.history.get(1).text == "diske yazilacak"
