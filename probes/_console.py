"""Sondaj scriptleri icin ortak konsol yardimcilari."""

from __future__ import annotations

import sys

from cascade.win32.structs import user32

VK_CONTROL, VK_MENU, VK_Q = 0x11, 0x12, 0x51


def setup_console() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def held(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def is_quit(vk: int) -> bool:
    """Ctrl+Alt+Q -- tum sondajlarda ayni cikis kombosu."""
    return vk == VK_Q and held(VK_CONTROL) and held(VK_MENU)


def banner(title: str, lines: list[str]) -> None:
    print(f"cascade -- {title}")
    print("-" * 66)
    for line in lines:
        print("  " + line)
    print("-" * 66)
    print("Not: AHK scripti da acikken iki hook birlikte calisir, normaldir.\n")


def stats(elapsed: float, counters: dict[str, int], hook, latencies: list[float]) -> None:
    print("\n" + "=" * 66)
    print(f"sure                  : {elapsed:.1f} s")
    for label, value in counters.items():
        print(f"{label:<22}: {value}")
    print(f"dusen olay (kuyruk)   : {hook.dropped}")
    print(f"en uzun hook callback : {hook.max_callback_ms:.3f} ms  (Windows siniri 300 ms)")
    if latencies:
        ordered = sorted(latencies)
        p50 = ordered[len(ordered) // 2]
        p99 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]
        print(f"hook->tuketici gecikme: p50 {p50:.2f} ms / p99 {p99:.2f} ms")
    print("=" * 66)
