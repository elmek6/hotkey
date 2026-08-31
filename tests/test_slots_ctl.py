"""SlotController testleri -- app.py'den ayrilan slot mantigi.

Denetleyici butun bagimliliklarini disaridan aldigi icin sahte geri
aramalarla kosuyor: pencere, hook ve disk disi hicbir sey gerekmiyor.
"""

from __future__ import annotations

import pytest

from cascade.slots_ctl import SlotController
from cascade.store import PASSWORD_SLOT, SlotStore


class Recorder:
    """Denetleyicinin disariya yaptigi cagrilari toplar."""

    def __init__(self) -> None:
        self.tips: list[str] = []
        self.menus: list[tuple] = []
        self.pasted: list[tuple[str, bool]] = []
        self.copied: list[tuple[str, bool]] = []
        self.filters: list[tuple[tuple, str]] = []
        self.keys: list[str] = []


@pytest.fixture
def controller(tmp_path):
    store = SlotStore(tmp_path)
    store.load()
    store.set_slot_content("", 1, "birinci")
    store.set_slot_name("", 1, "Ilk")
    store.set_slot_content("", PASSWORD_SLOT, "gizli-sifre")
    store.add_group("is")
    store.set_slot_content("is", 3, "is icerigi")

    log = Recorder()
    ctl = SlotController(
        store,
        tip_html=lambda body, ms: log.tips.append(body),
        show_menu=log.menus.append,
        paste_text=lambda text, private=False: log.pasted.append((text, private)),
        set_clipboard=lambda text, private=False: log.copied.append((text, private)),
        show_filter=lambda items, title: log.filters.append((items, title)),
        send_key=log.keys.append,
    )
    return ctl, log


def test_split_argument():
    assert SlotController.split("is/3") == ("is", 3)
    assert SlotController.split("/10") == ("", 10)
    assert SlotController.split("bozuk") == ("", 0)


def test_paste_slot_uses_default_group(controller):
    ctl, log = controller
    ctl.paste_slot("1")
    assert log.pasted == [("birinci", False)]


def test_paste_slot_empty_only_warns(controller):
    ctl, log = controller
    ctl.paste_slot("2")
    assert log.pasted == []
    assert "bos" in log.tips[-1]


def test_password_slot_is_private(controller):
    ctl, log = controller
    ctl.paste_slot(str(PASSWORD_SLOT))
    assert log.pasted == [("gizli-sifre", True)]
    # Ipucunda sifre GORUNMEMELI (store.slot_display maskeliyor).
    assert "gizli-sifre" not in log.tips[-1]


def test_paste_from_named_group(controller):
    ctl, log = controller
    ctl.paste_slot_of("is/3")
    assert log.pasted == [("is icerigi", False)]


def test_side_slot_needs_selection(controller):
    ctl, log = controller
    ctl.store.set_default_group("")
    ctl.paste_side_slot("3")
    assert log.pasted == []

    ctl.store.set_default_group("is")
    ctl.paste_side_slot("3")
    assert log.pasted == [("is icerigi", False)]


def test_copy_slot_marks_password_private(controller):
    ctl, log = controller
    ctl.copy_slot(f"/{PASSWORD_SLOT}")
    assert log.copied == [("gizli-sifre", True)]


def test_filter_skips_password_and_empty(controller):
    ctl, log = controller
    ctl.show_filter()
    items, title = log.filters[-1]
    assert title == "Slotlar"
    contents = [item.content for item in items]
    assert "birinci" in contents
    assert "is icerigi" in contents
    assert "gizli-sifre" not in contents


def test_menu_items_carry_group_and_index(controller):
    ctl, _ = controller
    items = ctl.items("is", "slot.paste_group")
    assert len(items) == 10
    assert items[2][1] == "slot.paste_group:is/3"
    assert items[1][0].endswith("(bos)")


def test_menu_spec_has_side_group_column(controller):
    ctl, _ = controller
    ctl.store.set_default_group("is")
    spec = ctl.menu_spec()
    labels = [row[0] for row in spec if isinstance(row, tuple)]
    assert any("Side slot [is]" in label for label in labels)
    assert any(label.startswith("⇥ ") for label in labels)


def test_registered_action_ids(controller):
    ctl, _ = controller
    registered: dict = {}

    class FakeRunner:
        @staticmethod
        def register(key, handler):
            registered[key] = handler

    ctl.register(FakeRunner())
    assert "slot.paste" in registered
    assert "menu.slots" in registered
    assert "slots.group_delete" in registered
