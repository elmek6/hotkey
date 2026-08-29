"""Dosya yollari -- AHK'deki `Path` sinifi.

Her sey programin yanindaki `Files/` altinda: tasinabilir kalsin, AppData'ya
dagilmasin. AHK'de de oyleydi. `.gitignore` bu klasoru disliyor -- icinde
kisisel pano icerigi ve log var.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ROOT / "Files"

LOG = FILES / "log.txt"
HOTKEYS = FILES / "hotkeys.json"
STATE = FILES / "state.json"  # Faz 5: pano gecmisi + sayaclar


def ensure_files_dir() -> Path:
    FILES.mkdir(parents=True, exist_ok=True)
    return FILES
