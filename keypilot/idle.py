"""Ekran koruyucu engelleyici -- sure hesabi.

Tur araligi 5 dakika. Is bilgisayari 8 saatlik butceyle acilir, ev
bilgisayari 0 (kapali). Kullanici `´` menusunden ("t: Zamanlayici...")
dakikayi degistirir, etiket saat:dakika gosterir.
"""

from __future__ import annotations

from enum import StrEnum

TICK_MINUTES = 5
IDLE_INTERVAL_MS = TICK_MINUTES * 60 * 1000
WORK_MINUTES = 8 * 60
HOME_MINUTES = 0


def ticks_for(minutes: int) -> int:
    minutes = max(0, int(minutes))
    if minutes == 0:
        return 0
    return (minutes + TICK_MINUTES - 1) // TICK_MINUTES


def minutes_for(ticks: int) -> int:
    return max(0, int(ticks)) * TICK_MINUTES


def clock_label(minutes: int) -> str:
    hours, mins = divmod(max(0, int(minutes)), 60)
    return f"{hours}:{mins:02d}"


class Computer(StrEnum):
    """Hangi bilgisayar -- `keymap.current_computer` karar verir."""

    WORK = "work"
    HOME = "home"


def startup_minutes(computer: Computer) -> int:
    return WORK_MINUTES if computer == Computer.WORK else HOME_MINUTES


def should_open_outlook(computer: Computer) -> bool:
    return computer == Computer.WORK
