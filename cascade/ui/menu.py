"""Acilir menu -- menus.ahk'nin `showF13menu()` girisi.

AHK'de menu Win32 `Menu()` nesnesiydi. Bir sure Qt'nin `QMenu`'su
kullanildi ama tepsi uygulamasinin aktif penceresi olmadigi icin menu
foreground olamiyor, ilk tiklama oge secmek yerine pencereyi aktive etmeye
gidiyordu ("bazen tiklama gitmiyor"). Artik AHK'deki gibi GERCEK Windows
menusu cizdiriliyor: `win32/menu.py` -> `TrackPopupMenu`. Klavye gezinme,
Esc, alt menu acilisi ve ekrana sigdirma isletim sisteminin isi.

Tanim veri olarak veriliyor: (etiket, eylem kimligi) ciftleri, `None`
ayrac. Eylem kimligi yerine ic ice bir demet verilirse ALT MENU olur --
AHK'deki `menuF14.Add("Special keys", subMenuKey)`. Boylece menu icerigi
keymap.py'de tek bir listede durur.

Tip (ui/tip.py) ile farki: bu menu odagi ALIR. Kasitli -- ok tuslari,
harfe basip secme ve fare tiklamasi Windows'un menu davranisidir, kullanici
onu bekler. Tip ise odak calmamak zorunda.

**Menu acikken hook susar.** `TrackPopupMenu` kapanana kadar donmez ve o
sirada tuslar MENUYE gitmelidir; `set_ui_open` ile dispatcher susturuluyor.
Yoksa hook Esc'i yutar ve menu kapanmazdi. Eylem, menu KAPANDIKTAN sonra
calisir -- eski QMenu'de de oyleydi.
"""

from __future__ import annotations

from collections.abc import Callable

from cascade.win32 import menu as win32_menu
from cascade.win32.menu import COLUMN

# Menu tanimi: (etiket, eylem kimligi) ciftleri.
#   * `None`            yatay ayrac
#   * `COLUMN` ("|")    buradan sonrasi YENI KOLON (AHK: MENU_COL)
#   * eylem yerine demet -> alt menu
#   * ucuncu alan       ikon adi: `"res:243"` / `"shell:260"` (AHK menuIcon
#                       ile ayni numaralar; renkli ikonun tek yolu, emoji
#                       klasik menude tek renk cizilir)
MenuSpec = tuple["tuple[str, str | tuple] | tuple[str, str, str] | str | None", ...]

__all__ = ["COLUMN", "MenuSpec", "PopupMenu"]


class PopupMenu:
    """Imlecin yaninda acilan Windows menusu. Secim eylem kimligi olarak doner."""

    def __init__(
        self,
        on_action: Callable[[str], None],
        set_ui_open: Callable[[bool], None] | None = None,
    ) -> None:
        self._on_action = on_action
        self._set_ui_open = set_ui_open
        self._open = False

    def show(
        self,
        spec: MenuSpec,
        title: str = "",
        default: str | tuple[str, ...] = "",
    ) -> None:
        if self._open:  # ic ice menu acilmasin: TrackPopupMenu bloklar
            return
        self._open = True
        if self._set_ui_open is not None:
            self._set_ui_open(True)
        try:
            action = win32_menu.track(spec, title=title, default=default)
        finally:
            self._open = False
            if self._set_ui_open is not None:
                self._set_ui_open(False)
        if action:
            self._on_action(action)

    @property
    def open(self) -> bool:
        """Menu acik mi.

        Dispatcher bunu Esc'i yakalamak icin soruyordu; Win32 menusu Esc'i
        kendi hallettigi ve menu acikken hook zaten susturuldugu icin artik
        `False` donmesi de yeterliydi -- yine de dogru bilgi veriliyor,
        baska bir karar buna dayanirsa yaniltmasin.
        """
        return self._open

    def close(self) -> None:
        """Disaridan kapatma. Win32 menusune WM_CANCELMODE gonderir."""
        if self._open:
            win32_menu.cancel()
