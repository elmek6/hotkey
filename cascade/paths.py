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
CAPTURES = FILES / "captures"  # F14 secimi -> "Sakla" buraya PNG yazar

# Bu iki dosyanin ADI DA BICIMI DE AHK ile ayni: `_AutoHotKey/Files/`
# altindakiler buraya kopyalandiginda okunur, buradakiler de AHK tarafinda
# acilir. Sebep tasima kolayligi degil, ayni makinede iki surumun ayni
# veriyi paylasabilmesi.
CLIPS = FILES / "clipboards.bin"  # ikili bicim v2 -- store.ClipStore
SLOTS = FILES / "slots.json"  # clip_slot.ahk bicimi -- store.SlotStore
SETTINGS = FILES / "settings.json"  # settings.ahk bicimi -- cascade.settings

# TODO(AHK): port edilmemis veri dosyalari (kaynak: _AutoHotKey/Files/)
#   bigclips.bin   1 MB ustu kopyalar -- clip_hist.ahk buyuk metni ayri
#                  dosyaya tasiyor, biz simdilik hic almiyoruz
#   clipimg.idx    gorsel pano: sabit slotlu indeks + 64x64 kucuk resim
#   clipimg.dat    gorsel pano: 500 MB dairesel PNG log'u
#                  (clip_image_store.ahk + gdip_mini.ahk)
#   profiles.json  app_shorts.ahk        repository.json  repository.ahk
#   incognito_appids.json  incognito.ahk


def ensure_files_dir() -> Path:
    FILES.mkdir(parents=True, exist_ok=True)
    return FILES
