"""Panonun Qt'de karsiligi olmayan tek parcasi: sira numarasi.

Okuma/yazma icin `QGuiApplication.clipboard()` yeterli ve daha guvenli
(format donusumlerini, gecikmeli render'i Qt hallediyor). Ama Qt "pano kac
kez degisti" sorusunu cevaplamiyor; gecikmeli okumada tazelik kontrolu icin
gereken sayac bu.

Onemli: sayac yalnizca panoya YAZILDIGINDA artar, okundugunda artmaz.
Bu yuzden "ben beklerken baskasi yazdi mi" sorusunun dogru olcusu.
"""

from __future__ import annotations

from cascade.win32.structs import user32


def sequence_number() -> int:
    """Win32: GetClipboardSequenceNumber. Erisim yoksa 0 doner."""
    return int(user32.GetClipboardSequenceNumber())
