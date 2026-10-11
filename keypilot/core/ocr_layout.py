"""OCR ciktisinin dizilmesi -- screen_ocr.ahk `_layout` ve arkadaslari.

Motor bize kelimeleri KUTULARIYLA veriyor (metin + x/y/w/h). Bu dosya o
kutulara bakip metni uc bicimden birine diziyor:

    duz     motorun kendi satirlari, oldugu gibi
    kolon   kolonlar SIRAYLA alt alta -- iki sutunlu makale/form dogru
            okuma sirasiyla cikar
    tablo   satirlar hizali, hucreler ayracla birlesik -- TAB secilirse
            Excel'e dogrudan yapistirilir, virgul secilirse CSV olur

Kolonu nasil buluyoruz (AHK `_findColumnSplits`): kelimelerin x araliklari
birlestirilir, aralarindaki BOS dikey seritlerden `gutter_min`den genis
olanlarin ORTASI bolme noktasi sayilir. Esik verilmezse karakter
yuksekliginin medyaninin 1.5 kati kullanilir -- cok kucuk secilirse kelime
aralari kolon sanilir, cok buyuk secilirse kolonlar birlesir.

Saf Python: Win32 yok, Qt yok, OCR motoru yok. Girdi bir kelime listesi
oldugu icin tamamen test edilebilir -- AHK'de bu mantik hic test edilemiyordu.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from enum import StrEnum

#: Satir ve kolon esiklerinin taban degerleri (AHK ile ayni sayilar).
MIN_GUTTER = 16
GUTTER_RATIO = 1.5  # medyan karakter yuksekliginin kati
MIN_ROW_EPS = 4


class LayoutMode(StrEnum):
    """AHK: `mode` parametresi ("plain" / "columns" / "table").

    `GRID` AHK'de YOK: kolonu tahmin etmek yerine kullanicinin OCR+
    cercevesinde cizdigi cizgileri kullanir (ui/snip.py).
    """

    PLAIN = "plain"
    COLUMNS = "columns"
    TABLE = "table"
    GRID = "grid"


@dataclass(frozen=True, slots=True)
class Grid:
    """Kullanicinin cizdigi izgara -- ui/snip.py'den gelir.

    Cizgiler ORAN (0..1) olarak tutuluyor; `width`/`height` kirpilan
    goruntunun kelime kutulariyla AYNI pikselindeki boyutu. Oran olmasi
    sayesinde DPI/olcek degisse de cevrim dogru kaliyor.

    Bir eksen BOS birakilabilir: o eksen otomatik bulunur (bkz.
    `grid_cells`). Tek bir dikey cizgi cekip satirlari motora birakmak
    tipik kullanim.
    """

    rows: tuple[float, ...] = ()
    cols: tuple[float, ...] = ()
    width: float = 0.0
    height: float = 0.0

    @property
    def drawn(self) -> bool:
        return bool(self.rows or self.cols) and self.width > 0 and self.height > 0


@dataclass(frozen=True, slots=True)
class Word:
    """Motorun verdigi tek kelime ve ekrandaki kutusu."""

    text: str
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass(frozen=True, slots=True)
class Layout:
    """Dizilmis sonuc. `info` panelde gosterilen tek satirlik ozet."""

    text: str
    info: str
    columns: int = 1
    rows: int = 0


def layout(
    words: list[Word] | tuple[Word, ...],
    lines: list[str] | tuple[str, ...],
    mode: LayoutMode = LayoutMode.PLAIN,
    separator: str = "\t",
    gutter: int = 0,
    grid: Grid | None = None,
) -> Layout:
    """AHK `_layout` birebir. `gutter` 0 ise esik otomatik hesaplanir.

    `lines` motorun kendi satirlari -- duz metin ve geri donus icin.
    `grid` yalniz `GRID` kipinde kullanilir (cizilmemisse duz metne doner).
    """
    plain = "\n".join(lines)
    if mode is LayoutMode.PLAIN:
        return Layout(plain, "duz metin")

    items = [word for word in words if word.text.strip()]
    if not items:
        return Layout(plain, "kelime yok")

    if mode is LayoutMode.GRID:
        if grid is None or not grid.drawn:
            return Layout(plain, "⚠ izgara cizilmedi (cetvelden cizgi ekle) -> duz metin")
        cells = grid_cells(items, grid, gutter)
        columns = len(cells[0]) if cells else 1
        # Hangi eksenin cizili hangisinin tahmin oldugu BILGI SATIRINDA
        # duruyor: "neden tek satir cikti" sorusunun cevabi orada gorunsun.
        return Layout(
            "\n".join(separator.join(row) for row in cells),
            f"izgara · {columns} kolon ({'cizili' if grid.cols else 'otomatik'})"
            f" x {len(cells)} satir ({'cizili' if grid.rows else 'otomatik'})"
            f" · ayrac {separator_label(separator)}",
            columns,
            len(cells),
        )

    median_h = _median([word.h for word in items])
    gutter_min = gutter if gutter > 0 else max(MIN_GUTTER, round(median_h * GUTTER_RATIO))
    splits = column_splits(items, gutter_min)
    if not splits:
        return Layout(plain, f"⚠ kolon ayraci yok (esik {gutter_min}px) -> duz metin")

    rows = group_rows(items, max(MIN_ROW_EPS, median_h / 2))
    count = len(splits) + 1
    suffix = f"{count} kolon x {len(rows)} satir · esik {gutter_min}px"
    if mode is LayoutMode.TABLE:
        return Layout(
            _table_text(rows, splits, count, separator),
            f"ayrac {separator_label(separator)} · {suffix}",
            count,
            len(rows),
        )
    return Layout(_columns_text(rows, splits, count), f"kolon · {suffix}", count, len(rows))


def grid_cells(words: list[Word], grid: Grid, gutter: int = 0) -> list[list[str]]:
    """Kelimeleri izgaranin hucrelerine dagitir: satir satir hucre metni.

    CIZILEN EKSEN KAZANIR, CIZILMEYEN OTOMATIK BULUNUR. Tabloda kolon
    ayraci cogu zaman tek bir yerde yanlis bulunuyor ama satirlar
    duzgun cikiyor; o tek dikey cizgiyi cekip satirlari motora birakmak
    isin buyuk kismini halletmeli. Iki ekseni birden cizmeye zorlamak
    on satirlik bir tablo icin on bir tiklama demekti.

    Cizili eksende tahmin YOK: her kelime `bisect` ile hangi araliga
    dustuyse o hucreye girer. Bu kipin varlik sebebi de bu -- otomatik
    satirlamada iki satira sarmis bir hucre degeri ikinci bir TABLO
    SATIRI uretip yanindaki hucrelerin hizasini kaydiriyor; yatay cizgi
    cekilen yerde satirin nerede bittigini metin degil CIZGI soyluyor ve
    sarmis satirlar tek hucre degerine katlaniyor.

    Bos satir/kolonlar ATILMAZ: kullanici o cizgiyi bilerek cekti,
    Excel'e yapistirinca hizanin korunmasi icin karsiligi bos hucre olmali.
    """
    col_cuts = _col_cuts(words, grid, gutter)
    out: list[list[str]] = []
    for row in _grid_rows(words, grid):
        cells: list[list[Word]] = [[] for _ in range(len(col_cuts) + 1)]
        for word in row:
            cells[column_index(word.cx, col_cuts)].append(word)
        out.append([_cell_text(cell) for cell in cells])
    return out


def grid_text(words: list[Word], grid: Grid, separator: str = "\t", gutter: int = 0) -> str:
    return "\n".join(separator.join(row) for row in grid_cells(words, grid, gutter))


def _col_cuts(words: list[Word], grid: Grid, gutter: int) -> list[float]:
    """Kolon sinirlari: cizilmisse onlar, degilse bos seritlerden bulunur."""
    if grid.cols:
        return sorted(frac * grid.width for frac in grid.cols)
    median_h = _median([word.h for word in words])
    gutter_min = gutter if gutter > 0 else max(MIN_GUTTER, round(median_h * GUTTER_RATIO))
    return column_splits(words, gutter_min)


def _grid_rows(words: list[Word], grid: Grid) -> list[list[Word]]:
    """Satirlar: cizilmisse CIZGILERDEN (bos satirlar dahil), degilse
    y-merkezi kumelemesinden (`group_rows`)."""
    if not grid.rows:
        return group_rows(words, max(MIN_ROW_EPS, _median([w.h for w in words]) / 2))
    cuts = sorted(frac * grid.height for frac in grid.rows)
    buckets: list[list[Word]] = [[] for _ in range(len(cuts) + 1)]
    for word in words:
        buckets[bisect.bisect_right(cuts, word.cy)].append(word)
    return buckets


def _cell_text(words: list[Word]) -> str:
    """Tek hucrenin metni; icindeki satirlar BOSLUKLA birlesir."""
    if not words:
        return ""
    row_eps = max(MIN_ROW_EPS, _median([word.h for word in words]) / 2)
    return " ".join(
        " ".join(word.text for word in line) for line in group_rows(words, row_eps)
    )


def column_splits(words: list[Word], gutter_min: float) -> list[float]:
    """Kelimelerin x araliklarini birlestirip genis bosluklarin ORTASINI
    doner. Bos liste = tek kolon. AHK: `_findColumnSplits`."""
    if not words:
        return []
    intervals = sorted(((word.x, word.x + word.w) for word in words), key=lambda iv: iv[0])
    merged: list[list[float]] = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    splits: list[float] = []
    for left, right in zip(merged, merged[1:], strict=False):
        gap = right[0] - left[1]
        if gap >= gutter_min:
            splits.append(left[1] + gap / 2)
    return splits


def group_rows(words: list[Word], row_eps: float) -> list[list[Word]]:
    """Kelimeleri satirlara boler; her satir kendi icinde soldan saga sirali.

    AHK `_groupRows` ile ayni kural: ayni satirdaki kelimelerin y-merkezleri
    karakter yuksekliginin yarisindan fazla oynamaz.
    """
    ordered = sorted(words, key=lambda word: word.cy)
    rows: list[list[Word]] = []
    current: list[Word] = []
    base = 0.0
    for word in ordered:
        if not current:
            current, base = [word], word.cy
            continue
        if abs(word.cy - base) > row_eps:
            rows.append(current)
            current, base = [word], word.cy
        else:
            current.append(word)
    if current:
        rows.append(current)
    for row in rows:
        row.sort(key=lambda word: word.cx)
    return rows


def column_index(cx: float, splits: list[float]) -> int:
    """Merkez x hangi kolona dusuyor (0 tabanli). AHK `_colIndex` 1 tabanliydi."""
    for index, split in enumerate(splits):
        if cx < split:
            return index
    return len(splits)


def _table_text(rows: list[list[Word]], splits: list[float], count: int, sep: str) -> str:
    """AHK `_tableText`: satirlar hizali, hucreler ayracla birlesik."""
    out: list[str] = []
    for row in rows:
        cells = [""] * count
        for word in row:
            index = column_index(word.cx, splits)
            cells[index] = f"{cells[index]} {word.text}".strip()
        line = sep.join(cells)
        if line.strip(" \t"):
            out.append(line)
    return "\n".join(out)


def _columns_text(rows: list[list[Word]], splits: list[float], count: int) -> str:
    """AHK `_columnsText`: kolonlar SIRAYLA alt alta, aralarinda bos satir."""
    blocks: list[str] = []
    for index in range(count):
        lines = []
        for row in rows:
            line = " ".join(word.text for word in row if column_index(word.cx, splits) == index)
            if line:
                lines.append(line)
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


# ---- ayrac: gorunmez karakterleri yazilabilir kilan kacislar ----
#
# AHK `_sepEscape` / `_sepUnescape`. TAB ve satir sonu bir metin kutusuna
# dogrudan yazilamaz; `\t` ve `\n` ile yazilir, burada cozulur.

#: (etiket, gercek metin) -- panelde hazir secenekler. AHK: `SEPS`.
SEPARATORS: tuple[tuple[str, str], ...] = (
    ("Tab", "\t"),
    (",  Virgul", ","),
    (".  Nokta", "."),
    (";  Noktali virgul", ";"),
    (":  Iki nokta", ":"),
    ("|  Boru", " | "),
    ("-  Tire", " - "),
    ("Bosluk", " "),
)


def escape_separator(value: str) -> str:
    """Gercek ayrac -> yazilabilir hali."""
    return value.replace("\\", "\\\\").replace("\t", "\\t").replace("\r\n", "\\n").replace(
        "\n", "\\n"
    )


def unescape_separator(value: str) -> str:
    """Yazilan metin -> gercek ayrac. `\\\\` once korunur, yoksa `\\\\t`
    yanlislikla TAB olurdu (AHK'deki ayni tuzak)."""
    marker = "\x00"
    value = value.replace("\\\\", marker)
    value = value.replace("\\t", "\t").replace("\\n", "\n").replace("\\s", " ")
    return value.replace(marker, "\\")


def separator_label(value: str) -> str:
    """Ayracin kullaniciya gosterilecek adi. AHK `_sepLabel`."""
    for label, real in SEPARATORS:
        if real == value:
            return label
    return f"«{escape_separator(value)}»"


def separator_from_text(text: str) -> str:
    """Kutuya yazilan/secilen metni gercek ayraca cevirir. AHK `_sepFromText`."""
    for label, real in SEPARATORS:
        if text == label:
            return real
    if len(text) >= 2 and text.startswith("«") and text.endswith("»"):
        text = text[1:-1]
    return unescape_separator(text)
