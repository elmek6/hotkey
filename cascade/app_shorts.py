"""Uygulamaya ozel kisayollar -- `app_shorts.ahk` portu (Files/profiles.json).

AHK'deki fikir: ON PLANDAKI PENCEREYE gore F13 menusune ekstra maddeler
girer. Her profil bir pencereyi tarif eder (`className` ve/veya baslikta
gecen bir parca) ve altinda "kisayol" listesi tutar; kisayol, sirayla
gonderilecek tus dizilerinden ibarettir.

Dosya bicimi AHK'nin yazdiginin AYNISI -- `Files/profiles.json` iki surum
arasinda paylasilabilsin diye anahtar adlarina dokunulmadi:

    {"projectName": "ProfileManager", "profiles": [
        {"profileName": "Chrome", "className": "Chrome_WidgetWin_1",
         "title": "Google Chrome", "shortCuts": [
            {"shortCutName": "Closed tab", "keyDescription": "",
             "keyStrokes": ["^+t"]}]}]}

`JsonStore` tabanindan gelmiyor: o taban BIZE ait dosyalara surum alani
ekliyor, buraya eklersek AHK tarafi dosyayi tanimaz.

**Eslesme kurali AHK ile birebir** (`findProfileByWindow`): baslik bossa
hicbir profil eslesmez; `className` doluysa TAM esitlik, `title` doluysa
baslikta GECMESI yeter; ilk eslesen kazanir, sira dosyadaki siradir.

**Port edilmeyen:** AHK'nin `showManagerGui` profil/aksiyon duzenleyicisi
ve `Record Macro` dugmesi. Duzenleme simdilik JSON dosyasindan yapiliyor
(F13 menusundeki "Profilleri duzenle" maddesi dosyayi Notepad ile acar) --
makro kaydedici zaten port edilmedigi icin GUI'nin yarisi bos kalirdi.
"""

from __future__ import annotations

import codecs
import logging
from dataclasses import dataclass, field
from pathlib import Path

import orjson

from cascade import paths
from cascade.store import backup_file

log = logging.getLogger("cascade.app_shorts")

#: AHK Send sozdiziminde modifier isaretleri. Bir tus dizisi bunlardan
#: biriyle BASLIYORSA kisayol, degilse duz metin sayilir (bkz. `stroke_kind`).
MODIFIER_CHARS = "^!+#"


@dataclass(frozen=True, slots=True)
class ShortCut:
    """AHK `ShortCut`. `strokes` sirayla gonderilir."""

    name: str
    description: str = ""
    strokes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AppProfile:
    """AHK `AppProfile`. `class_name` ve `title` bos birakilabilir."""

    name: str
    class_name: str = ""
    title: str = ""
    shortcuts: tuple[ShortCut, ...] = ()

    def matches(self, class_name: str, title: str) -> bool:
        """AHK `findProfileByWindow` govdesi: sinif TAM, baslik PARCA."""
        if self.class_name and self.class_name != class_name:
            return False
        return not (self.title and self.title not in title)


def stroke_kind(stroke: str) -> str:
    """Bir dizinin "kisayol" mu "metin" mi oldugu.

    AHK'nin `Send`i tek bicimdi: `"^+t"` kisayol, `"abc"` harf harf metin.
    Bizde iki ayri yol var (`send_key` / `send_text`), o yuzden ayrimi
    burada yapiyoruz. Kural, AHK dosyalarindaki kullanimin karsiligi:
    modifier isaretiyle baslayan ya da `{...}` iceren dizi kisayoldur.
    """
    if stroke.startswith(tuple(MODIFIER_CHARS)) or ("{" in stroke and "}" in stroke):
        return "key"
    return "text"


@dataclass
class ShortcutStore:
    """`Files/profiles.json` okuma/yazma + pencereye gore profil bulma."""

    directory: Path | None = None
    profiles: list[AppProfile] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return (self.directory or paths.FILES) / "profiles.json"

    # ---- okuma ----

    def load(self) -> list[AppProfile]:
        """Dosyayi okur. Yoksa bos liste; bozuksa yedekleyip bos liste.

        Acilista tek bir bozuk dosya programin hic acilmamasina yol
        acmamali -- store.py'deki diger depolarla ayni kural.
        """
        path = self.path
        self.profiles = []
        if not path.exists():
            return self.profiles
        try:
            # BOM: AHK `FileIO.writeText(..., "UTF-8")` dosyanin basina BOM
            # koyuyor ve orjson BOM'lu girdiyi reddediyor. Ayni dosyayi iki
            # surum de okuyacaksa BOM'u burada kirpmak gerekiyor.
            data = orjson.loads(path.read_bytes().lstrip(codecs.BOM_UTF8))
        except (OSError, orjson.JSONDecodeError):
            log.exception("%s okunamadi, yedeklenip atlaniyor", path.name)
            backup_file(path, "bozuk")
            return self.profiles
        if not isinstance(data, dict):
            log.error("%s beklenen bicimde degil", path.name)
            return self.profiles

        for raw in data.get("profiles") or ():
            if not isinstance(raw, dict):
                continue
            self.profiles.append(
                AppProfile(
                    name=str(raw.get("profileName") or ""),
                    class_name=str(raw.get("className") or ""),
                    title=str(raw.get("title") or ""),
                    shortcuts=tuple(_read_shortcuts(raw.get("shortCuts"))),
                )
            )
        log.info("%d uygulama profili okundu (%s)", len(self.profiles), path)
        return self.profiles

    # ---- sorgu ----

    def find(self, class_name: str, title: str) -> AppProfile | None:
        """Pencereye uyan ILK profil. Basliksiz pencerede AHK gibi None."""
        if not title:
            return None
        for profile in self.profiles:
            if profile.matches(class_name, title):
                return profile
        return None

    def shortcut(self, profile_name: str, index: int) -> ShortCut | None:
        """Menu maddesinin isaret ettigi kisayol (`shorts.play:Chrome/0`)."""
        for profile in self.profiles:
            if profile.name == profile_name and 0 <= index < len(profile.shortcuts):
                return profile.shortcuts[index]
        return None


def _read_shortcuts(raw) -> list[ShortCut]:
    result: list[ShortCut] = []
    for item in raw or ():
        if not isinstance(item, dict):
            continue
        strokes = item.get("keyStrokes") or ()
        result.append(
            ShortCut(
                name=str(item.get("shortCutName") or ""),
                description=str(item.get("keyDescription") or ""),
                strokes=tuple(str(stroke) for stroke in strokes if str(stroke)),
            )
        )
    return result
