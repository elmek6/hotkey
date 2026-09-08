"""QR penceresi -- ui/qr_view.py'nin Flet karsiligi.

BESINCI TASINAN PANEL. Ilk kez pencerede RESIM var: her tus vurusunda
yeniden uretilen bir kare.

IKI YENI SEY VAR:

    dogan/olen denetim   Sablon secilince alanlar SIFIRDAN kuruluyor
                         (`_build_fields`). Onceki dort panelde
                         denetimler `_build` icinde bir kez kurulup
                         saklaniyordu; burada form sutununun icerigi
                         calisma aninda degisiyor. Kalibi bozmuyor:
                         denetimleri doguran her yol FLET thread'inde
                         (radyo dugmesi, slot tiklamasi, `_show_now`).
    resim                `ft.Image` ham baytlari dogrudan aliyor
                         (`src=bytes`), base64'e cevirmek gerekmiyor.
                         `filter_quality=NONE` SART: QR keskin kenar
                         ister, yumusatilmis kare telefonda okunmuyor
                         (Qt'de `FastTransformation` idi).

PLANDAKI 4a/4b BOLMESI KALKTI. Plan "PNG kaydetme ve panoya kopyalama
ayri bir adim olsun" diyordu, gerekcesi `ft.FilePicker`in servis olarak
kurulmasiydi. Adim 4'te (`fui/log_view.py`) gelen `_on_qt` kalibi bunu
gereksiz birakti: dosya kutusu da pano da ZATEN Qt tarafinda kosmali,
yani ikisi de birer satir. Pencere tek adimda tamamlandi.

    -> Bunun bedeli: dosya kutusu hala `QFileDialog`, yani Qt gidince
       yerine `ft.FilePicker` yazilmasi gerekecek. Plana yazildi.

Qt surumunden farklar (bilerek):

    pencere olcusu   Qt `adjustSize` ile icerige gore kendini
                     ayarliyordu. Burada olcu ELLE hesaplaniyor: taban +
                     alan sayisi (bkz. `window_height`). Sonuc ayni --
                     Wifi sablonu Metin'den yuksek bir pencere aciyor.
    goz dugmesi      Qt parola kutusunun yanina ayri bir dugme koyuyordu;
                     Flet'in `TextField`i bunu kendi tasiyor
                     (`can_reveal_password`).
    panoya kopyalama Qt ekrandaki 260 piksellik kucultulmus kareyi
                     kopyaliyordu; burada kare `scale=8` ile yeniden
                     uretiliyor (~280 piksel). Fark gozle gorunmez,
                     kopyalanan kare bir tik daha keskin.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QFileDialog

from keypilot import paths, qr
from keypilot.fui import theme
from keypilot.fui.engine import FletEngine
from keypilot.settings import SETTINGS
from keypilot.store import PASSWORD_SLOT, SlotStore, slot_display

# Saf metin isi (bkz. fui/slot_edit.py'deki ayni satir): `ui/preview.py`
# yalnizca `html` kullaniyor, Qt'ye bagli degil.
from keypilot.ui.preview import shorten

#: Ham icerikte parolanin yerine konan karakter. Qt surumunde de ayni;
#: oradaki kopya `ui/qr_view.py` silinince gidecek.
MASK_CHAR = "•"

#: Icerik bu surumun uzerine cikarsa kare gozle okunamayacak kadar
#: sikilasiyor -- uyari veriliyor, engellenmiyor.
WARN_VERSION = 20

#: Ham icerik kutusu -- Qt: `setFixedWidth(260)`, `PIXEL_SIZE - 24`.
#: Yukseklik SATIR SAYISIYLA veriliyor, piksel `height` ile DEGIL:
#: `height` cok satirli bir `TextField`e verildiginde kutu yerini
#: ayirtiyor ama TEK SATIR cizip altini bos birakiyor (olculdu).
RAW_W = qr.PIXEL_SIZE
RAW_LINES = 13

#: Tek satirlik giris kutularinin yuksekligi. Verilmezse Material
#: varsayilani ~48 piksel ve pencere Qt surumunden belirgin uzuyor.
FIELD_H = 36

#: Slot listesinin yuksekligi -- Qt: `setFixedHeight(96)`.
SLOTS_H = 96

#: Form etiketleri sutunu. "Guvenlik" en uzun etiket.
LABEL_WIDTH = 72

#: Pencere genisligi -- Qt surumunun olcusu (`QrDialog.size()`: 640).
WIDTH = 640

#: Alansiz pencerenin yuksekligi. Sabit parcalar: baslik cubugu, dolgu,
#: grup satiri, slot listesi, sablon dugmeleri, kare, alt sira.
#:
#: Qt surumu bu pencerede DAHA KISA (istemci alani: metin 522, wifi 605).
#: Fark Flet'in Material denetimlerinden: bir giris kutusu en dar haliyle
#: bile Qt'nin ~24 pikseline inmiyor. Sabitler olculerek kondu -- pencere
#: icerigi tam sarsin, altinda bos serit KALMASIN.
BASE_HEIGHT = 561
#: Bir form satiri + arasindaki bosluk.
ROW_HEIGHT = 42

TEXT_SIZE = 12

#: Iki metin kutusunun ortak gorunumu (bkz. fui/slot_edit.py).
FIELD_STYLE = {
    "dense": True,
    "text_size": TEXT_SIZE,
    "color": theme.FG,
    "bgcolor": theme.FIELD_BG,
    "border_color": theme.BORDER,
    "border_radius": 4,
    "content_padding": 8,
}


def masked(content: str, password: str) -> str:
    """Ham icerikte parolayi yildizla. Bos parola maskelenmez."""
    if not password:
        return content
    return content.replace(password, MASK_CHAR * len(password))


def field_count(item: qr.Template) -> int:
    """Sablonun kac form satiri surdugu -- Wifi'nin "gizli ag" kutusu da
    bir satir."""
    return len(item.fields) + (1 if item.key == "wifi" else 0)


def window_height(item: qr.Template) -> int:
    """Qt `adjustSize`in karsiligi: alan sayisina gore pencere boyu."""
    return BASE_HEIGHT + field_count(item) * ROW_HEIGHT


def slot_rows(store: SlotStore, group: str) -> tuple[tuple[str, str], ...]:
    """Grubun DOLU slotlari: (gorunen satir, icerik).

    Sifre slotu YOK -- `store.py`nin kurali: icerigi hicbir listede
    gorunmez.
    """
    rows: list[tuple[str, str]] = []
    for index, slot in enumerate(store.slots(group)[:10], start=1):
        text = " ".join(slot.content.split())
        if not text or index == PASSWORD_SLOT:
            continue
        shown = slot_display(index, text, lambda t: shorten(t, 60))
        rows.append((f"{index % 10}  {slot.name or f'Slot {index}'}: {shown}", slot.content))
    return tuple(rows)


class QrPanel(QObject):
    """Sablon secimi + alanlar + canli kare. Esc kapatir."""

    #: Pencere gizlendi. `app.py` DINLEMIYOR (QR penceresi kisayollari
    #: susturmuyor); simdilik yalniz simetri icin -- oteki panellerde de
    #: var ve bir gun `ui_open` gerekirse baglanacak yer burasi.
    closed = Signal()

    #: "Su isi Qt'nin ana thread'inde kostur" -- fui/log_view.py'deki
    #: kalibin ayni. Pano, dosya kutusu ve slot dosyasini okuma Flet
    #: dongusunde kosmamali.
    _on_qt = Signal(object)

    def __init__(self, store: SlotStore | None = None) -> None:
        super().__init__()
        self._store = store
        #: `show_text` ile gelen, henuz cizilmemis metin.
        self._pending = ""
        #: Su anki QR icerigi -- kaydetme ve kopyalama bunu kullaniyor.
        self._content = ""
        self._template: qr.Template = qr.TEMPLATES[0]
        #: Secili slot grubu (bos = adsiz "base" grup).
        self._group_key = ""
        #: Qt thread'inde diskten okunan goruntuler. Flet tarafi yalniz
        #: bunlari ciziyor, `SlotStore`a hic dokunmuyor.
        self._groups_data: tuple[tuple[str, str], ...] = ()
        self._slots_data: tuple[tuple[str, str], ...] = ()
        #: Sablonun alanlari -- her sablon degisiminde yenileniyor.
        self._fields: dict[str, ft.Control] = {}

        self._engine = FletEngine(self._build)
        self._page: ft.Page | None = None
        self._groups: ft.Dropdown | None = None
        self._slots: ft.ListView | None = None
        self._radios: ft.RadioGroup | None = None
        self._form: ft.Column | None = None
        self._raw: ft.TextField | None = None
        self._image: ft.Image | None = None
        self._status: ft.Text | None = None

        self._on_qt.connect(self._run_on_qt)

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def show_text(self, text: str) -> None:
        """Verilen metinle pencereyi ac. Sablon metne bakip tahmin edilir."""
        self._pending = text.strip()
        # Diskten okuma ANA THREAD'DE: Flet dongusu dosya beklemesin.
        self._read_groups()
        if self._engine.page is None:
            # Sayfa yok: thread'i baslat, `_build` bu metinle cizecek.
            # Beklemiyoruz -- ana thread 3.5 saniye donarsa tepsi takilir.
            self._engine.start()
            return
        self._engine.call(self._show_now)

    def close(self) -> None:
        """Pencereyi gizle. `app.py` `_shutdown` bunu cagiriyor."""
        self._engine.call(self._hide_now)

    def shutdown(self) -> None:
        """Program kapaniyor: Flet istemcisini (`flet.exe`) gercekten kapat."""
        self._engine.stop()

    # -- Qt thread'i: disk ve pano ------------------------------------------

    @staticmethod
    def _run_on_qt(job: Callable[[], None]) -> None:
        """`_on_qt` sinyalinin alicisi -- ana thread'de kosar."""
        job()

    def _ask_qt(self, job: Callable[[], None]) -> None:
        self._on_qt.emit(job)

    def _read_groups(self) -> None:
        """Gruplari DISKTEN tazeler: dosyayi aradan baskasi degistirmis
        olabilir. Secili grup ayardan geliyor, listede yoksa ilki."""
        store = self._store
        if store is None:
            return
        store.load()
        # Adsiz grup "base" diye gorunur: kutuda bos satir olmasin.
        self._groups_data = tuple((name, name or "base") for name in store.groups)
        keys = [key for key, _label in self._groups_data]
        saved = qr.SLOT_GROUP.get()
        self._group_key = saved if saved in keys else (keys[0] if keys else "")
        self._read_slots()

    def _read_slots(self) -> None:
        """Secili grubun slotlarini DISKTEN okur (Qt thread)."""
        store = self._store
        if store is None:
            return
        self._slots_data = slot_rows(store, self._group_key)

    def _apply_group(self, key: str) -> None:
        """Grup secimi: ayara yaz, diske kaydet, slotlari tazele.

        Qt thread'inde kosuyor. Ayar nesnesi ve `SlotStore` program
        genelinde paylasiliyor -- Flet dongusunden yazilmamali.
        """
        self._group_key = key
        qr.SLOT_GROUP.set(key)
        # Hemen diske: cikista yazmak cokme/oldurulme halinde kayboluyor.
        SETTINGS.save(paths.SETTINGS)
        self._read_slots()
        self._engine.call(self._render_slots)

    def _save_now(self, content: str) -> None:
        """`QFileDialog` -- Qt penceresi, ana thread'de acilmali."""
        path, _filter = QFileDialog.getSaveFileName(None, "QR kaydet", "qr.png", "PNG (*.png)")
        if not path:
            return
        with open(path, "wb") as handle:
            handle.write(qr.png_bytes(content, scale=12))

    @staticmethod
    def _copy_now(content: str) -> None:
        """Pano QT nesnesi: ana thread'de yazilmali."""
        pixmap = QPixmap()
        if not pixmap.loadFromData(qr.png_bytes(content)):
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setPixmap(pixmap)

    # -- Flet thread'i: kurulum ---------------------------------------------

    def _build(self, page: ft.Page) -> None:
        """Sayfa hazir. Denetimleri kur ve hemen goster (FLET thread'i)."""
        self._page = page
        page.title = "QR kod"
        page.bgcolor = theme.BG
        page.padding = 14
        page.window.width = WIDTH
        # Kapatma DUSMESIN: `ft.run` doner, thread olur ve bir sonraki
        # acilis 3.5 saniyeyi yeniden odetirdi.
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        rows: list[ft.Control] = []

        # ---- slot secici (grup acilir kutusu + grubun slotlari)
        self._groups = ft.Dropdown(
            options=[],
            on_select=lambda _e: self._on_group(),
            expand=True,
            height=FIELD_H,
            **FIELD_STYLE,
        )
        self._slots = ft.ListView(controls=[], spacing=0, expand=True)
        if self._store is not None:
            rows.append(
                ft.Row(
                    controls=[
                        ft.Text("slot grubu", color=theme.MUTED, size=TEXT_SIZE),
                        self._groups,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
            rows.append(
                ft.Container(
                    height=SLOTS_H,
                    bgcolor=theme.FIELD_BG,
                    border_radius=4,
                    content=self._slots,
                )
            )

        # ---- sablon secimi
        self._radios = ft.RadioGroup(
            value=self._template.key,
            on_change=lambda _e: self._on_template(),
            content=ft.Row(
                controls=[
                    ft.Radio(
                        value=item.key,
                        label=item.label,
                        label_style=ft.TextStyle(color=theme.FG, size=TEXT_SIZE),
                    )
                    for item in qr.TEMPLATES
                ]
            ),
        )
        rows.append(self._radios)

        # ---- alanlar (sablona gore yeniden kuruluyor -- bkz. dosya basi)
        self._form = ft.Column(controls=[], spacing=6)
        rows.append(self._form)

        # ---- ham icerik + kare yan yana
        self._raw = ft.TextField(
            read_only=True,
            multiline=True,
            min_lines=RAW_LINES,
            max_lines=RAW_LINES,
            width=RAW_W,
            **FIELD_STYLE,
        )
        self._image = ft.Image(
            # Bos baytla kuruluyor: ilk kare `_refresh`te geliyor, o ana
            # kadar gizli (bos `src` Flutter tarafinda hata resmi cizer).
            src=b"",
            visible=False,
            width=qr.PIXEL_SIZE,
            height=qr.PIXEL_SIZE,
            fit=ft.BoxFit.CONTAIN,
            # Yumusatma YOK: QR keskin kenar ister, bulanik kare
            # telefonda okunmuyor (Qt: `FastTransformation`).
            filter_quality=ft.FilterQuality.NONE,
            # Kare yeniden uretilirken eskisi ekranda kalsin: her tus
            # vurusunda bir an bosluk gorunmesin.
            gapless_playback=True,
        )
        rows.append(
            ft.Row(
                spacing=10,
                controls=[
                    ft.Column(
                        spacing=4,
                        controls=[
                            self._raw,
                            ft.Text("ham icerik", color=theme.MUTED, size=TEXT_SIZE),
                        ],
                    ),
                    ft.Container(
                        width=qr.PIXEL_SIZE,
                        height=qr.PIXEL_SIZE,
                        # Beyaz zemin SART: koyu temada QR'in beyaz
                        # modulleri sayfaya karisiyor ve telefon kareyi
                        # bulamiyor.
                        bgcolor="#ffffff",
                        border_radius=4,
                        alignment=ft.Alignment.CENTER,
                        content=self._image,
                    ),
                ],
            )
        )

        # ---- alt sira
        self._status = ft.Text("", color=theme.MUTED, size=TEXT_SIZE)
        rows.append(
            ft.Row(
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    self._button("Kaydet PNG", self._save_png),
                    self._button("Panoya kopyala", self._copy_image),
                    ft.Container(expand=True),
                    self._status,
                ],
            )
        )

        page.controls.append(ft.Column(controls=rows, spacing=10))
        self._engine.call(self._show_now)

    def _button(self, label: str, action: Callable[[], None]) -> ft.ElevatedButton:
        return ft.ElevatedButton(
            content=ft.Text(label, size=TEXT_SIZE, color=theme.FG),
            height=32,
            bgcolor=theme.FIELD_BG,
            on_click=lambda _e: action(),
        )

    # -- Flet thread'i: cizim -----------------------------------------------

    async def _show_now(self) -> None:
        """Bekleyen metinle pencereyi kur ve one getir (FLET thread'i)."""
        page = self._page
        if page is None:
            return
        self._render_groups()
        # Sablon metne bakip tahmin ediliyor; yanilirsa kullanici ustteki
        # dugmelerden degistirir.
        item = qr.template(qr.guess_template(self._pending))
        if self._radios is not None:
            self._radios.value = item.key
        self._build_fields(item, self._pending)
        page.window.visible = True
        page.update()
        await page.window.to_front()

    def _hide_now(self) -> None:
        page = self._page
        if page is None:
            return
        page.window.visible = False
        page.update()

    def _render_groups(self) -> None:
        """Grup kutusunu Qt tarafinin okudugu listeyle doldurur."""
        groups = self._groups
        if groups is None:
            return
        groups.options = [
            ft.DropdownOption(key=key, text=label) for key, label in self._groups_data
        ]
        groups.value = self._group_key
        self._render_slots()

    def _render_slots(self) -> None:
        """Slot listesini cizer. Tiklanan slot alanlara cozuluyor."""
        listing = self._slots
        if listing is None:
            return
        listing.controls = [
            ft.Container(
                padding=ft.Padding(8, 3, 8, 3),
                on_click=lambda _e, c=content: self._use_slot(c),
                content=ft.Text(label, color=theme.FG, size=TEXT_SIZE, no_wrap=True),
            )
            for label, content in self._slots_data
        ]
        if not listing.controls:
            listing.controls = [
                ft.Container(
                    padding=ft.Padding(8, 3, 8, 3),
                    content=ft.Text(
                        "(bu grupta dolu slot yok)", color=theme.MUTED, size=TEXT_SIZE
                    ),
                )
            ]
        if self._page is not None:
            self._page.update()

    def _build_fields(self, item: qr.Template, initial: str) -> None:
        """Alanlari SIFIRDAN kurar (FLET thread'i).

        Sablon degisince eski alanlar anlamsizlasiyor; tasimaya calismak
        yaniltici olurdu (Qt surumunun gerekcesi aynen gecerli).
        """
        form = self._form
        if form is None:
            return
        self._template = item
        self._fields = {}
        controls: list[ft.Control] = []

        for spec in item.fields:
            widget: ft.Control
            if spec.choices:
                widget = ft.Dropdown(
                    options=[
                        ft.DropdownOption(key=choice, text=choice) for choice in spec.choices
                    ],
                    value=spec.default or spec.choices[0],
                    on_select=lambda _e: self._refresh(),
                    expand=True,
                    height=FIELD_H,
                    **FIELD_STYLE,
                )
            else:
                widget = ft.TextField(
                    # Parola gizli baslar. QR ekranda ACIK METIN demektir;
                    # gizlemek odadaki gozu engeller, ekrani goren
                    # telefonu engellemez. Goz simgesi kutunun kendinde:
                    # parolayi gormeden dogru yazdigindan emin olmanin
                    # baska yolu yok, kare zaten ekranda.
                    password=spec.secret,
                    can_reveal_password=spec.secret,
                    on_change=lambda _e: self._refresh(),
                    expand=True,
                    height=FIELD_H,
                    **FIELD_STYLE,
                )
            self._fields[spec.key] = widget
            controls.append(self._form_row(spec.label, widget))

        if item.key == "wifi":
            hidden = ft.Checkbox(
                label="gizli ag",
                value=False,
                on_change=lambda _e: self._refresh(),
                label_style=ft.TextStyle(color=theme.FG, size=TEXT_SIZE),
            )
            self._fields["hidden"] = hidden
            controls.append(self._form_row("", hidden))

        form.controls = controls

        # Gelen metin alanlara COZULUYOR (qr.parse). Hazir bir `WIFI:...;;`
        # dizgisi geldiginde eskiden metnin tamami SSID kutusuna giriyordu:
        # kacis karakterleri ikinci kez kacirilip cop bir kare cikiyordu.
        if initial:
            for key, value in qr.parse(item.key, initial).items():
                target = self._fields.get(key)
                if target is None or not value:
                    continue
                if key == "password" and set(value) <= {MASK_CHAR}:
                    # Maskelenmis ham icerik geri geldi: gercek parola
                    # degil, yildizin kendisi. Yazmak yaniltici olurdu.
                    continue
                if isinstance(target, (ft.TextField, ft.Dropdown)):
                    target.value = value
                elif isinstance(target, ft.Checkbox):
                    target.value = value == "1"

        self._resize()
        self._refresh()

    def _form_row(self, label: str, field: ft.Control) -> ft.Row:
        """QFormLayout'un bir satiri: solda etiket, sagda alan."""
        return ft.Row(
            controls=[
                ft.Text(label, color=theme.MUTED, size=TEXT_SIZE, width=LABEL_WIDTH),
                field,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _resize(self) -> None:
        """Pencere boyunu alan sayisina gore ayarla (Qt `adjustSize`)."""
        if self._page is not None:
            self._page.window.height = window_height(self._template)

    def _values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, widget in self._fields.items():
            if isinstance(widget, ft.Checkbox):
                values[key] = "1" if widget.value else "0"
            elif isinstance(widget, (ft.TextField, ft.Dropdown)):
                values[key] = widget.value or ""
        return values

    def _refresh(self) -> None:
        """Alanlardan metni kur, kareyi ve ham kutuyu tazele (FLET thread'i).

        Her tus vurusunda kosuyor: segno kareyi 1 ms altinda uretiyor ve
        PNG birkac kilobayt, yani Flutter tarafina giden yuk kucuk.
        """
        raw, image, status = self._raw, self._image, self._status
        if raw is None or image is None or status is None:
            return
        values = self._values()
        content = self._template.build(values)
        self._content = content
        # Ham kutuda parola ACIK gorunmuyor: kutu ekranin bir parcasi ve
        # QR'i dogrulamak icin bicimi gormek yetiyor.
        raw.value = masked(content, values.get("password", ""))

        data = qr.png_bytes(content)
        if not data:
            # Bos icerik: kare yok, sayac yok. `src=b""` Flutter tarafinda
            # hata resmi cizdiriyor, o yuzden gorunurluk kapatiliyor.
            image.visible = False
            status.value = ""
        else:
            image.visible = True
            image.src = data
            version = qr.version_of(content)
            note = "  ⚠ cok yogun" if version >= WARN_VERSION else ""
            status.value = f"ver{version}  ·  {len(content.encode())} bayt{note}"
        if self._page is not None:
            self._page.update()

    # -- olaylar ------------------------------------------------------------

    def _on_template(self) -> None:
        """Sablon dugmesi: alanlar sifirdan, metin TASINMIYOR."""
        radios = self._radios
        if radios is None:
            return
        self._build_fields(qr.template(radios.value or ""), "")

    def _on_group(self) -> None:
        """Grup kutusu: ayar yazma ve disk okuma Qt tarafinda."""
        groups = self._groups
        if groups is None:
            return
        key = groups.value or ""
        self._ask_qt(lambda: self._apply_group(key))

    def _use_slot(self, content: str) -> None:
        """Tiklanan slotun icerigi: sablon yeniden tahmin edilip alanlara
        cozuluyor."""
        if not content:
            return
        item = qr.template(qr.guess_template(content))
        if self._radios is not None:
            self._radios.value = item.key
        self._build_fields(item, content)

    def _save_png(self) -> None:
        content = self._content
        if content:
            self._ask_qt(lambda: self._save_now(content))

    def _copy_image(self) -> None:
        content = self._content
        if content:
            self._ask_qt(lambda: self._copy_now(content))

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        if event.key == "Escape":
            self._hide()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self._hide()

    def _hide(self) -> None:
        """Pencereyi gizle, thread'i YASAT, Qt'ye kapandigini bildir."""
        self._hide_now()
        self.closed.emit()
