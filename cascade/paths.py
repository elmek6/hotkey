"""DEVRE DISI -- dosya yollari. Istenmedi, kendiliginden eklenmisti.

AHK'deki `class Path` karsiligiydi; her sey Files/ altinda toplanacakti.
logs.py ve hotkeys.json okuma bu dosyaya dayaniyordu, ikisi de devre disi.
"""

#
# from __future__ import annotations
#
# from pathlib import Path
#
# ROOT = Path(__file__).resolve().parent.parent
# FILES = ROOT / "Files"
#
# LOG = FILES / "log.txt"
# HOTKEYS = FILES / "hotkeys.json"
# SETTINGS = FILES / "settings.json"
# CLIPBOARD = FILES / "clipboards.bin"
# SLOTS = FILES / "slots.json"
# PROFILES = FILES / "profiles.json"
# HANDOVER = FILES / "devir.md"
#
#
# def ensure_files_dir() -> Path:
#     """AHK: Path.initDirectory()"""
#     FILES.mkdir(parents=True, exist_ok=True)
#     return FILES
