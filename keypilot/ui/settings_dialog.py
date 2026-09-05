"""Ayar ekrani -- AHK `Lib/settings_dialog.ahk` portu.

Ustte arama, solda kategori, sagda ayar KARTLARI. Kart duzeni tablonun
yerini aldi; sebebi tek tek soyle:

    * DEGER ARTIK BIR NESNE, metin degil. Tabloda deger bir hucre metniydi
      ve degistirmek icin once satiri secip sonra cift tiklamak gerekiyordu
      -- iki adim, ikisi de ogrenilmesi gereken sey. Simdi degerin yerinde
      duran nesnenin kendisine TEK tiklaniyor: acik/kapali ve secenekler
      menuyu aciyor, sayi/metin dogrudan yaziliyor.
    * SECIM VURGUSU YOK. Tabloda satir mavi boyaniyordu ama secili olmak
      hicbir sey ifade etmiyordu: her kart kendi isini kendi yapiyor,
      "once sec sonra dokun" diye bir adim kalmadi. Tek tek sifirlama
      dugmesi de yok: kart basina bir `↺` denendi ve degerlerin hizasini
      bozdu -- karsiligi altta duran "Tumu varsayilana".
    * Bir kart tek ayar: ustte AD ve DEGER yan yana, altinda aciklama.
      Tabloda aciklama ucuncu sutundu ve satir yuksekligini iki katina
      cikariyordu; alt satirda yeri dogal.

Isaretler:

    * kalin DEGER   varsayilandan FARKLI olan ayar (AHK'de NM_CUSTOMDRAW ile
                    yapiliyordu). Isaret ADIN degil DEGERIN uzerinde: goz
                    zaten degerler sutununu tariyor.
    * menude tik    SECILI secenek; KALIN olan VARSAYILAN. (Menunun icinde
                    kalin "varsayilan" demek, kartta "varsayilan degil" --
                    ikisi ayri baglam: menude hangisine donecegini, kartta
                    hangisine dokundugunu ariyorsun.)
    * ortadaki bilgi  sayinin gecerli araligi (`1-9`, `0-500 ms`). Ayarin
                    `info` alanindan ya da `settings.between`in sinirlarindan
                    geliyor -- elle yazilmiyor. GECERSIZ deger yazilinca ayni
                    yazi KIRMIZI yaniyor: ayar degismez, yazdigin da silinmez.
                    Bilgisi olmayan ayarda o hucre bos bir ara (spacer).
    * arama         bosluk ile AND; arama varken kategori suzgeci devre disi

IPUCU (tooltip) YOK. Denendi ve kalkti: gosterdigi her sey (ret gerekcesi,
varsayilan) ya zaten ekranda duruyor ya da kartin bir isareti -- uzerine
gelmeden gorunmeyen ikinci bir katman kurmaya degmiyor.

Kaydetme kapanista (`Settings.save`): ekran acikken her degisiklikte diske
yazmak gereksiz, ayar dosyasi kucuk ama degisiklik cok olabiliyor.
"""

from __future__ import annotations

import subprocess

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from keypilot import paths
from keypilot.settings import SETTINGS, Category, Setting
from keypilot.ui.place import center_on_cursor_screen

ALL_LABEL = "Tümü"

#: Ret gerekcesinin rengi. Yazdigin sey yerinde kaliyor, kutunun saginda
#: kirmizi bir satir beliriyor -- ayri bir ipucu katmani yok.
INVALID_COLOR = "#da3633"

#: Yerinde yazilan tipler. bool ve enum menuden seciliyor -- ikisi de
#: metin girdisi degil, sayili secenek.
TYPED_KINDS = ("int", "float", "str")

#: Deger nesnesinin genisligi -- tip ne olursa olsun AYNI, cunku hepsi
#: satirin en saginda ayni sutunda duruyor.
VALUE_WIDTH = 170
#: Ortadaki bilgi hucresi. Sabit: yazisi olmayan ayarda bos ara olarak
#: duruyor ve deger sutunu yerinden oynamiyor.
INFO_WIDTH = 150

CARD_STYLE = """
QFrame#card {
    border: 1px solid palette(mid);
    border-radius: 6px;
    background: palette(base);
}
QFrame#card QLabel#desc { color: palette(dark); }
QFrame#card QLabel#info { color: palette(dark); }
/* Sayi kutusu bir KUTU gibi gorunmeli: cercevesiz haliyle karttaki duz
   metinden ayirt edilemiyordu ("bu yazi mi, yazabildigim bir sey mi"). */
QFrame#card QLineEdit#value {
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 3px 6px;
    background: palette(window);
}
QFrame#card QLineEdit#value:focus { border-color: palette(highlight); }
"""


class SettingCard(QFrame):
    """Tek ayar. Ust satir TEK BIR SABLON, uc tip icin de ayni:

        ad (esner)  |  bilgi/dogrulayici (yoksa bos ara)  |  deger (nesne)

    Deger saga dayali: acik/kapali, secenek ve sayi kartlar boyunca ayni
    sutunda. Ucu icin ayri duzen kurmak (dugmede sutunu atlamak, sayida
    eklemek) hem kodu ikiye boluyor hem de satirlari kaydiriyordu.

    Altinda aciklama.

    Kart kendi ayarini kendi yaziyor; ekranin tek yaptigi hangi kartlarin
    gorunecegine karar vermek. Degisiklikten sonra kart kendini tazeliyor
    (`refresh`), butun listeyi yeniden kurmuyoruz: kullanici bir menuden
    secim yaparken altindaki nesnenin yok edilmesi Qt'de sinyal ortasinda
    silme demek ve carpisma sebebi.
    """

    def __init__(self, item: Setting, on_change=lambda _message="": None) -> None:
        super().__init__()
        self.setObjectName("card")
        self.item = item
        self._on_change = on_change
        #: Son yazilan deger reddedildi mi -- kutu kirmizi duruyor.
        self.invalid = False
        #: Sayi/metin kutusunun ICINDEKI sifirlama dugmesi (yalniz o tipte).
        self.reset_action = None

        self.name = QLabel(item.name)
        self.name.setWordWrap(True)
        #: Ortadaki hucre: gecerli araligi yazar, gecersiz degerde kirmizi
        #: yanar. Bos oldugunda ara olarak duruyor -- sutun hizasi bozulmasin.
        self.info = QLabel(item.info_text())
        self.info.setObjectName("info")
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info.setFixedWidth(INFO_WIDTH)
        self.value = self._make_value()

        head = QHBoxLayout()
        head.addWidget(self.name, 1)
        head.addWidget(self.info)
        head.addWidget(self.value)

        self.desc = QLabel(item.desc or item.key)
        self.desc.setObjectName("desc")
        self.desc.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.addLayout(head)
        layout.addWidget(self.desc)

        self.refresh()

    # ---- deger nesnesi ----

    def _make_value(self) -> QWidget:
        """Tipin nesnesi: menu dugmesi ya da yazi kutusu."""
        if self.item.type_of() in TYPED_KINDS:
            box = QLineEdit(str(self.item.get()))
            box.setObjectName("value")
            box.setFixedWidth(VALUE_WIDTH)
            # Enter ya da odagi birakmak: iki yol da ayni seyi yapmali.
            # `textChanged` DEGIL -- her harfte dogrulamak "12" yazarken
            # "1" gecersiz diye kutuyu kirmiziya boyardi.
            box.editingFinished.connect(self._typed)
            # Varsayilana donus, kutunun ICINDE. Kartin sagina ayri bir
            # dugme olarak konulmustu ve deger sutununun hizasini bozuyordu.
            # HEP GORUNUR, varsayilandayken PASIF. Once gizleniyordu:
            # belirip kaybolan dugme hem "bu da ne" sorusu birakiyor hem de
            # dondurecek bir sey olmadigini ancak yoklugundan anlatiyordu.
            # Soluk bir dugme ayni seyi yerinde durarak soyluyor.
            # QAction ACIKCA kuruluyor ve kutuya ebeveyn veriliyor:
            # `box.addAction(icon, ...)` bicimiyle donen nesnenin sahipligi
            # belirsiz kaliyor ve Python tarafi onu toplayabiliyor
            # ("Internal C++ object already deleted").
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
            self.reset_action = QAction(icon, "", box)
            self.reset_action.triggered.connect(self._reset)
            box.addAction(self.reset_action, QLineEdit.ActionPosition.TrailingPosition)
            return box
        button = QPushButton()
        button.setFixedWidth(VALUE_WIDTH)
        # Tek tiklama: menu dugmenin ALTINDA acilir. Dugmenin kendi menusu
        # (`setMenu`) kullanilmadi, cunku o oka yer aciyor ve menuyu ilk
        # tiklamada acmiyor.
        button.clicked.connect(self._open_menu)
        return button

    def _choices(self) -> tuple:
        """Menude gorunecek degerler. bool'un da iki secenegi var: acik/kapali
        ayri bir tip degil, iki elemanli bir liste gibi davraniyor."""
        return (True, False) if self.item.type_of() == "bool" else self.item.choices

    def _label(self, value) -> str:
        if self.item.type_of() == "bool":
            return "acik" if value else "kapali"
        return self.item.label_for(value)

    def menu(self) -> QMenu:
        """Secenek menusu. Kurulum acmaktan AYRI: modal menuyu acmadan
        icerigini denetleyebilmek gerekiyor (test)."""
        menu = QMenu(self)
        for choice in self._choices():
            action = QAction(self._label(choice), menu)
            action.setCheckable(True)
            action.setChecked(choice == self.item.get())
            if choice == self.item.default:
                font = action.font()
                font.setBold(True)
                action.setFont(font)
            action.triggered.connect(
                lambda _checked=False, value=choice: self.apply(value)
            )
            menu.addAction(action)
        return menu

    def _open_menu(self) -> None:
        self.menu().exec(self.value.mapToGlobal(self.value.rect().bottomLeft()))

    # ---- degisiklik ----

    def apply(self, value) -> None:
        message = self.item.set(value)
        if message:  # menuden gelen deger dogrulayiciya takildi: nadir
            QMessageBox.warning(self, "Ayarlar", message)
        self.refresh()
        self._on_change()

    def _typed(self) -> None:
        """Kutuya yazilan sayi/metin. Gecersizse YAZDIGIN YERINDE KALIR.

        Eski deger geri yazilsaydi kullanici neyi yanlis yazdigini goremezdi;
        gerekce kutunun saginda kirmizi duruyor. `refresh` cagrilmiyor:
        kutuyu ayarin gecerli degerine dondururdu.
        """
        message = self.item.set(self.value.text())
        if message:
            self.invalid = True
            # Ortadaki yazi zaten "kac ile kac arasi" diyor; hata halinde
            # ayni yazi kirmizi yaniyor. Bilgisi olmayan ayarda ret
            # gerekcesi oraya dusuyor -- bos hucre isi gorsun.
            self.info.setText(self.item.info_text() or message)
            self.info.setStyleSheet(f"color: {INVALID_COLOR};")
            self._on_change(message)
            return
        self.refresh()
        self._on_change()

    def _reset(self) -> None:
        """Kutunun icindeki dugme: varsayilani geri yaz."""
        self.item.reset()
        self.refresh()
        self._on_change()

    def refresh(self) -> None:
        """Nesneyi ayarin O ANKI degerine getirir."""
        self.invalid = False
        changed = self.item.is_changed()
        font = self.value.font()
        font.setBold(changed)  # AHK: degismis ayar kalin
        self.value.setFont(font)
        if self.reset_action is not None:
            self.reset_action.setEnabled(changed)  # varsayilandayken soluk
        self.info.setText(self.item.info_text())
        self.info.setStyleSheet("")
        if isinstance(self.value, QLineEdit):
            self.value.blockSignals(True)
            self.value.setText(str(self.item.get()))
            self.value.blockSignals(False)
        else:
            self.value.setText(self._label(self.item.get()))


class SettingsDialog(QWidget):
    """Ayar penceresi. Tek ornek: app.py bunu saklayip yeniden gosteriyor."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("⚙️ Ayarlar")
        self.resize(860, 560)
        self.setStyleSheet(CARD_STYLE)
        self._rows: list[Setting] = []
        self.cards: list[SettingCard] = []
        self._category = ""  # "" = Tümü

        self.search = QLineEdit()
        self.search.setPlaceholderText("\U0001f50e ara (bosluk = ve)")
        self.search.textChanged.connect(self._refresh)

        self.categories = QListWidget()
        self.categories.setFixedWidth(180)
        self.categories.currentRowChanged.connect(self._on_category)

        # Kartlarin kabi. QListWidget + setItemWidget yerine duz kaydirma
        # alani: liste olsaydi her kart yine bir satirda dururdu ve satirin
        # secim vurgusu kartin uzerine binerdi -- burada secilecek bir sey
        # yok, kartin kendisi calisiyor.
        self.holder = QWidget()
        self.cards_layout = QVBoxLayout(self.holder)
        self.cards_layout.setSpacing(6)
        self.cards_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.holder)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll = scroll

        self.status = QLabel()

        reset_all = QPushButton("↺ Tumu varsayilana")
        reset_all.clicked.connect(self._reset_all)
        open_json = QPushButton("\U0001f4dd settings.json")
        open_json.clicked.connect(self._open_json)

        buttons = QHBoxLayout()
        buttons.addWidget(self.status, 1)
        buttons.addWidget(reset_all)
        buttons.addWidget(open_json)

        middle = QHBoxLayout()
        middle.addWidget(self.categories)
        middle.addWidget(scroll, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addLayout(middle, 1)
        layout.addLayout(buttons)

        self._fill_categories()
        self._refresh()

    # ---- kategori ----

    def _fill_categories(self) -> None:
        """Kategoriler, EN SONDA "Tümü". Ilk sirada dururken listeye her
        acilista onunla baslaniyordu; asil is belli bir kategoride ve
        "hepsi" bir geri cekilme secenegi -- yeri sonu."""
        self.categories.blockSignals(True)
        self.categories.clear()
        for name in SETTINGS.categories:
            self.categories.addItem(
                f"{Category.label(name)} ({len(SETTINGS.visible_in(name))})"
            )
        self._add_separator()
        self.categories.addItem(f"{ALL_LABEL} ({len(SETTINGS.visible)})")
        self.categories.setCurrentRow(self._all_row)
        self.categories.blockSignals(False)

    def _add_separator(self) -> None:
        """Kategorilerle "Tümü" arasina cizgi: "Tümü" bir kategori DEGIL,
        suzgeci kaldirmak. Ayni listede yan yana dururken ayni cinsten iki
        sey gibi okunuyordu."""
        line = QListWidgetItem()
        line.setFlags(Qt.ItemFlag.NoItemFlags)  # secilemez, uzerine gelinemez
        line.setSizeHint(QSize(0, 9))
        self.categories.addItem(line)
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.HLine)
        frame.setFrameShadow(QFrame.Shadow.Sunken)
        self.categories.setItemWidget(line, frame)

    @property
    def _all_row(self) -> int:
        """"Tümü" satirinin sirasi -- listenin sonu."""
        return self.categories.count() - 1

    def _on_category(self, row: int) -> None:
        names = SETTINGS.categories
        self._category = names[row] if 0 <= row < len(names) else ""
        self._refresh()

    # ---- liste ----

    def _refresh(self) -> None:
        query = self.search.text()
        items = SETTINGS.search(query)
        if query:  # arama varken kategori suzgeci devre disi (AHK ile ayni)
            self.categories.blockSignals(True)
            self.categories.setCurrentRow(self._all_row)
            self.categories.blockSignals(False)
            self._category = ""
        if self._category:
            items = [item for item in items if item.category == self._category]

        self._rows = items
        for card in self.cards:
            self.cards_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        for index, item in enumerate(items):
            card = SettingCard(item, self._on_card_change)
            self.cards_layout.insertWidget(index, card)
            self.cards.append(card)
        self.scroll.verticalScrollBar().setValue(0)
        self._update_status()

    def _on_card_change(self, message: str = "") -> None:
        """Kart bir ayari degistirdi (ya da reddetti). Liste YENIDEN
        KURULMAZ: kart kendini zaten tazeledi ve o an acik olan menuyu /
        yazi kutusunu altindan cekmek istemiyoruz."""
        self._update_status(message)

    def _update_status(self, message: str = "") -> None:
        if message:
            self.status.setText(message)
            return
        changed = sum(item.is_changed() for item in self._rows)
        self.status.setText(f"{len(self._rows)} ayar, {changed} degismis")

    # ---- toplu islem ----

    def _reset_all(self) -> None:
        answer = QMessageBox.question(
            self, "Ayarlar", "Tum ayarlar varsayilana donecek. Devam?"
        )
        if answer == QMessageBox.StandardButton.Yes:
            SETTINGS.reset_all()
            self._refresh()

    def _open_json(self) -> None:
        """AHK ile ayni: once diske yaz, sonra Notepad ile ac."""
        SETTINGS.save_now(paths.SETTINGS)
        subprocess.Popen(["notepad.exe", str(paths.SETTINGS)])  # noqa: S603, S607

    # ---- yasam dongusu ----

    def show_dialog(self) -> None:
        self._fill_categories()
        self._refresh()
        center_on_cursor_screen(self)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        """Kapanista kaydet -- AHK `SettingsDialog._close`."""
        SETTINGS.save(paths.SETTINGS)
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
