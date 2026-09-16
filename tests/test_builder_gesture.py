"""KeyBuilder jest / etiket / harvest."""

from keypilot.core.builder import KeyBuilder, PressType
from keypilot.core.hot_vectors import Direction, HotVectors
from keypilot.keymap import _harvest_gestures, build_cascades, build_gestures


def test_main_key_etiketli():
    definition = (
        KeyBuilder("F18", short=350, long=800)
        .main_key(PressType.MEDIUM, "send_key:Backspace", "Back")
        .main_key(PressType.LONG, "send_key:Home", "Home")
        .build()
    )
    assert definition.main[PressType.MEDIUM] == "send_key:Backspace"
    assert definition.main_labels[PressType.MEDIUM] == "Back"
    assert definition.overlay_center == {"P": "Back", "S": "Home"}


def test_gesture_every_ve_visible():
    definition = (
        KeyBuilder("F18")
        .gesture(Direction.LEFT, "Del", "send_key:Delete", every=5)
        .gestureVisible(False, "Back", "Home")
        .build()
    )
    assert definition.gestures[0].every == 5
    assert definition.gesture_visible is False
    assert definition.overlay_center == {"P": "Back", "S": "Home"}


def test_f13_jest_tek_kaynak_makineye_girmez():
    cascades = build_cascades()
    f13 = cascades[0x7C]
    assert f13.run_cascade is False
    assert len(f13.gestures) == 4
    gestures = build_gestures()
    assert gestures.has(0x7C)
    assert (0x7C, Direction.UP) in gestures.defs
    assert gestures.defs[(0x7C, Direction.UP)].desc == "Zoom+"


def test_f18_harvest_p_s():
    cascades = build_cascades()
    f18 = cascades[0x81]
    tracker = HotVectors()
    _harvest_gestures(tracker, f18)
    assert tracker.labels(0x81)["L"] == "Del"
    assert tracker.labels(0x81)["P"] == "Back"
    assert tracker.labels(0x81)["S"] == "Home"
    assert tracker.visible(0x81) is True


def test_every_bes_adimda_bir():
    t = HotVectors(step_px=10.0, lock_px=5.0)
    t.register(0x7C, Direction.RIGHT, "a", "A", every=5)
    t.start(0x7C)
    # 40 px = 4 adim -> tetik yok
    assert t.move(40, 0) == []
    # +10 = 5. adim -> 1 tetik
    events = t.move(10, 0)
    assert len(events) == 1 and events[0].steps == 1
