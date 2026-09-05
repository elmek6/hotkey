"""Windows ile birlikte baslatma -- ayar ekranindan acilip kapaniyor.

Kisayol `shell:startup` klasorune yaziliyor (Kayit Defteri `Run` degil):
kullanici klasoru Gorev Yoneticisi'nin "Baslangic" sekmesinde ve Explorer'da
gorunur, elle silinebilir. Ayni yontemi zaten elle kullaniyorduk.

Baslatilan sey `hotkey.vbs`: `pythonw` konsolsuz calissin diye. `wscript`
ile cagriliyor, boylece tek bir konsol penceresi bile yanip sonmuyor.

Ayarin degeri diskte DEGIL sistemde: acilista `sync()` kisayolun varligina
bakip ayari ona esitliyor. settings.json elle kopyalandiginda baska bir
makinede olmayan bir kisayol "acik" gorunmesin.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from keypilot import paths
from keypilot.settings import Category, setting

log = logging.getLogger("keypilot.autostart")

#: Kisayol adi -- eskiden elle konan `hotkey.lnk` ile ayni, iki tane olusmasin.
LINK_NAME = "hotkey.lnk"
SCRIPT = paths.ROOT / "hotkey.vbs"


def startup_dir() -> Path:
    return (
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft/Windows/Start Menu/Programs/Startup"
    )


def link_path() -> Path:
    return startup_dir() / LINK_NAME


def is_enabled() -> bool:
    return link_path().exists()


def _create() -> str:
    """`""` = basarili. Kisayolu WScript.Shell ile yaziyoruz -- .lnk bicimini
    elle uretmek yerine Windows'un kendi COM'u; pywin32 bagimliligi yok."""
    if not SCRIPT.exists():
        return f"Baslatma betigi yok: {SCRIPT}"
    target = link_path()
    script = (
        "$s = New-Object -ComObject WScript.Shell; "
        f"$l = $s.CreateShortcut('{target}'); "
        "$l.TargetPath = 'wscript.exe'; "
        f"$l.Arguments = '\"{SCRIPT}\"'; "
        f"$l.WorkingDirectory = '{paths.ROOT}'; "
        "$l.Save()"
    )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(  # noqa: S603
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],  # noqa: S607
            check=True,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.CalledProcessError) as error:
        log.exception("Baslangic kisayolu yazilamadi")
        return f"Kisayol olusturulamadi: {error}"
    return ""


def _remove() -> str:
    try:
        link_path().unlink(missing_ok=True)
    except OSError as error:
        log.exception("Baslangic kisayolu silinemedi")
        return f"Kisayol silinemedi: {error}"
    return ""


def _on_change(value, old) -> None:
    if value == old:  # apply_all: acilistaki ilk bildirim, sistemi ellemez
        return
    message = _create() if value else _remove()
    if message:
        log.warning("%s", message)
        AUTOSTART._value = not value  # noqa: SLF001  yazilamadiysa ayar yalan soylemesin


AUTOSTART = setting(
    "general.autostart",
    "Windows ile birlikte baslat",
    default=False,
    category=Category.GENERAL,
    tags="baslangic autostart startup acilis",
    desc=(
        "Kullanici Baslangic klasorune hotkey.vbs kisayolu koyar "
        "(shell:startup). Kapatinca kisayolu siler."
    ),
    on_change=_on_change,
)


def sync() -> None:
    """Acilista: ayari sistemdeki gercek duruma esitle."""
    AUTOSTART._value = is_enabled()  # noqa: SLF001  dosya sistemi kaynak, notify gereksiz
