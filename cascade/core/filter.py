"""Liste filtreleme -- array_filter.ahk'nin `MatchItem` + `UpdateList` bolumu.

AHK'de bu mantik GUI'nin icine gomuluydu: `MatchItem` dogrudan
`this.caseChk.Value` ve `this.modeDdl.Value` okuyordu, yani pencereyi
acmadan tek bir eslesmeyi bile deneyemezdin. Burada ayrildi -- sorgu bir
veri, filtre saf fonksiyon. Pencere (ui/array_filter.py) yalnizca sorguyu
kurar ve sonucu cizer.

Uc mod, AHK'deki dropdown ile ayni sirada ve ayni davranista:

    METIN   duz alt-dize aramasi
    JOKER   `*` ve `?` -- regex'e cevrilir, nokta satir sonunu da eslestirir
    REGEXP  kullanicinin yazdigi desen aynen

`Case` kutusu uc modla da birlesir (ortogonal), o yuzden ayri alan.

AHK'den aynen tasinan iki karar:

1. **Joker modunda DOTALL.** PCRE'de `.` satir sonunu eslestirmez; pano
   kayitlarinin cogu cok satirli, onsuz "SELECT*FROM" iki ayri satirdaki
   kelimeleri bulamaz. RegExp modunda EKLENMEZ -- orada bayragi kullanici
   kendi yazar.
2. **Cipa (anchor) yok.** Arama kutusu semantigi alt-dize aramasidir;
   `^...$` eklersek "abc*def" metnin ortasinda eslesmezdi.

Bozuk desen sessizce sifir sonuc dondurmez: `pattern_error` ile isaretlenir,
baslikta "(desen?)" yazar. Yoksa "kayit mi yok, desen mi bozuk" ayirt
edilemiyordu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum


class FilterMode(IntEnum):
    """AHK: modeDdl.Value -- sira dropdown ile ayni."""

    TEXT = 1
    WILD = 2
    REGEX = 3


@dataclass(frozen=True, slots=True)
class FilterItem:
    """AHK: slot Map("name", ..., "content", ...) -- artik tipli.

    `name` kisa etiket (pano gecmisinde sira ve sayac), `content` tam metin.
    Arama ikisinde birden yapilir, AHK'deki gibi.
    """

    name: str
    content: str
    key: int = 0  # cagiranin kendi kimligi; filtre dokunmaz


@dataclass(frozen=True, slots=True)
class Query:
    text: str = ""
    mode: FilterMode = FilterMode.TEXT
    case_sensitive: bool = False


@dataclass(frozen=True, slots=True)
class Result:
    items: tuple[FilterItem, ...]
    pattern_error: bool = False


def wild_to_regex(pattern: str) -> str:
    """Joker (`*`, `?`) -> regex.

    SIRA KRITIK: once TUM metakarakterler kacirilir, SONRA yalniz joker olan
    ikisi geri acilir. Ters yapilirsa kullanicinin yazdigi `.` de joker olur.
    """
    escaped = re.escape(pattern)
    return escaped.replace(r"\*", ".*").replace(r"\?", ".")


def compile_query(query: Query) -> re.Pattern[str] | None:
    """Sorguyu derler. Duz metin modunda None (regex'e gerek yok),
    bozuk desende ValueError."""
    if not query.text or query.mode is FilterMode.TEXT:
        return None
    pattern = (
        wild_to_regex(query.text) if query.mode is FilterMode.WILD else query.text
    )
    flags = re.NOFLAG
    if not query.case_sensitive:
        flags |= re.IGNORECASE
    if query.mode is FilterMode.WILD:
        flags |= re.DOTALL  # cok satirli pano kayitlari icin
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        raise ValueError(str(exc)) from exc


def apply(items: tuple[FilterItem, ...] | list[FilterItem], query: Query) -> Result:
    """AHK: UpdateList'in dongusu. Bos aramada liste oldugu gibi doner."""
    if not query.text:
        return Result(tuple(items))

    try:
        regex = compile_query(query)
    except ValueError:
        # Kullanici desenini yazmayi bitirene kadar eslesme yok; pencere
        # basliginda "(desen?)" gorunur.
        return Result((), pattern_error=True)

    if regex is None:
        needle = query.text if query.case_sensitive else query.text.casefold()

        def hit(item: FilterItem) -> bool:
            if query.case_sensitive:
                return needle in item.name or needle in item.content
            return needle in item.name.casefold() or needle in item.content.casefold()
    else:

        def hit(item: FilterItem) -> bool:
            return bool(regex.search(item.name) or regex.search(item.content))

    return Result(tuple(item for item in items if hit(item)))
