"""Hafiza bloklari -- ui/mem_slots.py'nin Flet karsiligi.

ONUNCU PANEL. Planin bu adim icin yazdigi gerekce YANLIS CIKTI: "diske
yazan `SlotStore`u slot kutusu ve QR ile PAYLASIYOR, `ask_qt` en siki
burada uygulanacak" deniyordu. Dosyaya bakinca oyle olmadigi gorundu --
bu pencerenin bloklari BELLEKTE yasiyor, `slots.json` ile ilgisi yok
(ui/mem_slots.py dosya basi bunu zaten yaziyor: "isim benzerligi
yuzunden karistiriliyordu"). Paylasilan durum yok, disk yok. Adim 5'in
dersi bir kez daha: tahmin, dosyaya bakilmadan uygulanmamali.

Yerine cikan UC yeni sey:

  * **Panel Qt'ye BAGIMLI DEGIL ama ANA THREAD'e bagimli.** `app.py`
    F1..F10 tuslarindan `paste_slot`/`save_slot`/`smart_paste` cagiriyor
    (ana thread) ve ayni alanlari Flet tarafindaki tiklamalar da
    degistiriyor. `ask_qt`e gerek YOK: dokunulan sey duz Python listesi,
    her atama tek ve bolunmez (`fui/repository.py`deki suzgec durumuyla
    ayni gerekce). Cizim ise HER IKI yoldan da `engine.call` ile
    isteniyor -- `call` zaten "bu thread'de dongu var mi" diye bakip
    dogru yere birakiyor.
  * **"Pencere acik mi" ANA THREAD'de cevaplaniyor** (`visible`).
    `app.py` `memslots_paste_enter` ve `smart_paste` her orta tusta bunu
    soruyor; Qt'de `isVisible()` idi. `fui/monitor.py`de kurulan kalip.
  * **HEP USTTE** (`page.window.always_on_top`) -- Qt:
    `WindowStaysOnTopHint`. Adim 8'de (`fui/ocr.py`) yapilmisti, tek satir.

    F1..F10 / orta tus  -> app.py (ANA THREAD) -> paste_slot / smart_paste
                                                -> call -> _draw
    pano degisti        -> clip_ctl (ANA THREAD) -> on_clip -> call -> _draw
    liste tiklamasi     -> Flet thread'i -> select_* -> call -> _draw
    cift tiklama        -> Flet thread'i -> copy_text / paste_text sinyali
                                            (Qt kuyruga alir, ana thread'de kosar)

Qt surumunden farklar (bilerek):

    SURUKLEME      Qt'de satir disari surukleniyordu (`DragTable`,
                   AHK `OleDragSource`): tabloda kisaltilmis onizleme
                   yazar, birakilan sey blogun TAM icerigi olurdu.
                   **Flet'te karsiligi YOK** -- `ft.Draggable` yalnizca
                   uygulamanin KENDI icinde tasiyor, isletim sistemine
                   birakma diye bir sey yok. Yerine duran yol: bloga
                   cift tikla (panoya kopyalar), sonra hedefte yapistir.
    cift tiklama   Qt'de `doubleClicked` idi; burada `ft.GestureDetector`
                   `on_double_tap`. Log ve olay izleyicide bu olay
                   YOKTU diye yazilmisti -- `Container`da gercekten yok,
                   ama `GestureDetector`da var. Bu panelde cift tiklama
                   AHK'den gelen ANA islevlerden biri (blok -> panoya,
                   gecmis -> yapistir), o yuzden burada aranip bulundu.
                   Bedeli: tek tiklama artik cift tiklama zaman asimi
                   kadar (~300 ms) gec islenir -- Flutter iki olayi
                   ancak boyle ayirabiliyor. Gorunen sey secim
                   cercevesinin gec gelmesi; yapilan is degismiyor.
    tablo          Qt'de iki `QTableWidget` vardi. Burada satir basina
                   TEK yazi: sabit genislikli yazi tipinde "F01" sutunu
                   dolguyla ayni satira giriyor (`row_text`). Sebep
                   cizim maliyeti -- flet-plan.md **Olculen degerler**.
    Esc            Qt surumunde yoktu; oteki Flet panelleriyle ayni
                   olsun diye eklendi (`fui/monitor.py` de boyle yapti).
                   Esc kapatmak demek: F1..F10 birakilir, pano modu
                   geri doner -- X ile kapatmakla ayni.

PENCERE KAPANMIYOR, GIZLENIYOR (oteki paneller gibi). Kapanis Qt
surumunun `closeEvent`i ile ayni isi yapiyor: once F1..F10 kutusu
indirilir (`fkeys_toggled(False)`), sonra `closed` yayilir -- `app.py`
pano modunu orada geri aliyor.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
from PySide6.QtCore import QObject, Signal

from keypilot.fui import theme

from keypilot.fui.engine import FletEngine

SLOT_COUNT = 10  # AHK: Loop 10
PREVIEW_LIMIT = 60  # AHK: _makePreview -> SubStr(preview, 1, 60)

#: AHK: Background0x2196F3 / 0x4CAF50 -- aktif liste renkli, oteki gri.
#: Qt surumundeki (ui/mem_slots.py) degerlerin AYNISI.
ACTIVE_SLOTS_BG = "#2196f3"
ACTIVE_HIST_BG = "#4caf50"
IDLE_BG = "#808080"

#: Qt: `resize(460, 680)` -- AHK "w450 h650", dar ve uzun. Genislik
#: birebir kopyalanabiliyor, yukseklik KOPYALANAMAZ (flet-plan.md
#: **PENCERE OLCUSU kurali**): ustteki dort denetim Material olculeriyle
#: Qt'nin iki satirindan yuksek.
SIZE = (480, 726)

MONO = "Consolas"
TEXT_SIZE = 12

#: Bir liste satirinin ust/alt dolgusu (fui/repository.py ile ayni
#: gerekce: Flet'in varsayilani Qt satirindan ferah, yirmi satir bir
#: ekrana sigmiyordu).
ROW_PAD = 3

#: "Blok" / "#" sutununun genisligi (karakter). Sabit genislikli yazi
#: tipinde butun satir TEK bir `Text`e siginca satir basina uc denetim
#: kaliyor (jest + kap + yazi); sutun basina bir yazi kursaydik daha
#: cok olurdu ve cizim maliyeti denetim sayisiyla dogru orantili.
W_LABEL = 5  # "F01" + iki bosluk


def preview(text: str, limit: int = PREVIEW_LIMIT) -> str:
    """AHK: _makePreview -- satir sonlari bosluga iner, uzunsa kirpilir.

    Qt surumunde de ayni fonksiyon var (ui/mem_slots.py). Ikisi TEK
    satirlik ve saf; Qt dosyasi silinince bu kalir (bkz. flet-plan.md,
    `MASK_CHAR` ile ayni durum).
    """
    flat = " ".join(text.split())
    if not flat:
        return "(Bos)"
    return flat if len(flat) <= limit else flat[: limit - 1] + "..."


def row_text(label: str, content: str) -> str:
    """Bir liste satiri: solda "F01", sagda onizleme -- dolguyla hizali.

    BOS blok bos gorunur: Qt'de de tablo hucresi bostu ("(Bos)" yalnizca
    gercekten bos bir GECMIS kaydinda cikar).
    """
    return f"{label:<{W_LABEL}}{preview(content) if content else ''}"


def header_text(first: str) -> str:
    """Sutun basliklari -- satirlarla AYNI dolguyla dizilir."""
    return f"{first:<{W_LABEL}}Icerik"


class MemSlotsPanel(QObject):
    """Hafiza bloklari penceresi. `app.py` bir kez kurup `start()` ile acar."""

    #: panoya yaz ve Ctrl+V gonder (metin, gizli mi)
    paste_text = Signal(str, bool)
    #: panoya yaz, yapistirma (metin, gizli mi)
    copy_text = Signal(str, bool)
    #: hedef uygulamadan Ctrl+C iste (secili metni bloga alacagiz)
    grab_clip = Signal()
    #: kisa ipucu (HTML)
    tip = Signal(str)
    #: F1..F10 kisayollari acildi / kapandi
    fkeys_toggled = Signal(bool)
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = [""] * SLOT_COUNT
        self.history: list[str] = []
        self.slot_index = 1  # 1 tabanli, AHK ile ayni
        self.hist_index = 1
        self._slots_active = False  # AHK: activeList -- acilista gecmis aktif
        self._pending_slot: int | None = None  # `^c` bekleyen blok

        #: ANA THREAD'IN sorusu: "pencere acik mi". Qt'de `isVisible()`
        #: idi; `app.py` `memslots_paste_enter` ve `smart_paste` her orta
        #: tusta buna bakiyor ve her tus icin Flet thread'ine gidip
        #: donmek olmaz (fui/monitor.py'de kurulan kalip).
        self.visible = False

        #: Kutular Flet'te ama KARARI ana thread veriyor: `on_clip` ve
        #: `smart_paste` bunlari okuyor. Flet tarafindan yazilan tek sey
        #: bir `bool` -- bolunmez. Varsayilanlar Qt surumuyle ayni:
        #: F tuslari KAPALI (sistem geneli kisayol, istemeden ele
        #: gecirmiyoruz), orta tus ACIK.
        self._fkeys_on = False
        self._allow_repeat = False
        self._middle_paste = True

        self._engine = FletEngine(self._build)
        self._page: ft.Page | None = None
        self._slot_list: ft.ListView | None = None
        self._hist_list: ft.ListView | None = None
        self._slots_header: ft.Container | None = None
        self._hist_header: ft.Container | None = None
        self._fkeys_box: ft.Checkbox | None = None

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def start(self, history: tuple[str, ...] | list[str]) -> None:
        """AHK: start(). Gecmisin ilk on kaydi yuklu acilir.

        Bloklarin ICERIGI KORUNUR: onceki acilista doldurulan kayitlar
        yerinde kalir -- pencereyi kapatip acmak kullanicinin doldurdugu
        bloklari silmemeli. Temizlemek isteyen "Slotlari temizle"
        dugmesini kullanir.
        """
        self.history = list(history)[:SLOT_COUNT]
        self.visible = True
        self.select_history(1)
        if self._engine.page is None:
            # Sayfa yok: thread'i baslat, `_build` bu veriyle cizecek.
            # Beklemiyoruz -- ana thread 3.5 saniye donarsa tepsi takilir.
            self._engine.start()
            return
        self._engine.call(self._show_now)

    def on_clip(self, text: str) -> None:
        """Pano degisti (mod MEM_SLOTS iken `clip_ctl` buraya verir).

        AHK: clipboardWatcher + _autoFillSlot. `^c` ile biz istediysek
        bekleyen bloga, degilse ilk bos bloga yazilir. ANA THREAD.
        """
        if not text:
            return
        pending, self._pending_slot = self._pending_slot, None
        if pending is not None:
            self._write_slot(pending, text)
            self.select_slot(pending)
            self.tip.emit(f"\U0001f4be <b>Blok {pending}</b> kaydedildi")
            return
        if not self._allow_repeat and text in self.blocks:
            return  # AHK: _isClipInSlots
        index = self._first_free()  # AHK: dolunca basa doner, ustune yazar
        self._write_slot(index, text)
        self.select_slot(index)

    # -- F1..F10 eylemleri (`app.py` cagirir, ANA THREAD) -------------------

    def paste_slot(self, index: int) -> None:
        """Kisa basim. AHK: pasteFromSlot."""
        text = self._slot(index)
        if not text:
            self.tip.emit(f"⚠️ <b>Blok {index}</b> bos")
            return
        self.select_slot(index)
        self.paste_text.emit(text, False)

    def paste_history(self, index: int) -> None:
        """Orta basim. AHK: _pasteFromHistory."""
        if not 1 <= index <= len(self.history):
            self.tip.emit(f"⚠️ <b>Gecmis {index}</b> yok")
            return
        self.select_history(index)
        self.paste_text.emit(self.history[index - 1], False)

    def save_slot(self, index: int) -> None:
        """Uzun basim (AHK'de cift basim). Once `^c`, gelen metin bloga."""
        if not 1 <= index <= SLOT_COUNT:
            return
        self._pending_slot = index
        self.grab_clip.emit()

    def smart_paste(self, middle: bool = False) -> None:
        """AHK: smartPaste(middlePressed) -- aktif listeden yapistir.

        Ayrim AHK'den birebir: ORTA TUS ile gelindiyse yapistirdiktan
        sonra siradaki kayda gecilir (arka arkaya basmak listeyi
        gezdirir); tus kombosuyla gelindiyse yalnizca yapistirir, secim
        yerinde kalir. Pencere kapaliyken hicbir sey olmaz -- orta tus
        her yerde calisan bir tus, yalniz bu pencere acikken anlam
        kazanir.
        """
        if not self.visible:
            return
        if middle and not self._middle_paste:
            return
        if self._slots_active:
            self.paste_slot(self.slot_index)
            if middle:
                self.select_slot(self._next(self.slot_index, self._used_slots()))
        else:
            self.paste_history(self.hist_index)
            if middle:
                self.select_history(self._next(self.hist_index, len(self.history)))

    def clear_slots(self) -> None:
        """AHK: _clearSlots

        Bekleyen `^c` istegi de DUSER: "uzun basim + temizle" sirasindan
        sonra gelen kopyalama, temizlenmis bir bloga sessizce dolmamali.
        """
        self._pending_slot = None
        self.blocks = [""] * SLOT_COUNT
        self.select_slot(1)

    def close(self) -> None:
        """Pencereyi gizle ve `closed` yay -- Qt'nin `closeEvent`i ile ayni is.

        Sira Qt surumundeki gibi: ONCE F1..F10 birakilir, sonra `closed`
        (app.py orada pano modunu geri aliyor).
        """
        if not self.visible:
            return
        self.visible = False
        self._release_fkeys()
        self._engine.call(self._hide_now)
        self.closed.emit()

    def shutdown(self) -> None:
        """Program kapaniyor: Flet istemcisini (`flet.exe`) gercekten kapat."""
        self._engine.stop()

    # -- secim ve liste durumu (iki thread'den de cagriliyor) ---------------

    def select_slot(self, index: int) -> None:
        """AHK: _selectSlotViewer"""
        self.slot_index = max(1, min(index, SLOT_COUNT))
        self._slots_active = True
        self._engine.call(self._draw)

    def select_history(self, index: int) -> None:
        """AHK: _selectHistoryViewer. Gecmis bossa secilecek sey yok."""
        if not self.history:
            return
        self.hist_index = max(1, min(index, len(self.history)))
        self._slots_active = False
        self._engine.call(self._draw)

    # -- ic yardimcilar -----------------------------------------------------

    def _history_text(self, row: int) -> str:
        """Gecmis satirinin TAM metni (1 tabanli)."""
        return self.history[row - 1] if 1 <= row <= len(self.history) else ""

    def _slot(self, index: int) -> str:
        return self.blocks[index - 1] if 1 <= index <= SLOT_COUNT else ""

    def _used_slots(self) -> int:
        """AHK: slotsLength -- sondan geriye dogru ilk dolu blok."""
        count = SLOT_COUNT
        while count >= 1 and not self.blocks[count - 1]:
            count -= 1
        return count

    def _first_free(self) -> int:
        used = self._used_slots()
        return used + 1 if used < SLOT_COUNT else 1

    @staticmethod
    def _next(index: int, limit: int) -> int:
        return index + 1 if index < limit else 1

    def _write_slot(self, index: int, text: str) -> None:
        """Blogu yazar. Cizimi `select_slot` istiyor (cagiran her yerde
        hemen ardindan cagiriyor) -- iki cizim yerine bir tane."""
        if 1 <= index <= SLOT_COUNT:
            self.blocks[index - 1] = text

    def _reverse_slots(self) -> None:
        """AHK: _reverseSlotsOrder -- yalniz dolu kisim ters cevrilir."""
        used = self._used_slots()
        self.blocks[:used] = list(reversed(self.blocks[:used]))
        self.select_slot(1)

    def _reverse_history(self) -> None:
        """AHK: _reverseHistoryOrder"""
        self.history.reverse()
        self.select_history(1)

    def _release_fkeys(self) -> None:
        """F1..F10 kaskadlarini sok -- Qt'de kutunun `setChecked(False)`u
        yapiyordu, sinyali de o yayiyordu."""
        if not self._fkeys_on:
            return
        self._fkeys_on = False
        if self._fkeys_box is not None:
            self._fkeys_box.value = False
        self.fkeys_toggled.emit(False)

    # -- Flet thread'i: kurulum ---------------------------------------------

    def _build(self, page: ft.Page) -> None:
        """Sayfa hazir. Denetimleri kur ve hemen goster (FLET thread'i)."""
        self._page = page
        page.title = "\U0001f9fe Hafiza Slotlari"
        page.bgcolor = theme.BG
        page.padding = 8
        page.window.width, page.window.height = SIZE
        # Qt: `WindowStaysOnTopHint`. Pencere calisirken hedef uygulamaya
        # yazilacak: altta kalirsa isini goremez.
        page.window.always_on_top = True
        # Kapatma DUSMESIN: `ft.run` doner, thread olur ve bir sonraki
        # acilis Flet'in baslama suresini yeniden odetirdi.
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        # AHK: fKeysEnabled -- default KAPALI. F1..F10 sistem geneli
        # kisayollar; kullanici istemeden ele gecirmiyoruz.
        self._fkeys_box = self._check(
            "F1-F10:  kisa=blok  orta=gecmis  uzun=kaydet",
            self._fkeys_on,
            self._on_fkeys,
        )
        allow_repeat = self._check(
            "Veri tekrarini kabul et", self._allow_repeat, self._on_allow_repeat
        )
        # AHK: middlePasteCheck -- varsayilan ACIK.
        middle = self._check(
            "Orta tus / Insert: aktif kaydi yapistir",
            self._middle_paste,
            self._on_middle,
        )

        self._slots_header = self._make_header(
            "\U0001f986 Hafiza slotlari", self._on_slots_header
        )
        self._hist_header = self._make_header(
            "\U0001f4cb Pano gecmisi", self._on_hist_header
        )
        self._slot_list = ft.ListView(controls=[], spacing=0, expand=True)
        self._hist_list = ft.ListView(controls=[], spacing=0, expand=True)

        page.controls.append(
            ft.Column(
                expand=True,
                spacing=6,
                controls=[
                    # AHK'de bu kutular iki satir x iki kolon; tek sirada
                    # dizilince pencere cok genisliyordu (Qt'de de oyle).
                    self._fkeys_box,
                    ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            allow_repeat,
                            ft.Container(expand=True),
                            ft.ElevatedButton(
                                content=ft.Text(
                                    "\U0001f5d1️ Slotlari temizle",
                                    size=TEXT_SIZE,
                                    color=theme.FG,
                                ),
                                height=30,
                                bgcolor=theme.FIELD_BG,
                                on_click=lambda _e: self.clear_slots(),
                            ),
                        ],
                    ),
                    middle,
                    self._slots_header,
                    self._column_header("Blok"),
                    self._frame(self._slot_list),
                    self._hist_header,
                    self._column_header("#"),
                    self._frame(self._hist_list),
                ],
            )
        )
        self._engine.call(self._show_now)

    @staticmethod
    def _check(
        label: str, value: bool, on_change: Callable[[ft.Event], None]
    ) -> ft.Checkbox:
        return ft.Checkbox(
            label=label,
            value=value,
            on_change=on_change,
            label_style=ft.TextStyle(color=theme.FG, size=TEXT_SIZE),
        )

    @staticmethod
    def _make_header(label: str, on_click: Callable[[], None]) -> ft.Container:
        """AHK: _activeViewerBackground -- renkli, tiklanabilir baslik seridi.

        Rengi `_paint_headers` veriyor; burada yalnizca kaliP kuruluyor.
        """
        return ft.Container(
            padding=ft.Padding(6, 4, 6, 4),
            alignment=ft.Alignment.CENTER,
            on_click=lambda _e: on_click(),
            content=ft.Text(label, color="#ffffff", size=TEXT_SIZE, weight=ft.FontWeight.BOLD),
        )

    @staticmethod
    def _column_header(first: str) -> ft.Container:
        """Tablonun sutun basligi -- Qt'de `setHorizontalHeaderLabels`."""
        return ft.Container(
            bgcolor=theme.FIELD_BG,
            padding=ft.Padding(6, 2, 6, 2),
            content=ft.Text(
                header_text(first),
                color=theme.MUTED,
                size=TEXT_SIZE,
                font_family=MONO,
                no_wrap=True,
            ),
        )

    @staticmethod
    def _frame(listing: ft.ListView) -> ft.Container:
        """Listeyi Qt'nin tablo cercevesine benzetir (fui/repository.py)."""
        return ft.Container(
            expand=True,
            bgcolor=theme.FIELD_BG,
            border=ft.Border.all(1, theme.BORDER),
            border_radius=4,
            content=listing,
        )

    # -- Flet thread'i: cizim -----------------------------------------------

    async def _show_now(self) -> None:
        """Pencereyi guncel veriyle kur ve one getir (FLET thread'i)."""
        page = self._page
        if page is None:
            return
        self._fill()
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
        """Cizime giren TEK yol. Iki thread'den de `engine.call` ile gelir."""
        page = self._page
        if page is None:
            return
        self._fill()
        page.update()

    def _fill(self) -> None:
        """Iki listeyi ve baslik seritlerini doldurur. `page.update()`
        CAGIRMAZ -- cagiran karar veriyor (acilista tek cizim yeter).

        Listeler BASTAN kuruluyor: yirmi satir (10 blok + en cok 10
        gecmis) ve satir basina uc denetim, yani olculen "bastan kurma"
        maliyetinin yuzde besi. Artimli cizim (fui/monitor.py) burada
        kazanc getirmezdi -- satirlarin sirasi da icerigi de her
        secimde degisebiliyor.
        """
        if self._slot_list is not None:
            self._slot_list.controls = [
                self._row(
                    f"F{index:02}",
                    self._slot(index),
                    selected=self._slots_active and index == self.slot_index,
                    tap=lambda i=index: self.select_slot(i),
                    double=lambda i=index: self._slot_double(i),
                )
                for index in range(1, SLOT_COUNT + 1)
            ]
        if self._hist_list is not None:
            self._hist_list.controls = [
                self._row(
                    f"F{index:02}",
                    self.history[index - 1],
                    selected=not self._slots_active and index == self.hist_index,
                    tap=lambda i=index: self.select_history(i),
                    double=lambda i=index: self._hist_double(i),
                )
                for index in range(1, len(self.history) + 1)
            ]
        self._paint_headers()

    def _row(
        self,
        label: str,
        content: str,
        selected: bool,
        tap: Callable[[], None],
        double: Callable[[], None],
    ) -> ft.GestureDetector:
        """Bir liste satiri: jest + kap + tek yazi.

        `GestureDetector` yalnizca cift tiklama icin: `Container`in
        `on_click`i tek tiklamayi goruyor ama cift tiklamayi gormuyor
        (log ve olay izleyicide bu yuzden "cift tiklama dustu"
        yazilmisti). Burada cift tiklama AHK'nin ana islevlerinden.
        """
        return ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda _e: tap(),
            on_double_tap=lambda _e: double(),
            content=ft.Container(
                bgcolor=theme.SELECT_BG if selected else None,
                padding=ft.Padding(6, ROW_PAD, 6, ROW_PAD),
                content=ft.Text(
                    row_text(label, content),
                    color=theme.FG,
                    size=TEXT_SIZE,
                    font_family=MONO,
                    no_wrap=True,
                ),
            ),
        )

    def _paint_headers(self) -> None:
        """AHK: _activeViewerBackground -- aktif liste renkli, oteki gri."""
        if self._slots_header is not None:
            self._slots_header.bgcolor = ACTIVE_SLOTS_BG if self._slots_active else IDLE_BG
        if self._hist_header is not None:
            self._hist_header.bgcolor = IDLE_BG if self._slots_active else ACTIVE_HIST_BG

    # -- Flet thread'i: olaylar ---------------------------------------------

    def _on_fkeys(self, event: ft.Event) -> None:
        """Kutu degisti: kaskadlari tak/sok. Sinyalin alicisi ana
        thread'de (`app.py`), Qt kendiliginden kuyruga aliyor."""
        self._fkeys_on = bool(event.control.value)
        self.fkeys_toggled.emit(self._fkeys_on)
        self.tip.emit(
            "\U0001f539 <b>F1-F10</b> " + ("acik" if self._fkeys_on else "kapali")
        )

    def _on_allow_repeat(self, event: ft.Event) -> None:
        self._allow_repeat = bool(event.control.value)

    def _on_middle(self, event: ft.Event) -> None:
        self._middle_paste = bool(event.control.value)

    def _slot_double(self, index: int) -> None:
        """AHK: _onSlotDoubleClick -- panoya kopyalar, yapistirmaz."""
        text = self._slot(index)
        if not text:
            return
        self.select_slot(index)
        self.copy_text.emit(text, False)
        self.tip.emit(f"\U0001f4cb {preview(text, 40)}")

    def _hist_double(self, index: int) -> None:
        """AHK: _onHistoryDoubleClick -- dogrudan yapistirir."""
        text = self._history_text(index)
        if not text:
            return
        self.select_history(index)
        self.paste_text.emit(text, False)

    def _on_slots_header(self) -> None:
        """Baslik seridine tiklama: aktif degilse aktif yapar, aktifse
        listeyi TERS cevirir. AHK'de de ayni cift islevli tiklama vardi."""
        if self._slots_active:
            self._reverse_slots()
        else:
            self.select_slot(self.slot_index)

    def _on_hist_header(self) -> None:
        if self._slots_active:
            self.select_history(self.hist_index)
        else:
            self._reverse_history()

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        if event.key == "Escape":
            self.close()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self.close()
