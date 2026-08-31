"""Kod parcasi deposu -- `repository.ahk` portunun VERI katmani.

AHK `Files/repository.json` yaziyordu. Biz METIN bicimine geciyoruz, cunku
kayitlarin ana icerigi (`text`) cok satirli: JSON'da tek satira sikisiyor
(`"tuya\\ntwo way audio\\n"`), URL'lerdeki egik cizgi bile kaciyordu
(`https:\\/\\/`). Depo elle okunup elle duzenlenebilsin diye bicim var;
JSON tam da bunu engelliyordu.

    Files/repository.md   ===  kayit ayraci
                          ---  baslik biter, govde baslar

    ===
    uuid: 05/11/2025_00:45_1692013593
    title: doorbell
    category: iot
    tags: tuya, zigbee
    ---
    tuya
    two way audio
    ===
    uuid: ...

AYRAC NEDEN `===`, `---` DEGIL: govde bir KOD PARCASI. Icinde `---` gecmesi
gayet olasi (Markdown yatay cizgi, YAML belge ayraci, diff ciktisi) ve ayrac
`---` olsaydi boyle bir govde iki kaydi sessizce BIRLESTIRIRDI. `===` satir
basinda cok daha nadir; yine de gecerse `_escape` basina bir bosluk koyuyor
ve okurken o bosluk geri aliniyor -- yani govdeye ne yazilirsa yazilsin
kayit sinirlari bozulmuyor.

Baslik alanlari duz `anahtar: deger`. YAML DEGIL ve olmasin: dort alan icin
ayristirici 20 satir, `pyyaml` bagimliligi ise kalici bir yuk olurdu.
Tanimadigimiz anahtarlar `extra` icinde saklanip geri yaziliyor -- bir surum,
tanimini bilmedigi alani silmemeli (settings.py'deki `orphans` ile ayni fikir).
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger("cascade.repository")

SEPARATOR = "==="
HEADER_END = "---"


def new_uuid() -> str:
    """AHK `Item.__New` ile ayni recete: zaman + sayac + rastgele.

    Bicim AHK'ninkiyle ayni tutuluyor cunku ESKI kayitlarin uuid'leri
    oldugu gibi korunuyor; ikisi ayni listede yan yana duracak.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ticks = int(time.monotonic() * 1000) % 10**9
    return f"{stamp}_{ticks}_{random.randint(1000, 9999)}"


@dataclass
class Item:
    """Tek kayit. AHK `class Item` ile ayni dort alan + kimlik."""

    title: str = ""
    category: str = ""
    text: str = ""
    tags: list[str] = field(default_factory=list)
    uuid: str = ""
    #: Tanimadigimiz baslik anahtarlari -- oldugu gibi geri yazilir.
    extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.uuid:
            self.uuid = new_uuid()

    def matches(self, query: str) -> bool:
        """AHK `Search`: baslik, kategori ve GOVDE icinde arar (harf duyarsiz).

        Etiketler aramaya dahil degil -- AHK'de de degildi. Etiket suzgeci
        ayri (`filter_tags`), cunku "etiketi olan" ile "metninde gecen"
        farkli sorular.
        """
        if not query:
            return True
        needle = query.casefold()
        return any(
            needle in value.casefold()
            for value in (self.title, self.category, self.text)
        )

    def has_tag(self, query: str) -> bool:
        """AHK `HasTagMatch`: etiketin ICINDE gecmesi yeter, tam esitlik degil."""
        needle = query.casefold()
        return any(needle in tag.casefold() for tag in self.tags)


def _escape(text: str) -> str:
    """Govdede satir basina denk gelen ayraci zararsizlastirir."""
    return "\n".join(
        " " + line if line.rstrip() in (SEPARATOR, HEADER_END) else line
        for line in text.split("\n")
    )


def _unescape(text: str) -> str:
    return "\n".join(
        line[1:] if line[:1] == " " and line.strip() in (SEPARATOR, HEADER_END) else line
        for line in text.split("\n")
    )


class Repository:
    """Kayitlarin tamami bellekte, disk tek dosya. AHK `SingleRepository`.

    Kayit sayisi kod parcasi deposu olcusunde kaliyor, bu yuzden arama ve
    suzme duz gezinme -- indeks tutmak karsiliksiz karmasiklik olurdu.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.items: list[Item] = []

    # ---- diskten / diske ----

    def load(self) -> bool:
        """Dosyayi okur. Yoksa bos depo (hata degil: ilk calistirma)."""
        if not self.path.exists():
            self.items = []
            return False
        try:
            text = self.path.read_text(encoding="utf-8-sig")
        except OSError:
            log.exception("repository okunamadi: %s", self.path)
            self.items = []
            return False
        self.items = parse(text)
        log.info("%d repository kaydi okundu (%s)", len(self.items), self.path)
        return True

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(dump(self.items), encoding="utf-8")
            return True
        except OSError:
            log.exception("repository yazilamadi: %s", self.path)
            return False

    # ---- degistirme (AHK: AddItem / UpdateItem / DeleteItem) ----

    def add(self, item: Item) -> Item:
        self.items.append(item)
        return item

    def get(self, uuid: str) -> Item | None:
        return next((item for item in self.items if item.uuid == uuid), None)

    def update(
        self, uuid: str, title: str, category: str, text: str, tags: list[str]
    ) -> bool:
        item = self.get(uuid)
        if item is None:
            return False
        item.title = title
        item.category = category
        item.text = text
        item.tags = list(tags)
        return True

    def delete(self, uuid: str) -> bool:
        before = len(self.items)
        self.items = [item for item in self.items if item.uuid != uuid]
        return len(self.items) != before

    # ---- sorgular (AHK: Search / FilterByTags / FilterByCategory) ----

    def search(self, query: str) -> list[Item]:
        return [item for item in self.items if item.matches(query)]

    def filter_tags(self, tags: list[str], source: list[Item] | None = None) -> list[Item]:
        """TUM etiketleri tasiyanlar (AHK `FilterByTags`: matchAll)."""
        items = self.items if source is None else source
        return [item for item in items if all(item.has_tag(tag) for tag in tags)]

    def filter_category(
        self, category: str, source: list[Item] | None = None
    ) -> list[Item]:
        items = self.items if source is None else source
        return [item for item in items if item.category.casefold() == category.casefold()]

    @property
    def categories(self) -> list[str]:
        """Kullanilan kategoriler, tekil ve sirali (AHK `updateCategoriesAndTags`)."""
        return sorted({item.category for item in self.items if item.category})

    @property
    def tags(self) -> list[str]:
        return sorted({tag for item in self.items for tag in item.tags})


# ---- bicim ----


def parse(text: str) -> list[Item]:
    """Metni kayitlara cevirir. BOZUK KAYIT TUM DOSYAYI DUSURMEZ.

    Basligi ayristirilamayan kayit atlanip log'a yaziliyor: elle duzenlenen
    bir dosyada tek yazim hatasi butun depoyu kaybettirmemeli.
    """
    items: list[Item] = []
    first = SEPARATOR + "\n"
    if text.startswith(first):
        text = text[len(first) :]
    for chunk in text.split("\n" + SEPARATOR + "\n"):
        block = chunk.strip("\n")
        if not block.strip():
            continue
        item = _parse_block(block)
        if item is not None:
            items.append(item)
    return items


def _parse_block(block: str) -> Item | None:
    head, found, body = block.partition("\n" + HEADER_END + "\n")
    if not found:
        # `---` yok: govdesiz kayit da gecerli, basligi yine de okuyalim.
        head, body = block.removesuffix("\n" + HEADER_END), ""
    fields: dict[str, str] = {}
    for raw in head.split("\n"):
        line = raw.strip()
        if not line:
            continue
        key, sep, value = line.partition(":")
        if not sep:
            log.warning("repository: anahtarsiz baslik satiri atlandi: %r", line)
            continue
        fields[key.strip().casefold()] = value.strip()
    title = fields.pop("title", "")
    if not title:
        # AHK `_saveItem` de basliksiz kaydi reddediyordu: listede
        # gosterilecek bir sey olmadan kayit ise yaramaz.
        log.warning(
            "repository: basliksiz kayit atlandi (uuid=%s)", fields.get("uuid", "?")
        )
        return None
    tags = [tag.strip() for tag in fields.pop("tags", "").split(",") if tag.strip()]
    return Item(
        title=title,
        category=fields.pop("category", ""),
        text=_unescape(body),
        tags=tags,
        uuid=fields.pop("uuid", ""),
        extra=fields,  # geri kalan ne varsa korunuyor
    )


def dump(items: list[Item]) -> str:
    """Kayitlari metne cevirir. `parse(dump(x))` girdiyi aynen vermeli."""
    parts: list[str] = []
    for item in items:
        lines = [SEPARATOR, f"uuid: {item.uuid}", f"title: {item.title}"]
        if item.category:
            lines.append(f"category: {item.category}")
        if item.tags:
            lines.append("tags: " + ", ".join(item.tags))
        for key, value in item.extra.items():
            lines.append(f"{key}: {value}")
        lines.append(HEADER_END)
        body = _escape(item.text).rstrip("\n")
        parts.append("\n".join(lines) + "\n" + (body + "\n" if body else ""))
    return "".join(parts)
