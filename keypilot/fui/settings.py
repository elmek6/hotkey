"""Ayar ekrani -- ui/settings_dialog.py'nin Flet karsiligi.

ONUCUNCU PANEL, ASAMA 2'NIN SONU. Gecisin en buyuk formu: ustte arama,
solda kategori, sagda ayar KARTLARI, altta toplu islem. Kart duzeninin
gerekcesi (neden tablo degil, neden deger bir NESNE, neden varsayilanda
kutu bos) Qt surumunun dosya basinda duruyor ve BURADA DA GECERLI --
tekrarlanmiyor, degistirilmiyor.

UC YENI SEY VAR:

    tipe gore denetim   Kart, ayarin TIPINE gore baska bir denetim
                        doguruyor: bool ve enum bir `ft.Dropdown`
                        (Qt'de menulu dugmeydi), sayi ve metin ise
                        cerceveli bir kutunun icinde `TextField` +
                        sifirlama + silik varsayilan. Kartlar suzgec
                        her degistiginde SIFIRDAN kuruluyor
                        (`fui/qr.py`de dogan kalip, bu sefer 26 kart).
    her `set()` Qt'de   Ayar degistirmek yalniz bir degeri yazmak DEGIL:
                        `Setting.set` abonelere haber veriyor ve
                        aboneler Qt'ye dokunuyor (`theme.apply`
                        `QApplication`in paletini degistiriyor,
                        `autostart.sync` kayit defterine yaziyor).
                        Yani Flet tarafi HICBIR degeri kendi yazmiyor;
                        her tiklama `ask_qt` ile ana thread'e dusuyor.
    tek kart tazeleme   Degisiklikten sonra liste YENIDEN KURULMUYOR --
                        yalnizca o kart tazeleniyor. Qt'deki gerekce
                        ("kullanici bir menudeyken altindaki nesneyi
                        silme") Flet'te de aynen gecerli: yazi
                        kutusunun altindan denetimi cekmek yazilani
                        goturur.

TEMA. Plan bu adima "tema secimi burada" diye not dusmustu. Ayarin
KENDISI burada ve calisiyor (`app.theme` -> `keypilot/theme.py` ->
Qt paleti), ama **Flet panelleri koyu SABIT kaliyor** (`fui/theme.py`).
Sebep olculdu: renkler denetimlere KURULURKEN giriyor (`_build` bir kez
kosuyor ve panel bir daha yok edilmiyor, gizleniyor), panel basina ayri
bir `flet.exe` var ve on iki panelin bir kismi kendi sabit renklerini
tasiyor (`fui/clip_images.py` `PREVIEW_BG`, `fui/monitor.py` satir
renkleri). Yani "acik tema" on iki panelin hepsinin elden gecirilmesi
demek -- ayri bir is, plana yazildi. Panel bunu SOYLUYOR: tema
degistirilince alt satirda uyari cikiyor, kullanici Flet pencerelerinin
neden degismedigini aramasin.

Qt surumunden farklar (bilerek):

    menu -> acilir kutu  Qt deger dugmesine basinca bir `QMenu`
                         aciyordu (secilide tik, varsayilan KALIN).
                         Flet'te menu denetimi bu ise oturmuyor;
                         `ft.Dropdown` ayni isi yapiyor -- secili deger
                         kutunun uzerinde yaziyor, varsayilan listede
                         KALIN duruyor. Tik isareti Dropdown'in kendi
                         isi.
    kaydirma alani       Qt `QScrollArea` + dikey yerlesim; burada
                         `ft.ListView`. Kartlar arasi bosluk ayni.
    ayrac cizgisi        Kategori listesindeki cizgi Qt'de
                         `QListWidgetItem` + `QFrame` idi; burada
                         `ft.Divider`.
    kart cercevesi       Qt stylesheet ile `palette(base)` uzerine
                         cizdiriyordu (tema izleme). Burada `fui/theme`
                         renkleri -- yukarida.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field, replace

import flet as ft
from PySide6.QtCore import QObject, Signal

from keypilot import paths
from keypilot.fui import theme
from keypilot.fui.engine import FletEngine
from keypilot.settings import SETTINGS, Category, Setting

log = logging.getLogger("keypilot.fui.settings")

#: Kategori listesinin son satiri -- Qt ile ayni metin.
ALL_LABEL = "Tümü"

#: Ret gerekcesinin rengi -- `ui/settings_dialog.py` ile ayni deger.
INVALID_COLOR = "#da3633"

#: Pencere olcusu -- Qt: `resize(860, 560)`.
SIZE = (860, 560)

#: Kategori sutunu -- Qt: `setFixedWidth(180)`.
LEFT_W = 180

#: Deger nesnesinin genisligi: tip ne olursa olsun AYNI, cunku hepsi
#: kartlarin en saginda ayni sutunda duruyor (Qt: VALUE_WIDTH).
VALUE_W = 170
#: Ortadaki bilgi hucresi -- yazisi olmayan ayarda BOS ARA olarak duruyor
#: ki deger sutunu yerinden oynamasin (Qt: INFO_WIDTH).
INFO_W = 150
#: Kutunun ICINDEKI sifirlama dugmesi -- kare, yalniz isaret.
RESET_W = 26

TEXT_SIZE = 12
#: Aciklama satiri -- Qt'de `desc` etiketiydi, kartin ikinci satiri.
DESC_SIZE = 11

#: Tek satirlik giris kutulari (bkz. fui/qr.py FIELD_H).
FIELD_H = 30

#: Bir liste satirinin ust/alt dolgusu (oteki panellerle ayni).
ROW_PAD = 3

#: Yazi kutusunun ortak gorunumu. Cerceve YOK: kutunun cercevesi
#: SARMALAYAN kapta (Qt'de de oyleydi -- deger, sifirlama ve varsayilan
#: TEK bir kutu gibi okunmali).
FIELD_STYLE = {
    "dense": True,
    "text_size": TEXT_SIZE,
    "color": theme.FG,
    "bgcolor": theme.FIELD_BG,
    "border": ft.InputBorder.NONE,
    "content_padding": 6,
}

#: Acilir kutunun gorunumu -- oteki panellerdeki kalibin ayni.
DROP_STYLE = {
    "dense": True,
    "text_size": TEXT_SIZE,
    "color": theme.FG,
    "bgcolor": theme.FIELD_BG,
    "border_color": theme.BORDER,
    "border_radius": 4,
    "content_padding": 6,
}

#: Menulu tipler -- ikisi de "sayili secenek", yerinde yazilmiyor.
MENU_KINDS = ("bool", "enum")

#: `bool`un iki secenegi. Ayri bir tip degil, iki elemanli bir liste gibi
#: davraniyor (Qt: `_choices`).
BOOL_CHOICES = (("true", "acik"), ("false", "kapali"))

#: Tema degistirilince alt satirda cikan uyari. Ayar GERCEKTEN
#: uygulaniyor -- yalnizca Qt pencerelerinde (bkz. dosya basi).
THEME_NOTE = "Tema Qt pencerelerinde uygulandi; Flet panelleri koyu sabit."


def bool_label(value: bool) -> str:
    """Qt: `_label` -- acik/kapali."""
    return "acik" if value else "kapali"


def choice_rows(item: Setting) -> tuple[tuple[str, str, bool], ...]:
    """Menulu tipin secenekleri: (ham deger, gorunen ad, varsayilan mi).

    Ham deger METIN olarak tasiniyor: Flet'ten geri gelen sey de metin ve
    `Setting.coerce` iki tipi de (bool "true"/"false", enum kimligi)
    kendi cozuyor.
    """
    if item.type_of() == "bool":
        return tuple(
            (raw, label, (raw == "true") == bool(item.default))
            for raw, label in BOOL_CHOICES
        )
    return tuple(
        (str(choice), item.label_for(choice), choice == item.default)
        for choice in item.choices
    )


def current_choice(item: Setting) -> str:
    """Menulu tipin SECILI ham degeri (`choice_rows` ile ayni dilde)."""
    if item.type_of() == "bool":
        return "true" if item.get() else "false"
    return str(item.get())


def value_text(item: Setting) -> str:
    """Sayi/metin kutusunda duracak yazi.

    VARSAYILANDA KUTU BOS (Qt `refresh`): ayni sayi hem solda hem sagda
    durunca iki farkli sey gibi okunuyordu ve bos kutu ayrica "buraya
    yazilir" diyor.
    """
    return str(item.get()) if item.is_changed() else ""


def status_text(shown: int, changed: int) -> str:
    """Alt satir -- Qt: `_update_status`."""
    return f"{shown} ayar, {changed} degismis"


@dataclass(frozen=True)
class CatRow:
    """Kategori listesinin bir satiri. `separator` ise tiklanamaz cizgi."""

    key: str
    label: str
    separator: bool = False


def category_rows() -> tuple[CatRow, ...]:
    """Kategoriler, ayracin ALTINDA GELISTIRME ve "Tümü" (Qt ile ayni sira).

    Gerekce Qt surumunde: "Tümü" bir kategori DEGIL, suzgeci kaldirmak;
    GELISTIRME de gunluk ayar degil -- ikisi de gunluk kategorilerin
    arasinda durmamali.
    """
    rows = [
        CatRow(name, f"{Category.label(name)} ({len(SETTINGS.visible_in(name))})")
        for name in SETTINGS.categories
        if name != Category.DEVELOPMENT
    ]
    rows.append(CatRow("", "", separator=True))
    if Category.DEVELOPMENT in SETTINGS.categories:
        rows.append(
            CatRow(
                Category.DEVELOPMENT,
                f"{Category.label(Category.DEVELOPMENT)} "
                f"({len(SETTINGS.visible_in(Category.DEVELOPMENT))})",
            )
        )
    rows.append(CatRow("", f"{ALL_LABEL} ({len(SETTINGS.visible)})"))
    return tuple(rows)


@dataclass(frozen=True)
class Card:
    """Bir ayarin CIZILECEK hali. Qt tarafinda hazirlanir, Flet cizer."""

    key: str
    name: str
    info: str
    desc: str
    kind: str
    changed: bool
    #: Menulu tip: secili ham deger + secenekler. Otekilerde bos.
    choice: str = ""
    choices: tuple[tuple[str, str, bool], ...] = ()
    #: Sayi/metin tipi: kutudaki yazi ve silik varsayilan.
    text: str = ""
    default: str = ""
    #: Ret gerekcesi -- doluysa bilgi hucresi KIRMIZI yaniyor.
    invalid: str = ""
    #: Kartin ustunde kategori basligi (yalniz suzgecsiz listede).
    group: str = ""


def card_of(item: Setting, invalid: str = "", group: str = "") -> Card:
    """Ayardan kart goruntusu uretir (ANA THREAD)."""
    kind = item.type_of()
    menulu = kind in MENU_KINDS
    return Card(
        key=item.key,
        name=item.name,
        # Gecersiz degerde Qt bilgi hucresine RET GEREKCESINI yaziyordu --
        # bilgisi olmayan ayarda o bos hucre isi gorsun.
        info=item.info_text() or invalid,
        desc=item.desc or item.key,
        kind=kind,
        changed=item.is_changed(),
        choice=current_choice(item) if menulu else "",
        choices=choice_rows(item) if menulu else (),
        text="" if menulu else value_text(item),
        default="" if menulu else str(item.default),
        invalid=invalid,
        group=group,
    )


@dataclass
class CardRefs:
    """Bir kartin CANLI denetimleri -- tek kart tazelemek icin (Qt:
    `SettingCard.refresh`). Liste yeniden kurulunca bunlar da yenilenir."""

    info: ft.Text
    value: ft.Control
    reset: ft.Control | None = None
    default: ft.Text | None = None


@dataclass
class _State:
    """Qt tarafinda hesaplanan goruntu -- Flet yalniz cizer."""

    cards: tuple[Card, ...] = ()
    categories: tuple[CatRow, ...] = ()
    status: str = ""
    note: str = ""
    invalid: dict[str, str] = field(default_factory=dict)


class SettingsPanel(QObject):
    """Ayar penceresi. `app.py` bir kez kurup `show_dialog()` ile gosteriyor.

    Disari acilan yuz Qt surumuyle AYNI (`show_dialog`), yani `app.py`de
    degisen tek sey hangi sinifin kuruldugu.
    """

    #: Pencere gizlendi. Qt surumunde karsiligi yoktu (kapanisin bir
    #: alicisi yok); oteki panellerle simetri icin duruyor.
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._state = _State()
        #: Suzgec durumu. Flet thread'i yazar, Qt thread'i okur -- ikisi de
        #: TEK ATOM (fui/repository.py'deki ayni kural).
        self._query = ""
        self._category = ""

        self._engine = FletEngine(self._build)
        self._page: ft.Page | None = None
        self._search: ft.TextField | None = None
        self._cat_list: ft.ListView | None = None
        self._cards: ft.ListView | None = None
        self._status: ft.Text | None = None
        self._dialog: ft.AlertDialog | None = None
        #: Anahtar -> o kartin canli denetimleri.
        self._refs: dict[str, CardRefs] = {}

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def show_dialog(self) -> None:
        """`app.settings` eylemi -- Qt surumuyle ayni ad ve ayni is."""
        self._recompute()
        if self._engine.page is None:
            # Sayfa yok: thread'i baslat, `_build` bu veriyle cizecek.
            # Beklemiyoruz -- ana thread 3.5 saniye donarsa tepsi takilir.
            self._engine.start()
            return
        self._engine.call(self._show_now)

    def close(self) -> None:
        """Pencereyi gizle. `app.py` `_shutdown` bunu cagiriyor."""
        self._save()
        self._engine.call(self._hide_now)

    def shutdown(self) -> None:
        """Program kapaniyor: Flet istemcisini (`flet.exe`) gercekten kapat."""
        self._engine.stop()

    # -- Qt thread'i: ayar defteri ve disk (`FletEngine.ask_qt` ile) --------

    def _recompute(self) -> None:
        """Suzgeci bastan uygular (Qt: `_refresh`). ANA THREAD.

        SIRA Qt surumuyle ayni: once arama, sonra kategori. Arama varken
        kategori suzgeci DEVRE DISI (AHK ile ayni karar) -- arama zaten
        butun ayarlarin icinde geziyor.
        """
        items = SETTINGS.search(self._query)
        if self._query:
            self._category = ""
        if self._category:
            items = [item for item in items if item.category == self._category]

        # KATEGORI BASLIGI yalnizca suzgec YOKKEN: tek kategoriye bakarken
        # ayni basligi kirk kez tekrarlamak gurultu (Qt'deki `grouped`).
        grouped = not self._category
        invalid = self._state.invalid
        cards: list[Card] = []
        seen = ""
        for item in items:
            group = ""
            if grouped and item.category != seen:
                seen = item.category
                group = Category.label(item.category)
            cards.append(card_of(item, invalid.get(item.key, ""), group))

        changed = sum(item.is_changed() for item in items)
        self._state = _State(
            cards=tuple(cards),
            categories=category_rows(),
            status=status_text(len(cards), changed),
            note=self._state.note,
            invalid=invalid,
        )

    def _filter_and_render(self) -> None:
        """Kutu/tiklama sonrasi: hesap ana thread'de, cizim Flet'te."""
        self._recompute()
        self._engine.call(self._render_all)

    def _apply_choice(self, key: str, raw: str) -> None:
        """Menuden secilen deger (ANA THREAD -- aboneler Qt'ye dokunuyor)."""
        item = SETTINGS.by_key.get(key)
        if item is None:
            return
        message = item.set(raw)
        if message:
            # Menuden gelen deger dogrulayiciya takildi: nadir. Qt burada
            # `QMessageBox.warning` aciyordu.
            self._engine.call(lambda: self._alert("Ayarlar", message))
        self._after_change(item, "" if message else self._note_for(item))

    def _apply_typed(self, key: str, text: str) -> None:
        """Kutuya yazilan sayi/metin (ANA THREAD).

        BOS = varsayilan (Qt `_typed`): kutu varsayilandayken zaten bos
        duruyor, yani yazdigini silmek gorunuse de uyan bir geri alma.
        Gecersiz degerde YAZDIGIN YERINDE KALIR ve bilgi hucresi kirmizi
        yanar -- neyi yanlis yazdigini gorebilesin.
        """
        item = SETTINGS.by_key.get(key)
        if item is None:
            return
        text = text.strip()
        message = item.reset() if not text else item.set(text)
        invalid = dict(self._state.invalid)
        if message:
            invalid[key] = message
        else:
            invalid.pop(key, None)
        self._state.invalid = invalid
        self._after_change(item, "" if message else self._note_for(item), keep_text=bool(message))

    def _reset_one(self, key: str) -> None:
        """Kutunun icindeki `↺` -- varsayilani geri yaz."""
        item = SETTINGS.by_key.get(key)
        if item is None:
            return
        item.reset()
        invalid = dict(self._state.invalid)
        invalid.pop(key, None)
        self._state.invalid = invalid
        self._after_change(item, self._note_for(item))

    @staticmethod
    def _note_for(item: Setting) -> str:
        """Degisiklikten sonra alt satirda duracak not (varsa)."""
        return THEME_NOTE if item.key == "app.theme" else ""

    def _after_change(self, item: Setting, note: str, keep_text: bool = False) -> None:
        """Tek kart + alt satir tazelenir; LISTE YENIDEN KURULMAZ.

        Qt'deki gerekce aynen gecerli (`_on_card_change`): kullanici o an
        yazi kutusunda ya da acilir kutuda olabilir, altindan denetim
        cekilmemeli. Sayilar (kac ayar degismis) yine de guncelleniyor.

        `keep_text` gecersiz degerde geliyor: kartin kendisi yine
        tazeleniyor (kalinlik, sifirlama dugmesi, kirmizi bilgi) ama
        cizim yazi kutusuna DOKUNMUYOR -- kullanicinin yazdigi kalsin.
        """
        fresh = card_of(item, self._state.invalid.get(item.key, ""))
        self._state.cards = tuple(
            replace(fresh, group=row.group) if row.key == item.key else row
            for row in self._state.cards
        )
        self._state.status = status_text(
            len(self._state.cards), sum(row.changed for row in self._state.cards)
        )
        self._state.note = note
        self._engine.call(lambda: self._render_card(item.key, keep_text))

    def _reset_all_now(self) -> None:
        """Toplu sifirlama (Qt: `_reset_all` -- onaydan sonra)."""
        item = SETTINGS.by_key.get("app.theme")
        before = item.get() if item is not None else None
        SETTINGS.reset_all()
        self._state.invalid = {}
        self._recompute()
        # Uyari yalnizca tema GERCEKTEN degistiyse: her sifirlamada
        # cikan bir not okunmaz olurdu.
        self._state.note = THEME_NOTE if item is not None and item.get() != before else ""
        self._engine.call(self._render_all)

    def _open_json_now(self) -> None:
        """AHK ile ayni: once diske yaz, sonra Notepad ile ac (ANA THREAD)."""
        SETTINGS.save_now(paths.SETTINGS)
        subprocess.Popen(["notepad.exe", str(paths.SETTINGS)])  # noqa: S603, S607

    @staticmethod
    def _save() -> None:
        """Kapanista kaydet -- Qt: `closeEvent`. Ekran acikken her
        degisiklikte diske yazmak gereksiz."""
        SETTINGS.save(paths.SETTINGS)

    # -- Flet thread'i: kurulum ---------------------------------------------

    def _build(self, page: ft.Page) -> None:
        """Sayfa hazir. Denetimleri kur ve hemen goster (FLET thread'i)."""
        self._page = page
        page.title = "⚙️ Ayarlar"
        page.bgcolor = theme.BG
        page.padding = 10
        page.window.width, page.window.height = SIZE
        # Kapatma DUSMESIN: `ft.run` doner, thread olur ve bir sonraki
        # acilis Flet'in baslama suresini yeniden odetirdi.
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        self._search = ft.TextField(
            hint_text="\U0001f50e ara (bosluk = ve)",
            on_change=self._on_search,
            height=FIELD_H + 6,
            dense=True,
            text_size=TEXT_SIZE,
            color=theme.FG,
            bgcolor=theme.FIELD_BG,
            border_color=theme.BORDER,
            border_radius=4,
            content_padding=8,
        )
        self._cat_list = ft.ListView(controls=[], spacing=0, expand=True)
        self._cards = ft.ListView(controls=[], spacing=6, expand=True)
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
                        controls=[
                            ft.Container(width=LEFT_W, content=self._cat_list),
                            self._cards,
                        ],
                    ),
                    ft.Row(
                        spacing=6,
                        controls=[
                            ft.Container(expand=True, content=self._status),
                            self._button("↺ Tumu varsayilana", self._ask_reset_all),
                            self._button("\U0001f4dd settings.json", self._open_json),
                            self._button("Kapat", self._hide),
                        ],
                    ),
                ],
            )
        )
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
        """Pencereyi Qt tarafinin hazirladigi veriyle kur ve one getir."""
        page = self._page
        if page is None:
            return
        self._fill_all()
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
        page = self._page
        if page is None:
            return
        self._fill_all()
        page.update()

    def _fill_all(self) -> None:
        """Kategori listesi + kartlar + alt satir. `page.update()` CAGIRMAZ."""
        state = self._state
        if self._cat_list is not None:
            self._cat_list.controls = [
                ft.Divider(height=9, color=theme.BORDER)
                if row.separator
                else self._cat_row(row)
                for row in state.categories
            ]
        if self._cards is not None:
            self._refs = {}
            controls: list[ft.Control] = []
            for card in state.cards:
                if card.group:
                    controls.append(self._group_header(card.group))
                controls.append(self._card(card))
            self._cards.controls = controls
        self._fill_status()

    def _fill_status(self) -> None:
        if self._status is None:
            return
        note = self._state.note
        self._status.value = f"{self._state.status}   ·   {note}" if note else self._state.status

    def _render_card(self, key: str, keep_text: bool) -> None:
        """Tek kartin denetimlerini ayarin o anki degerine getirir
        (Qt: `SettingCard.refresh`)."""
        page = self._page
        refs = self._refs.get(key)
        card = next((row for row in self._state.cards if row.key == key), None)
        if page is None or refs is None or card is None:
            return
        refs.info.value = card.info
        refs.info.color = INVALID_COLOR if card.invalid else theme.MUTED
        if isinstance(refs.value, ft.Dropdown):
            refs.value.value = card.choice
            refs.value.text_style = self._value_style(card.changed)
        elif isinstance(refs.value, ft.TextField):
            refs.value.text_style = self._value_style(card.changed)
            if not keep_text:
                # Gecersiz degerde kutuya DOKUNULMUYOR: yazdigi kalsin.
                refs.value.value = card.text
        if refs.reset is not None:
            refs.reset.disabled = not card.changed
        if refs.default is not None:
            refs.default.value = card.default
        self._fill_status()
        page.update()

    @staticmethod
    def _value_style(changed: bool) -> ft.TextStyle:
        """Degismis ayarin degeri KALIN (AHK ve Qt ile ayni isaret)."""
        return ft.TextStyle(
            size=TEXT_SIZE,
            color=theme.FG,
            weight=ft.FontWeight.BOLD if changed else ft.FontWeight.NORMAL,
        )

    def _cat_row(self, row: CatRow) -> ft.Container:
        """Kategori satiri. Secili olan mavi zeminli (oteki panellerle ayni)."""
        return ft.Container(
            # "Tümü" satirinin anahtari da bos: `_category` bosken
            # secili gorunen O satir olur -- Qt'de de oyleydi.
            bgcolor=theme.SELECT_BG if row.key == self._category else None,
            padding=ft.Padding(6, ROW_PAD, 6, ROW_PAD),
            on_click=lambda _e, key=row.key: self._on_category(key),
            content=ft.Text(row.label, color=theme.FG, size=TEXT_SIZE, no_wrap=True),
        )

    @staticmethod
    def _group_header(label: str) -> ft.Text:
        """Kartlarin arasindaki kategori basligi -- soldaki listedeki adin
        AYNISI (Qt: `_group_header`)."""
        return ft.Text(
            label,
            color=theme.MUTED,
            size=TEXT_SIZE,
            weight=ft.FontWeight.BOLD,
        )

    def _card(self, card: Card) -> ft.Container:
        """Tek ayar karti: ust satir (ad | bilgi | deger) + aciklama."""
        info = ft.Text(
            card.info,
            color=INVALID_COLOR if card.invalid else theme.MUTED,
            size=TEXT_SIZE,
            width=INFO_W,
            text_align=ft.TextAlign.CENTER,
        )
        value = self._value_control(card)
        refs = CardRefs(info=info, value=value)
        box = self._value_box(card, value, refs)
        self._refs[card.key] = refs
        return ft.Container(
            bgcolor=theme.FIELD_BG,
            border=ft.Border.all(1, theme.BORDER),
            border_radius=6,
            padding=ft.Padding(10, 8, 10, 8),
            content=ft.Column(
                spacing=4,
                controls=[
                    ft.Row(
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Container(
                                expand=True,
                                content=ft.Text(card.name, color=theme.FG, size=TEXT_SIZE),
                            ),
                            info,
                            box,
                        ],
                    ),
                    ft.Text(card.desc, color=theme.MUTED, size=DESC_SIZE),
                ],
            ),
        )

    def _value_control(self, card: Card) -> ft.Control:
        """Tipin nesnesi: acilir kutu ya da yazi kutusu (Qt: `_make_value`)."""
        if card.kind in MENU_KINDS:
            return ft.Dropdown(
                value=card.choice,
                options=[
                    ft.DropdownOption(
                        key=raw,
                        # VARSAYILAN KALIN -- Qt menusundeki ayni isaret:
                        # "dokunmasaydim ne olurdu" sorusunun cevabi.
                        content=ft.Text(
                            label,
                            size=TEXT_SIZE,
                            color=theme.FG,
                            weight=ft.FontWeight.BOLD if is_default else ft.FontWeight.NORMAL,
                        ),
                    )
                    for raw, label, is_default in card.choices
                ],
                text_style=self._value_style(card.changed),
                width=VALUE_W,
                height=FIELD_H,
                on_select=lambda _e, key=card.key: self._on_choice(key),
                **DROP_STYLE,
            )
        return ft.TextField(
            value=card.text,
            text_style=self._value_style(card.changed),
            expand=True,
            height=FIELD_H,
            # Enter ya da odagi birakmak: iki yol da ayni seyi yapmali
            # (Qt: `editingFinished`).
            on_submit=lambda _e, key=card.key: self._on_typed(key),
            on_blur=lambda _e, key=card.key: self._on_typed(key),
            **FIELD_STYLE,
        )

    def _value_box(self, card: Card, value: ft.Control, refs: CardRefs) -> ft.Control:
        """Yazi kutusunu KUTUYA sarar: deger | `↺` | silik varsayilan.

        Ucu de kutunun ICINDE ve kutu VALUE_W: kartlar arasi hiza
        korunuyor (Qt: `_wrap_value`). MENULU TIPTE KUTU YOK -- acilir
        kutunun kendisi zaten bir kutu ve varsayilani listede KALIN
        duruyor.
        """
        if card.kind in MENU_KINDS:
            return value
        reset = ft.TextButton(
            content=ft.Text("↺", size=TEXT_SIZE, color=theme.FG),
            width=RESET_W,
            disabled=not card.changed,
            on_click=lambda _e, key=card.key: self._on_reset(key),
        )
        default = ft.Text(card.default, color=theme.MUTED, size=DESC_SIZE)
        refs.reset = reset
        refs.default = default
        return ft.Container(
            width=VALUE_W,
            height=FIELD_H,
            bgcolor=theme.BG,
            border=ft.Border.all(1, theme.BORDER),
            border_radius=4,
            padding=ft.Padding(4, 0, 4, 0),
            content=ft.Row(
                spacing=2,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                # ESNEYEN yalniz DEGER; isaret ile varsayilan yan yana,
                # sagda (Qt'deki ayni karar).
                controls=[value, reset, default],
            ),
        )

    # -- Flet thread'i: olaylar ---------------------------------------------

    def _on_search(self, event: ft.ControlEvent) -> None:
        """Her tus vurusunda suzuyor (Qt: `textChanged`). Hesap Qt'de:
        ayar defteri program genelinde PAYLASILIYOR."""
        self._query = event.control.value or ""
        if self._query:
            self._category = ""
        self._engine.ask_qt(self._filter_and_render)

    def _on_category(self, key: str) -> None:
        """Kategori satiri. Arama kutusu doluysa Qt tarafi zaten suzgeci
        kaldiriyor -- burada yalnizca secim degisiyor."""
        self._category = key
        self._engine.ask_qt(self._filter_and_render)

    def _on_choice(self, key: str) -> None:
        refs = self._refs.get(key)
        if refs is None or not isinstance(refs.value, ft.Dropdown):
            return
        raw = refs.value.value or ""
        self._engine.ask_qt(lambda: self._apply_choice(key, raw))

    def _on_typed(self, key: str) -> None:
        refs = self._refs.get(key)
        if refs is None or not isinstance(refs.value, ft.TextField):
            return
        text = refs.value.value or ""
        self._engine.ask_qt(lambda: self._apply_typed(key, text))

    def _on_reset(self, key: str) -> None:
        self._engine.ask_qt(lambda: self._reset_one(key))

    def _ask_reset_all(self) -> None:
        """Toplu sifirlama ONAY ister (Qt: `QMessageBox.question`)."""
        page = self._page
        if page is None:
            return
        self._dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Ayarlar", color=theme.FG),
            content=ft.Text(
                "Tum ayarlar varsayilana donecek. Devam?",
                color=theme.FG,
                size=TEXT_SIZE,
            ),
            bgcolor=theme.FIELD_BG,
            actions=[
                ft.TextButton("Evet", on_click=lambda _e: self._confirm_reset_all()),
                ft.TextButton("Hayir", on_click=lambda _e: self._close_dialog()),
            ],
        )
        page.show_dialog(self._dialog)

    def _confirm_reset_all(self) -> None:
        self._close_dialog()
        self._engine.ask_qt(self._reset_all_now)

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

    def _open_json(self) -> None:
        self._engine.ask_qt(self._open_json_now)

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        if event.key == "Escape":
            self._hide()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self._hide()

    def _hide(self) -> None:
        """Pencereyi gizle, thread'i YASAT, ayarlari DISKE yaz.

        Kaydetme Qt tarafinda: `Registry.save` dosyaya yaziyor ve defter
        program genelinde paylasiliyor.
        """
        self._hide_now()
        self._engine.ask_qt(self._save)
        self.closed.emit()


# TODO(gecis): tema yalnizca Qt pencerelerinde uygulaniyor; Flet panelleri
#     koyu sabit (`fui/theme.py`). Gerekce dosya basinda, is plana yazildi.
