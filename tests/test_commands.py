"""Eylem katalogu -- StrEnum kimlik + parametreli cagri."""

from keypilot.commands import Cmd, Id


def test_parametresiz_strenum_dizgiye_esit():
    assert Cmd.Menu.F13 == "menu.f13"
    assert Cmd.App.PAUSE_DIALOG == "app.pause_dialog"
    assert Cmd.Menu.CLIP == "menu.clip"


def test_id_cagrisi_arguman_ekler():
    assert Cmd.Clip.PASTE(3) == "clip.paste:3"
    assert Cmd.Memslots.PASTE_SLOT(1) == "memslots.paste_slot:1"
    assert Cmd.Menu.QUICK("Slot") == "menu.quick:Slot"
    assert isinstance(Cmd.Clip.PASTE, Id)


def test_send_key_factory():
    assert Cmd.send_key("^z") == "send_key:^z"
    assert Cmd.send_key("#NumpadAdd") == "send_key:#NumpadAdd"
    assert Cmd.send_keys("^a", "^v") == "send_keys:^a ^v"
    assert Cmd.send_text("selam") == "send_text:selam"
