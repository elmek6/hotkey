"""Tus dagitimi -- CEKIRDEK katman. AHK'deki key_handler_*.ahk'lerin toplami.

Donanimdan gelen HER olay tek kapidan gecer: win32/hook.py olayi yakalar,
buradaki Dispatcher yut/birak kararini verir ve yapilacak isleri kuyruga
atar. Diger moduller tusa DOGRUDAN dokunmaz; ne yapilacagini keymap.py'deki
tablolarla buraya kayit ettirir, isin kendisi kuyruktan app.py'de calisir.

Mimari kural: bu sinifin key_filter/mouse_filter metotlari hook thread'inde
kosar. O(1) kalmak zorundalar -- karar ver, kuyruga at, don. Icinde I/O,
kilit bekleme, SendInput YOK (jest sirasindaki SetCursorPos tek istisna ve
yeniden girissiz). 300 ms asilirsa Windows hook'u sessizce dusurur.

Karar sirasi (her iki filtre icin ayni):

    1. kaskad makinesi (CascadeMachine.feed_key)  -- F15..F20, ScrollLock
    2. kombo takibi + kisayol tablosu (_dispatch)  -- F13 & F14, ^ & 1 ...
    3. onek durum makinesi (PrefixTracker)         -- yutma / geri gonderme
    4. jest ve surukleme ozel yollari              -- fare hareketi
"""

from __future__ import annotations

import contextlib
import queue
from collections.abc import Callable

from cascade.core.cascade import CascadeMachine, Phase, Run
from cascade.core.combo import ComboTracker
from cascade.core.hot_vectors import HotVectors
from cascade.core.hotkey import HotkeyTable
from cascade.core.keynames import key_name
from cascade.core.mouse import WM_MOUSEMOVE, MouseSeen, mouse_key
from cascade.core.prefix import Outcome, PrefixTracker
from cascade.core.turkish import TurkishLayout
from cascade.win32 import send
from cascade.win32.hook import KeyEvent, MouseEvent

VK_ESCAPE = 0x1B

# Fare onegi basiliyken bu kadar piksel oynarsa "surukleme" sayilir.
# Altinda kalan hareket titremedir; sag tik yaparken imlec bir iki piksel oynar.
DRAG_PX = 6

VK_LBUTTON = 0x01

# ARIZALI FARE FILTRESI (AHK: AutoHotkey.ahk `A_TimeSincePriorHotkey < 70`).
# Yipranmis mikro anahtar tek basimi iki basim olarak gonderir; ikinci basim
# ilkinden bu suren once gelirse insan eli degildir, yutuluyor. Gercek cift
# tiklamada iki basim arasi 100 ms'nin altina inmez (Windows'un cift tik
# suresi 500 ms), o yuzden bu esik normal kullanimi bozmaz.
DOUBLE_CLICK_MS = 70.0


class Dispatcher:
    """Yut/birak kararlarinin tek sahibi.

    `paused` ve `ui_open` bayraklarini app.py yazar: duraklatmada ve filtreli
    liste penceresi acikken hicbir karara girilmez, tuslar dokunulmadan gecer.
    """

    def __init__(
        self,
        machine: CascadeMachine,
        hotkeys: HotkeyTable,
        gestures: HotVectors,
        actions: queue.Queue,
        seen: queue.Queue,
        menu_open: Callable[[], bool],
    ) -> None:
        self.machine = machine
        self.hotkeys = hotkeys
        # Onek tuslari ayri bir durum makinesinde: yutma, basili tutma esigi
        # ve "kombo yapildi mi" bilgisi orada (core/prefix.py).
        self.prefixes = PrefixTracker(hotkeys.prefix_defs)
        # tracker basili tuslari bilir (hangi modifier, hangi onek);
        # tablo "bu kombo bize mi ait" sorusunu cevaplar.
        self.tracker = ComboTracker()
        # Jestler ayri bir izleyicide: fare hareketi sadece jest tanimli bir
        # onek basiliyken isleniyor, geri kalan zamanda hicbir sey yapmiyor.
        self.gestures = gestures
        self.actions = actions
        self.seen = seen  # (olay, yutuldu mu) -> olay izleyicisi
        self._menu_open = menu_open
        #: Cift basim icin BEKLETILEN kisa basim eylemleri:
        #: vk -> (eylem, aciklama, calisma ani). AHK'deki
        #: `KeyWait(key, "D T0.1")` beklemesinin karsiligi.
        self._pending_tap: dict[int, tuple[str, str, float]] = {}
        #: Son FIZIKSEL girdi ani (enjekte edilen girdi sayilmaz) --
        #: AHK `A_TimeIdlePhysical`. Ekran koruyucu engelleyici kullaniyor.
        self.last_physical = 0.0

        # Turkce eklentisi (AHK turkish_layout_addon.ahk). ScrollLock ile
        # acilir; hangi VK hangi harf, `turkish_keys` ile app.py'den gelir
        # (duzene bagli, calisma aninda soruluyor).
        self.turkish = TurkishLayout()
        self.turkish_keys: dict[int, str] = {}

        self.paused = False
        self._ui_open = False
        self._hk_swallowed: set[int] = set()  # yuttugumuz keydown'in keyup'i
        # Jest sirasinda imlecin tutulacagi nokta ve son geri bildirim ani.
        self._freeze_at: tuple[int, int] | None = None
        #: Jest sirasinda EN SON gorulen imlec noktasi -- fark buradan
        #: aliniyor (bkz. `_gesture_move`).
        self._gesture_at: tuple[int, int] | None = None
        #: `hotVector.freezeCursor`: eski davranis (imlec her olayda
        #: baslangica geri konur). app.py ayardan dolduruyor.
        self.freeze_cursor = False
        self._prefix_at: tuple[int, int] | None = None
        self._tip_t = 0.0
        # Yutup beklettigimiz fare onegi surukleme oldugu anlasilinca gercek
        # basimi enjekte ediliyor; bu kume onlari tutuyor ki birakma olayi
        # da uygulamaya gecsin.
        self._passed_through: set[int] = set()
        # `ui_open` acikken hicbir olay islenmiyor, ama SECIMI YAPAN tusun
        # birakilmasi yine de ogrenilmek zorunda: F14 basili tutulurken snip
        # acilir ve tus birakilinca secim biter. GetAsyncKeyState burada ise
        # yaramaz -- LL hook'ta YUTULAN keydown Windows'un tus durumu
        # tablosunu guncellemez, F14 hic basilmamis gorunur. Bu yuzden
        # durumu hook'un kendisinden tutuyoruz.
        self._watch_vk = 0
        self._watch_down = False
        # Arizali fare filtresi: son sol tus BASIMININ ani ve "yuttugumuz
        # basimin BIRAKMASI da yutulsun" bayragi.
        self._lbutton_t = 0.0
        self._bounce_up = False
        #: Filtre kapatilabilsin diye ayri bayrak (tepsi/menu ile acilir).
        self.double_click_guard = True

    def watch(self, vk: int) -> None:
        """Bu tusun basili/birakildi durumunu izle (ui/snip.py yokluyor).

        Baslangic durumu onek takipcisinden: eylem kuyruktan gecerken
        kullanici tusu coktan birakmis olabilir; o zaman "basili" demek
        secimi sonsuza dek acik birakirdi.
        """
        self._watch_vk = vk
        self._watch_down = bool(vk) and vk in self.prefixes.held

    def watch_held(self) -> bool:
        """Izlenen tus hala basili mi? (ui/snip.py yokluyor.)"""
        return self._watch_down

    # ---- hook thread ----

    def key_filter(self, event: KeyEvent) -> bool:
        """Hook thread'inde calisir. O(1): karar ver, kuyruga at, don."""
        if event.ours:
            return False
        # Izlenen tusun (F14) durumu her kosulda kaydedilir: menu/filtre
        # penceresi acikken olay asagida durdurulsa bile secimi bitiren
        # BIRAKMA kaybolmamali. Olayin kendisi yutulmuyor.
        if self._watch_vk and event.vk == self._watch_vk:
            self._watch_down = event.down
        if not event.injected:
            self.last_physical = event.t
        if self.paused or self.ui_open:
            return False

        # TURKCE ASAMASI kaskaddan ve kisayol tablosundan ONCE, ama yalniz
        # makine BOSTA ve hicbir onek basili degilken: `F15 & c` gibi bir
        # kombo Turkce harfe yem olmasin. Kapaliyken tek bayrak kontrolu.
        if (
            self.turkish.enabled
            and not self.prefixes.held
            and self.machine.phase == Phase.IDLE
        ):
            char = self.turkish_keys.get(event.vk)
            if char and not send.hard_modifier_down():
                upper = send.caps_on() != send.shift_down()
                swallow, actions = self.turkish.feed(char, event.down, event.t, upper)
                if swallow:
                    for action in actions:
                        self._put(Run(action, key=event.vk))
                    with contextlib.suppress(queue.Full):
                        self.seen.put_nowait((event, True))
                    return True

        # Acik menuyu Esc kapatsin. Menu klavye yakalamasini her zaman
        # alamiyor (tepsi uygulamasinin aktif penceresi yok), ama hook
        # her tusu goruyor -- en guvenli yer burasi.
        if event.down and event.vk == VK_ESCAPE and self._menu_open():
            self._put(Run("menu.close"))
            return True

        # Onek basiliyken kisayol tablosu kaskaddan ONCE denenir: `F13 & F15`
        # yazilabilsin diye. F15 ayni zamanda kaskad tusu; once makineye
        # sorulsa F13'u gormeden kendi kaskadini baslatirdi. Makine mesgulken
        # (HELD/MENU) sira degismez -- kaskad kombolari makinenin isi.
        if self.prefixes.held and self.machine.phase == Phase.IDLE:
            swallow, actions = self._dispatch(event.vk, event.down, event.t)
            if not swallow:
                swallow, extra = self.machine.feed_key(event.vk, event.down, event.t)
                actions += extra
        else:
            swallow, actions = self.machine.feed_key(event.vk, event.down, event.t)
            if not swallow:
                swallow, extra = self._dispatch(event.vk, event.down, event.t)
                actions += extra

        for action in actions:
            self._put(action)
        with contextlib.suppress(queue.Full):
            self.seen.put_nowait((event, swallow))
        return swallow

    def mouse_filter(self, event: MouseEvent) -> bool:
        """Fare de ayni yoldan gecer: dugme bir tus koduna cevrilir ve ayni
        tabloya sorulur. Boylece `~LButton & F16` yazimi calisiyor -- fare
        ile klavye tek bir kombo evreninde.

        Tekerlegin birakma olayi yok: basili kalmis gorunmesin diye
        ComboTracker'a basim ve birakma ard arda veriliyor. Verilmezse
        WheelUp sonsuza kadar "basili" sayilir ve sonraki tuslara onek olur.
        """
        if not event.injected:
            self.last_physical = event.t
        if event.ours or self.paused or self.ui_open:
            return False

        if event.message == WM_MOUSEMOVE:
            # Sicak yol: jest izlenmiyorsa tek bir bayrak kontrolu.
            if not self.gestures.watching:
                self._drag_check(event)
                return False
            return self._gesture_move(event)

        key = mouse_key(event.message, event.data)
        if key is None:
            return False
        vk, down = key

        # Arizali fare: cok hizli gelen IKINCI basim yutulur. Karar burada,
        # kaskad/kombo yollarindan ONCE: yutulan basim hicbir duruma
        # dokunmamali, yoksa onek takipcisi ac kapali kalir.
        if vk == VK_LBUTTON and self.double_click_guard:
            if down:
                gap = (event.t - self._lbutton_t) * 1000.0
                self._lbutton_t = event.t
                self._bounce_up = 0.0 < gap < DOUBLE_CLICK_MS
                if self._bounce_up:
                    self._put(Run(f"click.bounce:{gap:.0f}", key=vk))
                    return True
            elif self._bounce_up:
                # Yuttugumuz basimin birakmasi: uygulamaya tek basina
                # gitseydi "basilmadan birakildi" gibi gorunurdu.
                self._bounce_up = False
                return True

        # Gercek basimini gecirdigimiz onek (surukleme): birakmasi da gecsin.
        if not down and vk in self._passed_through:
            self._passed_through.discard(vk)
            self._prefix_at = None
            self.prefixes.key_up(vk, event.t)
            self.tracker.key_up(vk, event.t)
            return False

        # keymap F19'daki `.combo("LButton", ...)` icin: fare dugmesi
        # kaskad makinesine de gidiyor, yoksa F19 basiliyken sol tik
        # gorunmezdi.
        swallow, actions = self.machine.feed_key(vk, down, event.t)
        if not swallow:
            swallow, extra = self._dispatch(vk, down, event.t, momentary=vk > 0xFF)
            actions += extra
        for action in actions:
            self._put(action)
        # Fare dugmeleri de olay izleyicisine dusuyor (klavye gibi). Hareket
        # buraya HIC gelmiyor -- yukarida erken donuyor, yoksa liste saniyede
        # yuzlerce satirla dolardi.
        with contextlib.suppress(queue.Full):
            self.seen.put_nowait(
                (MouseSeen(vk=vk, down=down, t=event.t, x=event.x, y=event.y), swallow)
            )
        return swallow

    def tick(self, now: float) -> list[tuple[int, str]]:
        """Onek tuslarinin basili-tutma esigi -- Qt zamanlayicisi cagirir.

        Hook thread'inde yapilamaz: tus BASILI dururken hicbir olay gelmiyor,
        esigi yoklayan bir zamanlayici gerekiyor. AHK bunu bloke eden
        dongude yapiyordu.
        """
        fired = self.prefixes.tick(now)
        # Cift basim penceresi doldu: bekletilen kisa basim eylemi calissin.
        for vk, (action, _desc, deadline) in list(self._pending_tap.items()):
            if now >= deadline:
                del self._pending_tap[vk]
                fired.append((vk, action))
        return fired

    @property
    def ui_open(self) -> bool:
        return self._ui_open

    @ui_open.setter
    def ui_open(self, state: bool) -> None:
        """Pencere/menu acilirken ve kapanirken hayalet durumu temizler.

        Bayrak acikken `key_filter` / `mouse_filter` olaylari erkenden
        birakiyor -- BIRAKMA olaylari da dahil. F14'u basili tutup secim
        aracini acan kullanici tusu birakinca o keyup yutuluyor ve
        PrefixTracker F14'u sonsuza dek "basili" saniyordu: secim
        kapandiktan sonra her tekerlek `F14 & WheelUp` sayilip sesi
        oynatiyordu. Gecisin iki yaninda da temizlemek bunu bitirir.
        """
        if state == self._ui_open:
            return
        self._ui_open = state
        self.reset()

    def reset(self) -> None:
        """Duraklatma / busy kilidini acma: hayalet durumu temizler."""
        self.machine.reset()
        self.prefixes.reset()
        self.tracker.reset()
        self.gestures.reset()
        self._freeze_at = None
        self._gesture_at = None
        self._prefix_at = None
        self._pending_tap.clear()
        self._passed_through.clear()
        self._hk_swallowed.clear()

    # ---- ic akis (hepsi hook thread'inde) ----

    def _put(self, action) -> None:
        with contextlib.suppress(queue.Full):
            self.actions.put_nowait(action)

    def _has_drag(self, vk: int) -> bool:
        definition = self.prefixes.definition(vk)
        return definition is not None and bool(definition.drag_action)

    def _gesture_move(self, event: MouseEvent) -> bool:
        """Jest sirasindaki fare hareketi.

        Olcum jestin BASLADIGI noktadan, kesintisiz: her olayda bir onceki
        noktaya gore fark alinip birikime ekleniyor.

        Once imlec her olayda baslangica GERI KONUYORDU ("dondurma"). Yavas
        hareket o yuzden hic jest baslatmiyordu: imleci geri koymak
        Windows'un imlec hizlandirma birikimini de sifirliyor, yavas itilen
        farenin uretecegi hareket 0 piksele yuvarlaniyor ve olay hic fark
        tasimiyordu. Simdi imlec serbest -- hareket olayi yine YUTULUYOR
        (tiklama, hover, surukleme olmuyor), yalniz konum akmaya devam
        ediyor; jest bitince imlec baslangic noktasina geri konuyor
        (`_end_gesture`). Eski davranis `hotVector.freezeCursor` ayariyla
        geri gelir.
        """
        origin = self._freeze_at
        if origin is None:
            return False
        last = self._gesture_at or origin
        dx = event.x - last[0]
        dy = event.y - last[1]
        if dx or dy:
            self._gesture_at = (event.x, event.y)
            for gesture in self.gestures.move(dx, dy):
                self.prefixes.combo_used(gesture.prefix)
                for _ in range(gesture.steps):
                    self._put(Run(gesture.action, key=gesture.prefix, desc=gesture.desc))
            self._gesture_tip(event.t)
        if self.freeze_cursor:
            # Cagri hook thread'inde ama SendInput degil, yeniden girisli degil.
            send.set_cursor_pos(*origin)
            self._gesture_at = origin
        return True

    def _end_gesture(self) -> None:
        """Jest bitti: imleci basladigi yere geri koy ve sayaclari birak.

        Imleci geri vermek AHK'deki dondurmanin gorunur sonucuyla ayni:
        kullanici jesti bitirdiginde imlec kalktigi yerdedir.
        """
        origin = self._freeze_at
        if origin is not None and not self.freeze_cursor and self._gesture_at:
            send.set_cursor_pos(*origin)
        self._freeze_at = None
        self._gesture_at = None

    def _gesture_tip(self, t: float) -> None:
        """Yon ve mesafe geri bildirimi. AHK jest sirasinda bunu yaziyordu.

        Kisilmis: hareket olayi saniyede yuzlerce geliyor, ipucunu o hizda
        yeniden cizmek gereksiz. 60 ms'de bir yeter.
        """
        if (t - self._tip_t) < 0.06:
            return
        self._tip_t = t
        for prefix in self.gestures.active:
            status = self.gestures.status(prefix)
            if status is None:
                continue
            self._put(Run(f"tip:{status.text}", key=prefix))

    def _drag_check(self, event: MouseEvent) -> None:
        """Onek basiliyken fare suruldu mu? Iki ayri is yapar.

        1. **Surukleme eylemi olan onek** (F14): tusa basip fareyi kimildatmak
           tusun anlamini degistirir -- F14 icin ekran alani secimi baslar.
           Kimildatmadan birakilirsa onek kendi tap eylemini calistirir
           (slot menusu). AHK'de bu ayrim yoktu; tusa basar basmaz secim
           gelirdi ve tusun oteki isleri kullanilamazdi.
        2. **Yutup beklettigimiz fare onegi** (sag tus): basimi yutuyoruz ki
           tekerlek cevrilince baglam menusu acilmasin. Kullanici sag tusu
           basili tutup fareyi suruyorsa bu bir SURUKLEME -- beklemeyi
           bitirip gercek basimi enjekte ediyoruz, o andan sonra her sey
           uygulamaya geciyor. Tuketme YALNIZCA tekerlek cevrildiginde.
        """
        origin = self._prefix_at
        if origin is not None and max(abs(event.x - origin[0]), abs(event.y - origin[1])) < DRAG_PX:
            return  # titreme: tusa basarken imlec bir iki piksel oynar
        for vk in self.prefixes.held:
            definition = self.prefixes.definition(vk)
            if definition is not None and definition.drag_action:
                if self.prefixes.is_used(vk):
                    continue  # bu basimda bir kez calisti, yeter
                self.prefixes.combo_used(vk)  # birakilinca tap eylemi calismasin
                # `{x}` / `{y}` yer tutuculari: eylem, suruklemenin BASLADIGI
                # noktayi bilmek isteyebilir. F14 secimi icin sart -- pencere
                # acilana kadar (ekran yakalama ~100 ms) imlec coktan
                # kimildamis olur ve cerceve yanlis yerden baslardi.
                action = definition.drag_action
                if origin is not None and "{x}" in action:
                    action = action.format(x=origin[0], y=origin[1])
                self._put(Run(action, key=vk, desc=definition.desc))
                continue
            if vk not in send.MOUSE_VK_NAMES or vk in self._passed_through:
                continue
            if vk not in self._hk_swallowed:
                # Yutmadigimiz onek (`~LButton`) zaten uygulamaya gitti;
                # bir de biz basim enjekte edersek CIFT basim olur ve
                # Paint'te cizgi cekmek gibi surukleme isleri bozulur.
                # Sol tus hicbir kosulda tuketilmez.
                continue
            self._passed_through.add(vk)
            self._hk_swallowed.discard(vk)
            self.prefixes.combo_used(vk)
            self._put(Run(f"button_down:{key_name(vk)}", key=vk))

    def _dispatch(
        self, vk: int, down: bool, t: float, momentary: bool = False
    ) -> tuple[bool, list]:
        """Klavye ve farenin ortak yolu: kombo takibi + kisayol tablosu."""
        if down:
            chord = self.tracker.key_down(vk, t)
            if momentary:  # tekerlek: basili kalmaz
                self.tracker.key_up(vk, t)
        else:
            self.tracker.key_up(vk, t)
            chord = None
        return self._hotkey_key(vk, down, t, chord)

    def _hotkey_key(self, vk: int, down: bool, t: float, chord) -> tuple[bool, list]:
        """Kaskadin ilgilenmedigi tus: kisayol tablosuna bakilir.

        Onek tusu (F13, `^`) basildigi anda karar verilmek zorunda -- LL hook
        keydown'da cevap veriyor, AHK gibi bekleyemez. Yutup yutmamayi
        PrefixTracker soyler (`~` ile tanimlananlar yutulmaz); ne olacagi
        birakildiginda ya da esik gecince belli olur.
        """
        if not down:
            return self._hotkey_up(vk, t)

        if chord is None:  # modifier'in kendisi: dokunma
            return False, []

        # Onek tusu, uzerinde baska onek YOKKEN ve modifier basili
        # DEGILKEN: karari ertele. Modifier sarti Tab/CapsLock onek olunca
        # sart oldu -- Alt+Tab, Ctrl+Tab, Shift+Tab yutulup birakilinca
        # gonderilseydi pencere/sekme degistirme bozulurdu. Modifierli
        # basimda onek hic devreye girmez, tus dogrudan uygulamaya gider.
        if self.prefixes.is_prefix(vk) and chord.prefix is None and not chord.modifiers:
            swallow = self.prefixes.key_down(vk, t)
            pending = self._pending_tap.pop(vk, None)
            if pending is not None and not chord.repeat:
                # AHK: pressType 4. Tek basim eylemi hic calismadi -- bu
                # basimin da kendi isi yok, birakilinca sessizce bitsin.
                definition = self.prefixes.definition(vk)
                self.prefixes.combo_used(vk)
                if swallow:
                    self._hk_swallowed.add(vk)
                action = definition.double_action if definition else ""
                return swallow, [Run(action, key=vk, desc="cift basim")] if action else []
            if swallow:
                self._hk_swallowed.add(vk)
            # Jest baslar: sayaclar sifirlanir ve baslangic noktasi not
            # edilir. Hareket olaylari bundan sonra yutulur.
            #
            # BASILI TUTMA TEKRARI baslatmaz: F13 basili tutuldugunda Windows
            # saniyede ~30 keydown daha uretiyor. Her biri jesti sifirdan
            # baslatinca birikim silinip duruyordu -- ekranda "jest bekliyor /
            # yatay kilitli / jest bekliyor..." donup hicbir adim uretmemesinin
            # sebebi buydu.
            if self.gestures.has(vk) and vk not in self.gestures.active:
                self.gestures.start(vk)
                self._freeze_at = send.cursor_pos()
                self._gesture_at = self._freeze_at
            elif vk in send.MOUSE_VK_NAMES or self._has_drag(vk):
                # Surukleme olcumunun baslangic noktasi: fare onegi icin
                # "surukleme mi tekerlek mi", F14 icin "secim mi menu mu".
                self._prefix_at = send.cursor_pos()
            return swallow, []

        binding = self.hotkeys.match(vk, chord.modifiers, chord.prefix)
        if binding is None:
            return False, []
        if chord.prefix is not None:
            self.prefixes.combo_used(chord.prefix)
        # Tek basina `~` ile yazilan tus (orta tus, Insert): eylem calisir,
        # tus uygulamaya AYNEN gider. Kombodaki `~` bundan ayri: orada
        # yutulmayan sey ONEK, kombo tusu yine yutulur.
        keep = binding.hotkey.passthrough and binding.hotkey.prefix is None
        if vk <= 0xFF and not keep:  # tekerlegin birakma olayi yok
            self._hk_swallowed.add(vk)
        if chord.repeat:  # basili tutmada eylem tekrarlanmaz, yutma surer
            return not keep, []
        return not keep, [Run(binding.action, key=vk, desc=binding.desc)]

    def _hotkey_up(self, vk: int, t: float) -> tuple[bool, list]:
        was_ours = vk in self._hk_swallowed
        self._hk_swallowed.discard(vk)
        if not self.prefixes.is_prefix(vk):
            return was_ours, []

        # Jest yapildiysa tusun isi bitti: ne menu, ne tap eylemi, ne de
        # tusun geri gonderilmesi. Istenen davranis buydu.
        if self.gestures.stop(vk):
            self.prefixes.key_up(vk, t)
            if not self.gestures.watching:
                self._end_gesture()
            return was_ours, []

        if self.prefixes.key_up(vk, t) is Outcome.NOTHING:
            return was_ours, []  # kombo yapildi ya da basili tutma calisti

        if not self.gestures.watching:
            self._end_gesture()
        if vk in send.MOUSE_VK_NAMES or self._has_drag(vk):
            self._prefix_at = None

        definition = self.prefixes.definition(vk)
        binding = self.hotkeys.match(vk)  # onegin kendi tanimi var mi
        if binding is not None:
            if definition is not None and definition.double_action:
                # AHK `KeyWait(key, "D T0.1")`: ikinci basim gelir mi diye
                # beklenir. Gelmezse `tick` bu eylemi calistirir.
                self._pending_tap[vk] = (
                    binding.action, binding.desc, t + definition.double_ms / 1000.0
                )
                return was_ours, []
            return was_ours, [Run(binding.action, key=vk, desc=binding.desc)]
        if was_ours:
            # Hicbir sey olmadi: yuttugumuz tusu geri ver, `^` yazilabilsin.
            return was_ours, [Run(f"send_key:{key_name(vk)}", key=vk)]
        return was_ours, []
