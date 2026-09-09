"""Kod parcasi deposu -- ui/repository_view.py'nin Flet karsiligi.

DOKUZUNCU PANEL, ILK BUYUK FORM. Onceki sekizinde ekranda TEK is vardi
(bir liste, bir kutu, bir sonuc); burada uc sutun AYNI ANDA yasiyor:
solda suzgecler, ortada sonuclar, sagda secili kaydin alanlari. Kayit
alanlara doluyor, degistirilip kaydedilince listeye geri yaziliyor.

YENI OLAN TEK SEY BU: **iki yonlu akis**. Adim 7-8'de durum disaridan
gelip ekrana yaziliyordu; burada ekran kendi verisini degistiriyor ve
degisiklik ayni ekranin baska bir parcasini (sonuc listesi, kategori ve
etiket suzgecleri) yeniden kurduruyor.

    Flet (tus/tik)  -> ask_qt -> repo.search/filter (ANA THREAD, hesap)
                              -> call   -> _render_* (Flet thread'i)
    Flet (Kaydet)   -> ask_qt -> repo.update/add + repo.save (DISK)
                              -> call   -> _render_* + kutu

KURAL DEGISMEDI: `Repository` nesnesi `app.py` ile PAYLASILIYOR
(`repository.edit` komutu ve baslangicta okunan depo ayni nesne), yani
ona dokunan her satir Qt'nin ana thread'inde kosmali. Flet tarafi
yalnizca Qt'nin hazirladigi demetleri ciziyor -- `fui/qr.py`de slot
listesi icin kurulan kalibin aynisi, bu sefer bes demet.

SECIM UUID ILE: liste her suzgecte bastan kuruluyor, satir numarasi
baska kayda kayar (Qt surumunun ayni karari).

Qt surumunden farklar (bilerek):

    bolucu       Qt'de `QSplitter` vardi, sutun genisligi fareyle
                 degistirilebiliyordu. Flet'te sutunlar sabit
                 (`LEFT_W`/`MIDDLE_W`) ve saglaki genisliyor -- Qt'nin
                 acilis olculeri (250/280/gerisi) korundu.
    uyari kutusu QMessageBox yerine `ft.AlertDialog`
                 (`fui/log_view.py`de kurulan kalip).
    metin kutusu Qt `QPlainTextEdit`ti; burada cok satirli `TextField`.
                 Sarma davranisi ayni, sekmeler ve uzun satirlar da.
    kategori     "Secili satira tekrar tiklayinca secim kalkar"
                 davranisi Qt'de `ToggleList` adli bir alt sinif
                 gerektiriyordu; burada satirlar zaten elle ciziliyor,
                 tiklama isleyicisinde iki satir.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
from PySide6.QtCore import QObject, Signal

from keypilot.fui import theme
from keypilot.fui.engine import FletEngine
from keypilot.repository import Item, Repository

#: Etiket listesinin ilk satiri -- "etiket suzgeci yok" hali. Qt surumuyle
#: ayni metin ve ayni yer (KATEGORILERDE degil, ETIKETLERDE; gerekcesi
#: ui/repository_view.py dosya basinda).
TUMU = "(tumu)"

#: Pencere olcusu -- Qt: `resize(1020, 620)`.
SIZE = (1020, 620)

#: Sutun genislikleri -- Qt: `splitter.setSizes([250, 280, 470])`.
#: Ucuncu sutun genisliyor (Qt'de `setStretchFactor(2, 1)` idi).
LEFT_W = 250
MIDDLE_W = 280

TEXT_SIZE = 12

#: Bir liste satirinin ust/alt dolgusu. Qt'nin liste satiri ~20 piksel;
#: Flet'in varsayilani daha ferah, sonuc listesi bir ekrana sigmiyordu.
ROW_PAD = 3

#: Detay sutunundaki etiketler. "Etiketler" en uzun olan.
LABEL_WIDTH = 64

#: Tek satirlik giris kutulari (bkz. fui/qr.py FIELD_H): verilmezse
#: Material varsayilani ~48 piksel ve dort satirlik form pencereyi asiyor.
FIELD_H = 36

#: Giris kutularinin ortak gorunumu (fui/slot_edit.py, fui/qr.py ile ayni).
FIELD_STYLE = {
    "dense": True,
    "text_size": TEXT_SIZE,
    "color": theme.FG,
    "bgcolor": theme.FIELD_BG,
    "border_color": theme.BORDER,
    "border_radius": 4,
    "content_padding": 8,
}


def result_label(title: str, category: str) -> str:
    """Sonuc satirinin metni -- Qt: `f"{title} ({category})"`, kategorisiz
    kayitta parantez YOK."""
    return f"{title} ({category})" if category else title


class RepositoryPanel(QObject):
    """Depo penceresi. `app.py` bir kez kurup `open()` ile gosteriyor."""

    #: Pencere kapandi. Qt surumunde karsiligi yoktu (kapanisin bir
    #: alicisi yok); oteki panellerle simetri icin duruyor.
    closed = Signal()

    def __init__(self, repo: Repository) -> None:
        super().__init__()
        self.repo = repo

        # ---- suzgec durumu (ikisi de yalniz ANA THREAD'den okunur/yazilir
        # denemez: kutulardan gelen degerler Flet thread'inde atanir, tek
        # atom -- str/set/tuple yer degistirmesi GIL altinda bolunmez).
        self._query = ""
        self._category = ""
        self._tags: set[str] = set()

        # ---- Qt tarafinda hesaplanan goruntuler; Flet yalniz cizer
        self._categories: tuple[str, ...] = ()
        self._tag_rows: tuple[str, ...] = (TUMU,)
        #: (uuid, satir metni) -- sonuc listesi.
        self._shown: tuple[tuple[str, str], ...] = ()
        self._total = 0
        #: Detay panelinde duran kayit. Bos = yeni kayit (Qt ile ayni).
        self._current_uuid = ""
        #: (uuid, baslik, kategori, etiketler, metin) -- alanlara ne
        #: yazilacagi. Qt tarafinda dolduruluyor, Flet tarafinda ciziliyor.
        self._detail: tuple[str, str, str, str, str] = ("", "", "", "", "")

        self._engine = FletEngine(self._build)
        self._page: ft.Page | None = None
        self._search: ft.TextField | None = None
        self._category_list: ft.ListView | None = None
        self._tag_list: ft.ListView | None = None
        self._results: ft.ListView | None = None
        self._uuid_text: ft.Text | None = None
        self._title: ft.TextField | None = None
        self._category_edit: ft.TextField | None = None
        self._tags_edit: ft.TextField | None = None
        self._text: ft.TextField | None = None
        self._status: ft.Text | None = None
        self._dialog: ft.AlertDialog | None = None

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def open(self) -> None:
        """`repository.open` eylemi. Qt surumu gibi ONCE DISKTEN okuyor:
        depo Notepad'den de duzenlenebiliyor."""
        self._reload()
        if self._engine.page is None:
            # Sayfa yok: thread'i baslat, `_build` bu veriyle cizecek.
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

    # -- Qt thread'i: depo ve disk (`FletEngine.ask_qt` ile) ----------------

    def _reload(self) -> None:
        """Dosyayi diskten okur ve suzgecleri yeniden hesaplar.

        Qt: `reload_from_disk`. Depo nesnesi `app.py` ile paylasildigi
        icin bu satir ANA THREAD'de kosmali -- `repository.edit` komutu
        da ayni listeye yaziyor.
        """
        self.repo.load()
        self._recompute()

    def _reload_and_render(self) -> None:
        self._reload()
        self._engine.call(self._render_filters)

    def _recompute(self) -> None:
        """Suzgeci basdan uygular (Qt: `_apply_filters` + `_sync_tags`).

        SIRA ONEMLI ve Qt surumuyle ayni: once arama, sonra kategori,
        SONRA etiket listesi bu sonuctan toplaniyor, en son etiket
        suzgeci. Etiketler suzulmus kayitlardan geliyor ki listede duran
        her etiket sonucu daraltsin, hicbiri sifira dusurmesin.
        """
        items = self.repo.search(self._query)
        if self._category:
            items = self.repo.filter_category(self._category, items)
        available = sorted({tag for item in items for tag in item.tags})
        # Baglamdan dusen etiketin SECIMI DE DUSER: gorunmeyen bir suzgec
        # sonucu sessizce sifirda tutardi (Qt surumunun ayni karari).
        self._tags &= set(available)
        if self._tags:
            items = self.repo.filter_tags(sorted(self._tags), items)
        self._categories = tuple(self.repo.categories)
        self._tag_rows = (TUMU, *available)
        self._shown = tuple(
            (item.uuid, result_label(item.title, item.category)) for item in items
        )
        self._total = len(self.repo.items)

    def _filter_and_render(self) -> None:
        """Kutu/tiklama sonrasi: hesap ana thread'de, cizim Flet'te."""
        self._recompute()
        self._engine.call(self._render_filters)

    def _load_item(self, uuid: str) -> None:
        """Secilen kaydi alanlara hazirlar (ANA THREAD: `repo.get`)."""
        item = self.repo.get(uuid)
        if item is None:
            return
        self._current_uuid = item.uuid
        self._detail = (
            item.uuid,
            item.title,
            item.category,
            ", ".join(item.tags),
            item.text,
        )
        self._engine.call(self._render_detail)

    def _save_now(self, title: str, category: str, tags: list[str], text: str) -> None:
        """Qt: `save_current`. Var olan kaydi gunceller, yoksa ekler."""
        if not self.repo.update(self._current_uuid, title, category, text, tags):
            item = self.repo.add(
                Item(title=title, category=category, text=text, tags=tags)
            )
            self._current_uuid = item.uuid
        # Alanlar KULLANICININ yazdigi gibi kalsin; yalnizca UUID satiri
        # yeni kayitta degisiyor.
        self._detail = (self._current_uuid, title, category, ", ".join(tags), text)
        self._write()

    def _delete_now(self) -> None:
        """Onaydan sonra: kaydi sil, diske yaz, paneli bosalt."""
        self.repo.delete(self._current_uuid)
        self._current_uuid = ""
        self._detail = ("", "", "", "", "")
        self._write()

    def _write(self) -> None:
        """Diske yazar ve listeleri tazeler (Qt: `_write`)."""
        if not self.repo.save():
            self._engine.call(
                lambda: self._alert("Repository", "Dosya yazilamadi -- log'a bak.")
            )
            return
        self._recompute()
        self._engine.call(self._render_filters)
        self._engine.call(self._render_detail)

    # -- Flet thread'i: kurulum ---------------------------------------------

    def _build(self, page: ft.Page) -> None:
        """Sayfa hazir. Denetimleri kur ve hemen goster (FLET thread'i)."""
        self._page = page
        page.title = "\U0001f4da Repository"
        page.bgcolor = theme.BG
        page.padding = 10
        page.window.width, page.window.height = SIZE
        # Kapatma DUSMESIN: `ft.run` doner, thread olur ve bir sonraki
        # acilis Flet'in baslama suresini yeniden odetirdi.
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        self._search = ft.TextField(
            hint_text="\U0001f50e ara -- baslik, kategori ve govde icinde",
            on_change=self._on_search,
            height=FIELD_H,
            **FIELD_STYLE,
        )

        # ---- sol: kategori + etiket
        self._category_list = ft.ListView(controls=[], spacing=0, expand=True)
        self._tag_list = ft.ListView(controls=[], spacing=0, expand=True)
        left = ft.Column(
            width=LEFT_W,
            spacing=4,
            controls=[
                self._caption("Kategoriler (tekrar tiklayinca kalkar)"),
                self._frame(self._category_list),
                self._caption("Etiketler (secili kategoriden, coklu secim)"),
                self._frame(self._tag_list),
            ],
        )

        # ---- orta: sonuclar
        self._results = ft.ListView(controls=[], spacing=0, expand=True)
        middle = ft.Column(
            width=MIDDLE_W,
            spacing=4,
            controls=[self._caption("Sonuclar"), self._frame(self._results)],
        )

        # ---- sag: detaylar
        self._uuid_text = ft.Text("(yeni)", color=theme.MUTED, size=TEXT_SIZE)
        self._title = ft.TextField(height=FIELD_H, **FIELD_STYLE)
        self._category_edit = ft.TextField(height=FIELD_H, **FIELD_STYLE)
        self._tags_edit = ft.TextField(
            hint_text="virgulle ayir: tuya, zigbee", height=FIELD_H, **FIELD_STYLE
        )
        self._text = ft.TextField(
            multiline=True,
            hint_text="Govde. Ne yazarsan yaz -- kayit ayraci dosyadaki === satiri.",
            expand=True,
            **FIELD_STYLE,
        )
        right = ft.Column(
            expand=True,
            spacing=6,
            controls=[
                self._form_row("UUID", self._uuid_text),
                self._form_row("Baslik", self._title),
                self._form_row("Kategori", self._category_edit),
                self._form_row("Etiketler", self._tags_edit),
                self._caption("Metin"),
                self._text,
                ft.Row(
                    spacing=6,
                    controls=[
                        self._button("\U0001f4be Kaydet", self._save),
                        self._button("➕ Yeni", self._new_item),
                        self._button("\U0001f5d1️ Sil", self._ask_delete),
                        self._button("↺ Diskten tazele", self._reload_click),
                        self._button("Kapat", self._hide),
                    ],
                ),
            ],
        )

        self._status = ft.Text("", color=theme.MUTED, size=TEXT_SIZE)
        page.controls.append(
            ft.Column(
                expand=True,
                spacing=8,
                controls=[
                    self._search,
                    ft.Row(
                        expand=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                        controls=[left, middle, right],
                    ),
                    self._status,
                ],
            )
        )
        self._engine.call(self._show_now)

    @staticmethod
    def _caption(text: str) -> ft.Text:
        """Liste basliklari -- Qt'de duz `QLabel`di."""
        return ft.Text(text, color=theme.MUTED, size=TEXT_SIZE)

    @staticmethod
    def _frame(listing: ft.ListView) -> ft.Container:
        """Listeyi Qt'nin `QListWidget` cercevesine benzetir."""
        return ft.Container(
            expand=True,
            bgcolor=theme.FIELD_BG,
            border=ft.Border.all(1, theme.BORDER),
            border_radius=4,
            content=listing,
        )

    @staticmethod
    def _form_row(label: str, field: ft.Control) -> ft.Row:
        """QGridLayout'un bir satiri: solda etiket, sagda alan."""
        return ft.Row(
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Text(label, color=theme.MUTED, size=TEXT_SIZE, width=LABEL_WIDTH),
                ft.Container(expand=True, content=field),
            ],
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
        self._fill_filters()
        self._fill_detail()
        page.window.visible = True
        page.update()
        await page.window.to_front()

    def _hide_now(self) -> None:
        page = self._page
        if page is None:
            return
        page.window.visible = False
        page.update()

    def _render_filters(self) -> None:
        """Suzgecler + sonuc listesi (Qt: `_refresh_filters` + `_fill_results`)."""
        page = self._page
        if page is None:
            return
        self._fill_filters()
        page.update()

    def _render_detail(self) -> None:
        page = self._page
        if page is None:
            return
        self._fill_detail()
        page.update()

    def _fill_filters(self) -> None:
        """Uc listeyi ve alt satiri doldurur. `page.update()` CAGIRMAZ --
        cagiran karar veriyor (acilista tek cizim yeter)."""
        if self._category_list is not None:
            self._category_list.controls = [
                self._row(name, name == self._category, lambda n=name: self._on_category(n))
                for name in self._categories
            ]
        if self._tag_list is not None:
            self._tag_list.controls = [
                self._row(
                    name,
                    # `(tumu)` seciliyken hicbir etiket secili degil, ve
                    # tersi: ikisi BIRLIKTE isaretli kalamaz (Qt'de
                    # `_on_tags_changed` bunu elle duzeltiyordu).
                    (not self._tags) if name == TUMU else name in self._tags,
                    lambda n=name: self._on_tag(n),
                )
                for name in self._tag_rows
            ]
        if self._results is not None:
            self._results.controls = [
                self._row(label, uuid == self._current_uuid, lambda u=uuid: self._on_result(u))
                for uuid, label in self._shown
            ]
        if self._status is not None:
            self._status.value = f"{len(self._shown)} / {self._total} kayit"

    def _fill_detail(self) -> None:
        """Alanlari `_detail` ile doldurur. `page.update()` CAGIRMAZ."""
        uuid, title, category, tags, text = self._detail
        if self._uuid_text is not None:
            self._uuid_text.value = uuid or "(yeni)"
        if self._title is not None:
            self._title.value = title
        if self._category_edit is not None:
            self._category_edit.value = category
        if self._tags_edit is not None:
            self._tags_edit.value = tags
        if self._text is not None:
            self._text.value = text

    def _row(self, text: str, selected: bool, action: Callable[[], None]) -> ft.Container:
        """Bir liste satiri -- kap + tek yazi (fui/monitor.py ile ayni kalip)."""
        return ft.Container(
            data=text,
            bgcolor=theme.SELECT_BG if selected else None,
            padding=ft.Padding(6, ROW_PAD, 6, ROW_PAD),
            on_click=lambda _e: action(),
            content=ft.Text(text, color=theme.FG, size=TEXT_SIZE, no_wrap=True),
        )

    # -- Flet thread'i: olaylar ---------------------------------------------

    def _on_search(self, event: ft.ControlEvent) -> None:
        """Her tus vurusunda suzuyor (Qt: `textChanged`). Hesap Qt'de:
        depo bellekte ama nesne PAYLASILIYOR."""
        self._query = event.control.value or ""
        self._engine.ask_qt(self._filter_and_render)

    def _on_category(self, name: str) -> None:
        """Tek secim; secili satira tekrar tiklamak secimi KALDIRIR
        (Qt'de bu is icin `ToggleList` alt sinifi vardi)."""
        self._category = "" if name == self._category else name
        self._engine.ask_qt(self._filter_and_render)

    def _on_tag(self, name: str) -> None:
        """Coklu secim. `(tumu)` satiri secimi bosaltir."""
        if name == TUMU:
            self._tags = set()
        elif name in self._tags:
            self._tags = self._tags - {name}
        else:
            self._tags = self._tags | {name}
        self._engine.ask_qt(self._filter_and_render)

    def _on_result(self, uuid: str) -> None:
        self._current_uuid = uuid
        self._engine.ask_qt(lambda: self._load_item(uuid))

    def _new_item(self) -> None:
        """Detay panelini bosaltir. Kayit `Kaydet`e basilinca olusuyor --
        bos kayit listeye dusmesin (Qt: `new_item`)."""
        self._current_uuid = ""
        self._detail = ("", "", "", "", "")
        self._fill_detail()
        self._fill_filters()  # secili satirin zemini kalksin
        if self._page is not None:
            self._page.update()
        if self._title is not None:
            self._engine.call(self._title.focus)

    def _save(self) -> None:
        """Alanlari okur ve isi Qt'ye verir (Qt: `save_current`)."""
        if self._title is None or self._category_edit is None:
            return
        if self._tags_edit is None or self._text is None:
            return
        title = (self._title.value or "").strip()
        if not title:
            # Qt: `QMessageBox.warning` + baslik kutusuna odak.
            self._alert("Repository", "Baslik zorunlu.")
            self._engine.call(self._title.focus)
            return
        category = (self._category_edit.value or "").strip()
        tags = [tag.strip() for tag in (self._tags_edit.value or "").split(",") if tag.strip()]
        text = self._text.value or ""
        self._engine.ask_qt(lambda: self._save_now(title, category, tags, text))

    def _ask_delete(self) -> None:
        """Silme ONAY ister (Qt: `QMessageBox.question`)."""
        if not self._current_uuid:
            return
        _uuid, title, _category, _tags, _text = self._detail
        page = self._page
        if page is None:
            return
        self._dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Repository", color=theme.FG),
            content=ft.Text(f"Silinsin mi?\n\n{title}", color=theme.FG, size=TEXT_SIZE),
            bgcolor=theme.FIELD_BG,
            actions=[
                ft.TextButton("Evet", on_click=lambda _e: self._confirm_delete()),
                ft.TextButton("Hayir", on_click=lambda _e: self._close_dialog()),
            ],
        )
        page.show_dialog(self._dialog)

    def _confirm_delete(self) -> None:
        self._close_dialog()
        self._engine.ask_qt(self._delete_now)

    def _alert(self, title: str, message: str) -> None:
        """Tek dugmeli bilgi kutusu -- `QMessageBox.warning/critical`."""
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

    def _reload_click(self) -> None:
        """"Diskten tazele" -- dosyayi baskasi (ya da Notepad) degistirmis
        olabilir. Okuma ANA THREAD'de."""
        self._engine.ask_qt(self._reload_and_render)

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        if event.key == "Escape":
            self._hide()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self._hide()

    def _hide(self) -> None:
        self._hide_now()
        self.closed.emit()
