"""Kayitli ekran alanlari -- HENUZ SAHTE DEPO.

Alanlar su an yalnizca BELLEKTE yasiyor: program kapaninca gidiyorlar.
Kasitli bir ara adim -- once arayuzun nasil gorunecegini, alan kaydinin
gunluk kullanimda ise yarayip yaramadigini gormek istiyoruz. Kod geri
kalan her yerde deponun kalici oldugunu VARSAYARAK yazildi; diske gecis
yalnizca `load()` ile `save()`in govdesini doldurmak olacak
(`Files/areas.json`, store.py'deki oteki depolarla ayni kalip).

Koordinatlar DOGAL COZUNURLUKTE: sanal masaustunun fiziksel pikseli, yani
`win32/screen.py`nin ekseni. Monitore goreli saklama denendi ama once
dogal olcuyle gitmek istendi -- monitor duzeni degisirse alan yanlis yere
duser, o gun geldiginde `monitor` alani eklenecek.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger(__name__)


def default_name() -> str:
    """Yeni alanin hazir adi: tarih TERSTEN (yil-ay-gun), sonra saat.

    Tersten yazmak siralamayi ada birakiyor: alanlar alfabetik dizilince
    kendiliginden eskiden yeniye siralanir.
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M")


#: Kural sozlugu -- (kimlik, menude/listede gorunen ad). UI listeleri BU
#: tablolardan uretiliyor: yeni bir islem/hedef eklemek tek satir.
#:
#: Kimlikler kisa ve makine okur cinsten: kural JSON'a `{"do": "ocr",
#: "to": "file", ...}` diye gidecek ve Python tarafi ayni kimlikleri
#: gorecek. Etiketler degisebilir, kimlikler degismez.
DO_CHOICES = (
    ("shot", "Resim"),
    ("ocr", "OCR"),
)
TO_CHOICES = (
    ("clip", "Panoya"),
    ("file", "Dosyaya"),
    ("images", "Gorsellere"),
    ("py", "Python icin paketle"),
)
WHEN_CHOICES = (
    ("always", "Her seferinde"),
    ("changed", "Resim degisince"),
    ("contains", "Text bulununca"),
    ("missing", "Text bulunmayinca"),
)

_LABELS = {key: label for table in (DO_CHOICES, TO_CHOICES, WHEN_CHOICES) for key, label in table}


@dataclass
class Rule:
    """Bir alan uzerinde calisacak is: NE alinacak, NEREYE, NASIL, NE ZAMAN.

    Tetik iki bagimsiz yoldan gelebilir ve ikisi birden acik olabilir:
    `key` (kisayola basinca) ve `every` (saniyede bir). Ikisi de bossa kural
    yalnizca elle calistirilir -- "dene" dugmesi hep vardir.

    `when` bir TETIK degil SUZGEC: tetik geldiginde is yapilsin mi diye
    bakilir. "Text bulununca" bir zamanlayici degil, periyodik ya da
    kisayolla gelen isin sonucuna konan sart.
    """

    do: str = "ocr"
    to: str = "clip"
    #: Hedef KLASOR (dosyaya yaz / python paketi). Dosya ADI verilmiyor:
    #: her calisma kendi dosyasini `YYYYMMDD_HHmmss` damgasiyla aciyor --
    #: tek dosyaya yazmak eski sonucu ezerdi, adi kullaniciya sordurmak
    #: da otomasyonu her seferinde durdururdu.
    path: str = ""
    when: str = "always"
    #: "contains"/"missing" icin aranan metin.
    text: str = ""
    #: Kisayol, `parse_hotkey` bicimi: "F4", "Ctrl+Shift+K". Bos = tus yok.
    key: str = ""
    #: Periyot, SANIYE. 0 = periyodik degil.
    #: Periyot, SANIYE (0..3600). 0 = periyodik degil, tetiklenince BIR KEZ
    #: calisir.
    every: int = 0
    enabled: bool = True

    def filename(self, when: datetime | None = None) -> str:
        """`20260901_143005` + isin uzantisi -- otomatik dosya adi."""
        stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
        return f"{stamp}.png" if self.do == "shot" else f"{stamp}.txt"

    def label(self) -> str:
        """Listede gorunen tek satir: tetik · is → hedef (sart)."""
        trigger = self.key or "elle"
        if self.every:
            trigger += f" + her {self.every}sn"
        target = f" ({self.path})" if self.path else ""
        parts = [
            f"{trigger} · {_LABELS.get(self.do, self.do)}",
            f"→ {_LABELS.get(self.to, self.to)}{target}",
        ]
        if self.when != "always":
            suffix = f": {self.text}" if self.text else ""
            parts.append(f"[{_LABELS.get(self.when, self.when)}{suffix}]")
        return " ".join(parts)


@dataclass
class Area:
    """Adlandirilmis dikdortgen. `x/y/w/h` fiziksel piksel."""

    name: str
    x: int
    y: int
    w: int
    h: int
    desc: str = ""
    stamp: str = field(default_factory=default_name)
    #: Bu alana bagli kurallar. Alan silinince kurallari da gider -- kural
    #: alanin bir ozelligi, ayri bir varlik degil.
    rules: list[Rule] = field(default_factory=list)

    def label(self) -> str:
        """Menude gorunen satir: `ad (320x240 2026-09-01)`."""
        return f"{self.name} ({self.w}x{self.h} {self.stamp.split(' ')[0]})"

    def rule_owner(self, index: int) -> str:
        """Kuralin kisayol kayit defterindeki SAHIP adi.

        Alan adi ve kural sirasi -- `HotkeyTable.release` bu adla cagrilinca
        yalnizca o kuralin tusu birakilir; alanin tamami icin sahip oneki
        (`area:<ad>#`) yeterli.
        """
        return f"area:{self.name}#{index}"


class AreaStore:
    """Alan listesi. Ayni ada ikinci kez kaydetmek USTUNE YAZAR."""

    def __init__(self) -> None:
        self.areas: list[Area] = []

    def load(self) -> None:
        """Diskten okuma -- henuz yok (bkz. modul basi)."""

    def save(self) -> None:
        """Diske yazma -- henuz yok; ne yazilacagi log'a dusuyor ki
        akisin dogru yerde cagrildigi gorulebilsin."""
        log.info("alan deposu (sahte kayit): %d alan", len(self.areas))

    def put(self, area: Area) -> None:
        for index, existing in enumerate(self.areas):
            if existing.name == area.name:
                self.areas[index] = area
                break
        else:
            self.areas.append(area)
        self.save()

    def remove(self, name: str) -> bool:
        before = len(self.areas)
        self.areas = [area for area in self.areas if area.name != name]
        if len(self.areas) != before:
            self.save()
            return True
        return False

    def find(self, name: str) -> Area | None:
        return next((area for area in self.areas if area.name == name), None)
