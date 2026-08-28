"""Klavye kombo sondaji -- Faz 1'in canli karsiligi.

Olculen sey: AHK'nin tus dilinin tamami Python'da uretilebiliyor mu?
  - modifier kombolari, sol/sag ayrimiyla      (LCtrl+LShift+K)
  - prefix kombolari, AHK'deki 'a & b'         (CapsLock & J)
  - kisa / orta / uzun basim siniflandirmasi   (key_handler_cascade)
  - bir tusu tamamen yutup yeniden amaclandirma (CapsLock artik toggle etmez)

Calistir:  uv run python -m probes.keys
"""

from __future__ import annotations

import queue
import time

from cascade.core.combo import ComboTracker, Thresholds
from cascade.core.keynames import MODIFIER_VKS, key_name
from cascade.win32.hook import PASS, SWALLOW, HookThread, KeyEvent
from probes._console import banner, is_quit, setup_console, stats

VK_CAPSLOCK = 0x14

# Hook thread'inde yasar: yalnizca yut/birak karari icin. O(1) sozluk islemi.
_hook_state = ComboTracker()


def key_filter(event: KeyEvent) -> bool:
    if event.ours:
        return PASS

    if event.down:
        _hook_state.key_down(event.vk, event.t)
    else:
        _hook_state.key_up(event.vk, event.t)

    # 1) CapsLock tamamen yutulur -> hicbir zaman toggle etmez, serbest prefix olur.
    if event.vk == VK_CAPSLOCK:
        return SWALLOW
    # 2) CapsLock basiliyken normal tuslar da yutulur -> CapsLock+J 'j' yazmaz.
    if _hook_state.is_down(VK_CAPSLOCK) and event.vk not in MODIFIER_VKS:
        return SWALLOW
    return PASS


def main() -> int:
    setup_console()
    banner(
        "klavye kombo sondaji",
        [
            "Ctrl+Shift+K gibi     -> modifier kombosu, sol/sag ayrimiyla",
            "CapsLock              -> TAMAMEN YUTULUR, artik toggle etmiyor",
            "CapsLock + J          -> prefix kombosu, 'j' harfi de yazilmaz",
            "bir tusu basili tut   -> birakinca kisa/orta/uzun siniflandirmasi",
            "Ctrl+Alt+Q            -> cikis",
        ],
    )

    events: queue.Queue = queue.Queue(maxsize=4096)
    hook = HookThread(events, key_filter=key_filter)
    hook.start()

    view = ComboTracker(Thresholds(short_ms=200, long_ms=500))
    counters = {"kombo": 0, "basim": 0, "yutulan": 0, "tekrar": 0}
    latencies: list[float] = []
    started = time.perf_counter()

    try:
        while True:
            try:
                event = events.get(timeout=0.2)
            except queue.Empty:
                continue
            if not isinstance(event, KeyEvent) or event.ours:
                continue

            latencies.append((time.perf_counter() - event.t) * 1000.0)
            swallowed = event.vk == VK_CAPSLOCK or (
                view.is_down(VK_CAPSLOCK) and event.vk not in MODIFIER_VKS
            )

            if event.down:
                chord = view.key_down(event.vk, event.t)
                if chord is None:
                    print(f"  mod   {key_name(event.vk):<10} basildi")
                    continue
                if chord.repeat:
                    counters["tekrar"] += 1
                    continue
                counters["kombo"] += 1
                if swallowed:
                    counters["yutulan"] += 1
                tag = "  [YUTULDU]" if swallowed else ""
                kind = "prefix" if chord.prefix is not None else "kombo "
                print(f"{kind} {chord.text:<26} sc=0x{event.scan:02X}{tag}")
            else:
                press = view.key_up(event.vk, event.t)
                if press is None or event.vk in MODIFIER_VKS:
                    continue
                counters["basim"] += 1
                if swallowed:
                    counters["yutulan"] += 1
                note = ""
                if press.was_prefix:
                    note = "  (prefix olarak kullanildi -> kendi eylemi calismaz)"
                print(
                    f"       {press.text:<26} {press.ms:6.0f} ms"
                    f" -> {press.kind.label} basim{note}"
                )

            if event.down and is_quit(event.vk):
                print("\ncikis istendi.")
                break
    except KeyboardInterrupt:
        print("\nCtrl+C.")
    finally:
        hook.stop()

    stats(time.perf_counter() - started, counters, hook, latencies)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
