"""Acilir menu -- menus.ahk'nin `showF13menu()` girisi.

AHK'de menu Win32 `Menu()` nesnesiydi ve dosyanin yarisi onun kisitlarini
asmakla geciyordu: kolon kirma (`MENU_COL`), `SetIcon` ile DLL'den ikon
cekme, `Default` ile kalin oge. Qt'de bunlarin hicbiri gerekmiyor --
QMenu kendi kaydiriyor, ikon yerine emoji yaziyoruz, varsayilan oge
`setDefaultAction`.

Tanim veri olarak veriliyor: (etiket, eylem kimligi) ciftleri, `None`
ayrac. Boylece menu icerigi main.py'de tek bir listede durur ve ileride
JSON'a tasinabilir -- AHK'de her oge bir kod satiriydi.

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
MenuSpec = tuple[tuple[str, str] | None, ...]


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

        for entry in spec:
            if entry is None:
                menu.addSeparator()
                continue
            label, action_id = entry
            action = QAction(label, menu)
            action.triggered.connect(
                lambda _checked=False, a=action_id: self._on_action(a)
            )
            menu.addAction(action)
            if action_id == default:
                menu.setDefaultAction(action)

        self._menu = menu
        # popup(), exec()'in aksine olay dongusunu bloke etmez: hook'tan gelen
        # olaylari isleyen QTimer'lar donmeye devam eder.
        menu.popup(QCursor.pos())
