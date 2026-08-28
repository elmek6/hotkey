"""Ham olay dokumu. Hook katmaninin en dusuk seviyeli dogrulamasi.

Amac: portun tum projeyi batirabilecek tek varsayimini olcmek --
LL hook kuruluyor mu, sol/sag modifier ayriliyor mu, tus yutulabiliyor mu,
scancode SendInput karsi tarafta gorunuyor mu, callback suresi Windows'un
300 ms'lik LowLevelHooksTimeout esiginin ne kadar altinda kaliyor.

Calistir:  uv run python -m probes.raw
"""

from __future__ import annotations

import queue
import sys
import time

from cascade.core.keynames import key_name
from cascade.win32 import consts as C
from cascade.win32 import send
from cascade.win32.hook import PASS, SWALLOW, HookThread, KeyEvent, MouseEvent
from cascade.win32.structs import user32

VK_F8, VK_F9, VK_F10, VK_Q = 0x77, 0x78, 0x79, 0x51
VK_CONTROL, VK_MENU = 0x11, 0x12

MOUSE_NAMES = {
    C.WM_LBUTTONDOWN: "LButton down", C.WM_LBUTTONUP: "LButton up",
    C.WM_RBUTTONDOWN: "RButton down", C.WM_RBUTTONUP: "RButton up",
    C.WM_MBUTTONDOWN: "MButton down", C.WM_MBUTTONUP: "MButton up",
    C.WM_XBUTTONDOWN: "XButton down", C.WM_XBUTTONUP: "XButton up",
    C.WM_MOUSEWHEEL: "WheelV", C.WM_MOUSEHWHEEL: "WheelH",
    C.WM_MOUSEMOVE: "Move",
}


def held(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def key_filter(event: KeyEvent) -> bool:
    """Hook thread'inde calisir. Tek isi yut/birak karari vermek."""
    if event.ours:
        return PASS
    if event.vk == VK_F8:
        return SWALLOW
    return PASS


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("cascade -- klavye/fare sondaji")
    print("-" * 62)
    print("  herhangi bir tus / fare      -> olay dokumu")
    print("  F8                           -> YUTULUR (hicbir uygulamaya gitmez)")
    print("  F9                           -> scancode SendInput testi (odaktaki pencereye yazar)")
    print("  F10                          -> fare testi: 60 px saga, sonra geri")
    print("  Ctrl+Alt+Q                   -> cikis (Ctrl+C de calisir)")
    print("-" * 62)
    print("Not: AHK scripti da acikken iki hook birlikte calisir, normaldir.\n")

    events: queue.Queue = queue.Queue(maxsize=4096)
    hook = HookThread(events, key_filter=key_filter)
    hook.start()
    print(f"hook kuruldu (thread {hook._thread_id})\n")

    counts = {"key": 0, "mouse": 0, "swallowed": 0}
    latencies: list[float] = []
    started = time.perf_counter()

    try:
        while True:
            try:
                event = events.get(timeout=0.2)
            except queue.Empty:
                continue

            if isinstance(event, KeyEvent):
                counts["key"] += 1
                name = key_name(event.vk, event.scan, event.extended)
                tags = []
                if event.extended:
                    tags.append("ext")
                if event.injected:
                    tags.append("ours" if event.ours else "injected")
                if event.vk == VK_F8:
                    tags.append("YUTULDU")
                    counts["swallowed"] += 1
                suffix = f"  [{' '.join(tags)}]" if tags else ""
                print(
                    f"KEY   {name:<12} vk=0x{event.vk:02X} sc=0x{event.scan:02X} "
                    f"{'down' if event.down else 'up  '}{suffix}"
                )

                if event.down and not event.ours:
                    if event.vk == VK_Q and held(VK_CONTROL) and held(VK_MENU):
                        print("\ncikis istendi.")
                        break
                    if event.vk == VK_F9:
                        time.sleep(0.05)
                        send.type_text("cascade ✓ ıİğĞşŞçÇöÖüÜ ")
                        send.tap(0x41, 0xA0)  # Shift+A -> scancode yolu
                        print("      -> type_text + tap(Shift+A) gonderildi")
                    elif event.vk == VK_F10:
                        send.move_relative(60, 0)
                        time.sleep(0.15)
                        send.move_relative(-60, 0)
                        print("      -> fare 60 px gidip geldi")

            elif isinstance(event, MouseEvent):
                counts["mouse"] += 1
                label = MOUSE_NAMES.get(event.message, f"0x{event.message:04X}")
                extra = ""
                if event.message in (C.WM_MOUSEWHEEL, C.WM_MOUSEHWHEEL):
                    extra = f" delta={event.data:+d}"
                elif event.message in (C.WM_XBUTTONDOWN, C.WM_XBUTTONUP):
                    extra = f" XButton{event.data}"
                if event.ours:
                    extra += " [ours]"
                print(f"MOUSE {label:<14} ({event.x},{event.y}){extra}")

            latencies.append((time.perf_counter() - event.t) * 1000.0)

    except KeyboardInterrupt:
        print("\nCtrl+C.")
    finally:
        hook.stop()

    elapsed = time.perf_counter() - started
    print("\n" + "=" * 62)
    print(f"sure                  : {elapsed:.1f} s")
    print(f"klavye olayi          : {counts['key']}")
    print(f"fare olayi            : {counts['mouse']}")
    print(f"yutulan tus           : {counts['swallowed']}")
    print(f"dusen olay (kuyruk)   : {hook.dropped}")
    print(f"en uzun hook callback : {hook.max_callback_ms:.3f} ms  (Windows siniri 300 ms)")
    if latencies:
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p99 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.99))]
        print(f"hook->tuketici gecikme: p50 {p50:.2f} ms / p99 {p99:.2f} ms")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
