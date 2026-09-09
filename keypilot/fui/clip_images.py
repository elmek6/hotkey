"""Pano gorselleri penceresi -- ui/clip_images.py'nin Flet karsiligi.

ONIKINCI PANEL, ILK RESIM LISTESI. Adim 5'te (`fui/qr.py`) ekranda TEK
bir resim vardi ve onu program uretiyordu; burada resimler DISKTEN
geliyor, sayilari onceden belli degil ve her satirda bir tane var.

UC YENI SEY VAR:

    kucuk resim       Qt liste satirina `QPixmap` ikonu koyuyordu; Flet'e
                      verilebilen sey PNG BAYTI, o yuzden depodaki HAM
                      BGRA thumb (64x64) Qt thread'inde PNG'ye
                      cevriliyor (`thumb_png`). Cevrilen bayt SLOT+ID ile
                      onbellege giriyor: liste her tazelemede bastan
                      kuruluyor, ayni resmi her seferinde yeniden
                      kodlamak bosuna is olurdu.
    zoom + kaydirma   Qt'de elle yazilmis bir `QPainter` yuzeyiydi
                      (tekerlek zoom, surukleyerek kaydirma);
                      Flet'te `ft.InteractiveViewer` bunu ZATEN yapiyor.
                      Bizim isimiz yalnizca resmin TABAN olcusunu
                      hesaplamak (1:1 mi, sigdirilmis mi) --
                      `preview_size`.
    coklu isaretleme  Qt'de Ctrl/Shift + tik ile coklu secim vardi. Flet
                      tiklama olayi degistirici tuslari TASIMIYOR
                      (`ft.TapEvent`de alan yok), o yuzden her satirda
                      bir ISARET KUTUSU var. Islev ayni: "Sil" isaretli
                      satirlari siler, hicbiri isaretli degilse secili
                      olani.

Yon kurali degismedi: depoya (`ClipImageStore`) dokunan her satir Qt'nin
ana thread'inde kosuyor -- nesne `clip_ctl.py` ile PAYLASILIYOR ve
kopyalanan her gorsel oraya yaziliyor. Flet tarafi yalnizca Qt'nin
hazirladigi demetleri ciziyor.

    Flet (tik)      -> ask_qt -> store.read_png / touch / delete (ANA THREAD)
                              -> call   -> _render_* (Flet thread'i)
    QTimer(900 ms)  -> store.rev degistiyse reload -> call -> _render_list

SECIM SLOT ILE tasiniyor, satir numarasiyla degil (Qt surumunun ayni
karari): canli liste yeni gorselle bastan kuruluyor ve satir numarasi
baska kayda kayardi.

Qt surumunden farklar (bilerek):

    bolucu        Qt'de `QSplitter` vardi ve liste kolonlarin gercek
                  genisligine cekiliyordu (`_fit_list_width`). Flet'te
                  liste sabit genislikte (`LIST_W`, Qt'nin acilis
                  olcusu) ve onizleme genisliyor.
    1:1           Qt cizimi `devicePixelRatio`ya BOLEREK bir goruntu
                  pikselini bir EKRAN pikseline oturtuyordu. Flet'te
                  cizim Flutter'in mantiksal pikselinde; buradaki 1:1
                  "bir goruntu pikseli = bir mantiksal piksel", yani
                  %150 olcekli ekranda gorsel bir tik buyuk cikar.
                  Olcegi veren bir Flet alani yok.
    yumusatma     Qt buyutmede yumusatmayi kapatiyordu. Burada TABAN
                  olcuye gore secili: sigdirilmis (kucultulmus) resim
                  yumusatiliyor, 1:1 keskin kaliyor. Viewer ile yapilan
                  zoom Flutter'in kendi suzgecinden geciyor.
    silme onayi   `QMessageBox.question` yerine `ft.AlertDialog`
                  (`fui/log_view.py`de kurulan kalip). Onay kutusu
                  acikken yoklama DURMUYOR (Qt durduruyordu): liste
                  tazelense de isaretler slotla tasindigi icin secim
                  bozulmuyor.
    pencere yeri  Qt `center_on_cursor_screen` ile imlecin ekranina
                  aciliyordu; Flet'te pencere yerini isletim sistemi
                  veriyor (tasinan onceki paneller de boyle).

Kalan TODO'lar Qt surumundekilerle ayni ve gecerli: gorseli baska bir
uygulamaya SURUKLEYIP birakma yok (adim 10'un engeliyle ayni, bkz.
flet-plan.md), tekerlek yalnizca pencere odaktayken calisiyor.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

import flet as ft
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QFileDialog

from keypilot import paths
from keypilot.fui import theme
from keypilot.fui.engine import FletEngine
from keypilot.imgstore import THUMB_SIZE, ClipImageStore, ImageRecord, thumb_to_image
from keypilot.store import _from_ahk_ms
from keypilot.win32 import shell

log = logging.getLogger("keypilot.fui.clipimages")

#: Depo degisikligini yoklama sikligi -- Qt surumuyle ayni (AHK: POLL_MS).
POLL_MS = 900

#: Pencere olcusu -- Qt: `resize(1080, 640)`.
SIZE = (1080, 640)

#: Liste sutununun genisligi -- Qt: `splitter.setSizes([430, 620])`.
LIST_W = 430

#: Sayfa dolgusu ve iki sutun arasi bosluk.
PADDING = 10
GAP = 10

#: Onizleme kutusunun olcusu. Kutu ekranda GENISLIYOR (expand); bu iki
#: sabit yalnizca SIGDIRMA HESABI icin duruyor -- resmin taban olcusu
#: cizimden once, Qt thread'inden gelen veriyle belirleniyor ve olculecek
#: bir denetim yok. Yukseklik pencereden geri sayilarak kondu: baslik
#: cubugu, dolgu, dugme sirasi, bilgi ve sayac satirlari.
PREVIEW_W = SIZE[0] - LIST_W - 2 * PADDING - GAP
PREVIEW_H = 498

#: Onizleme zemini -- Qt: `fillRect(..., QColor("#1b1f24"))`.
PREVIEW_BG = "#1b1f24"

#: Zoom sinirlari -- Qt: ZOOM_MIN / ZOOM_MAX. Taban olcuye GORE, yani
#: sigdirilmis bir resimde 8x, 1:1'deki 8x'ten kucuk bir buyutme demek.
ZOOM_MIN = 0.1
ZOOM_MAX = 8.0

#: Tekerlegin bir tiklaminda yapilan zoom. Flutter'da BUYUK deger yavas
#: zoom demek; varsayilan 200 Qt'nin 1.25'lik adimindan hantal kaliyordu.
SCALE_FACTOR = 120

#: Kaydirma payi. Flutter sonsuz kabul ediyor ama sonsuz bir sayi
#: Flet'in mesajina girmiyor; buyuk sonlu bir deger ayni ise yariyor --
#: 1:1'de kutuya sigmayan bir resmin her kosesine gidilebiliyor.
BOUNDARY = 3000

TEXT_SIZE = 12

#: Bir liste satirinin ust/alt dolgusu (fui/repository.py ile ayni).
ROW_PAD = 3

#: Satirin ilk metin sutunu: "son kullanim / boyut". Ikincisi kalani
#: aliyor (Qt'de iki kolon kendi icerigine gore olculuyordu).
WHEN_W = 150


def format_ts(ms: int) -> str:
    """AHK `_formatTs`: yerel epoch ms -> okunur tarih (Qt ile ayni)."""
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(_from_ahk_ms(ms)).strftime("%d.%m.%Y %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def row_texts(record: ImageRecord) -> tuple[str, str, str, str]:
    """Satirin dort metni: (son kullanim, boyut, ilk kayit, tekrar).

    Qt surumunde bunlar IKI kolona ikiser satir olarak giriyordu; metnin
    kendisi harfi harfine ayni.
    """
    repeats = f"{record.count} kez" if record.count > 1 else "tek kayit"
    size = f"{record.w}x{record.h}  ·  {round(record.dat_size / 1024)} KB"
    return format_ts(record.ts), size, format_ts(record.created_ts), repeats


def info_text(record: ImageRecord) -> str:
    """Alt bilgi satiri -- Qt: `_update_info`."""
    parts = [
        f"{record.w}x{record.h} px",
        f"{record.dat_size / 1024:.0f} KB",
        f"#{record.id}",
    ]
    if record.count > 1:
        parts.append(f"{record.count} kez kopyalandi")
    parts.append(f"ilk: {format_ts(record.created_ts)}")
    return "   ·   ".join(parts)


def stats_text(count: int, total_bytes: int, copies: int) -> str:
    """En alttaki sayac -- Qt: `_refresh_stats` (AHK: getStats)."""
    return (
        f"{count} gorsel   ·   {total_bytes / (1024 * 1024):.1f} MB   ·   "
        f"{copies} kopyalama"
    )


def fit_scale(image_w: int, image_h: int, box_w: int, box_h: int) -> float:
    """Kutuya sigdirma orani. Qt: `_Preview._compute_fit`.

    Sigiyorsa BUYUTMUYOR (`min(1.0, ...)`) -- kucuk gorseller bosuna
    buyutulup bulaniklasmasin.
    """
    if image_w <= 0 or image_h <= 0:
        return 1.0
    return min(1.0, box_w / image_w, box_h / image_h)


def preview_size(
    image_w: int, image_h: int, box_w: int, box_h: int, one_to_one: bool
) -> tuple[int, int]:
    """Onizlemedeki TABAN olcu. `one_to_one` ise gercek piksel olcusu."""
    scale = 1.0 if one_to_one else fit_scale(image_w, image_h, box_w, box_h)
    return max(1, round(image_w * scale)), max(1, round(image_h * scale))


def thumb_png(raw: bytes | None) -> bytes | None:
    """Depodaki HAM BGRA thumb -> PNG bayti (Flet resim olarak bunu alir).

    Qt `QImage`i ham tampondan sarabiliyordu; Flet'in `ft.Image`i
    kodlanmis bayt istiyor. Kodlama ANA THREAD'de, cagiran taraftaki
    onbellekle birlikte: 64x64'luk bir PNG ucuz ama liste her tazelemede
    bastan kuruluyor.
    """
    if raw is None:
        return None
    try:
        buffer = BytesIO()
        thumb_to_image(raw).save(buffer, "PNG")
    except (OSError, ValueError):
        log.exception("kucuk resim PNG'ye cevrilemedi")
        return None
    return buffer.getvalue()


@dataclass(frozen=True)
class Row:
    """Listede cizilecek bir satir -- Qt tarafinda hazirlanir.

    `ident` (kaydin id'si) onbellek anahtarinin parcasi: slot numaralari
    silinince YENIDEN kullaniliyor, yani tek basina slot eski resmi
    gosterebilirdi.
    """

    slot: int
    ident: int
    when: str
    size: str
    created: str
    repeats: str
    thumb: bytes | None


class ClipImagesPanel(QObject):
    """Gorsel gecmisi penceresi. Tek ornek `clip_ctl.py`de tutulur.

    Disari acilan yuz Qt surumuyle AYNI (`open`, `close`, `copied`), yani
    `clip_ctl.py`de degisen tek sey hangi sinifin kuruldugu.
    """

    #: Kayit panoya alindi / diske yazildi -- ipucunu `clip_ctl.py`
    #: gosteriyor. Metin Qt surumuyle ayni, yoksa oradaki ipucu degisirdi.
    copied = Signal(str)
    closed = Signal()

    def __init__(self, store: ClipImageStore) -> None:
        super().__init__()
        self.store = store

        # ---- Qt tarafinda hesaplanan goruntu; Flet yalniz cizer
        self._rows: tuple[Row, ...] = ()
        self._stats = ""
        self._info = ""
        #: (PNG bayti, genislik, yukseklik) -- secili kaydin onizlemesi.
        self._preview: tuple[bytes, int, int] | None = None
        self._seen_rev = -1
        #: (slot, id) -> PNG. Kayit silinince dusuyor (bkz. `_reload`).
        self._thumbs: dict[tuple[int, int], bytes] = {}

        # ---- secim durumu (Flet thread'i yazar, Qt thread'i okur; ikisi
        # de TEK ATOM: degeri ya da kumenin kendisini yer degistiriyoruz,
        # ayni kural fui/repository.py'deki `_tags`te).
        self._current: int | None = None
        self._marked: frozenset[int] = frozenset()
        #: Onizleme 1:1 mi, sigdirilmis mi ("1:1 / sigdir" dugmesi).
        self._one_to_one = False

        self._engine = FletEngine(self._build)
        self._page: ft.Page | None = None
        self._list: ft.ListView | None = None
        self._preview_box: ft.Container | None = None
        self._info_text: ft.Text | None = None
        self._stats_text: ft.Text | None = None
        self._dialog: ft.AlertDialog | None = None

        # Pencere KAPALIYKEN maliyet sifir olmali: yoklama yalniz
        # gorunurken kosuyor (Qt'de `open` / `closeEvent` idi).
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        self.closed.connect(self._timer.stop)

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def open(self) -> None:
        """`clip.images` eylemi -- Qt surumuyle ayni ad ve ayni is."""
        self._reload()
        self._timer.start()
        if self._engine.page is None:
            # Sayfa yok: thread'i baslat, `_build` bu veriyle cizecek.
            # Beklemiyoruz -- ana thread 3.5 saniye donarsa tepsi takilir.
            self._engine.start()
            return
        self._engine.call(self._show_now)

    def close(self) -> None:
        """Pencereyi gizle. `clip_ctl.close()` bunu cagiriyor."""
        self._timer.stop()
        self._engine.call(self._hide_now)

    def shutdown(self) -> None:
        """Program kapaniyor: Flet istemcisini (`flet.exe`) gercekten kapat."""
        self._timer.stop()
        self._engine.stop()

    # -- Qt thread'i: depo, disk ve pano (`FletEngine.ask_qt` ile) ----------

    def _poll(self) -> None:
        """AHK `_poll`: depo degistiyse listeyi tazele. ANA THREAD."""
        if self.store.rev != self._seen_rev:
            self._reload()
            self._engine.call(self._render_all)

    def _reload(self) -> None:
        """Listeyi depodan tazeler (Qt: `reload`). ANA THREAD.

        Secim SLOT ile korunuyor: yeni bir gorsel kopyalanip liste basa
        kaydiginda bakilan kayit degismesin.
        """
        records = self.store.records()
        self._seen_rev = self.store.rev
        self._rows = tuple(self._row_of(record) for record in records)

        live = {(row.slot, row.ident) for row in self._rows}
        # Silinen kayitlarin resmi onbellekte kalmasin: slot numarasi
        # yeniden dagitiliyor ve depo 500 kayde kadar cikabiliyor.
        self._thumbs = {key: png for key, png in self._thumbs.items() if key in live}

        slots = [row.slot for row in self._rows]
        self._marked = frozenset(slot for slot in self._marked if slot in slots)
        if self._current not in slots:
            self._current = slots[0] if slots else None
        self._stats = stats_text(*self.store.stats())
        self._load_current()

    def _row_of(self, record: ImageRecord) -> Row:
        """Kaydi cizilebilir satira cevirir; kucuk resmi onbellekten alir."""
        key = (record.slot, record.id)
        png = self._thumbs.get(key)
        if png is None:
            png = thumb_png(self.store.read_thumb(record.slot))
            if png is not None:
                self._thumbs[key] = png
        when, size, created, repeats = row_texts(record)
        return Row(record.slot, record.id, when, size, created, repeats, png)

    def _record(self, slot: int | None) -> ImageRecord | None:
        if slot is None or not 0 <= slot < len(self.store.slots):
            return None
        return self.store.slots[slot]

    def _load_current(self) -> None:
        """Secili kaydin PNG'sini ve bilgi satirini hazirlar. ANA THREAD.

        Onizleme boyu KAYITTAN geliyor (`record.w/h`): Qt cozulmus
        `QImage`den okuyordu, burada PNG'yi cozmeye gerek yok -- olcu
        zaten diskteki basligin icinde.
        """
        record = self._record(self._current)
        if record is None:
            self._preview = None
            self._info = ""
            return
        png = self.store.read_png(record.slot)
        if png is None:
            self._preview = None
            self._info = "kayit okunamadi"
            return
        self._preview = (png, record.w, record.h)
        self._info = info_text(record)

    def _select_now(self, slot: int) -> None:
        """Tiklanan satir: diskten oku, sonra ciz (Qt: `_on_select`)."""
        self._current = slot
        # Yeni resim sigdirilmis baslar -- Qt `set_image` -> `reset_view`.
        self._one_to_one = False
        self._load_current()
        self._engine.call(self._render_preview)

    def _copy_now(self, slot: int) -> None:
        """Panoya al. Pano QT nesnesi: ana thread'de yazilmali."""
        png = self.store.read_png(slot)
        if png is None:
            self.copied.emit("")
            return
        image = QImage()
        image.loadFromData(png, "PNG")
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            self.copied.emit("")
            return
        clipboard.setImage(image)
        # Son kullanim tazeleniyor: kayit listenin basina gecsin (AHK ile
        # ayni). `rev` degistigi icin yoklama listeyi kendiliginden
        # yeniden cizecek.
        self.store.touch(slot)
        self.copied.emit(f"{image.width()}x{image.height()}")

    def _delete_now(self, slots: tuple[int, ...]) -> None:
        """Isaretli (ya da secili) kayitlari siler. ANA THREAD."""
        if not slots:
            return
        if not self.store.delete_many(list(slots)):
            return
        self._marked = frozenset()
        self._reload()
        if not self._rows:
            # Qt surumu de bosalinca pencereyi kapatiyordu.
            self._close_from_qt()
            return
        self._engine.call(self._render_all)

    def _export_now(self, slot: int) -> None:
        """PNG kaydet -- `QFileDialog` Qt penceresi, ana thread'de acilmali."""
        record = self._record(slot)
        if record is None:
            return
        target, _filter = QFileDialog.getSaveFileName(
            None, "PNG olarak kaydet", f"clip_{record.id}.png", "PNG (*.png)"
        )
        if not target:
            return
        if not target.lower().endswith(".png"):
            target += ".png"
        if self.store.export_to(slot, target):
            self.copied.emit(f"kaydedildi: {target}")

    def _paint_now(self, slot: int) -> None:
        """Gecici PNG'ye yazip Paint'te acar (Qt: `paint_selected`).

        Gecici dosya SLOT adiyla yaziliyor, yani ayni slot iki kez
        acilinca klasor sismiyor. Silmiyoruz: Paint dosyayi acik tutuyor
        ve kullanici uzerinde calisip "Kaydet" diyebilir.
        """
        paths.PAINT.mkdir(parents=True, exist_ok=True)
        target = paths.PAINT / f"clip-{slot}.png"
        if not self.store.export_to(slot, target) or not shell.open_in_paint(target):
            self._engine.call(
                lambda: self._alert("Paint", "Gorsel Paint'te acilamadi.")
            )

    def _close_from_qt(self) -> None:
        """Pencereyi ANA THREAD'den gizle (liste bosaldi)."""
        self._engine.call(self._hide_now)
        self.closed.emit()

    # -- Flet thread'i: kurulum ---------------------------------------------

    def _build(self, page: ft.Page) -> None:
        """Sayfa hazir. Denetimleri kur ve hemen goster (FLET thread'i)."""
        self._page = page
        page.title = "\U0001f5bc️ Pano Gorselleri"
        page.bgcolor = theme.BG
        page.padding = PADDING
        page.window.width, page.window.height = SIZE
        # Kapatma DUSMESIN: `ft.run` doner, thread olur ve bir sonraki
        # acilis Flet'in baslama suresini yeniden odetirdi.
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        self._list = ft.ListView(controls=[], spacing=0, expand=True)
        listing = ft.Column(
            width=LIST_W,
            spacing=4,
            controls=[self._header(), self._frame(self._list)],
        )

        # Onizleme: icerigi CALISMA ANINDA degisiyor (resim ya da
        # "onizleme yok" yazisi), o yuzden kap saklaniyor.
        self._preview_box = ft.Container(
            expand=True,
            bgcolor=PREVIEW_BG,
            border_radius=4,
            alignment=ft.Alignment.CENTER,
            content=ft.Text("onizleme yok", color=theme.MUTED, size=TEXT_SIZE),
        )

        self._info_text = ft.Text("", color=theme.FG, size=TEXT_SIZE)
        self._stats_text = ft.Text("", color=theme.MUTED, size=11)

        page.controls.append(
            ft.Column(
                expand=True,
                spacing=8,
                controls=[
                    ft.Row(
                        expand=True,
                        spacing=GAP,
                        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                        controls=[listing, self._preview_box],
                    ),
                    ft.Row(
                        spacing=6,
                        controls=[
                            self._button("\U0001f4cb Panoya Al", self._copy_selected),
                            self._button("\U0001f5d1️ Sil", self._ask_delete),
                            self._button("1:1 / sigdir", self._toggle_fit),
                            self._button("\U0001f4be PNG Kaydet", self._export_selected),
                            self._button("\U0001f3a8 Paint+pano", self._paint_selected),
                            self._button("Kapat", self._hide),
                        ],
                    ),
                    self._info_text,
                    self._stats_text,
                ],
            )
        )
        self._engine.show_on_build(self._show_now)

    @staticmethod
    def _header() -> ft.Row:
        """Qt'nin kolon basliklari. Soldaki bosluk isaret kutusu +
        kucuk resim genisligi kadar."""
        return ft.Row(
            spacing=8,
            controls=[
                ft.Container(width=THUMB_SIZE + 34),
                ft.Text(
                    "Son kullanim / boyut", color=theme.MUTED, size=TEXT_SIZE, width=WHEN_W
                ),
                ft.Text("Ilk kayit / tekrar", color=theme.MUTED, size=TEXT_SIZE),
            ],
        )

    @staticmethod
    def _frame(listing: ft.ListView) -> ft.Container:
        """Listeyi Qt'nin `QTreeWidget` cercevesine benzetir."""
        return ft.Container(
            expand=True,
            bgcolor=theme.FIELD_BG,
            border=ft.Border.all(1, theme.BORDER),
            border_radius=4,
            content=listing,
        )

    def _button(self, label: str, action: Callable[[], None]) -> ft.ElevatedButton:
        return ft.ElevatedButton(
            content=ft.Text(label, size=TEXT_SIZE, color=theme.FG),
            height=32,
            bgcolor=theme.FIELD_BG,
            on_click=lambda _e: action(),
        )

    # -- Flet thread'i: cizim -----------------------------------------------

    async def _show_now(self) -> None:
        """Pencereyi Qt tarafinin hazirladigi veriyle kur ve one getir."""
        page = self._page
        if page is None:
            return
        self._fill_list()
        self._fill_preview()
        page.window.visible = True
        page.update()
        await page.window.to_front()

    def _hide_now(self) -> None:
        page = self._page
        if page is None:
            return
        page.window.visible = False
        page.update()

    def _render_all(self) -> None:
        """Liste + onizleme (tazeleme ve silme sonrasi)."""
        page = self._page
        if page is None:
            return
        self._fill_list()
        self._fill_preview()
        page.update()

    def _render_preview(self) -> None:
        page = self._page
        if page is None:
            return
        # Secili satirin zemini de degisti: liste de yeniden doluyor.
        self._fill_list()
        self._fill_preview()
        page.update()

    def _fill_list(self) -> None:
        """Satirlari kurar. `page.update()` CAGIRMAZ -- cagiran karar
        veriyor (acilista tek cizim yeter)."""
        if self._list is not None:
            self._list.controls = [self._row(row) for row in self._rows]

    def _fill_preview(self) -> None:
        """Onizlemeyi ve iki alt satiri doldurur. `page.update()` CAGIRMAZ.

        Viewer her seferinde SIFIRDAN kuruluyor: yeni resimde zoom ve
        kaydirma basa donmeli (Qt: `set_image` -> `reset_view`) ve
        kurulmus bir viewer'in donusumunu sifirlamanin yolu es zamansiz
        bir cagri (`InteractiveViewer.reset`).
        """
        box = self._preview_box
        if box is None:
            return
        if self._info_text is not None:
            self._info_text.value = self._info
        if self._stats_text is not None:
            self._stats_text.value = self._stats

        shot = self._preview
        if shot is None:
            box.content = ft.Text("onizleme yok", color=theme.MUTED, size=TEXT_SIZE)
            return
        png, width, height = shot
        shown_w, shown_h = preview_size(
            width, height, PREVIEW_W, PREVIEW_H, self._one_to_one
        )
        box.content = ft.InteractiveViewer(
            expand=True,
            min_scale=ZOOM_MIN,
            max_scale=ZOOM_MAX,
            scale_factor=SCALE_FACTOR,
            # Pay olmadan kaydirma resmin kendi sinirlarinda kaliyor ve
            # 1:1'de kutuyu asan kisma ULASILAMIYOR.
            boundary_margin=ft.Margin.all(BOUNDARY),
            content=ft.Container(
                alignment=ft.Alignment.CENTER,
                content=ft.Image(
                    src=png,
                    width=shown_w,
                    height=shown_h,
                    # Olcu ZATEN hesaplandi: `FILL` verilmezse Flutter
                    # bir kez daha sigdirip 1:1'i bozabiliyor.
                    fit=ft.BoxFit.FILL,
                    # Kucultulmus resim yumusatiliyor, 1:1 keskin kaliyor
                    # (Qt: `SmoothPixmapTransform` yalniz zoom < 1'de).
                    filter_quality=(
                        ft.FilterQuality.NONE
                        if shown_w >= width
                        else ft.FilterQuality.MEDIUM
                    ),
                    gapless_playback=True,
                ),
            ),
        )

    def _row(self, row: Row) -> ft.GestureDetector:
        """Bir liste satiri: isaret kutusu + kucuk resim + iki metin sutunu.

        `GestureDetector` cift tiklama icin: `Container`in `on_click`i
        tek tiklamayi goruyor ama cift tiklamayi gormuyor (fui/mem_slots.py
        dosya basinda ayni not).
        """
        return ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda _e, slot=row.slot: self._on_row(slot),
            on_double_tap=lambda _e, slot=row.slot: self._on_double(slot),
            content=ft.Container(
                bgcolor=theme.SELECT_BG if row.slot == self._current else None,
                padding=ft.Padding(6, ROW_PAD, 6, ROW_PAD),
                content=ft.Row(
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Checkbox(
                            value=row.slot in self._marked,
                            visual_density=ft.VisualDensity.COMPACT,
                            on_change=lambda event, slot=row.slot: self._on_mark(
                                slot, bool(event.control.value)
                            ),
                        ),
                        self._thumb(row),
                        ft.Column(
                            width=WHEN_W,
                            spacing=0,
                            controls=[
                                ft.Text(row.when, color=theme.FG, size=TEXT_SIZE),
                                ft.Text(row.size, color=theme.MUTED, size=TEXT_SIZE),
                            ],
                        ),
                        ft.Column(
                            expand=True,
                            spacing=0,
                            controls=[
                                ft.Text(row.created, color=theme.FG, size=TEXT_SIZE),
                                ft.Text(row.repeats, color=theme.MUTED, size=TEXT_SIZE),
                            ],
                        ),
                    ],
                ),
            ),
        )

    @staticmethod
    def _thumb(row: Row) -> ft.Control:
        """64x64 kucuk resim. Okunamadiysa ayni olcude BOS kutu -- satirlar
        kaymasin (Qt'de ikonsuz satir da ayni yukseklikteydi)."""
        if row.thumb is None:
            return ft.Container(width=THUMB_SIZE, height=THUMB_SIZE)
        return ft.Image(
            src=row.thumb,
            width=THUMB_SIZE,
            height=THUMB_SIZE,
            fit=ft.BoxFit.CONTAIN,
            filter_quality=ft.FilterQuality.NONE,
        )

    # -- Flet thread'i: olaylar ---------------------------------------------

    def _on_row(self, slot: int) -> None:
        """Satira tiklama: disk okuma Qt tarafinda."""
        self._engine.ask_qt(lambda: self._select_now(slot))

    def _on_double(self, slot: int) -> None:
        """Cift tiklama panoya alir (Qt: `itemDoubleClicked`)."""
        self._current = slot
        self._engine.ask_qt(lambda: self._copy_now(slot))

    def _on_mark(self, slot: int, marked: bool) -> None:
        """Isaret kutusu -- Qt'deki Ctrl/Shift secimin karsiligi.

        Yalnizca "Sil"i ilgilendiriyor; onizleme secili satira bakiyor.
        """
        self._marked = (self._marked | {slot}) if marked else (self._marked - {slot})

    def _targets(self) -> tuple[int, ...]:
        """Silinecek slotlar: isaretliler, hicbiri yoksa secili satir.

        Qt'de secim zaten en az bir satirdi (`selectedItems`); isaret
        kutusuna gecince "hicbiri isaretli degil" hali dogdu.
        """
        if self._marked:
            return tuple(row.slot for row in self._rows if row.slot in self._marked)
        return () if self._current is None else (self._current,)

    def _copy_selected(self) -> None:
        slot = self._current
        if slot is not None:
            self._engine.ask_qt(lambda: self._copy_now(slot))

    def _export_selected(self) -> None:
        slot = self._current
        if slot is not None:
            self._engine.ask_qt(lambda: self._export_now(slot))

    def _paint_selected(self) -> None:
        slot = self._current
        if slot is not None:
            self._engine.ask_qt(lambda: self._paint_now(slot))

    def _toggle_fit(self) -> None:
        """"1:1 / sigdir" -- Qt: `_Preview.toggle_fit`. Cizim isi, Qt'ye
        gitmiyor: resim zaten elde."""
        self._one_to_one = not self._one_to_one
        self._fill_preview()
        if self._page is not None:
            self._page.update()

    def _ask_delete(self) -> None:
        """Toplu silmede ONAY sorulur, tekli silme onaysiz (Qt ile ayni)."""
        slots = self._targets()
        if not slots:
            return
        if len(slots) == 1:
            self._engine.ask_qt(lambda: self._delete_now(slots))
            return
        page = self._page
        if page is None:
            return
        self._dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Toplu silme", color=theme.FG),
            content=ft.Text(
                f"{len(slots)} gorsel silinecek.\nEmin misiniz?",
                color=theme.FG,
                size=TEXT_SIZE,
            ),
            bgcolor=theme.FIELD_BG,
            actions=[
                ft.TextButton("Evet", on_click=lambda _e: self._confirm_delete(slots)),
                ft.TextButton("Hayir", on_click=lambda _e: self._close_dialog()),
            ],
        )
        page.show_dialog(self._dialog)

    def _confirm_delete(self, slots: tuple[int, ...]) -> None:
        self._close_dialog()
        self._engine.ask_qt(lambda: self._delete_now(slots))

    def _alert(self, title: str, message: str) -> None:
        """Tek dugmeli bilgi kutusu -- `QMessageBox.warning` karsiligi."""
        page = self._page
        if page is None:
            return
        self._dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, color=theme.FG),
            content=ft.Text(message, color=theme.FG, size=TEXT_SIZE),
            bgcolor=theme.FIELD_BG,
            actions=[ft.TextButton("Tamam", on_click=lambda _e: self._close_dialog())],
        )
        page.show_dialog(self._dialog)

    def _close_dialog(self) -> None:
        page = self._page
        if page is not None and self._dialog is not None:
            page.pop_dialog()
            self._dialog = None

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        """Esc kapatir, Delete siler (Qt: `keyPressEvent`)."""
        if event.key == "Escape":
            self._hide()
        elif event.key == "Delete":
            self._ask_delete()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self._hide()

    def _hide(self) -> None:
        """Pencereyi gizle, thread'i YASAT, Qt'ye kapandigini bildir
        (yoklama zamanlayicisi `closed` ile duruyor)."""
        self._hide_now()
        self.closed.emit()


# TODO(AHK): clip_image_dialog.ahk'nin surukleyip disari birakma yolu
#     (ole_drag_source.ahk) port edilmedi -- listedeki gorseli baska bir
#     uygulamaya surukleme. Qt surumunde de yoktu; Flet'te karsiligi
#     olmayan islerden (bkz. flet-plan.md, adim 10).
# TODO(gecis): "PNG Kaydet" hala `QFileDialog` kullaniyor. Qt gidince
#     yerine `ft.FilePicker` gerekecek -- fui/qr.py'deki ayni not.
