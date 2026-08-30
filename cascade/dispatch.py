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
from cascade.core.gesture import GestureTracker
from cascade.core.hotkey import HotkeyTable
from cascade.core.keynames import key_name
from cascade.core.mouse import WM_MOUSEMOVE, mouse_key
from cascade.core.prefix import Outcome, PrefixTracker
from cascade.win32 import send
from cascade.win32.hook import KeyEvent, MouseEvent

VK_ESCAPE = 0x1B

# Fare onegi basiliyken bu kadar piksel oynarsa "surukleme" sayilir.
# Altinda kalan hareket titremedir; sag tik yaparken imlec bir iki piksel oynar.
DRAG_PX = 6


class Dispatcher:
    """Yut/birak kararlarinin tek sahibi.

    `paused` ve `ui_open` bayraklarini app.py yazar: duraklatmada ve filtreli
    liste penceresi acikken hicbir karara girilmez, tuslar dokunulmadan gecer.
    """

    def __init__(
        self,
        machine: CascadeMachine,
        hotkeys: HotkeyTable,
        gestures: GestureTracker,
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

        self.paused = False
        self.ui_open = False
        self._hk_swallowed: set[int] = set()  # yuttugumuz keydown'in keyup'i
        # Jest sirasinda imlecin tutulacagi nokta ve son geri bildirim ani.
        self._freeze_at: tuple[int, int] | None = None
        self._prefix_at: tuple[int, int] | None = None
        self._tip_t = 0.0
        # Yutup beklettigimiz fare onegi surukleme oldugu anlasilinca gercek
        # basimi enjekte ediliyor; bu kume onlari tutuyor ki birakma olayi
        # da uygulamaya gecsin.
        self._passed_through: set[int] = set()

    # ---- hook thread ----

    def key_filter(self, event: KeyEvent) -> bool:
        """Hook thread'inde calisir. O(1): karar ver, kuyruga at, don."""
        if event.ours or self.paused or self.ui_open:
            return False

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
        return swallow

    def tick(self, now: float) -> list[tuple[int, str]]:
        """Onek tuslarinin basili-tutma esigi -- Qt zamanlayicisi cagirir.

        Hook thread'inde yapilamaz: tus BASILI dururken hicbir olay gelmiyor,
        esigi yoklayan bir zamanlayici gerekiyor. AHK bunu bloke eden
        dongude yapiyordu.
        """
        return self.prefixes.tick(now)

    def reset(self) -> None:
        """Duraklatma / busy kilidini acma: hayalet durumu temizler."""
        self.machine.reset()
        self.prefixes.reset()
        self.tracker.reset()
        self.gestures.reset()
        self._freeze_at = None
        self._prefix_at = None
        self._passed_through.clear()
        self._hk_swallowed.clear()

    # ---- ic akis (hepsi hook thread'inde) ----

    def _put(self, action) -> None:
        with contextlib.suppress(queue.Full):
            self.actions.put_nowait(action)

    def _gesture_move(self, event: MouseEvent) -> bool:
        """Jest sirasindaki fare hareketi.

        Imlec DONDURULUYOR: hareket olayi yutuluyor ve imlec baslangictaki
        noktaya geri konuyor. AHK'de de jest sirasinda imlec sabitti --
        yanlislikla bir seye tiklanmasin ve jest bitince imlec yerinde
        kalsin diye. Yutuldugu icin mutlak konum akmaz; delta, dondurma
        noktasina gore olculur.
        """
        anchor = self._freeze_at
        if anchor is None:
            return False
        dx = event.x - anchor[0]
        dy = event.y - anchor[1]
        # Kendi SetCursorPos'umuzun urettigi olay: delta sifir, isleme.
        if dx or dy:
            for gesture in self.gestures.move(dx, dy):
                self.prefixes.combo_used(gesture.prefix)
                for _ in range(gesture.steps):
                    self._put(Run(gesture.action, key=gesture.prefix, desc=gesture.desc))
            self._gesture_tip(event.t)
        # Yutmak cogu farede imleci zaten dondurur; surucusu kendi konumunu
        # yazanlar icin ikinci kemer. Cagri hook thread'inde ama SendInput
        # degil, yeniden girisli degil.
        send.set_cursor_pos(*anchor)
        return True

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
        """Yutup beklettigimiz bir fare onegi varken fare suruldu mu?

        Sag tus icin: basimi yutuyoruz ki tekerlek cevrilince baglam menusu
        acilmasin. Ama kullanici sag tusu basili tutup fareyi suruyorsa bu
        bir SURUKLEME -- beklemeyi burada bitirip gercek basimi enjekte
        ediyoruz, o andan sonra her sey uygulamaya geciyor. Istenen sira
        buydu: tuketme YALNIZCA tekerlek cevrildiginde.
        """
        origin = self._prefix_at
        if origin is not None and max(abs(event.x - origin[0]), abs(event.y - origin[1])) < DRAG_PX:
            return  # titreme: sag tik yaparken imlec bir iki piksel oynar
        for vk in self.prefixes.held:
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
            self.prefixes.combo_used(vk)  # birakilinca tap eylemi calismasin
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

        # Onek tusu, uzerinde baska onek yokken: karari ertele.
        if self.prefixes.is_prefix(vk) and chord.prefix is None:
            swallow = self.prefixes.key_down(vk, t)
            if swallow:
                self._hk_swallowed.add(vk)
            # Jest baslar: sayaclar sifirlanir ve imlecin donacagi nokta
            # not edilir. Hareket olaylari bundan sonra yutulur.
            if self.gestures.has(vk):
                self.gestures.start(vk)
                self._freeze_at = send.cursor_pos()
            elif vk in send.MOUSE_VK_NAMES:
                # Fare onegi: surukleme mi tekerlek mi, imlecin nereden
                # kalktigina bakarak anlayacagiz.
                self._prefix_at = send.cursor_pos()
            return swallow, []

        binding = self.hotkeys.match(vk, chord.modifiers, chord.prefix)
        if binding is None:
            return False, []
        if chord.prefix is not None:
            self.prefixes.combo_used(chord.prefix)
        if vk <= 0xFF:  # tekerlegin birakma olayi yok, listede birakmayalim
            self._hk_swallowed.add(vk)
        if chord.repeat:  # basili tutmada eylem tekrarlanmaz, yutma surer
            return True, []
        return True, [Run(binding.action, key=vk, desc=binding.desc)]

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
                self._freeze_at = None
            return was_ours, []

        if self.prefixes.key_up(vk, t) is Outcome.NOTHING:
            return was_ours, []  # kombo yapildi ya da basili tutma calisti

        if not self.gestures.watching:
            self._freeze_at = None
        if vk in send.MOUSE_VK_NAMES:
            self._prefix_at = None

        binding = self.hotkeys.match(vk)  # onegin kendi tanimi var mi
        if binding is not None:
            return was_ours, [Run(binding.action, key=vk, desc=binding.desc)]
        if was_ours:
            # Hicbir sey olmadi: yuttugumuz tusu geri ver, `^` yazilabilsin.
            return was_ours, [Run(f"send_key:{key_name(vk)}", key=vk)]
        return was_ours, []
