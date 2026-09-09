"""ADIM 14'un OLCUMU: Flet penceresi odagi caliyor mu?

Asama 3'te bekleyen dokuz pencerenin DORDU ayni sorunun arkasinda
duruyor (`ui/array_filter.py`, `ui/quick_panel.py`, `ui/tip.py`,
`ui/incognito_badge.py`): pencere acilirken YAZDIGIN uygulamanin odagi
kaybolmamali. Kod yazmadan once olculuyor -- adim 10'un dersi
(surukleme once denendi, sonra "olmuyor" denildi).

Bes senaryo, hepsi ayni yontemle: once HEDEF pencere one getiriliyor
(`probes/focus_target.py` -- ayri bir surecte kucuk bir Qt penceresi),
sonra Flet penceresi gosteriliyor ve iki saniye boyunca 20 ms'de bir
`GetForegroundWindow` orneklenip DEGISIM anlari yaziliyor.

OLCUM KIRLENEBILIR: makinede odak calan baska bir uygulama varsa
(ilk denemede calisan bir Flutter ornegi vardi) senaryo bosa gider. Bu
yuzden her senaryo TEMIZ bir olcum alana kadar en fazla `TRIES` kez
tekrarlaniyor; olmazsa "OLCULEMEDI" yaziyor -- yanlis veriyle karar
vermektense olcum yapmamak yeglenir.

    A  varsayilan       `window.visible = True` + `to_front()`
                        -- panellerimizin BUGUN yaptigi sey
    B  to_front YOK     yalniz `window.visible = True`
    C  focused = False  Flet'in kendi bayragi
    D  Win32           `WS_EX_NOACTIVATE` + `ShowWindow(SW_SHOWNOACTIVATE)`
                        -- Flet'e hic sormadan, pencere tutamagi uzerinden
    E  geri verme      A'dan sonra `SetForegroundWindow(eski pencere)`
    F  ILK ACILIS      `flet.exe` sifirdan ayaga kalkarken -- A-E hep
                        ZATEN AYAKTA olan bir pencereyi gosteriyor,
                        bu ise surecin kendisini baslatiyor
    G  odagi ALMA      `window.focused = True` + `to_front()`. Bu ters
                        soru: pano gecmisi ve hizli panel kutusuna
                        YAZILIYOR, yani odagi ALMALILAR. Odak calmayan
                        bir pencere onlar icin sorun.
    H  odagi ZORLAMA   G calismazsa: odagi BIZIM surecimizden Flet
                        penceresine vermek (`AttachThreadInput` +
                        `SetForegroundWindow`).

Calistir:  uv run python -m probes.focus

Ekranda Not Defteri ve kucuk bir Flet penceresi acilir, ~30 saniye
surer ve kendi kendine kapanir. Sonuc konsola TABLO olarak yaziliyor;
plana o tablo giriyor.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from collections.abc import Callable
from ctypes import wintypes

import flet as ft

from keypilot.fui.engine import FletEngine
from keypilot.win32 import window as win
from keypilot.win32.structs import user32
from probes.focus_target import TITLE as TARGET_TITLE

#: Olcum penceresinin basligi -- Flet'in tutamagini bununla buluyoruz.
TITLE = "KeyPilot odak sondaji"

#: F senaryosunun IKINCI penceresi: ayri bir `flet.exe` ayaga kalkiyor.
TITLE_BOOT = "KeyPilot odak sondaji 2"

#: Ornekleme: iki saniye boyunca 20 ms'de bir. Odak degisimi
#: gozle gorulmeden once oluyor; siklik ondan.
SAMPLE_SECONDS = 2.0
SAMPLE_STEP = 0.02

#: Flet istemcisinin ayaga kalkmasi (olculdu: 1.0-3.5 sn).
BOOT_TIMEOUT = 20.0

#: Bir senaryo temiz olcum alana kadar kac kez denenir. Alti: makinede
#: odak calan bir uygulama varken (IDE, calisan bir Flutter ornegi) uc
#: deneme yetmedi.
TRIES = 6

#: Odagi ZORLA geri almak icin. `SetForegroundWindow` tek basina
#: yetmiyor: Windows odak calmayi kisitliyor ve baska bir uygulama
#: ondeyken cagri `False` donuyor (ilk olcumde tam bu oldu -- araya
#: baska bir Flutter penceresi girdi ve Not Defteri bir daha one
#: gelemedi). `AttachThreadInput` ile o pencerenin girdi kuyruguna
#: baglanip izin aliniyor. SONDAJA OZEL bir numara: olcum "cozuluyor"
#: derse duzgun yeri `keypilot/win32/window.py`.
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4

# `SetWindowLongW` keypilot/win32'de YOK ve oraya eklenmiyor: bu bir
# sondaj, kalici bir yetenek degil. Olcum "cozuluyor" derse o zaman
# duzgun yerine yazilir.
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def force_focus(hwnd: int, tries: int = 3) -> bool:
    """Pencereyi ZORLA one getir (bkz. `AttachThreadInput` notu).

    Birden fazla deneme: odak calan bir uygulama varken tek atis
    yetmiyor -- bir kez alip hemen kaybetmek de olabiliyor.
    """
    for _ in range(tries):
        if win.activate(hwnd) and win.foreground_window() == hwnd:
            return True
        front = win.foreground_window()
        front_thread = user32.GetWindowThreadProcessId(front, None)
        ours = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(ours, front_thread, True)
        try:
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
        finally:
            user32.AttachThreadInput(ours, front_thread, False)
        time.sleep(0.25)
        if win.foreground_window() == hwnd:
            return True
    return False


def describe(hwnd: int) -> str:
    """Pencereyi tek satirda tanit: hwnd, sinif, baslik."""
    if not hwnd:
        return "(pencere yok)"
    return f"{hwnd:#x} [{win.window_class(hwnd)}] {win.window_title(hwnd)!r}"


class Probe:
    """Olcum penceresi. Flet tarafi olabildigince BOS: olculen sey
    pencerenin kendisi, icindekiler degil."""

    def __init__(self, title: str = TITLE) -> None:
        self.title = title
        self.engine = FletEngine(self._build)
        self.page: ft.Page | None = None
        self.hwnd = 0

    def _build(self, page: ft.Page) -> None:
        self.page = page
        page.title = self.title
        page.bgcolor = "#0d1117"
        page.window.width, page.window.height = 420, 220
        page.window.prevent_close = True
        page.controls.append(
            ft.Text("odak sondaji", color="#e6edf3", size=16)
        )
        page.update()

    # -- pencereyi gosterme yollari (hepsi FLET dongusunde kosar) ----------

    async def show_default(self) -> None:
        """A: panellerimizin bugun yaptigi sey."""
        page = self.page
        if page is None:
            return
        page.window.visible = True
        page.update()
        await page.window.to_front()

    def show_no_front(self) -> None:
        """B: `to_front()` YOK."""
        page = self.page
        if page is None:
            return
        page.window.visible = True
        page.update()

    async def show_focused(self) -> None:
        """G: odagi ISTEYEREK al."""
        page = self.page
        if page is None:
            return
        page.window.focused = True
        page.window.visible = True
        page.update()
        await page.window.to_front()

    def show_unfocused(self) -> None:
        """C: Flet'in kendi bayragi."""
        page = self.page
        if page is None:
            return
        page.window.focused = False
        page.window.visible = True
        page.update()

    def hide(self) -> None:
        page = self.page
        if page is None:
            return
        page.window.visible = False
        page.update()


def wait_for_window(title: str = TITLE) -> int:
    """Flet istemcisi ayaga kalkip pencereyi acana kadar bekler."""
    deadline = time.monotonic() + BOOT_TIMEOUT
    while time.monotonic() < deadline:
        hwnd = win.find_window(title=title)
        if hwnd:
            return hwnd
        time.sleep(0.1)
    return 0


def sample(seconds: float = SAMPLE_SECONDS) -> list[tuple[float, int]]:
    """Odak degisimlerini (saniye, hwnd) olarak dokur -- ilk deger dahil."""
    start = time.monotonic()
    changes: list[tuple[float, int]] = [(0.0, win.foreground_window())]
    while time.monotonic() - start < seconds:
        time.sleep(SAMPLE_STEP)
        current = win.foreground_window()
        if current != changes[-1][1]:
            changes.append((time.monotonic() - start, current))
    return changes


def report(name: str, target: int, flet_hwnd: int, changes: list[tuple[float, int]]) -> str:
    """Bir senaryonun sonucu: odak hedefte kaldi mi, kaldiysa ne zaman
    gitti ve nereye."""
    shown = bool(user32.IsWindowVisible(flet_hwnd))
    if changes[0][1] != target:
        # Baslangic bozuk: hedef odakta degilken olculen sey Flet degil.
        return f"--- {name}\n    OLCULEMEDI: baslangicta odak {describe(changes[0][1])}"
    last = changes[-1][1]
    stolen = [(at, hwnd) for at, hwnd in changes[1:] if hwnd == flet_hwnd]
    lines = [f"--- {name}"]
    for at, hwnd in changes:
        lines.append(f"    {at:5.2f}s  {describe(hwnd)}")
    if stolen:
        lines.append(f"    SONUC: odak CALINDI ({stolen[0][0]:.2f}s sonra)")
    elif last != target:
        lines.append(
            "    SONUC: odak hedeften gitti ama Flet'e de GITMEDI "
            "-- araya baska uygulama girdi, olcum KIRLI"
        )
    else:
        lines.append("    SONUC: odak HEDEFTE KALDI")
    # "Odak kalmis" demek ancak pencere GERCEKTEN gorunduyse bir sey
    # anlatir: gorunmeyen pencere zaten odak calmaz.
    lines.append(f"    (flet penceresi gorunur mu: {shown})")
    if not shown:
        lines.append("    OLCULEMEDI: pencere gorunmedi")
    return "\n".join(lines)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)  # FletEngine bir QObject; ornek gerekiyor
    _ = app

    print("hedef pencere aciliyor...")
    target_proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "probes.focus_target"]
    )
    target = 0
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline and not target:
        target = win.find_window(title=TARGET_TITLE)
        time.sleep(0.1)
    if not target:
        print("hedef pencere acilmadi -- olcum yapilamadi")
        target_proc.terminate()
        return 1
    print(f"hedef pencere: {describe(target)}")

    probe = Probe()
    probe.engine.start()
    flet_hwnd = wait_for_window()
    if not flet_hwnd:
        print("Flet penceresi bulunamadi -- olcum yapilamadi")
        probe.engine.stop()
        return 1
    print(f"flet penceresi: {describe(flet_hwnd)}\n")

    out: list[str] = []

    def prepare() -> bool:
        """Her senaryo ayni yerden basliyor: pencere gizli, odak hedefte.

        Odak hedefe DONMEZSE senaryo olculmez: kirli olcum yanlis karar
        verdirir (ilk denemede tam bu oldu -- araya baska bir uygulama
        girdi ve dort senaryo bosa gitti).
        """
        probe.engine.call(probe.hide)
        time.sleep(0.5)
        for _ in range(3):
            if force_focus(target):
                time.sleep(0.4)
                return True
            time.sleep(0.3)
        print(f"UYARI: odak hedefe donmedi -- onde: {describe(win.foreground_window())}")
        return False

    def run(name: str, show: Callable[[], None]) -> None:
        """Senaryoyu TEMIZ bir olcum cikana kadar dener."""
        line = ""
        for turn in range(TRIES):
            if not prepare():
                continue
            show()
            line = report(name, target, flet_hwnd, sample())
            if "OLCULEMEDI" not in line and "KIRLI" not in line:
                out.append(line if turn == 0 else f"{line}\n    ({turn + 1}. deneme)")
                return
        out.append(line or f"--- {name}\n    OLCULEMEDI: odak hedefe hic donmedi")

    # ---- A: varsayilan yol -- panellerimizin BUGUN yaptigi sey
    run(
        "A  varsayilan (visible + to_front)",
        lambda: probe.engine.call(probe.show_default),
    )

    # ---- B: to_front yok
    run("B  to_front YOK (yalniz visible)", lambda: probe.engine.call(probe.show_no_front))

    # ---- C: Flet'in focused bayragi
    run("C  window.focused = False", lambda: probe.engine.call(probe.show_unfocused))

    # ---- D: Win32 yolu (Flet'e hic sormadan, pencere tutamagi uzerinden)
    style = user32.GetWindowLongW(flet_hwnd, GWL_EXSTYLE)

    def show_noactivate() -> None:
        user32.SetWindowLongW(flet_hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        user32.ShowWindow(flet_hwnd, SW_SHOWNOACTIVATE)

    def hide_win32() -> None:
        user32.ShowWindow(flet_hwnd, SW_HIDE)

    probe.engine.call(probe.show_no_front)  # Flet tarafi "gorunur" sansin
    time.sleep(0.5)
    hide_win32()
    run("D  WS_EX_NOACTIVATE + SW_SHOWNOACTIVATE", show_noactivate)
    user32.SetWindowLongW(flet_hwnd, GWL_EXSTYLE, style)

    # ---- E: odagi geri verme
    prepare()
    probe.engine.call(probe.show_default)
    time.sleep(0.8)
    before = win.foreground_window()
    ok = force_focus(target)
    changes = sample(1.0)
    out.append(
        "--- E  odagi GERI VERME (A'dan sonra SetForegroundWindow)\n"
        f"    geri vermeden once: {describe(before)}\n"
        f"    zorla geri verme basarili mi: {ok}\n"
        + "\n".join(f"    {at:5.2f}s  {describe(hwnd)}" for at, hwnd in changes)
        + f"\n    SONUC: {'odak GERI GELDI' if changes[-1][1] == target else 'odak geri GELMEDI'}"
    )

    # ---- G: odagi ALMA (array_filter / quick_panel icin gerekli)
    run("G  window.focused = True + to_front", lambda: probe.engine.call(probe.show_focused))

    # ---- H: odagi Flet penceresine ZORLA vermek. G calismadiysa tek
    # kalan yol bu: cagriyi BIZIM surecimiz yapiyor (Windows odak
    # kuralinda "son girdiyi alan surec" ayricalikli).
    if prepare():
        probe.engine.call(probe.show_default)
        time.sleep(0.6)
        forced = force_focus(flet_hwnd)
        time.sleep(0.3)
        where = win.foreground_window()
        out.append(
            "--- H  odagi Flet penceresine ZORLAMA\n"
            f"    zorlama basarili mi: {forced}\n"
            f"    odak simdi: {describe(where)}\n"
            f"    SONUC: {'Flet penceresi odagi ALDI' if where == flet_hwnd else 'ALAMADI'}"
        )
    else:
        out.append("--- H  odagi ZORLAMA\n    OLCULEMEDI: odak hedefe donmedi")

    # ---- F: ILK ACILIS. A-E hep ayakta bir pencereyi gosteriyor;
    # gercekte panelin ILK acilisi `flet.exe`yi ayaga kaldiriyor ve yeni
    # surecin penceresi Windows'tan odak izni alabilir. Her deneme YENI
    # bir surec baslatiyor: ikinci kez "ilk acilis" olmuyor.
    boots: list[Probe] = []
    for turn in range(3):
        boot = Probe(f"{TITLE_BOOT} {turn}")
        boots.append(boot)
        if not prepare():
            continue
        start = time.monotonic()
        boot.engine.start()
        changes = [(0.0, win.foreground_window())]
        boot_hwnd = 0
        while time.monotonic() - start < 12.0:
            time.sleep(SAMPLE_STEP)
            if not boot_hwnd:
                boot_hwnd = win.find_window(title=boot.title)
            current = win.foreground_window()
            if current != changes[-1][1]:
                changes.append((time.monotonic() - start, current))
        lines = ["--- F  ILK ACILIS (flet.exe sifirdan)"]
        lines += [f"    {at:5.2f}s  {describe(hwnd)}" for at, hwnd in changes]
        stolen = [at for at, hwnd in changes[1:] if boot_hwnd and hwnd == boot_hwnd]
        dirty = changes[0][1] != target or (
            not stolen and changes[-1][1] != target
        )
        if stolen:
            lines.append(f"    SONUC: odak CALINDI ({stolen[0]:.2f}s sonra)")
        elif dirty:
            lines.append("    SONUC: OLCULEMEDI -- araya baska uygulama girdi")
        else:
            lines.append("    SONUC: odak HEDEFTE KALDI")
        lines.append(f"    (yeni pencere acildi mi: {bool(boot_hwnd)})")
        if turn:
            lines.append(f"    ({turn + 1}. deneme)")
        if not dirty:
            out.append("\n".join(lines))
            break
    else:
        out.append("--- F  ILK ACILIS\n    OLCULEMEDI: temiz olcum alinamadi")

    print("\n".join(out))
    for boot in boots:
        boot.engine.stop()
    probe.engine.stop()
    target_proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
