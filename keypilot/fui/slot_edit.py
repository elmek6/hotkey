"""Slot duzenleme kutusu -- ui/slot_edit.py'nin Flet karsiligi.

UCUNCU TASINAN PANEL. Onceki ikisinde bilgi DISARI cikiyordu (tablo
gosterildi, dugmeye basildi); burada ilk kez ICERI geliyor ve diske
yaziliyor: kutuya yazilan ad ve icerik `slots_ctl.py` uzerinden
`SlotStore`a gidiyor.

KULLANIM SEKLI DEGISTI. Qt surumu her acilista YENI bir pencere kuruyor,
kapaninca yok ediyordu (`WA_DeleteOnClose`). Flet'te bu her seferinde
3.5 saniye demek -- istemci (`flet.exe`) bastan ayaga kalkardi. Burada
panel BIR KEZ kurulup yasiyor ve `show_slot` ile guncelleniyor; pencere
kapanmiyor, gizleniyor. Bu yuzden arayuz de degisti:

    Qt      SlotEditDialog(index, name, content, proposed)  + accepted/values()
    Flet    show_slot(index, name, content, proposed)       + saved(ad, icerik)

`accepted` + `values()` ikilisi tek sinyale indi: pencere yasadigi icin
"kapanmadan once degerleri oku" diye bir sira kalmadi.

SIFRE KURALI BURADA DEGIL. Sifre slotunda kutunun BOS acilmasi
`slots_ctl.py`nin isi (`proposed` orada hesaplaniyor); panel yalnizca
eski degerin MASKELI gosterilmesini biliyor.

Qt surumunden farklar (bilerek):

    konum       Qt kutuyu imlecin bulundugu ekranin ortasina aciyordu
                (`ui/place.py`). Flet'te pencere kendi varsayilan yerine
                aciliyor -- konumu elle vermek fiziksel/mantiksal piksel
                cevrimi demek ve bu adimin disinda.
    olcu        Qt `adjustSize` ile 380-520 piksel arasinda kendini
                ayarliyordu; burada olcu sabit.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
from PySide6.QtCore import QObject, Signal

from keypilot.fui import theme
from keypilot.fui.engine import FletEngine
from keypilot.store import MASK, PASSWORD_SLOT

# Saf metin isi, Qt'ye bagli degil (`ui/preview.py` yalnizca `html`
# kullaniyor). O dosya silinirken buraya tasinacak; gecis suresince tek
# kaynak orasi.
from keypilot.ui.preview import shorten

#: Eski deger etiketinde gosterilen en fazla karakter. Amac hatirlatmak,
#: tam metni gostermek degil -- uzun icerik kutuyu ekran boyuna cikariyordu.
OLD_LIMIT = 160

#: Yeni deger kutusunun satir sayisi. Slot icerigi cogu zaman tek satir;
#: daha buyugu bos yer demek. Qt'de piksel cinsindendi (`VALUE_HEIGHT`).
VALUE_LINES = 3

#: Qt `setMinimumWidth(380)` / `setMaximumWidth(520)` arasi bir olcu.
SIZE = (480, 330)

#: Form etiketleri sutunu -- QFormLayout'un sol sutununun karsiligi.
LABEL_WIDTH = 40

#: Iki giris kutusunun ortak gorunumu -- ui/slot_edit.py'de bunu
#: `keypilot/theme.py`nin stylesheet'i yapiyordu.
FIELD_STYLE = {
    "dense": True,
    "text_size": 12,
    "color": theme.FG,
    "bgcolor": theme.FIELD_BG,
    "border_color": theme.BORDER,
    "border_radius": 4,
    "content_padding": 8,
    "expand": True,
}


def old_value(index: int, content: str) -> str:
    """"eski" satirinda ne yazacagi. Bos icerikte BOS doner -- arayan
    `(bos)` yaziyor, Qt surumundeki `shown or "(bos)"` ile ayni."""
    if index == PASSWORD_SLOT and content:
        # Sifre slotunun eski degeri EKRANA CIKMAZ; burada olma sebebi
        # slotun dolu oldugunu gostermek.
        return MASK
    return shorten(" ".join(content.split()), OLD_LIMIT)


def form_row(label: str, field: ft.Control) -> ft.Row:
    """QFormLayout'un bir satiri: solda etiket, sagda alan."""
    return ft.Row(
        controls=[
            ft.Text(label, color=theme.MUTED, size=12, width=LABEL_WIDTH),
            field,
        ],
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


class SlotEditPanel(QObject):
    """Ad + eski deger + yeni deger. Kaydedilince `saved` yayilir."""

    #: (ad, icerik) -- Kaydet'e basildi. Hangi slot oldugu BURADA YOK:
    #: paneli acan `slots_ctl.py` hedefi kendi tutuyor, cunku ayni anda
    #: tek kutu acik. Alicisi Qt'nin ana thread'inde oldugu icin sinyal
    #: kendiliginden kuyruga alinir -- diske yazan kod Flet thread'inde
    #: kosmamali.
    saved = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        #: (index, ad, eski, yeni) -- TEK DEMET olarak tutuluyor: demet
        #: atamasi GIL altinda bolunmez, yani Flet thread'i ya eski ya
        #: yeni degerleri gorur, yarisini gormesi mumkun degil.
        self._pending: tuple[int, str, str, str] = (0, "", "", "")
        self._engine = FletEngine(self._build)
        # Denetimler FLET thread'inde, `_build` icinde kuruluyor; Qt
        # tarafindan yalnizca `show_slot` uzerinden dokunuluyor.
        self._page: ft.Page | None = None
        self._name: ft.TextField | None = None
        self._old: ft.Text | None = None
        self._value: ft.TextField | None = None

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def show_slot(self, index: int, name: str, content: str, proposed: str) -> None:
        """Kutuyu bu slotla ac. `content` slotun ESKI degeri, `proposed`
        kutuya hazir yazilan yeni deger (cogu zaman pano)."""
        self._pending = (index, name, old_value(index, content), proposed)
        if self._engine.page is None:
            # Sayfa yok: thread'i baslat, `_build` bu degerlerle cizecek.
            # Beklemiyoruz -- ana thread 3.5 saniye donarsa tepsi takilir.
            self._engine.start()
            return
        self._engine.call(self._show_now)

    def shutdown(self) -> None:
        """Program kapaniyor: Flet istemcisini (`flet.exe`) gercekten kapat."""
        self._engine.stop()

    # -- Flet thread'i ------------------------------------------------------

    def _build(self, page: ft.Page) -> None:
        """Sayfa hazir. Denetimleri kur ve hemen goster (FLET thread'i)."""
        self._page = page
        page.bgcolor = theme.BG
        page.padding = 12
        page.window.width, page.window.height = SIZE
        # Kapatma DUSMESIN: `ft.run` doner, thread olur ve bir sonraki
        # acilis 3.5 saniyeyi yeniden odetirdi. Kapatmayi yakalayip
        # pencereyi gizliyoruz.
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        self._name = ft.TextField(
            # Imlec ad kutusunda: en sik degisen alan o, icerik cogu
            # zaman panodan hazir geliyor.
            autofocus=True,
            # Qt'de QDialogButtonBox'in varsayilan dugmesi Save'di, yani
            # ad kutusunda Enter kaydediyordu.
            on_submit=lambda _e: self._save(),
            **FIELD_STYLE,
        )
        self._old = ft.Text("", color=theme.MUTED, size=12, selectable=True)
        self._value = ft.TextField(
            multiline=True,
            min_lines=VALUE_LINES,
            max_lines=VALUE_LINES,
            **FIELD_STYLE,
        )

        page.controls.append(
            ft.Column(
                controls=[
                    form_row("ad", self._name),
                    form_row("eski", self._old),
                    form_row("yeni", self._value),
                    ft.Row(
                        # Windows sirasi: once Kaydet, sonra Iptal.
                        controls=[
                            self._button("Kaydet", self._save),
                            self._button("Iptal", self._hide_now),
                        ],
                        alignment=ft.MainAxisAlignment.END,
                        spacing=8,
                    ),
                ],
                spacing=8,
            )
        )
        self._engine.show_on_build(self._show_now)

    def _button(self, label: str, action: Callable[[], None]) -> ft.ElevatedButton:
        return ft.ElevatedButton(
            content=ft.Text(label, size=13, color=theme.FG),
            width=96,
            height=34,
            bgcolor=theme.FIELD_BG,
            on_click=lambda _e: action(),
        )

    async def _show_now(self) -> None:
        """Kutuyu bekleyen slotla doldur ve one getir (FLET thread'i).

        `to_front` ve `focus` bu surumde coroutine: beklenmezlerse
        pencere arkada kalir ve ad kutusu odagi almaz -- hicbir hata
        vermeden.
        """
        page = self._page
        if page is None or self._name is None or self._old is None or self._value is None:
            return
        index, name, old, proposed = self._pending
        # Qt: `setWindowTitle(f"Slot {index % 10}")` -- 10. slot "Slot 0".
        page.title = f"Slot {index % 10}"
        self._name.value = name
        self._name.hint_text = f"Slot {index}"
        self._old.value = old or "(bos)"
        self._value.value = proposed
        page.window.visible = True
        page.update()
        await page.window.to_front()
        await self._name.focus()

    # -- cikan yollar -------------------------------------------------------

    def _save(self) -> None:
        """Kaydet: ONCE pencereyi gizle, SONRA sinyali gonder (fui/pause.py
        ile ayni sira -- sinyalin alicisi ipucu gosteriyor)."""
        if self._name is None or self._value is None:
            return
        name = self._name.value or ""
        content = self._value.value or ""
        self._hide_now()
        self.saved.emit(name, content)

    def _hide_now(self) -> None:
        """Iptal: pencereyi gizle, SINYAL GONDERME. Qt'deki `reject`."""
        page = self._page
        if page is None:
            return
        page.window.visible = False
        page.update()

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        if event.key == "Escape":
            self._hide_now()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        """X: Qt'de de kutuyu kapatmak Iptal demekti."""
        if event.type == ft.WindowEventType.CLOSE:
            self._hide_now()
