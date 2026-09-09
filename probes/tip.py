"""ADIM 16'nin OLCUMU: ipucu penceresi gercekten SAYDAM mi?

`fui/tip.py` "icerige gore boy" sorununu saydamlikla cozuyor: pencereye
comert bir olcu verilip zemini `TRANSPARENT` birakiliyor, gorunen kutu
icindeki `Container`. Bu bir VARSAYIM -- Flet'in `window.bgcolor` ile
Windows'ta gercekten saydam pencere yapip yapmadigi OLCULMEDI.

Bu sondaj olcer. Yontem GOZE degil PIKSELE bakiyor:

    1. ekran yakalanir (ipucu KAPALIYKEN)
    2. ipucu gosterilir, pencere tutamagi baslikla bulunur
    3. ekran TEKRAR yakalanir
    4. pencerenin dikdortgeninde DEGISEN pikseller sayilir

Saydamsa yalnizca KUTUNUN oldugu yer degisir; degilse dikdortgenin
TAMAMI degisir. Oran ekrana yaziliyor, karar ona gore.

Ayni kosuda olculen ikinci sey ACILIS SURESI: on isitmali (`warm`) ve
isitmasiz ilk gosterim arasindaki fark -- adim 15'in isitmasi ipucunda
gercekten ise yariyor mu.

Calistir:  uv run python -m probes.tip

Ekranda birkac saniye kucuk kutular acilip kapanir, sonuc konsola
yazilir. Olcum sirasinda makineye dokunmak gerekmiyor (odak olcumunden
farki bu: burada odak degil PIKSEL okunuyor).
"""

from __future__ import annotations

import sys
import time

from PySide6.QtWidgets import QApplication

from keypilot.fui.tip import TipPanel
from keypilot.win32 import screen
from keypilot.win32 import window as win
from keypilot.win32.send import set_cursor_pos
from keypilot.win32.window import GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST

#: Bayrak dokumu icin -- `win32/window.py`de olmayanlar.
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_EX_LAYERED = 0x00080000

#: Panelin pencere basligi -- tutamagi bununla buluyoruz (`fui/tip.py`).
TITLE = "KeyPilot ipucu"

#: Flet istemcisinin ayaga kalkmasi (olculdu: 1.0-3.5 sn).
BOOT_TIMEOUT = 25.0

#: Gosterimden sonra cizimin oturmasi icin. Flutter kareyi hemen
#: basmiyor; kisa tutulursa "degismedi" diye olculur.
SETTLE = 1.2

#: Imlec buraya konuyor ki yerlestirme DETERMINISTIK olsun.
CURSOR = (600, 400)


def pump(seconds: float) -> None:
    """Qt olay dongusunu `seconds` boyunca cevir.

    `time.sleep` OLMAZ: panelin zamanlayicisi ve `ask_qt` sinyalleri ana
    thread'in dongusunde kosuyor, uyursak panel kendi isini yapamaz.
    """
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def wait_window(title: str = TITLE, timeout: float = BOOT_TIMEOUT) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = win.find_window(title=title)
        if hwnd:
            return hwnd
        pump(0.05)
    return 0


def diff_rect(before, after, rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """Dikdortgende (fiziksel piksel) DEGISEN piksel sayisi ve toplam.

    `before`/`after` `grab_virtual()`den gelen tam ekran goruntuleri;
    sanal masaustu sol-ustu negatif olabilecegi icin ofset dusuluyor.
    """
    left, top, right, bottom = rect
    origin_x, origin_y, _w, _h = screen.virtual_rect()
    changed = 0
    total = 0
    # Her pikseli okumak pahali (bir kutu ~300x80 = 24 bin okuma, Python
    # dongusunde saniyeler); ikiser atlaniyor -- oran icin fazlasiyla yeter.
    for y in range(top, bottom, 2):
        for x in range(left, right, 2):
            px, py = x - origin_x, y - origin_y
            if px < 0 or py < 0 or px >= before.width() or py >= before.height():
                continue
            total += 1
            if before.pixel(px, py) != after.pixel(px, py):
                changed += 1
    return changed, total


def measure_transparency(panel: TipPanel, hwnd: int, body: str, label: str) -> str:
    """Bir gosterimin kac pikselini boyadigini olcer."""
    panel.hide()
    if not wait_hidden(hwnd):
        return f"--- {label}\n    OLCULEMEDI: pencere gizlenmedi"
    pump(0.4)
    before, _box = screen.grab_virtual()

    set_cursor_pos(*CURSOR)
    panel.show_html(body, 0)
    pump(SETTLE)

    rect = win.window_rect(hwnd)
    after, _box = screen.grab_virtual()
    changed, total = diff_rect(before, after, rect)
    left, top, right, bottom = rect
    ratio = (changed / total * 100) if total else 0.0
    lines = [
        f"--- {label}",
        f"    pencere: {right - left}x{bottom - top} @ ({left},{top}) fiziksel",
        f"    degisen piksel: {changed}/{total}  ({ratio:.0f}%)",
    ]
    if ratio > 90:
        lines.append("    SONUC: SAYDAM DEGIL -- pencerenin tamami boyandi")
    elif ratio < 5:
        lines.append("    SONUC: OLCULEMEDI -- pencere hic cizilmemis olabilir")
    else:
        lines.append(f"    SONUC: SAYDAM -- yalnizca %{ratio:.0f} boyandi (kutu)")
    return "\n".join(lines)


def measure_fit(panel: TipPanel, hwnd: int, body: str, label: str) -> str:
    """Kutu pencereye SIGIYOR mu -- `CHAR_PX` tahmini tutuyor mu?

    `window_size` genisligi karakter sayisindan TAHMIN ediyor (Segoe UI
    oransal, olculebilen bir metrik yok). Tahmin kucuk kalirsa Flutter
    metni kirpar. Olcut: BOYANAN bolgenin sag kenari pencerenin sag
    kenarina DAYANIYORSA kirpilma var demektir -- kutu sigmis olsa
    saginda saydam bir serit kalirdi.
    """
    panel.hide()
    if not wait_hidden(hwnd):
        return f"--- {label}\n    OLCULEMEDI: pencere gizlenmedi"
    pump(0.4)
    before, _box = screen.grab_virtual()
    set_cursor_pos(*CURSOR)
    panel.show_html(body, 0)
    pump(SETTLE)
    rect = win.window_rect(hwnd)
    after, _box = screen.grab_virtual()
    left, top, right, bottom = rect
    origin_x, origin_y, _w, _h = screen.virtual_rect()
    box_right = left
    box_bottom = top
    for y in range(top, bottom):
        for x in range(left, right):
            px, py = x - origin_x, y - origin_y
            if px < 0 or py < 0 or px >= before.width() or py >= before.height():
                continue
            if before.pixel(px, py) != after.pixel(px, py):
                box_right = max(box_right, x)
                box_bottom = max(box_bottom, y)
    sag_bosluk = right - box_right
    alt_bosluk = bottom - box_bottom
    lines = [
        f"--- {label}",
        f"    pencere {right - left}x{bottom - top}, kutu sag kenara "
        f"{sag_bosluk} px, alt kenara {alt_bosluk} px kaldi",
    ]
    if sag_bosluk <= 2:
        lines.append("    SONUC: KIRPILMA RISKI -- kutu pencereye dayaniyor")
    else:
        lines.append("    SONUC: SIGIYOR")
    return chr(10).join(lines)


def measure_boot(cold: bool) -> str:
    """Ilk gosterimin ekranda GORUNME suresi. `cold` ise isitma YOK."""
    panel = TipPanel()
    if not cold:
        panel.warm()
        pump(5.0)  # isitma BITSIN: olculen sey isitmadan SONRAKI gosterim
    set_cursor_pos(*CURSOR)
    start = time.monotonic()
    panel.show_html("olcum", 0)
    hwnd = wait_window()
    # Pencerenin ACILMASI degil GORUNMESI olculuyor: isitilmis panelde
    # tutamak zaten var, bakilacak sey `IsWindowVisible`.
    visible = 0.0
    deadline = time.monotonic() + BOOT_TIMEOUT
    while time.monotonic() < deadline:
        if hwnd and win.is_window(hwnd) and _visible(hwnd):
            visible = time.monotonic() - start
            break
        if not hwnd:
            hwnd = win.find_window(title=TITLE)
        pump(0.02)
    panel.shutdown()
    return f"{visible:.2f} sn" if visible else "GORUNMEDI"


def _visible(hwnd: int) -> bool:
    from keypilot.win32.structs import user32

    return bool(user32.IsWindowVisible(hwnd))


def wait_hidden(hwnd: int, timeout: float = 3.0) -> bool:
    """Pencere GERCEKTEN gizlenene kadar bekle.

    Ilk olcumde bu yoktu ve olcum KIRLENDI: "onceki" ekran goruntusu
    ipucu HALA EKRANDAYKEN alindi, degisen piksel yalnizca metin oldu
    (%3) ve sonuc "pencere cizilmemis" gibi gorundu.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _visible(hwnd):
            return True
        pump(0.05)
    return False


def styles(hwnd: int) -> str:
    """Pencere bayraklari -- hangi Flet ayari ISLEDI, hangisi islemedi."""
    from keypilot.win32.structs import user32

    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    return "\n".join(
        [
            f"    always_on_top  -> WS_EX_TOPMOST    : {bool(ex_style & WS_EX_TOPMOST)}",
            f"    skip_task_bar  -> WS_EX_TOOLWINDOW : {bool(ex_style & WS_EX_TOOLWINDOW)}",
            f"    (saydamlik)    -> WS_EX_LAYERED    : {bool(ex_style & WS_EX_LAYERED)}",
            f"    frameless      -> WS_CAPTION YOK   : {not bool(style & WS_CAPTION)}",
            f"    frameless      -> WS_THICKFRAME YOK: {not bool(style & WS_THICKFRAME)}",
        ]
    )


def main() -> int:
    app = QApplication(sys.argv)
    _ = app

    out: list[str] = []

    print("ipucu isitiliyor...")
    panel = TipPanel()
    panel.warm()
    pump(4.0)  # `flet.exe` ayaga kalksin (olculdu: 1.0-3.5 sn)
    # Isitilan pencere GIZLI, `find_window` yalniz gorunur pencere
    # buluyor -- once bir kez gostermek gerekiyor.
    set_cursor_pos(*CURSOR)
    panel.show_html("hazirlik", 0)
    hwnd = wait_window()
    if not hwnd:
        print("ipucu penceresi acilmadi -- olcum yapilamadi")
        panel.shutdown()
        return 1
    print(f"pencere: {hwnd:#x} [{win.window_class(hwnd)}]\n")

    # Uc govde: tek satir, uc satir ve menu. Saydamlik varsa BOYANAN
    # ORAN ucunde de farkli olmali -- kutu buyudukce artmali.
    out.append(measure_transparency(panel, hwnd, "kisa", "A  tek satir"))
    out.append(
        measure_transparency(
            panel,
            hwnd,
            "<b>bir</b><br>iki<br>uc<br>dort<br>bes",
            "B  bes satir",
        )
    )

    # Olcunun TAHMIN olan yani: genislik karakter sayisindan cikiyor.
    out.append(measure_fit(panel, hwnd, "kisa", "D1 kisa metin"))
    out.append(
        measure_fit(
            panel,
            hwnd,
            "son hata panoya kopyalandi: dosya bulunamadi (clip.json)",
            "D2 uzun tek satir",
        )
    )
    out.append(
        measure_fit(
            panel,
            hwnd,
            "📋 <b>gorsel</b> &nbsp;·&nbsp; 1920x1080 piksel",
            "D3 emoji + kalin",
        )
    )
    out.append("--- C  pencere bayraklari (hangi Flet ayari ISLEDI)" + chr(10) + styles(hwnd))

    panel.hide()
    pump(0.4)
    panel.shutdown()

    print("\n".join(out))
    print("\n--- D  ACILIS SURESI (adim 15'in isitmasi ise yariyor mu)")
    print(f"    ISITILMIS ilk gosterim: {measure_boot(cold=False)}")
    print(f"    ISITILMAMIS ilk gosterim: {measure_boot(cold=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
