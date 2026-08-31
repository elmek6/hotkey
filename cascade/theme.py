"""Acik/koyu tema -- AHK'de karsiligi YOK, Qt'nin isiydi.

Windows 11'de Qt `windows11` stilini secip koyu modu kendi uyguluyordu;
Windows 10'da ise `windowsvista` stiline dusuyor ve o stil koyu paleti hic
desteklemiyor. "Sistem koyu ama program acik" sikayetinin sebebi bu.

Cozum stil degistirmek: `Fusion` her iki paleti de dogru ciziyor ve her
Windows surumunde ayni duruyor. Sistem KOYU ise Fusion + koyu palet, ACIK
ise yerel stil (yerel gorunum bedava geliyorsa birakalim).

SISTEM TEMASI IKI AYRI ANAHTAR -- Windows 10'da Ayarlar > Kisisellestirme >
Renkler altinda "Windows modu" ve "Uygulama modu" bagimsiz secilir:

    SystemUsesLightTheme   gorev cubugu / baslat menusu
    AppsUseLightTheme      UYGULAMALAR  <-- bizi ilgilendiren bu

Qt de `AppsUseLightTheme`i okur. Kullanici gorev cubugunu koyu, uygulama
modunu acik birakmissa Qt "acik" der ve HAKLIDIR; bu yuzden ayara elle
"Koyu" secenegi koyuyoruz -- sistemi degistirmeden zorlayabilsin.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from cascade.settings import Category, setting

log = logging.getLogger("cascade.theme")

SYSTEM = "system"
LIGHT = "light"
DARK = "dark"

THEME_LABELS = {
    SYSTEM: "Sistem",
    LIGHT: "Acik",
    DARK: "Koyu",
}

THEME = setting(
    "app.theme",
    "Tema",
    default=SYSTEM,
    choices=(SYSTEM, LIGHT, DARK),
    labels=THEME_LABELS,
    category=Category.GENERAL,
    tags="tema renk koyu acik dark light gorunum",
    desc=(
        "Pencerelerin rengi. 'Sistem' Windows'un UYGULAMA modunu izler "
        "(Ayarlar > Kisisellestirme > Renkler > 'Uygulama modu' -- gorev "
        "cubugu ayari degil, o ayri). Windows 10'da sistem koyu secilse bile "
        "Qt yerel stili koyu cizemedigi icin program acik kalir; 'Koyu' "
        "secersen sistemden bagimsiz olarak koyu palet uygulanir."
    ),
)


def system_is_dark() -> bool:
    """Windows'un UYGULAMA modu koyu mu? Okunamazsa acik say."""
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def resolve(choice: str | None = None) -> bool:
    """Ayardan "koyu mu?" sonucunu cikarir."""
    choice = choice if choice is not None else THEME.get()
    if choice == DARK:
        return True
    if choice == LIGHT:
        return False
    return system_is_dark()


# GitHub'in koyu paleti -- ui/ icindeki sabit renkler (#6e7681 vb.) zaten
# bu aileden, palet onlarla ayni tonda dursun.
_DARK = {
    QPalette.ColorRole.Window: "#1f2228",
    QPalette.ColorRole.WindowText: "#e6edf3",
    QPalette.ColorRole.Base: "#16191d",
    QPalette.ColorRole.AlternateBase: "#22262c",
    QPalette.ColorRole.Text: "#e6edf3",
    QPalette.ColorRole.Button: "#2a2f36",
    QPalette.ColorRole.ButtonText: "#e6edf3",
    QPalette.ColorRole.ToolTipBase: "#2a2f36",
    QPalette.ColorRole.ToolTipText: "#e6edf3",
    QPalette.ColorRole.Highlight: "#2f6fd0",
    QPalette.ColorRole.HighlightedText: "#ffffff",
    QPalette.ColorRole.Link: "#4c9aff",
    QPalette.ColorRole.PlaceholderText: "#7d8590",
}

#: Yerel stilin adi -- koyudan acika donerken geri kurulsun diye acilista
#: bir kez saklaniyor ("windowsvista" / "windows11").
_native_style = ""


def _dark_palette() -> QPalette:
    palette = QPalette()
    for role, color in _DARK.items():
        palette.setColor(role, QColor(color))
    # Devre disi ogeler: ayni renkte kalirsa "kapali" oldugu anlasilmiyor.
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6e7681"))
    return palette


def apply(_value=None, _old=None) -> None:
    """Ayari uygular. `Setting.subscribe` imzasina uysun diye iki argumanli."""
    app = QApplication.instance()
    if app is None:
        return
    global _native_style
    if not _native_style:
        _native_style = app.style().objectName()

    if resolve():
        app.setStyle("Fusion")
        app.setPalette(_dark_palette())
    else:
        app.setStyle(_native_style or "Fusion")
        app.setPalette(app.style().standardPalette())


def install() -> None:
    """Ayari dinlemeye basla + sistem temasi degisince (Sistem secilinse)
    canli guncelle. `SETTINGS.apply_all()` acilista `apply`i zaten cagirir."""
    THEME.subscribe(apply)
    QGuiApplication.styleHints().colorSchemeChanged.connect(
        lambda _scheme: apply() if THEME.get() == SYSTEM else None
    )
