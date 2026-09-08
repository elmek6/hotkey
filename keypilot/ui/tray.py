"""Sistem tepsisi -- AHK'deki TraySetIcon + A_TrayMenu karsiligi.

Menu: Pause/Play (surumle birlikte) / Reload / Pause menu / Settings / Event monitor /
Copy last error / Exit. Metinler INGILIZCE -- AHK tepsi menusu de oyleydi,
aliskanlik bozulmasin.

Duraklat, AHK'nin `Suspend` komutunun karsiligi: hook yerinde kalir ama
hicbir tus yutulmaz, hicbir eylem calismaz. Hook'u sokup takmak yerine
bayrak kullanmanin sebebi, yeniden kurulan hook'un zincirin sonuna
dusmesi ve sira garantisinin kaybolmasi.

Arac ipucu (fare tepside beklerken): surum + calisan kopya, sonra tek/cift
tiklamanin O ANDAKI karsiligi. Ayardan okunuyor ve TEK PARCADA (`_tooltip`)
uretiliyor -- parca parca guncellenen bir metinde durumun bir yarisi eski
kaliyordu.

IPUCU TEK SATIR OLMAK ZORUNDA. Ilk deneme uc satirdi ve tepside yalnizca
ilki gorunuyordu: Windows 11'in tepsi ipucu (XAML) `szTip` icindeki satir
sonlarini gostermiyor. Uzunluk da bedava degil -- kabuk bu alani eski
surumlerde 64 karakterde kesiyor ve fazlasi sessizce dusuyor; bu yuzden
parcalar ONEM SIRASINA gore ekleniyor (bkz. `_fit`) ve surumun yapim
damgasi ipucuna girmiyor (tam surum tepsi menusunun ilk maddesinde).

Simge dosyadan degil, cizilerek uretiliyor -- ne .ico dosyasi tasimak
gerekiyor ne de paketlemede kaynak gomme derdi var. Dort durumu var: calisiyor
(mavi), duraklatildi (gri), uyari var (sari), gercek hata var (kirmizi).

KIRMIZI PAHALI BIR RENKTIR. Once her WARNING+ kaydi kirmiziya boyuyordu ve
en cok goruleni "cift tiklama yutuldu" idi -- kendi log satiri bile "program
hatasi degil" diyen bir kayit. Simgeye bakan "keypilot coktu mu" diye
irkiliyor, sonra ariza farenin normal bir gunune bakiyordu. Artik esik
ERROR: WARNING sariya duser, kirmizi yalnizca gercekten bozulan bir sey
oldugunda yanar.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from keypilot.settings import Category, setting

BACKGROUND = QColor("#1f6feb")
PAUSED_BACKGROUND = QColor("#6e7681")
ERROR_BACKGROUND = QColor("#da3633")
WARN_BACKGROUND = QColor("#bb8009")
BAR = QColor("#ffffff")
#: Gelistirme modu (keypilot/dev.py) acikken simgenin cevresine cizilen
#: halka. ZEMIN DEGIL cerceve: zemin renkleri zaten dolu (duraklatildi /
#: hata / uyari) ve mor onlarin yerine gecseydi gelistirme modu hata
#: isaretini ORTERDI. Halka ayri bir kanal -- ikisi ayni anda gorunur.
DEV_RING = QColor("#a371f7")

#: Cift tiklama eylemleri. Ayara KIMLIK yazilir, menude ETIKET gorunur --
#: menu metnini degistirmek kayitli secimi bozmasin.
DOUBLE_CLICK_LABELS = {
    "pause": "Pause/Play",
    "restart": "Reload",
    "pause_dialog": "Pause menu",
    "settings": "Settings",
    "monitor": "Event monitor",
    "copy_error": "Copy last error",
    "show_log": "Show log",
}
#: settings.json'da duran eski (metin) degerler.
DOUBLE_CLICK_LEGACY = {label: name for name, label in DOUBLE_CLICK_LABELS.items()}

#: TEK tiklama secenekleri: cift tiklamanin ayni maddeleri + "hicbir sey".
#: Varsayilan `none` cunku tek tik cift tiklamanin ilk yarisidir -- bir is
#: baglanirsa cift tiklama ayarindaki eylem her seferinde ONCE tek tikin
#: isini yapar. Ikisini birden kullanacak olan bunu bilerek seciyor.
SINGLE_CLICK_LABELS = {"none": "Hicbir sey", **DOUBLE_CLICK_LABELS}
SINGLE_CLICK_LEGACY = {label: name for name, label in SINGLE_CLICK_LABELS.items()}

DOUBLE_CLICK = setting(
    "tray.doubleClick",
    "Tepsi simgesine cift tiklama",
    default="pause",
    choices=tuple(DOUBLE_CLICK_LABELS),
    labels=DOUBLE_CLICK_LABELS,
    legacy=DOUBLE_CLICK_LEGACY,
    category=Category.TRAY,
    tags="tepsi tray cift tiklama simge",
    desc=(
        "Sistem tepsisindeki simgeye cift tiklayinca ne olsun -- secenekler "
        "tepsi menusundeki maddelerin ayni. Tek tiklama Windows'un kendi isi "
        "(menuyu acar), ona karisilmiyor. Simge ISARETLI iken (kirmizi = hata, "
        "sari = uyari) bu ayar gecersiz: son hatalar penceresi acilir."
    ),
)

SINGLE_CLICK = setting(
    "tray.singleClick",
    "Tepsi simgesine tek tiklama",
    default="none",
    choices=tuple(SINGLE_CLICK_LABELS),
    labels=SINGLE_CLICK_LABELS,
    legacy=SINGLE_CLICK_LEGACY,
    category=Category.TRAY,
    tags="tepsi tray tek tiklama sol tik simge",
    desc=(
        "Sistem tepsisindeki simgeye SOL tek tiklayinca ne olsun. Sag tik "
        "menuyu acar, ona karisilmiyor.\n\n"
        "Cift tiklama ayariyla birlikte kullanilirsa tek tikin isi HER "
        "SEFERINDE once calisir (cift tiklama tek tikla baslar) -- ikisine "
        "birden is baglamadan once bunu hesaba kat. Simge ISARETLI iken "
        "(kirmizi = hata, sari = uyari) bu ayar gecersiz: son hatalar "
        "penceresi acilir."
    ),
)


#: Ipucunun uzunluk siniri: `szTip` alaninin gercek kapasitesi (128
#: karakterlik alan, sonda bos sonlandirici). Once 63'e cekilmisti (cok
#: eski kabuklarin siniri) ve tek tik + cift tik BIRLIKTE ayarliyken
#: ikincisi sessizce dusuyordu -- ipucunun tasimasi gereken asil bilgi.
#: Sira yine onemli (bkz. `_tooltip`): kesilecek olan metnin SONU olur.
TOOLTIP_LIMIT = 127

#: Parca ayraci: HER PARCA KENDI SATIRINDA. Tek satira sikistirilmisti,
#: cunku uc satir denemesinde tepside yalnizca ilki goruluyordu -- sucu
#: Windows'un degil, ipucunu ezen `app.on_start` satirininmis.
TOOLTIP_SEP = "\n"


def _fit(parts: list[str]) -> str:
    """Parcalari sinira kadar birlestirir; sigmayan SONDAN dusuyor."""
    tip = parts[0]
    for part in parts[1:]:
        candidate = f"{tip}{TOOLTIP_SEP}{part}"
        if len(candidate) > TOOLTIP_LIMIT:
            break
        tip = candidate
    return tip


def make_icon(
    size: int = 64,
    paused: bool = False,
    error: bool = False,
    warn: bool = False,
    dev: bool = False,
) -> QIcon:
    """Kaskadi anlatan basit simge: saga dogru inen uc cubuk.

    Duraklatilmisken ayni sekil gri zeminde -- AHK'nin Suspend simgesi gibi,
    program calisiyor ama tuslara dokunmuyor demek. Sonra siddet sirasi:
    kirmizi (ERROR+, bir sey bozuldu), sari (WARNING, dikkat ama calisiyor).
    Duraklatma hepsinden oncelikli, cunku o an tuslarin neden olmedigini
    bilmek birikmis bir uyaridan daha acil.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    if paused:
        ground = PAUSED_BACKGROUND
    elif error:
        ground = ERROR_BACKGROUND
    elif warn:
        ground = WARN_BACKGROUND
    else:
        ground = BACKGROUND

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(ground))
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)

    painter.setBrush(QBrush(BAR))
    unit = size / 16.0
    for index in range(3):
        painter.drawRoundedRect(
            QRectF(
                unit * (3 + index * 1.6),
                unit * (3.2 + index * 3.6),
                unit * (9 - index * 1.6),
                unit * 2.2,
            ),
            unit * 1.1,
            unit * 1.1,
        )

    # Gelistirme modu: mor halka. Simge tepside 16 px'e inecegi icin
    # cizgi kalinligi oranli veriliyor ve dikdortgen yarim kalinlik iceri
    # cekiliyor -- yoksa halkanin disi kirpiliyor.
    if dev:
        stroke = size * 0.09
        pen = QPen(DEV_RING)
        pen.setWidthF(stroke)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = stroke / 2.0
        painter.drawRoundedRect(
            QRectF(inset, inset, size - stroke, size - stroke),
            size * 0.20,
            size * 0.20,
        )
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    def __init__(
        self,
        version: str,
        on_monitor: Callable[[], None],
        on_restart: Callable[[], None],
        on_exit: Callable[[], None],
        on_restart_dev_off: Callable[[], None] = lambda: None,
        on_pause_dialog: Callable[[], None] = lambda: None,
        on_toggle_pause: Callable[[], None] = lambda: None,
        on_settings: Callable[[], None] = lambda: None,
        on_copy_error: Callable[[], None] = lambda: None,
        on_show_log: Callable[[], None] = lambda: None,
        on_show_errors: Callable[[], None] = lambda: None,
        computer: str = "",
        parent=None,
    ) -> None:
        super().__init__(make_icon(), parent)
        self.version = version
        #: Hangi bilgisayar: `work` / `home` -- `keymap.current_computer`.
        #: Ipucunun ILK yarisi bu: davranis farklarini (is bilgisayarinda
        #: ekran koruyucu engelleyici gibi) aciklayan bilgi. "Profil"
        #: DEMIYORUZ; o kelime uygulama profillerinin (profiles.json).
        self.computer = computer
        self.paused = False
        #: Gelistirme modu acik mi -- simgede mor halka, ipucunda etiket.
        #: Ayardan da gelebilir bayraktan da; tepsi ayrimi bilmiyor.
        self.dev = False
        self.error_count = 0
        #: Bunlarin kaci ERROR+ -- simgeyi KIRMIZI yapan sayi budur.
        self.severe_count = 0

        self._handlers = {
            "pause": on_toggle_pause,
            "restart": on_restart,
            "restart_dev_off": on_restart_dev_off,
            "pause_dialog": on_pause_dialog,
            "settings": on_settings,
            "monitor": on_monitor,
            "copy_error": on_copy_error,
            "show_log": on_show_log,
        }
        #: Simge KIRMIZI ya da SARI iken cift tiklama bunu cagirir -- cift
        #: tiklama ayarindan bagimsiz. Isaretli simgeye tiklayan "ne oldu"
        #: diye bakiyor; o an Pause/Play yapmak istemiyor.
        self._on_show_errors = on_show_errors

        menu = QMenu()

        # AHK: Suspend.  Isaretlenebilir tek madde -- ayri "devam et" maddesi
        # koymak yerine kutucuk, cunku durumu da gostermesi gerekiyor. Surum
        # ayri bir baslik satirinda degil burada: menunun ilk satiri zaten
        # okunuyor, pasif bir baslik bir satiri bosa harciyordu.
        self.pause_action = self._add(menu, "", on_toggle_pause)
        self.pause_action.setCheckable(True)
        self._add(menu, "Reload", on_restart)
        # YALNIZ gelistirme modu acikken gorunur (bkz. set_dev). Mod
        # `--dev` bayragiyla aciksa duz "Reload" onu her seferinde geri
        # getiriyor; bu madde bir sonraki calismayi kapali baslatiyor.
        self.dev_off_action = self._add(menu, "Reload (dev off)", on_restart_dev_off)
        self.dev_off_action.setVisible(False)
        # AHK menus.ahk `DialogPauseGui` (Pause & c / Pause & End): duraklat +
        # yeniden baslat + kaydetmeden yeniden baslat + cikis tek pencerede.
        # Tepsiden de acilsin -- Pause tusu olmayan klavyede tek yol buydu.
        self._add(menu, "Pause menu...", on_pause_dialog)
        menu.addSeparator()

        self._add(menu, "Settings...", on_settings)
        self._add(menu, "Event monitor...", on_monitor)
        self.error_action = self._add(menu, "", on_copy_error)
        self._add(menu, "Show log...", on_show_log)
        menu.addSeparator()
        self._add(menu, "Exit", on_exit)

        self._menu = menu  # GC'ye yem olmasin
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        # Ipucu tek yerde (`_tooltip`) ve TEK SEFERDE kuruluyor: parca parca
        # eklenen bir metin, durumun bir parcasi degisince yarisi eski
        # kaliyordu. Bu iki cagri durumu tamamliyor, ipucu ondan sonra
        # yaziliyor.
        self.set_paused(False)
        self.set_error_count(0)
        # Tiklama satirlari AYARDAN okunuyor; ayar degisince ipucu da
        # tazelensin -- "dbClick = Pause" yazarken baska is yapmasin.
        self._click_sub = lambda _value, _old: self._refresh()
        SINGLE_CLICK.subscribe(self._click_sub)
        DOUBLE_CLICK.subscribe(self._click_sub)

    @staticmethod
    def _add(menu: QMenu, text: str, slot: Callable[[], None]) -> QAction:
        action = QAction(text, menu)
        action.triggered.connect(lambda _checked=False: slot())
        menu.addAction(action)
        return action

    def _on_activated(self, reason) -> None:
        """Tek / cift tiklama -- ikisi de ayardan.

        Windows tek tikta once `Trigger`, cift tikta `Trigger` VE ardindan
        `DoubleClick` gonderir; ayirmak icin zamanlayiciyla beklemek
        gerekirdi ve o bekleme tek tiki hissedilir sekilde yavaslatirdi.
        Bunun yerine tek tikin varsayilani "hicbir sey": iki ayara birden
        is baglayan, tek tikin de calisacagini bilerek yapiyor (ayarin
        aciklamasinda yaziyor).
        """
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            name = str(SINGLE_CLICK.get())
            if name == "none":
                return
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            name = str(DOUBLE_CLICK.get())
        else:
            return
        # Isaretli simge her iki tiklamada da "ne oldu" demektir.
        if self.error_count:
            self._on_show_errors()
            return
        self._handlers.get(name, self._handlers["pause"])()

    # ---- durum ----

    def set_paused(self, paused: bool) -> None:
        """Menu kutucugu + simge + arac ipucu tek yerden guncellenir."""
        self.paused = paused
        self.pause_action.setChecked(paused)
        self.pause_action.setText(
            f"Play  (v{self.version})" if paused else f"Pause  (v{self.version})"
        )
        self._refresh()

    def set_dev(self, active: bool) -> None:
        """Gelistirme modunu simgede goster.

        Neden gorunur olmali: mod, programin davranisini degistiriyor
        (nobetci calisir, log sisirir) ve komut satirindan da acilabiliyor
        -- yani ayar ekraninda KAPALI gorunurken acik olabilir. Boyle bir
        sey ekranda hicbir iz birakmadan durmamali.
        """
        if active == self.dev:
            return
        self.dev = active
        self.dev_off_action.setVisible(active)
        self._refresh()

    def set_error_count(self, count: int, severe: int = 0) -> None:
        """Kayit sayisi: menude sayi gorunur, simge renk degistirir.

        `severe` = bunlarin kaci ERROR+. Simge YALNIZCA o sayi sifirdan
        buyukken kirmizi; geri kalani (WARNING) sari. Bkz. dosya basi.
        """
        self.error_count = count
        self.severe_count = min(severe, count)
        self.error_action.setText(
            f"Copy last error  ({count})" if count else "Copy last error"
        )
        self.error_action.setEnabled(bool(count))
        self._refresh()

    def _refresh(self) -> None:
        self.setIcon(
            make_icon(
                paused=self.paused,
                error=bool(self.severe_count),
                warn=bool(self.error_count),
                dev=self.dev,
            )
        )
        self.setToolTip(self._tooltip())

    def _tooltip(self) -> str:
        """Fare tepside beklerken cikan metin -- SATIR SATIR, TEK PARCADA.

        Sira ONEM sirasi (bkz. `_fit`): kimlik (surum + calisan kopya),
        sonra tiklamalar, en sonda durum. Durum en sonda cunku onu simgenin
        RENGI zaten soyluyor (gri = duraklatildi, kirmizi = hata, sari =
        uyari, mor halka = gelistirme); sinira takilip dusecek olan, iki
        yerde birden duran bilgi olsun.

        Tiklamalar ayardan okunuyor: sabit yazilmis olsaydi ayari degistiren
        kullanicida yanlis bilgi olarak asili kalirdi.
        """
        # Yapim damgasi (`+0908_0907*`) ipucuna GIRMIYOR: tek basina 16
        # karakter yiyor. Tam surum tepsi menusunun ilk maddesinde duruyor.
        head = f"KeyPilot {self.version.split('+', 1)[0]}"
        if self.computer:
            head += f" - {self.computer}"
        parts = [head]

        # Simge ISARETLIYKEN her iki tiklama da log penceresini aciyor
        # (bkz. `_on_activated`); ipucu o an ayardaki eylemi yazsaydi
        # tikladiginda baska sey olurdu.
        marked = bool(self.error_count)
        log_label = DOUBLE_CLICK_LABELS["show_log"]
        single = str(SINGLE_CLICK.get())
        if single != "none":
            parts.append(f"click = {log_label if marked else SINGLE_CLICK.label_for(single)}")
        double = str(DOUBLE_CLICK.get())
        parts.append(f"dbClick = {log_label if marked else DOUBLE_CLICK.label_for(double)}")

        if self.dev:
            parts.append("GELISTIRME")
        if self.paused:
            parts.append("paused")
        # "1 error" ile "1 warning" cok farkli iki haber; ayri duruyorlar.
        if self.severe_count:
            parts.append(f"{self.severe_count} error")
        if self.error_count - self.severe_count:
            parts.append(f"{self.error_count - self.severe_count} warning")
        return _fit(parts)

    def notify(self, title: str, message: str, ms: int = 2500) -> None:
        """AHK: TrayTip"""
        self.showMessage(title, message, make_icon(), ms)
