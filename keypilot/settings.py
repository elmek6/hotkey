"""Ayar sistemi -- AHK `Lib/settings.ahk` portu.

Tanim DAGITIK, kayit MERKEZI: her modul kendi ayarini yaninda tanimlar
(`setting(...)` cagrisi), hepsi tek bir kayit defterine (`SETTINGS`) girer.
Deger okuma HER ZAMAN `Setting.get()` uzerinden olmali -- kod icinde
sabitten okunan bir yer kalirsa "ayar kaydediliyor ama etkisi yok" olur.

    KEEP_OPEN = setting(
        "filter.keep_open", "Array filter: odak kaybedince kapanmasin",
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
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from keypilot.store import backup_file, write_atomic

log = logging.getLogger("keypilot.settings")

VERSION = 1


class Category(StrEnum):
    """AHK: `class Cat`. Ayar ekranindaki sol sutun.

    Uyeler KIMLIK (`StrEnum`), etiketler `_CATEGORY_LABELS`. Ayrilar cunku
    kimlik esitlik karsilastirmasinda ve `tree` anahtari olarak kullaniliyor:
    baslik metnini degistirmek mantigi bozmamali.

    Komut kimlikleri (`Cmd`) buraya girmez: ayar grubu ile eylem farkli
    sozluklerdir.
    """

    GENERAL = "general"
    TRAY = "tray"
    GESTURE = "gesture"  # F13 + fare hareketi (core/hot_vectors.py)
    MOUSE = "mouse"
    CLIP = "clip"
    LIST = "list"  # tus tus suzen liste penceresi (ui/array_filter.py)
    WINDOW = "window"
    OCR = "ocr"
    MACRO = "macro"  # macro_recorder.ahk: Cat.Macro
    #: Gunluk kullanimin parcasi OLMAYAN mekanizmalar: nobetciler,
    #: ayrinti log'lari. Hepsi varsayilan kapali ve ana salteri var
    #: (keypilot/dev.py). Adi BUYUK harf: gunluk ayarlarla karisip
    #: yanlislikla acilmasin. Ekranda en uste dusuyor cunku `main.py`
    #: `keypilot.dev`i ilk import ediyor ve sira kayit sirasi.
    DEVELOPMENT = "development"

    @classmethod
    def label(cls, category: Category) -> str:
        return _CATEGORY_LABELS.get(category, category)


_CATEGORY_LABELS = {
    Category.GENERAL: "Genel",
    Category.TRAY: "Sistem tepsisi",
    Category.GESTURE: "Jestler",
    Category.MOUSE: "Fare",
    Category.CLIP: "Pano",
    Category.LIST: "Array filter",
    Category.WINDOW: "Pencere",
    Category.OCR: "OCR",
    Category.MACRO: "Makro",
    Category.DEVELOPMENT: "GELISTIRME",
}


class Kind(StrEnum):
    """Ayar degerinin tipi -- `coerce` ve ayar ekranindaki girdi bunu secer.

    Verilmezse `Setting.type_of` varsayilandan cikarir.
    """

    BOOL = "bool"
    ENUM = "enum"
    INT = "int"
    FLOAT = "float"
    STR = "str"


class Setting[T]:
    """Tek bir ayar. `get`/`set`, degisince aboneleri uyarir.

    `T` varsayilandan cikarilir: `setting(..., default=10)` bir
    `Setting[int]`, `get()` de `int` doner.
    """

    def __init__(
        self,
        key: str,
        name: str,
        default: T,
        category: Category = Category.GENERAL,
        kind: Kind | None = None,
        tags: str = "",
        desc: str = "",
        choices: tuple[T, ...] = (),
        labels: dict[T, str] | None = None,
        legacy: dict[str, T] | None = None,
        validate: Callable[[T], str] | None = None,
        on_change: Callable[[T, T], None] | None = None,
        hidden: bool = False,
        info: str = "",
    ) -> None:
        self.key = key
        self.name = name
        self.default = default
        self.category = category
        self.kind = kind
        self.tags = tags
        self.desc = desc
        self.choices = tuple(choices)
        #: enum kimligi -> ekranda gorunen ad. Bos ise kimlik gosterilir.
        self.labels: dict[T, str] = dict(labels or {})
        #: dosyada duran ESKI deger -> yeni kimlik. Kimlige gecmeden once
        #: settings.json'a gorunen metin yaziliyordu; kullanicinin secimi
        #: bir surum gecisinde varsayilana dusmesin.
        self.legacy: dict[str, T] = dict(legacy or {})
        self.validate = validate
        #: Ayar ekraninda degerin YANINDA duran kisa bilgi ("0=yok 500-60000ms").
        #: Verilmezse `between` dogrulayicisinin sinirlarindan turetiliyor;
        #: elle yazmak yalniz aralik disi kurallari olan ayarlarda gerekiyor.
        self.info = info
        #: AYAR EKRANINDA GORUNMEZ. Ayarin kendisi tam ayar: diske yazilir,
        #: abonelikleri calisir, `SETTINGS.get` ile okunur -- yalniz listede
        #: yeri yoktur, cunku asil anahtari baska bir yerde (menu, tepsi).
        #: Iki yerden degistirilebilen ayar kullanicida "hangisi gecerli"
        #: sorusu birakiyordu.
        self.hidden = hidden
        self._value: T = default
        self._subs: list[Callable[[T, T], None]] = []
        if on_change is not None:
            self._subs.append(on_change)

    def info_text(self) -> str:
        """Deger kutusunun yanindaki kisa bilgi -- yoksa bos."""
        if self.info:
            return self.info
        if isinstance(self.validate, Between):
            return self.validate.span
        return ""

    def label_for(self, value: T) -> str:
        """enum kimliginin ekranda gorunen adi."""
        return self.labels.get(value, str(value))

    def type_of(self) -> Kind:
        """`kind` verilmemisse varsayilandan cikarilir."""
        if self.kind is not None:
            return self.kind
        if self.choices:
            return Kind.ENUM
        if isinstance(self.default, bool):
            return Kind.BOOL
        if isinstance(self.default, int):
            return Kind.INT
        if isinstance(self.default, float):
            return Kind.FLOAT
        return Kind.STR

    def get(self) -> T:
        """Ayarin o anki degeri -- `coerce` onu tanimdaki tipe zorluyor."""
        return self._value

    def is_changed(self) -> bool:
        return self._value != self.default

    def set(self, value: object) -> str:
        """`""` = basarili, dolu string = ret gerekcesi (AHK ile ayni).

        `object` alir: ayar ekrani kutudaki METNI veriyor, `coerce` tipe
        cevirir ya da reddeder.
        """
        coerced, ok = self.coerce(value)
        if not ok:
            return f"Gecersiz deger: {self.name}"
        if self.validate is not None:
            message = self.validate(coerced)
            if message:
                return message
        old = self._value
        if old == coerced:
            return ""
        self._value = coerced
        SETTINGS.dirty = True
        self.notify(coerced, old)
        return ""

    def toggle(self) -> str:
        return self.set(not self.get())

    def reset(self) -> str:
        return self.set(self.default)

    def subscribe(self, callback: Callable[[T, T], None]) -> Callable[[T, T], None]:
        self._subs.append(callback)
        return callback

    def unsubscribe(self, callback: Callable[[T, T], None]) -> None:
        if callback in self._subs:
            self._subs.remove(callback)

    def notify(self, value: T, old: T) -> None:
        for callback in self._subs:
            try:
                callback(value, old)
            except Exception:  # dinleyici hatasi ayari geri almamali
                log.exception("Ayar dinleyicisi hatasi: %s", self.key)

    def coerce(self, value: Any) -> tuple[Any, bool]:
        """Elle duzenlenmis json'a karsi: tip tutmuyorsa (varsayilan, False).

        Donus `Any`: dal `type_of()`a gore secildigi icin deger `T`dir ama
        bunu tip denetleyicisine kanitlamak her dalda `cast` demek.
        """
        kind = self.type_of()
        if kind == Kind.BOOL:
            if isinstance(value, bool):
                return value, True
            if value in (0, 1, "0", "1", "true", "false", "True", "False"):
                return value in (1, "1", "true", "True"), True
            return self.default, False
        if kind == Kind.INT:
            try:
                return int(value), True
            except (TypeError, ValueError):
                return self.default, False
        if kind == Kind.FLOAT:
            try:
                return float(value), True
            except (TypeError, ValueError):
                return self.default, False
        if kind == Kind.ENUM:
            value = self.legacy.get(value, value)
            # Dosyadaki duz dizge yerine TANIMDAKI secenek: `StrEnum` ile
            # tanimlanan ayar `get()`te enum uyesi dondursun.
            for choice in self.choices:
                if choice == value:
                    return choice, True
            return self.default, False
        return str(value), True


class Registry:
    """AHK: `class Settings`. Kayit defteri, json okuma/yazma, arama."""

    def __init__(self) -> None:
        self.all: list[Setting[Any]] = []
        self.by_key: dict[str, Setting[Any]] = {}
        self.tree: dict[Category, list[Setting[Any]]] = {}
        self.dirty = False
        #: Tanimi yuklu olmayan anahtarlar -- geri yazilsinlar diye duruyor.
        self.orphans: dict[str, object] = {}

    def register[T](self, item: Setting[T]) -> Setting[T]:
        if item.key in self.by_key:
            raise ValueError(f"Ayar anahtari iki kez tanimlanmis: {item.key}")
        self.by_key[item.key] = item
        self.all.append(item)
        self.tree.setdefault(item.category, []).append(item)
        return item

    @property
    def categories(self) -> list[Category]:
        """Tanim sirasi -- alfabetik degil (AHK: catOrder).

        GORUNUR ayari olmayan kategori hic listelenmiyor: bir kategorinin
        tek ayari gizlenirse geride bos bir baslik kalmasin.
        """
        return [name for name, items in self.tree.items() if any(not i.hidden for i in items)]

    @property
    def visible(self) -> list[Setting]:
        """Ayar ekraninda gosterilecekler (bkz. `Setting.hidden`)."""
        return [item for item in self.all if not item.hidden]

    def visible_in(self, category: Category) -> list[Setting]:
        return [item for item in self.tree.get(category, ()) if not item.hidden]

    def get(self, key: str, fallback=None):
        item = self.by_key.get(key)
        return item.get() if item is not None else fallback

    def load(self, path: Path) -> bool:
        if not path.exists():
            return False
        try:
            root = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            log.exception("settings.json okunamadi")
            return False
        except (ValueError, UnicodeDecodeError):
            # Bozuk dosya: kapanista uzerine yazilacak ve kullanicinin butun
            # ayarlari sessizce gidecekti. Diger depolarla ayni kural --
            # yaninda sakla, varsayilanlarla devam et.
            log.exception("settings.json okunamadi")
            backup_file(path, "bozuk")
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
        """Atomik yazar (`.tmp` + yer degistirme, store.py ile ayni kural):
        kapanis sirasinda yarim kalan bir yazim BUTUN ayarlari goturmesin."""
        values: dict[str, object] = dict(self.orphans)
        for item in self.all:
            if item.is_changed():
                values[item.key] = item.get()
        text = json.dumps({"_v": VERSION, "values": values}, ensure_ascii=False, indent=2)
        if not write_atomic(path, text.encode("utf-8")):
            return False
        self.dirty = False
        return True

    def reset_all(self) -> None:
        for item in self.all:
            item.reset()

    def search(self, query: str) -> list[Setting]:
        """Bosluk = AND; ad, anahtar, aciklama, etiket ve secenekler icinde.

        Gizli ayarlar aramaya da girmiyor: ekranda acilamayan bir satiri
        arama sonucunda gostermek daha da kafa karistirici olurdu.
        """
        query = query.strip().lower()
        if not query:
            return self.visible
        terms = query.split()
        found = []
        for item in self.visible:
            hay = " ".join(
                (
                    item.name,
                    item.key,
                    item.desc,
                    item.tags,
                    Category.label(item.category),
                    *map(str, item.choices),
                    *map(str, item.labels.values()),
                )
            ).lower()
            if all(term in hay for term in terms):
                found.append(item)
        return found


SETTINGS = Registry()


@dataclass(frozen=True, slots=True)
class Between:
    """Aralik dogrulayicisi. Ret gerekcesi ayar ekraninda kutunun saginda
    kirmizi olarak gorunuyor, o yuzden BIRIMI de tasiyor: "0-500 arasi
    olmali" ile "0-500 ms arasi olmali" ayni cumle degil.

    Tek tek yazilan `lambda v: "" if 0 <= v <= 500 else "..."` satirlarinin
    yerine geciyor: sinir ile gerekce metni ayri yerlerde durunca biri
    degisip oteki eski kaliyordu.

    Ayar ekrani sinirlari OKUYOR: deger kutusunun yanindaki bilgi buradan
    turetiliyor (bkz. `Setting.info_text`). Kapanisin icine gomulseydi her
    ayar araligini bir de elle yazmak zorunda kalirdi.
    """

    low: float
    high: float
    unit: str = ""

    @property
    def span(self) -> str:
        return f"{self.low}-{self.high}{' ' + self.unit if self.unit else ''}"

    def __call__(self, value) -> str:
        return "" if self.low <= value <= self.high else f"{self.span} arasi olmali"


def between(low: float, high: float, unit: str = "") -> Between:
    return Between(low, high, unit)


def setting[T](key: str, name: str, default: T, **kwargs: Any) -> Setting[T]:
    """Tanimla ve kaydet -- modullerin cagirdigi tek fonksiyon."""
    return SETTINGS.register(Setting(key, name, default, **kwargs))
