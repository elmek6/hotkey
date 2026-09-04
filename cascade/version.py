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

Damga bicimi `MMDD_HHmm` -- ayi/gunu ve saati. Yil yok: elde tutulan kopya
en fazla birkac aylik olur ve dort hane okumasi kolay. CALISMA ANINDA
hesaplaniyor; elle guncellenen bir sabit olmamasinin sebebi basit: elle
guncellenen damga her zaman eskidir.

DEGISTIRILMIS CALISMA AGACI YILDIZLA BITER (`0904_1530*`). Damga once
yalnizca son git islemesinin tarihiydi ve calisirken kodu kurcalamak onu
kimildatmiyordu: dosyalari degistirip programi yeniden baslatan "hala dunun
tarihi yaziyor" goruyordu. Yildiz varken tarih son DEGISIKLIGIN saati ve
"bu kopya hicbir islemeye esit degil" demek -- hata bildiriminde tam olarak
bilinmesi gereken sey. Git hic yoksa (kaynak kopyalanmis) yine dosya
tarihlerine duselir.

`VERSION_INFO` demeti karsilastirma icin (`VERSION_INFO >= (1, 1, 0)`);
metinle surum karsilastirmak `1.10.0 < 1.9.0` gibi yanlislar uretiyor.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path

VERSION_INFO = (1, 2, 0)
VERSION = ".".join(str(part) for part in VERSION_INFO)

GIT_TIMEOUT_S = 2  # git takilirsa acilis beklemesin
STAMP_FORMAT = "%m%d_%H%M"
#: Calisma agaci kirliyken damganin sonuna eklenir.
DIRTY_MARK = "*"

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str | None:
    """git ciktisi; git yoksa/takilirsa None (bos cikti "" olarak doner)."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def _source_stamp() -> str:
    """En son degistirilen KAYNAK dosyanin tarihi.

    Tek bir dosyaya (version.py) bakmak yetmiyordu: app.py'yi degistirip
    version.py'ye dokunmayan -- yani her zamanki -- degisiklikte damga
    kimildamiyordu.
    """
    newest = 0.0
    for path in (*(ROOT / "cascade").rglob("*.py"), ROOT / "main.py"):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    if not newest:
        newest = Path(__file__).stat().st_mtime
    return datetime.fromtimestamp(newest).strftime(STAMP_FORMAT)


@lru_cache(maxsize=1)
def build_stamp() -> str:
    """`0901_1642`, degistirilmis agacta `0904_1530*`.

    Bir kez hesaplanip onbellege giriyor: her tooltip cizisinde surec
    baslatmak istemiyoruz. Yeniden baslatma yeni bir surec demek, yani
    kaydedip reload eden taze damgayi gorur.
    """
    # Kirlilik ONCE sorulur: kirliyken islemenin tarihi zaten yanlis cevap.
    # `--porcelain` .gitignore'a uyar, yani Files/ ve .venv damgayi
    # kirletmez; bos cikti = temiz, None = git yok.
    if _git("status", "--porcelain"):
        return _source_stamp() + DIRTY_MARK
    return _git("log", "-1", "--format=%cd", f"--date=format:{STAMP_FORMAT}") or (
        # git yok: kaynagin kendi tarihi. Kesin degil ama "hangi haftanin
        # kopyasi" sorusuna yine de cevap veriyor.
        _source_stamp()
    )


def full_version() -> str:
    """`1.0.0+0901_1642` -- kullaniciya gosterilen tam surum."""
    return f"{VERSION}+{build_stamp()}"
