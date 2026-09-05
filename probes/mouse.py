"""Fare sondaji -- dugmeler, tekerlek, XButton'lar ve fare/klavye komboları.

Onemli tasarim noktasi: fare dugmeleri VK 0x01/0x02/0x04/0x05/0x06 olarak
ayni ComboTracker'a besleniyor. Boylece 'MButton & RButton' ve
'CapsLock & RButton' gibi AHK kombolari ek kod olmadan cikiyor -- klavye ile
fare tek bir tus uzayi.

Calistir:  uv run python -m probes.mouse
"""

from __future__ import annotations

import queue
import time

from keypilot.core.combo import ComboTracker
from keypilot.core.keynames import key_name
from keypilot.win32 import consts as C
from keypilot.win32.hook import PASS, SWALLOW, HookThread, KeyEvent, MouseEvent
from probes._console import banner, is_quit, setup_console, stats

VK_LBUTTON, VK_RBUTTON, VK_MBUTTON = 0x01, 0x02, 0x04
VK_XBUTTON1, VK_XBUTTON2 = 0x05, 0x06

BUTTON_DOWN = {
    C.WM_LBUTTONDOWN: VK_LBUTTON,
    C.WM_RBUTTONDOWN: VK_RBUTTON,
    C.WM_MBUTTONDOWN: VK_MBUTTON,
}
BUTTON_UP = {
    C.WM_LBUTTONUP: VK_LBUTTON,
    C.WM_RBUTTONUP: VK_RBUTTON,
    C.WM_MBUTTONUP: VK_MBUTTON,
}

_hook_state = ComboTracker()


def _button_vk(event: MouseEvent) -> tuple[int | None, bool]:
    """(vk, down) -- dugme olayi degilse (None, False)."""
    if event.message in BUTTON_DOWN:
        return BUTTON_DOWN[event.message], True
    if event.message in BUTTON_UP:
        return BUTTON_UP[event.message], False
    if event.message == C.WM_XBUTTONDOWN:
        return (VK_XBUTTON1 if event.data == 1 else VK_XBUTTON2), True
    if event.message == C.WM_XBUTTONUP:
        return (VK_XBUTTON1 if event.data == 1 else VK_XBUTTON2), False
    return None, False


def mouse_filter(event: MouseEvent) -> bool:
    if event.ours:
        return PASS
    vk, down = _button_vk(event)
    if vk is None:
        return PASS
    if down:
        _hook_state.key_down(vk, event.t)
    else:
        _hook_state.key_up(vk, event.t)
    # XButton2 (ileri tusu) tamamen yutulur -> fare dugmesi de yutulabiliyor mu?
    if vk == VK_XBUTTON2:
        return SWALLOW
    return PASS


def key_filter(event: KeyEvent) -> bool:
    if event.ours:
        return PASS
    if event.down:
        _hook_state.key_down(event.vk, event.t)
    else:
        _hook_state.key_up(event.vk, event.t)
    return PASS


def main() -> int:
    setup_console()
    banner(
        "fare sondaji",
        [
            "sol/sag/orta tik      -> dugme + koordinat",
            "XButton1 (geri)       -> yakalanir, gecer",
            "XButton2 (ileri)      -> YUTULUR, tarayicida ileri gitmez",
            "tekerlek              -> dikey/yatay, delta ile",
            "MButton basiliyken sag tik / CapsLock basiliyken tik -> kombo",
            "Ctrl+Alt+Q            -> cikis",
        ],
    )

    events: queue.Queue = queue.Queue(maxsize=4096)
    hook = HookThread(events, key_filter=key_filter, mouse_filter=mouse_filter)
    hook.start()

    view = ComboTracker()
    counters = {"dugme": 0, "tekerlek": 0, "yutulan": 0, "kombo": 0}
    latencies: list[float] = []
    started = time.perf_counter()

    try:
        while True:
            try:
                event = events.get(timeout=0.2)
            except queue.Empty:
                continue
            if event.ours:
                continue
            latencies.append((time.perf_counter() - event.t) * 1000.0)

            if isinstance(event, KeyEvent):
                if event.down:
                    view.key_down(event.vk, event.t)
                    if is_quit(event.vk):
                        print("\ncikis istendi.")
                        break
                else:
                    view.key_up(event.vk, event.t)
                continue

            if not isinstance(event, MouseEvent):
                continue

            if event.message in (C.WM_MOUSEWHEEL, C.WM_MOUSEHWHEEL):
                counters["tekerlek"] += 1
                eksen = "WheelH" if event.message == C.WM_MOUSEHWHEEL else "WheelV"
                yon = "yukari/saga" if event.data > 0 else "asagi/sola"
                onek = "+".join(key_name(k) for k in view.held)
                onek = f"{onek} & " if onek else ""
                print(f"tekerlek {onek}{eksen:<8} delta={event.data:+5d} ({yon})")
                continue

            vk, down = _button_vk(event)
            if vk is None:
                continue

            if down:
                chord = view.key_down(vk, event.t)
                counters["dugme"] += 1
                if vk == VK_XBUTTON2:
                    counters["yutulan"] += 1
                if chord is not None and chord.prefix is not None:
                    counters["kombo"] += 1
                text = chord.text if chord else key_name(vk)
                tag = "  [YUTULDU]" if vk == VK_XBUTTON2 else ""
                print(f"dugme    {text:<26} ({event.x},{event.y}){tag}")
            else:
                press = view.key_up(vk, event.t)
                if press is None:
                    continue
                note = "  (prefix olarak kullanildi)" if press.was_prefix else ""
                print(f"         {press.text:<26} {press.ms:6.0f} ms -> {press.kind.label}{note}")
    except KeyboardInterrupt:
        print("\nCtrl+C.")
    finally:
        hook.stop()

    stats(time.perf_counter() - started, counters, hook, latencies)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
