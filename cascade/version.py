"""Surum -- SemVer 2.0 (`MAJOR.MINOR.PATCH`) + yapim damgasi.

Neden ucler: "1.0" ile yama surumu anlatilamiyordu. Kural sanayide ne ise o
(semver.org):

    MAJOR  geriye donuk KIRAN degisiklik (kisayol/dosya bicimi degisti)
    MINOR  geriye donuk yeni ozellik
    PATCH  yalniz hata duzeltmesi

Yapim damgasi SemVer'in "build metadata" alani: surumun `+`dan sonrasi.
Standart bunu SURUM SIRASINA KATMAZ -- yani `1.0.0+20260901` ile
`1.0.0+20260902` ayni surumdur, damga yalnizca "elimdeki kopya hangi gunun
kodu" sorusunu cevaplar. Hata bildiriminde en cok bu ise yariyor.

Damga bicimi `MMDD_HHmm` -- son islemenin ayi/gunu ve saati. Yil yok:
elde tutulan kopya en fazla birkac aylik olur ve dort hane okumasi kolay.
CALISMA ANINDA git'ten okunuyor; git yoksa -- kaynak kopyalanmis olabilir
-- dosyanin degistirilme tarihine duselir. Elle guncellenen bir sabit
olmamasinin sebebi basit: elle guncellenen damga her zaman eskidir.

`VERSION_INFO` demeti karsilastirma icin (`VERSION_INFO >= (1, 1, 0)`);
metinle surum karsilastirmak `1.10.0 < 1.9.0` gibi yanlislar uretiyor.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path

VERSION_INFO = (1, 1, 1)
VERSION = ".".join(str(part) for part in VERSION_INFO)

GIT_TIMEOUT_S = 2  # git takilirsa acilis beklemesin


@lru_cache(maxsize=1)
def build_stamp() -> str:
    """`0901_1642` -- son islemenin ay/gun ve saati.

    Bir kez hesaplanip onbellege giriyor: her tooltip cizisinde surec
    baslatmak istemiyoruz.
    """
    root = Path(__file__).resolve().parent.parent
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cd", "--date=format:%m%d_%H%M"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=True,
        )
        stamp = out.stdout.strip()
        if stamp:
            return stamp
    except (OSError, subprocess.SubprocessError):
        pass
    # git yok: kaynagin kendi tarihi. Kesin degil ama "hangi haftanin
    # kopyasi" sorusuna yine de cevap veriyor.
    when = datetime.fromtimestamp(Path(__file__).stat().st_mtime)
    return when.strftime("%m%d_%H%M")


def full_version() -> str:
    """`1.0.0+0901_1642` -- kullaniciya gosterilen tam surum."""
    return f"{VERSION}+{build_stamp()}"
