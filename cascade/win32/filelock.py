"""Dislayici dosya kilidi -- incognito.ahk `_lockFile` portu.

Jump list dosyalari (`*.automaticDestinations-ms`) acikken Explorer onlara
yaziyor. Dondurmanin yolu dosyayi PAYLASIMSIZ acip handle'i acik tutmak:
`dwShareMode = 0` verildiginde G/C yoneticisi baska hicbir surece o dosyayi
actirmiyor -- okumak, yazmak, silmek dahil (STATUS_SHARING_VIOLATION).

PYTHON'UN `open()`I BU ISI GORMEZ: CPython dosyalari FILE_SHARE_READ |
FILE_SHARE_WRITE ile aciyor, yani kilitlemiyor. `msvcrt.locking` da bayt
araligi kilidi -- ancak isbirlikci sureclere etki eder, Explorer'a etmez.
Tek yol CreateFileW'yu dogrudan cagirmak.

AHK tarafinda ogrenilen ve BURADA DA GECERLI olan ders: kilitlemek icin
YAZMA KIPINDE acma. AHK'de `"w-"` denendi ve 49 gercek jump list dosyasi
sifirlandi (~1,15 MB, geri alinamadi) -- cunku "w" dosyayi truncate ediyor.
Dislamayi saglayan sey erisim kipi degil PAYLASIM kipi; `GENERIC_READ` +
share 0 ayni korumayi veriyor. Asagidaki bayraklar bilincli olarak salt
okuma; yazma erisimi eklemek gereksiz ve salt-okunur ozniteligi olan
dosyalarda acilisi da engelliyor.
"""

from __future__ import annotations

import ctypes
import logging
from collections.abc import Iterator
from ctypes import wintypes
from pathlib import Path

from cascade.win32.structs import kernel32

log = logging.getLogger("cascade.incognito.lock")

GENERIC_READ = 0x80000000
FILE_SHARE_NONE = 0x00000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
kernel32.CreateFileW.restype = wintypes.HANDLE


class ExclusiveLocks:
    """Acik kilit handle'lari -- AHK `this.handles` Map'inin karsiligi.

    Yollar buyuk/kucuk harf duyarsiz karsilastirilir (AHK: CaseSense "Off");
    ayni dosyayi iki kez kilitlemek ikinci handle sizdirmasi demek olurdu.
    """

    def __init__(self) -> None:
        self._handles: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self._handles)

    def __contains__(self, path: Path | str) -> bool:
        return self._key(path) in self._handles

    def paths(self) -> Iterator[Path]:
        return (Path(p) for p in self._handles)

    @staticmethod
    def _key(path: Path | str) -> str:
        return str(path).casefold()

    def lock(self, path: Path | str) -> bool:
        """Dosyayi dislayici olarak acar. Zaten kilitliyse / acilamiyorsa False.

        Acilamamak normaldir: o an Windows dosyayi tutuyor olabilir. Cagiran
        (incognito.watch_tick) bir sonraki turda tekrar dener.
        """
        key = self._key(path)
        if key in self._handles:
            return False
        handle = kernel32.CreateFileW(
            str(path),
            GENERIC_READ,
            FILE_SHARE_NONE,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if not handle or handle == INVALID_HANDLE_VALUE:
            return False
        self._handles[key] = handle
        return True

    def unlock_all(self) -> None:
        """Kilitleri birakir.

        SIRA SART: geri yuklemeden ONCE cagrilmali -- kilitli dosya
        kopyalanamaz, paylasim kipi okumayi da kesiyor.
        """
        for handle in self._handles.values():
            kernel32.CloseHandle(wintypes.HANDLE(handle))
        self._handles.clear()
