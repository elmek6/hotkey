"""Duraklatma penceresi -- ui/pause.py'nin Flet karsiligi.

IKINCI TASINAN PANEL. Kisayol haritasindan farki DISARI CIKAN YOL: orada
tek olay vardi (pencere kapandi), burada dort ayri komut var ve ucu
programi yeniden baslatiyor ya da kapatiyor. Yani Flet->Qt yonunun
gercek testi bu panel.

Qt surumunun tek pencere numarasi `WindowStaysOnTopHint`ti; Flet'te
karsiligi `page.window.always_on_top`. Baska bir sey kaybolmuyor.

KAPANMA SIRASI KORUNDU. Qt surumunde dugme once pencereyi kapatiyor,
sonra sinyali gonderiyordu: "Cikis" sinyali programi kapattigi icin ters
sirada pencere ekranda ASILI kaliyordu. Burada da once gizleniyor sonra
sinyal atiliyor -- ustelik sinyal Qt'nin kuyruguna giriyor, yani gizleme
kesinlikle once isliyor.

X ve Esc `resume` demek: AHK'de de pencere kapaninca `Suspend(0)`
calisiyordu. Dugmeyle kapanista bu YANLIS olurdu (iki sinyal birden
giderdi) -- `visible = False` pencere kapatma olayini tetiklemedigi icin
ayrica bir bayrak tutmaya gerek yok; Qt surumundeki `_closing` bayragi
burada gereksiz.
"""

from __future__ import annotations

import flet as ft
from PySide6.QtCore import QObject, Signal, SignalInstance

from keypilot.fui import theme
from keypilot.fui.engine import FletEngine

#: (etiket, sinyal adi) -- sira ui/pause.py ile ayni, o da AHK'den geldi.
BUTTONS = (
    ("▶️  Devam et", "resume"),
    ("\U0001f501  Kaydetmeden yeniden baslat", "restart_nosave"),
    ("\U0001f501  Yeniden baslat", "restart"),
    ("\U0001f6d1  Cikis", "exit"),
)

TITLE = "Program duraklatildi -- tuslar dokunulmadan geciyor."

#: Qt `adjustSize()` yapiyordu: kritik hata metni gelince pencere buyuyor.
#: Flet'te kendiliginden olmuyor, iki olcu elle veriliyor.
SIZE = (420, 300)
SIZE_CRITICAL = (460, 420)


class PausePanel(QObject):
    """Duraklatildi penceresi. Qt'deki `PauseDialog` ile ayni arayuz."""

    resume = Signal()
    restart_nosave = Signal()
    restart = Signal()
    exit_app = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._critical = ""
        self._engine = FletEngine(self._build)
        self._page: ft.Page | None = None
        self._message: ft.Text | None = None

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def show_paused(self, critical: str = "") -> None:
        """AHK `DialogPauseGui(criticalMsg)` -- kritik hata metni istege bagli."""
        self._critical = critical
        if self._engine.page is None:
            self._engine.start()
            return
        self._engine.call(self._show_now)

    def close(self) -> None:
        """Pencereyi gizle, SINYAL GONDERME.

        `app.py` `_shutdown` bunu cagiriyor. Kapanis sirasinda `resume`
        atmak duraklatmayi kaldirip kapanmakta olan programa is
        cikarirdi.
        """
        self._engine.call(self._hide_now)

    def shutdown(self) -> None:
        """Program kapaniyor: Flet istemcisini (`flet.exe`) gercekten kapat."""
        self._engine.stop()

    # -- Flet thread'i ------------------------------------------------------

    def _build(self, page: ft.Page) -> None:
        self._page = page
        page.title = "⏸️ KeyPilot durduruldu"
        page.bgcolor = theme.BG
        page.padding = 16
        # Qt: setWindowFlag(WindowStaysOnTopHint). Duraklatilmis programin
        # penceresi kaybolursa kullanici neden tuslarin calismadigini
        # bulamiyor.
        page.window.always_on_top = True
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        # Ornek uzerinden erisilince tip `SignalInstance` -- sinifin
        # uzerindeki `Signal` degil. `emit` yalnizca ilkinde var.
        signals: dict[str, SignalInstance] = {
            "resume": self.resume,
            "restart_nosave": self.restart_nosave,
            "restart": self.restart,
            "exit": self.exit_app,
        }
        buttons = [
            ft.ElevatedButton(
                content=ft.Text(label, size=13, color=theme.FG),
                height=38,
                bgcolor=theme.FIELD_BG,
                on_click=lambda _e, s=signals[name]: self._fire(s),
            )
            for label, name in BUTTONS
        ]
        self._message = ft.Text("", color=theme.DANGER, size=12, visible=False)

        page.controls.append(
            ft.Column(
                controls=[
                    ft.Text(TITLE, color=theme.MUTED, size=12),
                    *buttons,
                    self._message,
                ],
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )
        )
        self._engine.show_on_build(self._show_now)

    async def _show_now(self) -> None:
        page = self._page
        if page is None:
            return
        message = self._message
        if message is not None:
            message.visible = bool(self._critical)
            message.value = f"⚠ KRITIK HATA:\n{self._critical}" if self._critical else ""
        page.window.width, page.window.height = (
            SIZE_CRITICAL if self._critical else SIZE
        )
        page.window.visible = True
        page.update()
        await page.window.to_front()

    def _hide_now(self) -> None:
        page = self._page
        if page is None:
            return
        page.window.visible = False
        page.update()

    # -- cikan yollar -------------------------------------------------------

    def _fire(self, signal: SignalInstance) -> None:
        """Dugme: ONCE pencereyi gizle, SONRA sinyali gonder."""
        self._hide_now()
        signal.emit()

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        if event.key == "Escape":
            self._fire(self.resume)

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        """X: AHK'de de pencere kapaninca `Suspend(0)` calisiyordu."""
        if event.type == ft.WindowEventType.CLOSE:
            self._fire(self.resume)
