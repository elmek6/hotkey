"""Profil yoneticisi -- ui/profiles_view.py'nin Flet karsiligi.

ON BIRINCI PANEL (adim 10 karara baglanamadigi icin ondan once bitti).
Adim 9'un (`fui/repository.py`) uc sutunlu kalibi burada IKI KADEMELI:
solda profiller, ortada SECILI PROFILIN aksiyonlari, sagda SECILI
AKSIYONUN alanlari. Yani bir listedeki secim oteki listeyi kuruyor.

YENI OLAN SEY BU DEGIL. Yeni olan, panelin **Flet'in yapamadigi bir isi
Qt'ye yaptirmasi**: kisayol yakalama.

    Kisayol kutusu -> ask_qt -> Qt'de kucuk bir pencere (KeyCapture)
                             -> tus VK koduyla okunur
                             -> call -> alanlara yazilir

`ft.KeyboardEvent` Windows sanal tus kodunu (VK) VERMIYOR; programin
geri kalani (keynames, hotkey, dispatch) VK ile konusuyor ve F13/F14
gibi klavyede olmayan tuslar ancak oradan dogru adlaniyor (plan, Asama 3
#16 tam bu). O yuzden yakalama kutusu Qt'de KALDI --
`fui/qr.py`deki `QFileDialog` ile ayni gerekce ve ayni gecici cozum
(`FletEngine.ask_qt`, bkz. **QT'YE IS YAPTIRMA kurali**).

DEPO PAYLASILIYOR: `ShortcutStore` nesnesi `app.py` ile ayni
(`self.shorts`) -- F13 menusu, kayit defteri baglamalari ve bu pencere
ayni listeyi okuyor. Bu yuzden ona dokunan HER satir Qt'nin ana
thread'inde kosuyor (`ask_qt`); Flet tarafi yalnizca Qt'nin hazirladigi
demetleri ciziyor (`fui/repository.py`de kurulan kalip).

Qt surumunden farklar (bilerek):

    bolucu       Qt'de `QSplitter` vardi (sutun genisligi fareyle
                 degisiyordu); burada sutunlar sabit, Qt'nin acilis
                 olculeri (330/250/gerisi) korundu.
    kutular      `QMessageBox` yerine `ft.AlertDialog`.
    kisayol      Qt'de kutunun kendisi tusu yakaliyordu; burada kutuya
                 tiklayinca Qt tarafinda kucuk bir pencere aciliyor
                 (yukaridaki gerekce). Yakalama kurallari AYNEN ayni --
                 Esc iptal, Backspace/Delete siler, tek basina modifier
                 kabul edilmez (`ui/key_capture.py`).
    imlec ekrani Qt penceresi `ui/place.py` ile calisilan monitore
                 ortalaniyordu; Flet penceresi kendi yerinde aciliyor
                 (oteki dokuz panelle ayni kayip). Yakalama kutusu Qt
                 oldugu icin O hala imlecin ekraninda aciliyor.

PENCERE KAPANMIYOR, GIZLENIYOR (oteki paneller gibi).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import flet as ft
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from keypilot.app_shorts import AppProfile, ShortCut, ShortcutStore, stroke_kind
from keypilot.fui import theme
from keypilot.fui.engine import FletEngine
from keypilot.ui.key_capture import KeyCapture
from keypilot.ui.place import center_on_cursor_screen

#: "Kayit YOK" -- Qt surumundeki `YENI` ile ayni anlam ve ayni deger.
YENI = -1

#: Pencere olcusu -- Qt: `resize(1000, 600)`. Genislik birebir,
#: yukseklik degil (flet-plan.md **PENCERE OLCUSU kurali**).
SIZE = (1000, 660)

#: Sutun genislikleri -- Qt: `splitter.setSizes([330, 250, 400])`,
#: ucuncu sutun genisliyor (`setStretchFactor(2, 1)`).
LEFT_W = 330
MIDDLE_W = 250

TEXT_SIZE = 12

#: Bir liste satirinin ust/alt dolgusu (fui/repository.py ile ayni).
ROW_PAD = 3

#: Form etiketlerinin genisligi. "Pencere sinifi" en uzun olan.
LABEL_WIDTH = 92

#: Tek satirlik giris kutulari: verilmezse Material varsayilani ~48
#: piksel ve uc satirlik form pencereyi asiyor (fui/repository.py).
FIELD_H = 36

#: Giris kutularinin ortak gorunumu (oteki panellerle ayni).
FIELD_STYLE = {
    "dense": True,
    "text_size": TEXT_SIZE,
    "color": theme.FG,
    "bgcolor": theme.FIELD_BG,
    "border_color": theme.BORDER,
    "border_radius": 4,
    "content_padding": 8,
}

#: Kisayolu olmayan aksiyonun kutusunda yazan sey (Qt: KeyCapture
#: `"kisayol yok"`).
NO_KEY = "kisayol yok"


def rule_text(class_name: str, title: str) -> str:
    """Eslesme kuralini duz Turkce yazar (Qt: `_update_rule`).

    AHK'de bu bilgi YOKTU; eslesme kurali gorunmezdi ve "neden bu profil
    acilmiyor" sorusunun cevabi ancak koda bakinca bulunuyordu.
    """
    parts = []
    if class_name:
        parts.append(f"sinifi TAM olarak `{class_name}`")
    if title:
        parts.append(f"basliginda `{title}` GECEN")
    if not parts:
        return (
            "⚠️ Sinif da baslik da bos: bu profil HER pencereye uyar ve "
            "listede kendinden sonrakileri golgeler."
        )
    return "Eslesme: " + " ve ".join(parts) + " pencere."


def read_strokes(text: str) -> tuple[str, ...]:
    """AHK `StrSplit(..., "\\n", "\\r")` + bos satir eleme (Qt ile ayni)."""
    return tuple(line.strip() for line in text.split("\n") if line.strip())


def stroke_hint(text: str) -> str:
    """Hangi satirin kisayol, hangisinin duz metin sayildigi.

    `abc` ile `^+t` arasindaki fark dosyada gorunmuyordu ve "neden
    harfleri tek tek yaziyor" sorusuna sebep oluyordu.

    Qt'de bu satir her tus vurusunda yeniden yaziliyordu; burada da oyle
    ama hesap FLET tarafinda kaliyor: `stroke_kind` saf ve ucuz bir
    fonksiyon, depoya dokunmuyor. Her harfte Qt'ye gidip donmenin
    gerekcesi yok (depoya dokunan her sey icin `ask_qt` kurali surer).
    """
    strokes = read_strokes(text)
    if not strokes:
        return ""
    return "  ·  ".join(
        f"`{stroke}` → {'kisayol' if stroke_kind(stroke) == 'key' else 'duz metin'}"
        for stroke in strokes
    )


def profile_label(profile: AppProfile) -> str:
    return profile.name or "(adsiz)"


def action_label(shortcut: ShortCut) -> str:
    return shortcut.name or "(adsiz)"


class ProfilesPanel(QObject):
    """Profil yoneticisi. `app.py` bir kez kurup `open()` ile gosteriyor."""

    #: Pencere kapandi. Qt surumunde karsiligi yoktu (alicisi yok);
    #: oteki panellerle simetri icin duruyor.
    closed = Signal()

    def __init__(self, store: ShortcutStore) -> None:
        super().__init__()
        self.store = store
        #: Kaydettikten sonra cagrilan kanca (`app.py` verir): atanan
        #: kisayollari kayit defterine yeniden tutturur. Qt surumundeki
        #: `keys_changed` alaninin AYNISI -- `app.py` tek satir degisiyor.
        self.keys_changed: Callable[[], None] | None = None

        # ---- Qt tarafinda hesaplanan goruntuler; Flet yalniz cizer
        self._profile_index = YENI
        self._action_index = YENI
        self._profiles: tuple[str, ...] = ()
        self._actions: tuple[str, ...] = ()
        #: (ad, sinif, baslik)
        self._profile_fields: tuple[str, str, str] = ("", "", "")
        #: (ad, aciklama, kisayol, tus dizileri)
        self._action_fields: tuple[str, str, str, str] = ("", "", "", "")
        self._rule = ""
        self._status = ""

        self._engine = FletEngine(self._build)
        self._page: ft.Page | None = None
        self._profile_list: ft.ListView | None = None
        self._action_list: ft.ListView | None = None
        self._name: ft.TextField | None = None
        self._class: ft.TextField | None = None
        self._title: ft.TextField | None = None
        self._rule_text: ft.Text | None = None
        self._action_name: ft.TextField | None = None
        self._action_desc: ft.TextField | None = None
        self._key_button: ft.ElevatedButton | None = None
        self._strokes: ft.TextField | None = None
        self._hint_text: ft.Text | None = None
        self._status_text: ft.Text | None = None
        self._dialog: ft.AlertDialog | None = None

    # -- Qt tarafinin gordugu yuz -------------------------------------------

    def open(self, profile_name: str = "") -> None:
        """`shorts.manage[:<ad>]`. Qt surumu gibi ONCE DISKTEN okuyor:
        profiles.json Notepad'den de duzenlenebiliyor.

        Ad verilmezse (ya da bulunamazsa) ilk profil secilir -- AHK
        burada hicbir seyi secmiyordu ve pencere bos aciliyordu.
        """
        self.store.load()
        self._refresh_profiles()
        index = self._named(profile_name) if profile_name else 0
        if 0 <= index < len(self.store.profiles):
            self._select_profile(index)
        self._show()

    def open_new(self, class_name: str = "") -> None:
        """`shorts.add:<sinif>` -- bos profille acar, sinif alani dolu.

        `open()` her zaman bir profil seciyor; "ekle" derken var olan bir
        profilin uzerine yazma riski dogar, o yuzden ayri giris.
        """
        self.store.load()
        self._refresh_profiles()
        self._new_profile()
        self._profile_fields = ("", class_name, "")
        self._rule = rule_text(class_name, "")
        self._show()
        # Qt: `name_edit.setFocus()`. Odak sayfa kurulduktan sonra
        # isteniyor -- ilk acilista `_build` daha kosmamis olabilir.
        self._engine.call(self._focus_name)

    def close(self) -> None:
        """Pencereyi gizle. `app.py` `_shutdown` bunu cagiriyor."""
        self._engine.call(self._hide_now)

    def shutdown(self) -> None:
        """Program kapaniyor: Flet istemcisini (`flet.exe`) gercekten kapat."""
        self._engine.stop()

    def _show(self) -> None:
        if self._engine.page is None:
            # Sayfa yok: thread'i baslat, `_build` bu veriyle cizecek.
            # Beklemiyoruz -- ana thread 3.5 saniye donarsa tepsi takilir.
            self._engine.start()
            return
        self._engine.call(self._show_now)

    # -- Qt thread'i: depo ve disk (`FletEngine.ask_qt` ile) ----------------

    def _named(self, name: str) -> int:
        for index, profile in enumerate(self.store.profiles):
            if profile.name == name:
                return index
        return YENI

    def _current(self) -> AppProfile | None:
        if 0 <= self._profile_index < len(self.store.profiles):
            return self.store.profiles[self._profile_index]
        return None

    def _refresh_profiles(self) -> None:
        """Profil listesi + alt satir (Qt: `_fill_profiles`)."""
        self._profiles = tuple(profile_label(p) for p in self.store.profiles)
        self._status = (
            f"{len(self.store.profiles)} profil, "
            f"{sum(len(p.shortcuts) for p in self.store.profiles)} aksiyon"
        )

    def _refresh_actions(self) -> None:
        profile = self._current()
        self._actions = (
            tuple(action_label(s) for s in profile.shortcuts) if profile is not None else ()
        )

    def _select_profile(self, index: int) -> None:
        """Profil secildi: alanlar dolar, aksiyon listesi kurulur ve sag
        sutun BOSALIR (Qt: `_on_profile` sonunda `new_action`)."""
        self._profile_index = index
        profile = self._current()
        if profile is None:
            return
        self._profile_fields = (profile.name, profile.class_name, profile.title)
        self._rule = rule_text(profile.class_name, profile.title)
        self._refresh_actions()
        self._new_action()

    def _select_profile_and_render(self, index: int) -> None:
        self._select_profile(index)
        self._engine.call(self._draw)

    def _new_profile(self) -> None:
        """Qt: `new_profile` -- alanlari bosaltir, kayit `Kaydet`te olusur."""
        self._profile_index = YENI
        self._profile_fields = ("", "", "")
        self._rule = rule_text("", "")
        self._actions = ()
        self._new_action()

    def _new_profile_and_render(self) -> None:
        self._new_profile()
        self._engine.call(self._draw)
        self._engine.call(self._focus_name)

    def _save_profile(self, name: str, class_name: str, title: str) -> None:
        """Qt: `save_profile`. Dondurulmus veri sinifi: yerinde
        degistirmek yerine `replace` ile YENISI kuruluyor -- "yarim
        guncellenmis profil" diye bir ara durum olusmasin."""
        profile = self._current()
        if profile is None:
            self.store.profiles.append(
                AppProfile(name=name, class_name=class_name, title=title)
            )
            self._profile_index = len(self.store.profiles) - 1
        else:
            self.store.profiles[self._profile_index] = replace(
                profile, name=name, class_name=class_name, title=title
            )
        self._profile_fields = (name, class_name, title)
        self._rule = rule_text(class_name, title)
        self._write()

    def _delete_profile(self) -> None:
        """Onaydan sonra: profili sil, diske yaz, alanlari bosalt."""
        if self._current() is None:
            return
        del self.store.profiles[self._profile_index]
        self._profile_index = YENI
        self._write()
        self._new_profile()
        self._engine.call(self._draw)

    # -- Qt thread'i: aksiyonlar --------------------------------------------

    def _load_action(self, index: int) -> None:
        profile = self._current()
        self._action_index = index
        if profile is None or not 0 <= index < len(profile.shortcuts):
            return
        shortcut = profile.shortcuts[index]
        self._action_fields = (
            shortcut.name,
            shortcut.description,
            shortcut.key,
            "\n".join(shortcut.strokes),
        )
        self._engine.call(self._draw)

    def _new_action(self) -> None:
        self._action_index = YENI
        self._action_fields = ("", "", "", "")

    def _new_action_and_render(self) -> None:
        self._new_action()
        self._engine.call(self._draw)

    def _save_action(self, name: str, description: str, strokes_text: str) -> None:
        """Qt: `save_action`. Kisayol alani KUTUDAN degil panelin kendi
        durumundan geliyor -- yakalama Qt tarafinda oldu ve sonucu
        `_action_fields`e yazildi."""
        profile = self._current()
        if profile is None:
            self._engine.call(
                lambda: self._alert("Profiller", "Once profil sec ya da kaydet.")
            )
            return
        shortcut = ShortCut(
            name=name,
            description=description,
            strokes=read_strokes(strokes_text),
            key=self._action_fields[2],
        )
        shortcuts = list(profile.shortcuts)
        if 0 <= self._action_index < len(shortcuts):
            shortcuts[self._action_index] = shortcut
        else:
            shortcuts.append(shortcut)
            self._action_index = len(shortcuts) - 1
        self.store.profiles[self._profile_index] = replace(
            profile, shortcuts=tuple(shortcuts)
        )
        self._action_fields = (name, description, shortcut.key, strokes_text)
        self._write()

    def _delete_action(self) -> None:
        profile = self._current()
        if profile is None or not 0 <= self._action_index < len(profile.shortcuts):
            return
        shortcuts = list(profile.shortcuts)
        del shortcuts[self._action_index]
        self.store.profiles[self._profile_index] = replace(
            profile, shortcuts=tuple(shortcuts)
        )
        self._action_index = YENI
        self._new_action()
        self._write()

    def _move_action(self, delta: int) -> None:
        """Qt: `move_action` -- sira F13 menusundeki siradir, onemli."""
        profile = self._current()
        if profile is None:
            return
        source = self._action_index
        target = source + delta
        count = len(profile.shortcuts)
        if not (0 <= source < count and 0 <= target < count):
            return
        shortcuts = list(profile.shortcuts)
        shortcuts[source], shortcuts[target] = shortcuts[target], shortcuts[source]
        self.store.profiles[self._profile_index] = replace(
            profile, shortcuts=tuple(shortcuts)
        )
        self._action_index = target
        self._write()

    def _write(self) -> None:
        """Diske yazar ve listeleri tazeler (Qt: `_write`)."""
        if not self.store.save():
            self._engine.call(
                lambda: self._alert(
                    "Profiller", "profiles.json yazilamadi -- log'a bak."
                )
            )
            return
        self._refresh_profiles()
        self._refresh_actions()
        # Kisayollar dosyayla birlikte degisti: kayit defteri tazelensin,
        # yoksa yeni atanan tus program yeniden baslayana kadar olu kalir.
        if self.keys_changed is not None:
            self.keys_changed()
        self._engine.call(self._draw)

    # -- Qt thread'i: kisayol yakalama (Flet'in yapamadigi is) --------------

    def _capture_key(self) -> None:
        """Kucuk bir Qt penceresi acar ve basilan tusu alir. ANA THREAD.

        `ft.KeyboardEvent` Windows VK kodunu vermiyor; programin geri
        kalani VK ile konusuyor (bkz. dosya basi). Kutu `ui/key_capture.py`
        -- yakalama kurallari oradan geliyor, burada yalniz bir cerceve
        var. Gecici: Asama 3 #16 cozulunce bu fonksiyon gider.
        """
        dialog = QDialog()
        dialog.setWindowTitle("Kisayol")
        # Flet penceresi onde duruyor: kutu altina duserse kullanici
        # neye bastigini goremez.
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel("Kutuya tikla, sonra tusa bas.\nEsc: iptal   Backspace: kisayolu sil"))
        capture = KeyCapture(self._action_fields[2])
        box.addWidget(capture)

        def taken(spec: str) -> None:
            name, description, _key, strokes = self._action_fields
            self._action_fields = (name, description, spec, strokes)
            dialog.accept()

        capture.changed.connect(taken)
        center_on_cursor_screen(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        # Kutu ACIK gelsin: kullanici pencereyi acar acmaz tusa basabilsin
        # (Qt surumunde once kutuya tiklaniyordu; burada pencerenin kendisi
        # zaten "tus bekliyorum" demek).
        capture.click()
        dialog.exec()
        self._engine.call(self._draw)

    # -- Flet thread'i: kurulum ---------------------------------------------

    def _build(self, page: ft.Page) -> None:
        """Sayfa hazir. Denetimleri kur ve hemen goster (FLET thread'i)."""
        self._page = page
        page.title = "\U0001f9e9 Profiller ve Kisayollar"
        page.bgcolor = theme.BG
        page.padding = 10
        page.window.width, page.window.height = SIZE
        # Kapatma DUSMESIN: `ft.run` doner, thread olur ve bir sonraki
        # acilis Flet'in baslama suresini yeniden odetirdi.
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.on_keyboard_event = self._on_key

        # ---- sol: profiller
        self._profile_list = ft.ListView(controls=[], spacing=0, expand=True)
        self._name = ft.TextField(height=FIELD_H, **FIELD_STYLE)
        self._class = ft.TextField(height=FIELD_H, **FIELD_STYLE)
        self._title = ft.TextField(
            hint_text="baslikta GECEN bir parca", height=FIELD_H, **FIELD_STYLE
        )
        self._rule_text = ft.Text("", color=theme.MUTED, size=TEXT_SIZE)
        left = ft.Column(
            width=LEFT_W,
            spacing=6,
            controls=[
                self._caption("Profiller"),
                self._frame(self._profile_list),
                self._form_row("Profil adi", self._name),
                self._form_row("Pencere sinifi", self._class),
                self._form_row("Baslik (parca)", self._title),
                ft.Row(
                    spacing=6,
                    controls=[
                        self._button("➕ Yeni", self._on_new_profile),
                        self._button("\U0001f4be Kaydet", self._on_save_profile),
                        self._button("\U0001f5d1️ Sil", self._ask_delete_profile),
                    ],
                ),
                self._rule_text,
            ],
        )

        # ---- orta: aksiyonlar
        self._action_list = ft.ListView(controls=[], spacing=0, expand=True)
        middle = ft.Column(
            width=MIDDLE_W,
            spacing=6,
            controls=[
                self._caption("Aksiyonlar"),
                self._frame(self._action_list),
                ft.Row(
                    spacing=6,
                    controls=[
                        self._button("▲ Yukari", lambda: self._on_move(-1)),
                        self._button("▼ Asagi", lambda: self._on_move(1)),
                    ],
                ),
            ],
        )

        # ---- sag: aksiyon detayi
        self._action_name = ft.TextField(height=FIELD_H, **FIELD_STYLE)
        self._action_desc = ft.TextField(height=FIELD_H, **FIELD_STYLE)
        self._key_button = ft.ElevatedButton(
            content=ft.Text(NO_KEY, size=TEXT_SIZE, color=theme.FG),
            height=32,
            bgcolor=theme.FIELD_BG,
            on_click=lambda _e: self._engine.ask_qt(self._capture_key),
        )
        self._strokes = ft.TextField(
            multiline=True,
            hint_text="her satir bir tus dizisi:\n^+t\nmerhaba",
            on_change=self._on_strokes,
            expand=True,
            **FIELD_STYLE,
        )
        self._hint_text = ft.Text("", color=theme.MUTED, size=TEXT_SIZE)
        right = ft.Column(
            expand=True,
            spacing=6,
            controls=[
                self._form_row("Aksiyon adi", self._action_name),
                self._form_row("Aciklama", self._action_desc),
                self._form_row("Kisayol", self._key_button),
                self._caption("Tus dizileri (her satir bir tane)"),
                self._strokes,
                self._hint_text,
                ft.Row(
                    spacing=6,
                    controls=[
                        self._button("➕ Yeni", self._on_new_action),
                        self._button("\U0001f4be Kaydet", self._on_save_action),
                        self._button("\U0001f5d1️ Sil", self._ask_delete_action),
                        self._button("Kapat", self._hide),
                    ],
                ),
            ],
        )

        self._status_text = ft.Text("", color=theme.MUTED, size=TEXT_SIZE)
        page.controls.append(
            ft.Column(
                expand=True,
                spacing=8,
                controls=[
                    ft.Row(
                        expand=True,
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                        controls=[left, middle, right],
                    ),
                    self._status_text,
                ],
            )
        )
        self._engine.show_on_build(self._show_now)

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
        """Cizime giren TEK yol (Qt tarafi `engine.call` ile buraya gelir)."""
        page = self._page
        if page is None:
            return
        self._fill()
        page.update()

    def _fill(self) -> None:
        """Iki listeyi ve iki formu doldurur. `page.update()` CAGIRMAZ --
        cagiran karar veriyor (acilista tek cizim yeter)."""
        if self._profile_list is not None:
            self._profile_list.controls = [
                self._row(
                    label,
                    index == self._profile_index,
                    lambda i=index: self._on_profile(i),
                )
                for index, label in enumerate(self._profiles)
            ]
        if self._action_list is not None:
            self._action_list.controls = [
                self._row(
                    label,
                    index == self._action_index,
                    lambda i=index: self._on_action(i),
                )
                for index, label in enumerate(self._actions)
            ]
        name, class_name, title = self._profile_fields
        if self._name is not None:
            self._name.value = name
        if self._class is not None:
            self._class.value = class_name
        if self._title is not None:
            self._title.value = title
        if self._rule_text is not None:
            self._rule_text.value = self._rule

        action_name, description, key, strokes = self._action_fields
        if self._action_name is not None:
            self._action_name.value = action_name
        if self._action_desc is not None:
            self._action_desc.value = description
        if self._key_button is not None:
            self._key_button.content = ft.Text(
                key or NO_KEY, size=TEXT_SIZE, color=theme.FG
            )
        if self._strokes is not None:
            self._strokes.value = strokes
        if self._hint_text is not None:
            self._hint_text.value = stroke_hint(strokes)
        if self._status_text is not None:
            self._status_text.value = self._status

    def _row(
        self, text: str, selected: bool, action: Callable[[], None]
    ) -> ft.Container:
        """Bir liste satiri -- kap + tek yazi (fui/repository.py ile ayni)."""
        return ft.Container(
            bgcolor=theme.SELECT_BG if selected else None,
            padding=ft.Padding(6, ROW_PAD, 6, ROW_PAD),
            on_click=lambda _e: action(),
            content=ft.Text(text, color=theme.FG, size=TEXT_SIZE, no_wrap=True),
        )

    def _focus_name(self) -> None:
        if self._name is not None:
            return self._name.focus()
        return None

    # -- Flet thread'i: olaylar ---------------------------------------------

    def _on_profile(self, index: int) -> None:
        self._engine.ask_qt(lambda: self._select_profile_and_render(index))

    def _on_action(self, index: int) -> None:
        self._engine.ask_qt(lambda: self._load_action(index))

    def _on_new_profile(self) -> None:
        self._engine.ask_qt(self._new_profile_and_render)

    def _on_save_profile(self) -> None:
        """Alanlari okur ve isi Qt'ye verir (Qt: `save_profile`)."""
        if self._name is None or self._class is None or self._title is None:
            return
        name = (self._name.value or "").strip()
        if not name:
            # Qt: `QMessageBox.warning` + ad kutusuna odak.
            self._alert("Profiller", "Profil adi zorunlu.")
            self._engine.call(self._focus_name)
            return
        class_name = (self._class.value or "").strip()
        title = (self._title.value or "").strip()
        self._engine.ask_qt(lambda: self._save_profile(name, class_name, title))

    def _on_new_action(self) -> None:
        self._engine.ask_qt(self._new_action_and_render)

    def _on_save_action(self) -> None:
        if self._action_name is None or self._action_desc is None:
            return
        if self._strokes is None:
            return
        name = (self._action_name.value or "").strip()
        if not name:
            self._alert("Profiller", "Aksiyon adi zorunlu.")
            self._engine.call(self._action_name.focus)
            return
        description = (self._action_desc.value or "").strip()
        strokes = self._strokes.value or ""
        self._engine.ask_qt(lambda: self._save_action(name, description, strokes))

    def _on_move(self, delta: int) -> None:
        self._engine.ask_qt(lambda: self._move_action(delta))

    def _on_strokes(self, event: ft.ControlEvent) -> None:
        """Ipucu satiri her tus vurusunda tazeleniyor (Qt: `textChanged`).

        Hesap Flet'te kaliyor: `stroke_kind` saf ve ucuz, depoya
        dokunmuyor (bkz. `stroke_hint`).
        """
        if self._hint_text is None or self._page is None:
            return
        self._hint_text.value = stroke_hint(event.control.value or "")
        self._page.update()

    def _ask_delete_profile(self) -> None:
        """Silme ONAY ister (Qt: `QMessageBox.question`)."""
        if self._profile_index == YENI:
            return
        name = self._profile_fields[0]
        self._confirm(f"Profil silinsin mi?\n\n{name}", self._delete_profile)

    def _ask_delete_action(self) -> None:
        if self._action_index == YENI:
            return
        name = self._action_fields[0]
        self._confirm(f"Aksiyon silinsin mi?\n\n{name}", self._delete_action)

    def _confirm(self, question: str, job: Callable[[], None]) -> None:
        page = self._page
        if page is None:
            return

        def yes() -> None:
            self._close_dialog()
            self._engine.ask_qt(job)

        self._dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Profiller", color=theme.FG),
            content=ft.Text(question, color=theme.FG, size=TEXT_SIZE),
            bgcolor=theme.FIELD_BG,
            actions=[
                ft.TextButton("Evet", on_click=lambda _e: yes()),
                ft.TextButton("Hayir", on_click=lambda _e: self._close_dialog()),
            ],
        )
        page.show_dialog(self._dialog)

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

    def _on_key(self, event: ft.KeyboardEvent) -> None:
        if event.key == "Escape":
            self._hide()

    def _on_window_event(self, event: ft.WindowEvent) -> None:
        if event.type == ft.WindowEventType.CLOSE:
            self._hide()

    def _hide(self) -> None:
        self._hide_now()
        self.closed.emit()
