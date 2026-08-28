"""Ipucu penceresi -- AHK'deki ToolTip()'in yerine gecen zengin metin surumu.

AHK'nin ToolTip'i tek renk, tek font, duz metindir; emoji ve vurgu yapamaz.
Burada QLabel zengin metin (RichText) modunda: HTML alt kumesi, renk, kalin,
emoji ve satir yapisi calisiyor. Qt'nin QLabel'i CSS2'nin bir alt kumesini
destekler -- tablo hucre arka plani ve renk calisir, border-radius calismaz;
o yuzden pencerenin kendi yuvarlak kosesi stylesheet'ten, ic rozetler tablo
hucresinden geliyor.

Neden QMenu degil: acilan bir QMenu klavyeyi kapar ve on plandaki pencereden
odagi alir. Bizim mimaride tus secimi zaten hook'ta yutuluyor, menunun
klavyeye ihtiyaci yok. Bu yuzden odak calmayan, cercevesiz, hep ustte duran
bir etiket kullaniliyor.

Kullanim:
    tip.show_text("duz metin \U0001f642", 2000)      # kacisli, guvenli
    tip.show_html("<b>kalin</b> ve <i>egik</i>")     # ham HTML
    tip.show_menu("ScrollLock", (("1", "Metin yaz"),), footer="Esc  iptal")
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QFont, QGuiApplication
from PySide6.QtWidgets import QLabel

# Tek yerden renk -- tepsi simgesiyle ayni mavi.
FG = "#e6edf3"
DIM = "#8b949e"
ACCENT = "#58a6ff"
BADGE_BG = "#30363d"
BADGE_FG = "#f0f6fc"
BG = "#1b1f24"
BORDER = "#30363d"

# Emoji'nin gercekten cizilmesi icin yedek aile zinciri gerekiyor:
# Segoe UI'de sekil yoksa Qt Segoe UI Emoji'ye duser.
FAMILY = "'Segoe UI', 'Segoe UI Emoji', 'Noto Color Emoji', sans-serif"
MONO = "'Cascadia Mono', Consolas, monospace"


class Tip(QLabel):
    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setMargin(10)
        font = QFont("Segoe UI")
        font.setPointSize(10)
        self.setFont(font)
        self.setStyleSheet(
            f"background-color: {BG}; color: {FG};"
            f"border: 1px solid {BORDER}; border-radius: 6px;"
        )
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    # ---- gosterim ----

    def show_html(self, body: str, ms: int = 0) -> None:
        """Ham HTML. Cagiran kacislamadan sorumlu."""
        self.setText(f"<div style=\"font-family:{FAMILY};\">{body}</div>")
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        if ms > 0:
            self._timer.start(ms)
        else:
            self._timer.stop()

    def show_text(self, text: str, ms: int = 0) -> None:
        """Duz metin: HTML olarak yorumlanmaz, satir sonlari korunur."""
        self.show_html(html.escape(text).replace("\n", "<br>"), ms)

    def show_menu(
        self,
        title: str,
        items: tuple[tuple[str, str], ...],
        footer: str = "Esc  iptal",
        ms: int = 0,
    ) -> None:
        """AHK autoPreview'in karsiligi: baslik + 'tus  aciklama' listesi.

        Aciklama icinde emoji ve <b>/<i> gibi basit etiketler kullanilabilir;
        tus rozeti her zaman kacislanir.
        """
        rows = "".join(
            f'<tr>'
            f'<td bgcolor="{BADGE_BG}" style="color:{BADGE_FG};font-family:{MONO};">'
            f"&nbsp;<b>{html.escape(key)}</b>&nbsp;</td>"
            f'<td>&nbsp;&nbsp;{desc}</td>'
            f"</tr>"
            for key, desc in items
        )
        body = (
            f'<div style="color:{ACCENT};"><b>{html.escape(title)}</b></div>'
            f'<table cellspacing="3" cellpadding="2">{rows}</table>'
        )
        if footer:
            body += f'<div style="color:{DIM};">{html.escape(footer)}</div>'
        self.show_html(body, ms)

    # ---- yerlestirme ----

    def _place(self) -> None:
        """Imlecin sag altina; ekran disina tasarsa ice ceker."""
        pos = QCursor.pos()
        x, y = pos.x() + 18, pos.y() + 18
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = min(x, area.right() - self.width() - 4)
            y = min(y, area.bottom() - self.height() - 4)
            x = max(x, area.left() + 4)
            y = max(y, area.top() + 4)
        self.move(x, y)
