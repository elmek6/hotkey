"""Ipucu/menu metni kisaltma -- app.py'den ayrildi.

Tek isi: uzun panoda/slotta duran metni ekrana sigan bir onizlemeye
cevirmek. Hem pano hem slot tarafi ayni kurali kullansin diye burada.
"""

from __future__ import annotations

import html

from keypilot.ui.tip import DIM

#: Ipucunda gosterilecek en fazla satir / satir basina en fazla karakter.
TIP_LINES = 5
TIP_WIDTH = 70


def shorten(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def dim(body: str) -> str:
    """Ipucunda SOLUK (ikincil) metin. `body` HTML'dir -- kacislamak
    cagiranin isi. Renk tek yerde: ui/tip.py `DIM`."""
    return f"<span style='color:{DIM};'>{body}</span>"


def preview_html(text: str, lines: int = TIP_LINES, width: int = TIP_WIDTH) -> str:
    """Cok satirli onizleme -- KACISLANMIS HTML doner.

    Ipucu QLabel'i zengin metin (bkz. ui/tip.py), yani tek satir zorunlulugu
    yok; onceden metin `preview` ile tek satira eziliyordu ve 3 satirlik bir
    kopya tek satir gorunuyordu. AHK'nin ToolTip'i gibi: ilk birkac satir,
    fazlasi "… +n satir" diye ozetlenir.
    """
    rows = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    shown = [html.escape(shorten(row.rstrip(), width)) for row in rows[:lines]]
    body = "<br>".join(shown)
    rest = len(rows) - lines
    if rest > 0:
        body += f"<br>{dim(f'… +{rest} satir')}"
    return body
