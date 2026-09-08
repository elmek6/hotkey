"""Kisayol haritasi -- ui/key_map_view.py'nin Flet karsiligi.

ILK TASINAN PANEL. Secilme sebebi: salt okunur. Veri tek seferde
`show_rows` ile giriyor, disari tek olay cikiyor (pencere kapandi).
Hicbir ayar yazmiyor, hicbir durum degistirmiyor -- yani gecis kirilirsa
kaybedilen sey "tablo acilmadi"dan ibaret, tuslar calismaya devam eder.

Qt surumunden farklar (bilerek):

    baslik tiklamasi   Qt'de sutun basligina tiklayip siralanabiliyordu
                       (`setSortingEnabled`). Burada YOK: siralama sabit,
                       catisanlar ustte. Asil soru "F4 bosta mi" ve cevabi
                       zaten en ustte duruyor; filtre kutusu geri kalanini
                       hallediyor.
    ilk acilis         ~3.5 saniye: Flet'in kendi istemcisi (flet.exe)
                       ayaga kalkiyor. Sonraki acilislar aninda, cunku
                       pencere kapanmiyor GIZLENIYOR (bkz. `_hide`).

Ayni kalan her sey ayni: sutun sirasi, catisanlarin kirmizi zemini,
sistem satirlarinin soluklugu, uc filtre, alt satirdaki sayac ve Esc.

ARAYUZ Qt surumuyle AYNI (`show_rows` + `closed`): app.py'de degisen tek
sey hangi sinifin kuruldugu.
"""

from __future__ import annotations

import flet as ft
from PySide6.QtCore import QObject, Signal

from keypilot.fui import theme
from keypilot.fui.engine import FletEngine

# Qt surumunden aliniyor -- saf metin isi, iki yerde tutulup birbirinden
# ayri dusmesin. O dosya silindiginde bu satir ve `owner_label` buraya
# tasinacak; gecis suresince tek kaynak eski dosya.
from keypilot.ui.key_map_view import owner_label

COLUMNS = ("Sahip", "Tus", "Aciklama", "Eylem")

WINDOW_SIZE = (920, 560)


class KeyMapPanel(QObject):
    """Kisayol tablosu. Qt'deki `KeyMapView` ile ayni arayuz.

    QObject olmasinin TEK sebebi `closed`: panel Flet thread'inde
    kapaniyor ama `ui_open` bayragini indirmek dispatcher'in `reset()`
    zincirini calistiriyor ve o zincir kilitsiz durum makinelerine
    dokunuyor. Alicisi ana thread'de olan bir Qt sinyali kendiliginden
    kuyruga alinir, yani slot Qt'nin ana thread'inde koser -- gecis
    boyunca iki motoru birbirine baglayan tek nokta burasi.
    """

    #: Pencere kapandi. app.py bunu dinleyip `ui_open`i indiriyor: pencere
    #: acikken dusuk seviye hook susturuluyor ve sinyal olmadan bir daha
    #: ACILMIYORDU -- kapattiktan sonra hicbir kisayol calismiyordu.
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._rows: tuple[tuple[str, str, str, str, bool], ...] = ()
        self._engine = FletEngine(self._build)
        # Denetimler FLET thread'inde, `_build` icinde kuruluyor; Qt
        # tarafindan yalnizca `show_rows` uzerinden dokunuluyor.
        self._page: ft.Page | None = None
        self._search: ft.TextField | None = None
        self._only_mine: ft.Checkbox | None = None
        self._conflicts_only: ft.Checkbox | None = None
        self._table: ft.DataTable | None = None
        self._status: ft.Text | None = None

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def show_rows(self, rows: tuple[tuple[str, str, str, str, bool], ...]) -> None:
        """(sahip, tus, aciklama, eylem, catisiyor_mu) satirlarini gosterir."""
        # Demet atamasi GIL altinda bolunmez: Flet thread'i ya eski ya yeni
        # demeti gorur, yarim liste gormesi mumkun degil.
        self._rows = rows
        if self._engine.page is None:
            # Sayfa yok: thread'i baslat, `_build` bu satirlarla cizecek.
            # Beklemiyoruz -- ana thread 3.5 saniye donarsa tepsi takilir.
            self._engine.start()
            return
        self._engine.call(self._show_now)

    def shutdown(self) -> None:
        """Program kapaniyor: Flet penceresini gercekten kapat.

        Qt widget'inda karsiligi yoktu -- Qt penceresi surecle birlikte
        olurdu. Flet'in istemcisi AYRI bir surec (`flet.exe`) ve kimse
        soylemezse ardimizdan gorev cubugunda kaliyor.
        """
        self._engine.stop()

    # -- Flet thread'i ------------------------------------------------------

    def _build(self, page: ft.Page) -> None:
        """Sayfa hazir. Denetimleri kur ve hemen goster (FLET thread'i)."""
        self._page = page
        page.title = "Kisayol haritasi"
        page.bgcolor = theme.BG
        page.padding = 12
        page.window.width, page.window.height = WINDOW_SIZE
        # Kapatma DUSMESIN: `ft.run` doner, thread olur ve bir sonraki
        # acilis 3.5 saniyeyi yeniden odetirdi. Kapatmayi yakalayip
        # pencereyi gizliyoruz.
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        self._search = ft.TextField(
            hint_text="ara: tus, sahip, eylem...",
            on_change=lambda _e: self._apply_and_update(),
            autofocus=True,
            dense=True,
            text_size=12,
            color=theme.FG,
            bgcolor=theme.FIELD_BG,
            border_color=theme.BORDER,
            border_radius=4,
            content_padding=8,
            expand=True,
        )
        # Sistem tuslari listenin dortte ucunu kapliyor; kullanicinin kendi
        # attigi kisayollari gormek istedigi an bu kutu isini goruyor.
        self._only_mine = ft.Checkbox(
            label="yalniz benim atadiklarim",
            value=False,
            on_change=lambda _e: self._apply_and_update(),
            label_style=ft.TextStyle(color=theme.FG, size=12),
        )
        self._conflicts_only = ft.Checkbox(
            label="yalniz catisanlar",
            value=False,
            on_change=lambda _e: self._apply_and_update(),
            label_style=ft.TextStyle(color=theme.FG, size=12),
        )
        self._table = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text(name, color=theme.MUTED, size=12)) for name in COLUMNS
            ],
            rows=[],
            heading_row_color=theme.FIELD_BG,
            heading_row_height=34,
            data_row_min_height=28,
            data_row_max_height=28,
            column_spacing=18,
            divider_thickness=0,
        )
        self._status = ft.Text("", color=theme.MUTED, size=12)

        page.controls.append(
            ft.Column(
                controls=[
                    ft.Row(
                        controls=[self._search, self._only_mine, self._conflicts_only],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    # Tablo kendi kendine kaydirmiyor; sarmalayan sutun
                    # kaydiriyor. Qt'de bu is QTableWidget'in icindeydi.
                    ft.Column(controls=[self._table], scroll=ft.ScrollMode.AUTO, expand=True),
                    self._status,
                ],
                expand=True,
            )
        )
        self._engine.call(self._show_now)

    async def _show_now(self) -> None:
        """Tabloyu tazele ve pencereyi one getir (FLET thread'i).

        `to_front` ve `focus` bu surumde coroutine: beklenmezlerse
        pencere arkada kalir ve arama kutusu odagi almaz -- hicbir hata
        vermeden.
        """
        page = self._page
        if page is None:
            return
        self._apply()
        page.window.visible = True
        page.update()
        await page.window.to_front()
        if self._search is not None:
            await self._search.focus()

    def _apply_and_update(self) -> None:
        self._apply()
        if self._page is not None:
            self._page.update()

    def _apply(self) -> None:
        """Filtreleri uygula ve satirlari yeniden kur. Qt surumuyle ayni."""
        table, status = self._table, self._status
        if table is None or status is None:
            return
        search = self._search.value if self._search is not None else ""
        query = (search or "").strip().lower()
        only_mine = bool(self._only_mine.value) if self._only_mine is not None else False
        clashes_only = (
            bool(self._conflicts_only.value) if self._conflicts_only is not None else False
        )

        rows = [
            row for row in self._rows
            if (not query or query in " ".join(row[:4]).lower())
            and (not clashes_only or row[4])
            and (not only_mine or not row[0].startswith(("keymap", "keypilot")))
        ]
        # Catisanlar once: pencerenin asil derdi onlar.
        rows.sort(key=lambda row: (not row[4], row[0], row[1]))

        table.rows = [self._data_row(row, index) for index, row in enumerate(rows)]
        clashes = sum(1 for row in rows if row[4])
        status.value = (
            f"{len(rows)} / {len(self._rows)} kisayol"
            + (f"  -  {clashes} catisma" if clashes else "  -  catisma yok")
        )

    def _data_row(self, row: tuple[str, str, str, str, bool], index: int) -> ft.DataRow:
        owner, key, desc, action, clash = row
        system = owner.startswith(("keymap", "keypilot"))
        # Sistem satirlari soluk: burada olma sebepleri okunmak degil,
        # tusun DOLU oldugunu gostermek.
        color = theme.MUTED if system else theme.FG
        return ft.DataRow(
            color=theme.CONFLICT_BG if clash else (theme.ALT_BG if index % 2 else None),
            cells=[
                ft.DataCell(ft.Text(text, color=color, size=12, no_wrap=True))
                for text in (owner_label(owner), key, desc, action)
            ],
        )

    # -- kapanis ------------------------------------------------------------

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        """Esc kapatir -- oteki pencerelerle ayni davranis."""
        if event.key == "Escape":
            self._hide()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self._hide()

    def _hide(self) -> None:
        """Pencereyi gizle, thread'i YASAT, Qt'ye kapandigini bildir."""
        page = self._page
        if page is not None:
            page.window.visible = False
            page.update()
        # Qt'nin ana thread'ine gecis: sinyal kuyruga alinir.
        self.closed.emit()
