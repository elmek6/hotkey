"""Acilir menu -- menus.ahk'nin `showF13menu()` girisi.

AHK'de menu Win32 `Menu()` nesnesiydi ve dosyanin yarisi onun kisitlarini
asmakla geciyordu: kolon kirma (`MENU_COL`), `SetIcon` ile DLL'den ikon
cekme, `Default` ile kalin oge. Qt'de bunlarin hicbiri gerekmiyor --
QMenu kendi kaydiriyor, ikon yerine emoji yaziyoruz, varsayilan oge
`setDefaultAction`.

Tanim veri olarak veriliyor: (etiket, eylem kimligi) ciftleri, `None`
ayrac. Eylem kimligi yerine ic ice bir demet verilirse ALT MENU olur --
AHK'deki `menuF14.Add("Special keys", subMenuKey)`. Boylece menu icerigi
main.py'de tek bir listede durur ve ileride JSON'a tasinabilir; AHK'de her
oge bir kod satiriydi.

Tip (ui/tip.py) ile farki: bu menu odagi ALIR. Kasitli -- ok tuslari,
harfe basip secme ve fare tiklamasi Windows'un menu davranisidir, kullanici
onu bekler. Tip ise odak calmamak zorunda, cunku tus secimi hook'ta
yutuluyor.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import QMenu

# (etiket, eylem kimligi) -- None ayrac demek.
# Eylem kimligi yerine demet gelirse o oge bir alt menudur.
MenuSpec = tuple["tuple[str, str | tuple] | None", ...]


class PopupMenu:
    """Imlecin yaninda acilan menu. Secim eylem kimligi olarak geri doner."""

    def __init__(self, on_action: Callable[[str], None]) -> None:
        self._on_action = on_action
        self._menu: QMenu | None = None  # GC'ye yem olmasin

    def show(self, spec: MenuSpec, title: str = "", default: str = "") -> None:
        menu = QMenu()

        if title:
            header = QAction(title, menu)
            header.setEnabled(False)
            menu.addAction(header)
            menu.addSeparator()

        self._fill(menu, spec, default)
        self._menu = menu
        # popup(), exec()'in aksine olay dongusunu bloke etmez: hook'tan gelen
        # olaylari isleyen QTimer'lar donmeye devam eder.
        menu.popup(QCursor.pos())
        # Odagi ZORLA almak gerekiyor: tepsi uygulamasinin aktif penceresi
        # olmadigi icin acilan menu klavye yakalamasini kendiliginden
        # almiyordu ve Esc / ok tuslari ona ulasmiyordu. Menu kapaninca
        # odak eski pencereye kendiliginden doner.
        menu.setFocus()
        menu.activateWindow()
        menu.raise_()

    @property
    def open(self) -> bool:
        return self._menu is not None and self._menu.isVisible()

    def close(self) -> None:
        """Disaridan kapatma -- hook Esc'i gorunce cagiriyor.

        Klavye yakalamasi bize gelmediginde Esc menuye ulasmiyor; hook zaten
        her tusu goruyor, kapatmayi oradan tetiklemek en guvenlisi.
        """
        if self._menu is not None:
            self._menu.close()

    def _fill(self, menu: QMenu, spec: MenuSpec, default: str = "") -> None:
        for entry in spec:
            if entry is None:
                menu.addSeparator()
                continue
            label, target = entry
            if isinstance(target, tuple):  # alt menu
                submenu = menu.addMenu(label)
                self._fill(submenu, target)
                continue
            action = QAction(label, menu)
            action.triggered.connect(
                lambda _checked=False, a=target: self._on_action(a)
            )
            menu.addAction(action)
            if target == default:
                menu.setDefaultAction(action)
