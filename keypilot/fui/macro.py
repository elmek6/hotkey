"""Makro kayit ekrani -- ui/macro_view.py'nin Flet karsiligi.

YEDINCI PANEL, ASAMA 2'NIN BASI. Asama 1'in alti paneli ya bilgi
GOSTERIYOR ya da bir dugmeye basildigini haber veriyordu; burada ilk kez
panel DISARIDAN gelen bir durumu yaziyor: kayit basladi, oynatma surdu,
makro diske gitti. Durumu `macro_ctl.py` biliyor, panel yalnizca
gosteriyor -- Qt surumunun docstring'indeki kural aynen gecerli, EKRAN
KARAR VERMEZ.

DURUM HANGI THREAD'DEN GELIYOR. `set_state` Qt'nin ANA thread'inde
cagriliyor (oynatma ayri thread'de kosuyor ama sonucu `MacroController`
bir sinyalle ana thread'e donduruyor -- macro_ctl.py `finished`). Yani
buradaki kural oteki panellerdekiyle ayni: alanlar ana thread'de
guncelleniyor, CIZIM `engine.call` ile Flet dongusune birakiliyor.

    macro_ctl (ana thread)  -> set_state()     alanlari yaz
                            -> engine.call     -> _draw (Flet thread'i)
    dugmeler (Flet thread)  -> Signal          -> macro_ctl (ana thread)
                            -> ask_qt          -> disk (ad yazma, notepad)

`name` ARTIK DUZ BIR OZELLIK. Qt surumunde `macro_ctl.py` panelin icine
uzanip `self.view.name.text()` diyordu, yani dogrudan bir `QLineEdit`e.
Flet'te o widget Flet thread'ine ait ve baska thread'den okunmamali;
panel adi `name` diye duz bir `str` olarak sunuyor, Flet tarafi her
tusta onu tazeliyor. Cagiran dosya da degisti (slot kutusunda da boyle
olmustu, bkz. flet-plan.md).

Qt surumunden farklar (bilerek):

    "Hazir" zamanlayicisi  Qt'de 200 ms'lik bir `QTimer` bosta durum
                           yazisini "Hazir"a cekiyordu. Burada durum
                           yalnizca DEGISTIGINDE yaziliyor (`set_state`
                           bosta zaten "Hazir" diyor): saniyede bes kez
                           bedava cizim yapmanin Flet'te bedeli var
                           (bkz. fui/monitor.py olcumleri).
    konum                  Qt kutuyu imlecin ekranina ortaliyordu
                           (`ui/place.py`); Flet penceresi kendi
                           varsayilan yerinde aciliyor.
    olcu                   Genislik Qt'den (430 -> 520: Material
                           denetimleri kalin), yukseklik yeniden
                           olculdu -- bkz. **PENCERE OLCUSU kurali**.

PENCERE KAPANMIYOR, GIZLENIYOR (oteki paneller gibi). Kapatmak Qt'de
"kaydi durdur ve yaz" demekti; o davranis KORUNDU -- `_hide` once
`stop_requested` yayiyor.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

import flet as ft
from PySide6.QtCore import QObject, Signal

from keypilot import macro
from keypilot.fui import theme
from keypilot.fui.engine import FletEngine

#: Qt `resize(430, 250)`. Genislik Qt'den buyutuldu (Material denetimleri
#: kalin), yukseklik iki onay kutusu + uc dugme sirasi + durum satirina
#: gore olculdu.
SIZE = (520, 400)

TEXT_SIZE = 13

#: Tek satirlik denetimlerin yuksekligi. Verilmezse Material varsayilani
#: ~48 piksel ve pencere gozle gorulur uzuyor (PENCERE OLCUSU kurali).
FIELD_H = 38

#: Giris kutusu ve acilir listelerin ortak gorunumu -- Qt tarafinda bunu
#: `keypilot/theme.py`nin stylesheet'i yapiyordu.
FIELD_STYLE = {
    "dense": True,
    "text_size": 12,
    "color": theme.FG,
    "bgcolor": theme.FIELD_BG,
    "border_color": theme.BORDER,
    "border_radius": 4,
    "content_padding": 8,
}


class MacroPanel(QObject):
    """Kayit ekrani. Qt'deki `MacroView` ile ayni sinyaller."""

    #: (slot, kayit turu) -- kayda basildi
    record_requested = Signal(int, str)
    #: (slot, ad) -- durdur ve kaydet
    stop_requested = Signal(int, str)
    #: slot -- oynat
    play_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        #: ANA THREAD'IN okudugu alanlar. `macro_ctl.py` bunlara bakiyor;
        #: Flet tarafi yaziyor ama yazilan seyler bolunmez (int, str,
        #: bool) -- kilide gerek yok, `fui/monitor.py`deki `_paused` ile
        #: ayni gerekce.
        self._slot = 1
        self.name = ""
        self._kind = str(macro.RECORD_TYPE.get())

        #: Pencere acik mi. Qt'de `isVisible()` idi; burada duz bayrak.
        self.visible = False

        #: Cizilecek durum -- `set_state` yaziyor, `_draw` okuyor.
        self._recording = False
        self._playing = False
        self._status_text = "Hazir"
        #: (slot, etiket) listesi. DISKTEN okunuyor, yani ana thread'de:
        #: `reload` her acilista ve her bos duruma dususte cagriliyor.
        self._slots_data: tuple[tuple[int, str], ...] = ()

        self._engine = FletEngine(self._build)
        self._page: ft.Page | None = None
        self._slots: ft.Dropdown | None = None
        self._types: ft.Dropdown | None = None
        self._name: ft.TextField | None = None
        self._record_button: ft.ElevatedButton | None = None
        self._play_button: ft.ElevatedButton | None = None
        self._record_window: ft.Checkbox | None = None
        self._activate_window: ft.Checkbox | None = None
        self._status: ft.Text | None = None

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def open(self) -> None:
        """Pencereyi ac/one getir. Qt'de `show`+`raise_`+`activateWindow`."""
        self.visible = True
        self.reload()
        if self._engine.page is None:
            # Sayfa yok: thread'i baslat, `_build` bu degerlerle cizecek.
            # Beklemiyoruz -- ana thread saniyelerce donarsa tepsi takilir.
            self._engine.start()
            return
        self._engine.call(self._show_now)

    def reload(self) -> None:
        """Slot listesini DISKTEN tazeler; secim KORUNUR (ana thread).

        Qt surumunde bu is dogrudan `QComboBox`a yaziyordu; burada
        yalnizca alanlar dolduruluyor, cizimi `_draw` yapiyor.
        """
        self._slots_data = tuple(macro.iter_slots())
        if not any(slot == self._slot for slot, _label in self._slots_data):
            self._slot = self._slots_data[0][0] if self._slots_data else 1
        self.name = macro.slot_name(self._slot)

    def slot(self) -> int:
        return self._slot

    @property
    def status(self) -> str:
        """Durum satirinin METNI. Qt'de bu bir `QLabel`di ve disaridan
        `status.text()` diye okunuyordu (testler); denetim Flet
        thread'ine ait oldugu icin metin duz bir alandan veriliyor."""
        return self._status_text

    def set_state(self, recording: bool, playing: bool, note: str = "") -> None:
        """Denetleyici durumu degistikce cagirir (ANA THREAD).

        Qt surumuyle ayni sira: bayraklar, not, sonra bostaysa `reload`.
        """
        self._recording, self._playing = recording, playing
        if note:
            self._status_text = note
        if not recording and not playing:
            self.reload()
            if not note:
                # Qt'de bu isi 200 ms'lik zamanlayici yapiyordu.
                self._status_text = "Hazir"
        self._engine.call(self._draw)

    def close(self) -> None:
        """Pencereyi gizle. `app.py` `_shutdown` bunu cagiriyor.

        Qt'de `close()` `closeEvent`i tetikliyor, o da kaydi durduruyordu;
        ayni sira burada da korunuyor. `_hide`den farki cizim yolu: bu
        cagri ANA THREAD'den geliyor, gizleme `call` ile Flet dongusune
        birakiliyor ve disk isi zaten dogru thread'de.
        """
        self.visible = False
        self._engine.call(self._hide_now)
        self._commit_name()
        self.stop_requested.emit(self._slot, self.name)

    def shutdown(self) -> None:
        """Program kapaniyor: Flet istemcisini (`flet.exe`) gercekten kapat."""
        self._engine.stop()

    # -- Qt thread'i: disk (`FletEngine.ask_qt` ile) -------------------------

    def _commit_name(self) -> None:
        """Ad kutusundaki degeri slot dosyasina yaz. DISK isi -- Flet
        dongusunde kosmamali."""
        macro.set_slot_name(self._slot, self.name)

    def _load_name(self) -> None:
        """Slot degisti: yeni slotun adini diskten oku ve kutuya yaz."""
        self.name = macro.slot_name(self._slot)
        self._engine.call(self._draw)

    def _open_file(self) -> None:
        path = macro.slot_path(self._slot)
        if not path.exists():
            self._status_text = f"Dosya yok: {path.name}"
            self._engine.call(self._draw)
            return
        subprocess.Popen(["notepad.exe", str(path)])

    # -- Flet thread'i: kurulum ---------------------------------------------

    def _build(self, page: ft.Page) -> None:
        """Sayfa hazir. Denetimleri kur ve hemen goster (FLET thread'i)."""
        self._page = page
        page.title = "⏺️ Macro Recorder"
        page.bgcolor = theme.BG
        page.padding = 12
        page.window.width, page.window.height = SIZE
        # Kapatma DUSMESIN: `ft.run` doner, thread olur ve bir sonraki
        # acilis Flet'in baslama suresini yeniden odetirdi.
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        self._slots = ft.Dropdown(
            options=[],
            on_select=lambda _e: self._on_slot_change(),
            expand=True,
            height=FIELD_H,
            **FIELD_STYLE,
        )
        self._types = ft.Dropdown(
            options=[
                ft.DropdownOption(key=kind, text=macro.RECORD_TYPE.label_for(kind))
                for kind in macro.REC_TYPES
            ],
            value=self._kind,
            on_select=lambda _e: self._on_type_change(),
            width=150,
            height=FIELD_H,
            **FIELD_STYLE,
        )
        self._name = ft.TextField(
            hint_text="Kaydin adi (dosyanin ilk satirinda durur)",
            # Her tusta ANA THREAD'in okudugu alan tazeleniyor: kaydi
            # durduran `macro_ctl.py` adi buradan aliyor.
            on_change=self._on_name_change,
            # Qt'de `editingFinished` -- odak kaybi ya da Enter diske
            # yaziyordu.
            on_blur=lambda _e: self._engine.ask_qt(self._commit_name),
            on_submit=lambda _e: self._engine.ask_qt(self._commit_name),
            expand=True,
            height=FIELD_H,
            **FIELD_STYLE,
        )
        self._record_button = self._button("\U0001f6d1 Kaydet", self._on_record)
        self._play_button = self._button("▶️ Oynat", self._on_play)
        self._record_window = self._option(macro.RECORD_WINDOW)
        self._activate_window = self._option(macro.ACTIVATE_WINDOW)
        self._status = ft.Text(self._status_text, color=theme.MUTED, size=TEXT_SIZE)

        page.controls.append(
            ft.Column(
                controls=[
                    ft.Row(controls=[self._slots, self._types], spacing=8),
                    ft.Row(
                        controls=[
                            ft.Text("Ad:", color=theme.MUTED, size=TEXT_SIZE),
                            self._name,
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        controls=[
                            self._record_button,
                            self._button("⏹️ Durdur", self._on_stop),
                            self._play_button,
                        ],
                        spacing=8,
                    ),
                    self._record_window,
                    self._activate_window,
                    self._status,
                    ft.Row(
                        controls=[
                            self._button(
                                "\U0001f4dd Not defterinde ac",
                                lambda: self._engine.ask_qt(self._open_file),
                                width=200,
                            ),
                            self._button("Kapat", self._hide),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=10,
            )
        )
        self._engine.call(self._show_now)

    def _button(
        self, label: str, action: Callable[[], None], width: int = 150
    ) -> ft.ElevatedButton:
        return ft.ElevatedButton(
            content=ft.Text(label, size=TEXT_SIZE, color=theme.FG),
            width=width,
            height=34,
            bgcolor=theme.FIELD_BG,
            on_click=lambda _e: action(),
        )

    def _option(self, item) -> ft.Checkbox:
        """Ayarin KENDISI degistiriliyor -- Qt surumundeki gerekce aynen:
        iki yerde iki ayri bayrak tutmak, birinden degistirince otekinin
        yalan soylemesi demek. Ayar yazma DISK isi, `ask_qt` ile."""
        return ft.Checkbox(
            label=item.name,
            tooltip=item.desc,
            value=bool(item.get()),
            on_change=lambda e, s=item: self._engine.ask_qt(
                lambda v=bool(e.control.value): s.set(v)
            ),
            label_style=ft.TextStyle(color=theme.FG, size=TEXT_SIZE),
        )

    # -- Flet thread'i: cizim -----------------------------------------------

    async def _show_now(self) -> None:
        """Pencereyi goster ve one getir (FLET thread'i)."""
        page = self._page
        if page is None:
            return
        self._draw()
        page.window.visible = True
        page.update()
        await page.window.to_front()

    def _hide_now(self) -> None:
        page = self._page
        if page is None:
            return
        page.window.visible = False
        page.update()

    def _draw(self) -> None:
        """Alanlari denetimlere yaz ve ekrana ciz. Cizime giren TEK yol."""
        page = self._page
        if page is None or self._slots is None or self._name is None:
            return
        busy = self._recording or self._playing

        self._slots.options = [
            ft.DropdownOption(key=str(number), text=label)
            for number, label in self._slots_data
        ]
        self._slots.value = str(self._slot)
        self._slots.disabled = busy
        if self._types is not None:
            self._types.value = self._kind
            self._types.disabled = busy
        self._name.value = self.name
        if self._record_button is not None:
            self._record_button.disabled = self._playing
            self._record_button.content = ft.Text(
                "⏺️ Kayitta" if self._recording else "\U0001f6d1 Kaydet",
                size=TEXT_SIZE,
                color=theme.FG,
            )
        if self._play_button is not None:
            self._play_button.disabled = busy
        if self._record_window is not None:
            self._record_window.value = bool(macro.RECORD_WINDOW.get())
        if self._activate_window is not None:
            self._activate_window.value = bool(macro.ACTIVATE_WINDOW.get())
        if self._status is not None:
            self._status.value = self._status_text
        page.update()

    # -- Flet thread'i: olaylar ---------------------------------------------

    def _on_name_change(self, event: ft.Event) -> None:
        # Yalnizca ana thread'in okudugu alan tazeleniyor: cizim YOK,
        # diske yazma YOK (o odak kaybinda).
        self.name = event.control.value or ""

    def _on_slot_change(self) -> None:
        if self._slots is None:
            return
        self._slot = int(self._slots.value or 1)
        # Ad DISKTEN geliyor -- Qt tarafinda okunup geri ciziliyor.
        self._engine.ask_qt(self._load_name)

    def _on_type_change(self) -> None:
        if self._types is None:
            return
        self._kind = str(self._types.value or macro.KEY)

    def _on_record(self) -> None:
        """Qt surumuyle ayni: kayittayken bu dugme DURDURUYOR."""
        if self._recording:
            self._on_stop()
            return
        slot, kind, name = self._slot, self._kind, self.name

        def start() -> None:
            macro.set_slot_name(slot, name)
            macro.RECORD_TYPE.set(kind)
            self.record_requested.emit(slot, kind)

        # Uc is de ana thread'de: ikisi diske yaziyor, ucuncusu kaydi
        # baslatan denetleyiciyi cagiriyor.
        self._engine.ask_qt(start)

    def _on_stop(self) -> None:
        """AHK'de durdurma yalnizca panik tusuydu; burada dugme de var --
        oynatma sirasinda klavye kullanicinin elinden ciktigi icin fareyle
        ulasilabilen bir cikis lazim (Esc yine calisiyor)."""
        self.stop_requested.emit(self._slot, self.name)

    def _on_play(self) -> None:
        slot, name = self._slot, self.name

        def start() -> None:
            macro.set_slot_name(slot, name)
            self.play_requested.emit(slot)

        self._engine.ask_qt(start)

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        if event.key == "Escape":
            self._hide()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self._hide()

    def _hide(self) -> None:
        """Pencereyi gizle. Qt'nin `closeEvent`i ile ayni is: adi yaz,
        suren kaydi durdur, sonra gizle.

        `close()` ile ayni yol: `app.py` cikista bunu cagiriyor ve
        yarim kalan kaydin diske yazilmasi Qt surumunun davranisiydi.
        """
        self.visible = False
        self._hide_now()
        slot, name = self._slot, self.name
        self._engine.ask_qt(lambda: macro.set_slot_name(slot, name))
        self.stop_requested.emit(slot, name)
