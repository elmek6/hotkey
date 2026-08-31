"""Ayar sistemi -- AHK `Lib/settings.ahk` portu.

Tanim DAGITIK, kayit MERKEZI: her modul kendi ayarini yaninda tanimlar
(`setting(...)` cagrisi), hepsi tek bir kayit defterine (`SETTINGS`) girer.
Deger okuma HER ZAMAN `Setting.get()` uzerinden olmali -- kod icinde
sabitten okunan bir yer kalirsa "ayar kaydediliyor ama etkisi yok" olur.

    KEEP_OPEN = setting(
        "filter.keep_open", "Liste odak kaybedince kapanmasin",
        default=False, category=Category.LIST, tags="filtre liste odak",
    )
    if KEEP_OPEN.get(): ...

Diske yazilan: `Files/settings.json`. Yalniz VARSAYILANDAN FARKLI olanlar
yaziliyor -- varsayilan degisirse eski deger dosyada donup kalmasin.
Tanimi su an yuklu olmayan (kaldirilmis ya da henuz eklenmemis) anahtarlar
`_orphans` icinde saklanip geri yaziliyor: bir surum, tanimini bilmedigi
ayari silmemeli.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("cascade.settings")

VERSION = 1


class Category:
    """AHK: `class Cat`. Ayar ekranindaki sol sutun."""

    GENERAL = "Genel"
    MOUSE = "Fare"
    CLIP = "Pano"
    LIST = "Liste"
    WINDOW = "Pencere"
    OCR = "OCR"


class Setting:
    """Tek bir ayar. `get`/`set`, degisince aboneleri uyarir."""

    def __init__(
        self,
        key: str,
        name: str,
        default,
        category: str = Category.GENERAL,
        kind: str = "",
        tags: str = "",
        desc: str = "",
        choices: tuple = (),
        validate: Callable[[object], str] | None = None,
        on_change: Callable[[object, object], None] | None = None,
    ) -> None:
        self.key = key
        self.name = name
        self.default = default
        self.category = category
        self.kind = kind
        self.tags = tags
        self.desc = desc
        self.choices = tuple(choices)
        self.validate = validate
        self._value = default
        self._subs: list[Callable[[object, object], None]] = []
        if on_change is not None:
            self._subs.append(on_change)

    def type_of(self) -> str:
        """"bool" | "enum" | "int" | "float" | "str" -- verilmemisse cikarilir."""
        if self.kind:
            return self.kind
        if self.choices:
            return "enum"
        if isinstance(self.default, bool):
            return "bool"
        if isinstance(self.default, int):
            return "int"
        if isinstance(self.default, float):
            return "float"
        return "str"

    def get(self):
        return self._value

    def is_changed(self) -> bool:
        return self._value != self.default

    def set(self, value) -> str:
        """`""` = basarili, dolu string = ret gerekcesi (AHK ile ayni)."""
        value, ok = self.coerce(value)
        if not ok:
            return f"Gecersiz deger: {self.name}"
        if self.validate is not None:
            message = self.validate(value)
            if message:
                return message
        old = self._value
        if old == value:
            return ""
        self._value = value
        SETTINGS.dirty = True
        self.notify(value, old)
        return ""

    def toggle(self) -> str:
        return self.set(not self.get())

    def reset(self) -> str:
        return self.set(self.default)

    def subscribe(self, callback: Callable[[object, object], None]) -> Callable:
        self._subs.append(callback)
        return callback

    def unsubscribe(self, callback: Callable) -> None:
        if callback in self._subs:
            self._subs.remove(callback)

    def notify(self, value, old) -> None:
        for callback in self._subs:
            try:
                callback(value, old)
            except Exception:  # dinleyici hatasi ayari geri almamali
                log.exception("Ayar dinleyicisi hatasi: %s", self.key)

    def coerce(self, value) -> tuple[object, bool]:
        """Elle duzenlenmis json'a karsi: tip tutmuyorsa (varsayilan, False)."""
        kind = self.type_of()
        if kind == "bool":
            if isinstance(value, bool):
                return value, True
            if value in (0, 1, "0", "1", "true", "false", "True", "False"):
                return value in (1, "1", "true", "True"), True
            return self.default, False
        if kind == "int":
            try:
                return int(value), True
            except (TypeError, ValueError):
                return self.default, False
        if kind == "float":
            try:
                return float(value), True
            except (TypeError, ValueError):
                return self.default, False
        if kind == "enum":
            return (value, True) if value in self.choices else (self.default, False)
        return str(value), True


class Registry:
    """AHK: `class Settings`. Kayit defteri, json okuma/yazma, arama."""

    def __init__(self) -> None:
        self.all: list[Setting] = []
        self.by_key: dict[str, Setting] = {}
        self.tree: dict[str, list[Setting]] = {}
        self.dirty = False
        #: Tanimi yuklu olmayan anahtarlar -- geri yazilsinlar diye duruyor.
        self.orphans: dict[str, object] = {}

    def register(self, item: Setting) -> Setting:
        if item.key in self.by_key:
            raise ValueError(f"Ayar anahtari iki kez tanimlanmis: {item.key}")
        self.by_key[item.key] = item
        self.all.append(item)
        self.tree.setdefault(item.category, []).append(item)
        return item

    @property
    def categories(self) -> list[str]:
        """Tanim sirasi -- alfabetik degil (AHK: catOrder)."""
        return list(self.tree)

    def get(self, key: str, fallback=None):
        item = self.by_key.get(key)
        return item.get() if item is not None else fallback

    def load(self, path: Path) -> bool:
        if not path.exists():
            return False
        try:
            root = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.exception("settings.json okunamadi")
            return False
        values = root.get("values") if isinstance(root, dict) else None
        if not isinstance(values, dict):
            return False
        for key, raw in values.items():
            item = self.by_key.get(key)
            if item is None:
                self.orphans[key] = raw
                continue
            value, ok = item.coerce(raw)
            item._value = value if ok else item.default  # noqa: SLF001
            if not ok:
                self.dirty = True  # bozuk deger duzeltilmis haliyle geri yazilsin
        return True

    def apply_all(self) -> None:
        """`load()` sonrasi BIR KEZ: moduller dosyadan gelen degeri gorsun."""
        for item in self.all:
            item.notify(item.get(), item.get())

    def save(self, path: Path) -> bool:
        return self.save_now(path) if self.dirty else False

    def save_now(self, path: Path) -> bool:
        values: dict[str, object] = dict(self.orphans)
        for item in self.all:
            if item.is_changed():
                values[item.key] = item.get()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"_v": VERSION, "values": values}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            log.exception("settings.json yazilamadi")
            return False
        self.dirty = False
        return True

    def reset_all(self) -> None:
        for item in self.all:
            item.reset()

    def search(self, query: str) -> list[Setting]:
        """Bosluk = AND; ad, anahtar, aciklama, etiket ve secenekler icinde."""
        query = query.strip().lower()
        if not query:
            return list(self.all)
        terms = query.split()
        found = []
        for item in self.all:
            hay = " ".join(
                (
                    item.name,
                    item.key,
                    item.desc,
                    item.tags,
                    item.category,
                    *map(str, item.choices),
                )
            ).lower()
            if all(term in hay for term in terms):
                found.append(item)
        return found


SETTINGS = Registry()


def setting(key: str, name: str, default, **kwargs) -> Setting:
    """Tanimla ve kaydet -- modullerin cagirdigi tek fonksiyon."""
    return SETTINGS.register(Setting(key, name, default, **kwargs))
