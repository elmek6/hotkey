"""Dispatcher'in yutma karari: onek tusu, kombo ve geri gonderme.

Dispatcher dogrudan kuruluyor (hook thread'i yok, Qt yok); karar veren
metotlar dogrudan cagriliyor. Test ettigimiz sey tam olarak hook
callback'inin icinde calisan kod.
"""

import queue

from cascade.core.cascade import CascadeMachine
from cascade.core.hot_vectors import HotVectors
from cascade.core.hotkey import HotkeyTable
from cascade.core.keynames import VK_WHEEL_UP, register_name
from cascade.dispatch import Dispatcher

F13, F14, CARET, ONE = 0x7C, 0x7D, 0xDC, 0x31
LBUTTON, MBUTTON, F16 = 0x01, 0x04, 0x7F
CTRL = 0xA2


def _drain(q: queue.Queue) -> list:
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    return items


def make_dispatcher() -> Dispatcher:
    register_name(CARET, "Caret")
    table = (
        HotkeyTable()
        .add("F13", "tip:F13", "ipucu")
        .add("F13 & F14", "tip:kombo", "kombo")
        .add("F13 & WheelUp", "send_key:#NumpadAdd", "buyut")
        .add("Caret & 1", "send_key:^v", "yapistir")
        .add("~LButton & F16", "send_key:^v", "tikla + yapistir")
        .prefix("Caret", hold_action="menu.clip", hold_ms=350)
    )
    return Dispatcher(
        machine=CascadeMachine(),
        hotkeys=table,
        # Bos jest izleyicisi: `has()` her tusa False der, yani jest yolu
        # kapali. Jestin kendi testleri tests/test_gesture.py icinde.
        gestures=HotVectors(),
        actions=queue.Queue(),
        seen=queue.Queue(),
        menu_open=lambda: False,
    )


def feed(box: Dispatcher, vk: int, down: bool, t: float, momentary: bool = False):
    """key_filter / mouse_filter'in ortak yarisi: tracker + tablo."""
    return box._dispatch(vk, down, t, momentary)


def actions(result) -> list[str]:
    return [a.action for a in result[1]]


def test_onek_tusu_basildiginda_yutulur_eylem_ertelenir():
    box = make_dispatcher()
    swallow, acts = feed(box, F13, True, 0.0)
    assert swallow is True
    assert acts == []  # F13'un kendi eylemi daha calismaz


def test_onek_tusu_tek_basina_birakilinca_kendi_eylemi_calisir():
    box = make_dispatcher()
    feed(box, F13, True, 0.0)
    result = feed(box, F13, False, 0.1)
    assert result[0] is True  # keyup da yutulur
    assert actions(result) == ["tip:F13"]


def test_kombo_yapilinca_onegin_kendi_eylemi_calismaz():
    """AHK'de de F13 & F14 sonrasi sade F13 tetiklenmez."""
    box = make_dispatcher()
    feed(box, F13, True, 0.0)
    combo = feed(box, F14, True, 0.05)
    assert combo[0] is True
    assert actions(combo) == ["tip:kombo"]

    feed(box, F14, False, 0.06)
    release = feed(box, F13, False, 0.10)
    assert actions(release) == []


def test_caret_tek_basina_kalirsa_geri_gonderilir():
    """`^` yutuldu ama komboya donusmedi: kullanici `^` yazabilmeli."""
    box = make_dispatcher()
    assert feed(box, CARET, True, 0.0)[0] is True
    result = feed(box, CARET, False, 0.08)
    assert actions(result) == ["send_key:Caret"]


def test_caret_ile_bir_yapistirir_ve_caret_yazilmaz():
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    combo = feed(box, ONE, True, 0.05)
    assert combo[0] is True
    assert actions(combo) == ["send_key:^v"]

    feed(box, ONE, False, 0.06)
    release = feed(box, CARET, False, 0.10)
    assert actions(release) == []  # geri gonderme YOK, `^` ekrana yazilmaz


def test_baglanmamis_tusa_dokunulmaz():
    box = make_dispatcher()
    assert feed(box, 0x41, True, 0.0) == (False, [])  # A tusu


def test_onek_basiliyken_baglanmamis_tus_serbest():
    """`^` basiliyken 2'ye basmak: tanim yok, tus alttaki uygulamaya gider."""
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    assert feed(box, 0x32, True, 0.05) == (False, [])


def test_otomatik_tekrar_eylemi_cogaltmaz():
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    first = feed(box, ONE, True, 0.05)
    repeat = feed(box, ONE, True, 0.10)  # tus basili kaldi
    assert actions(first) == ["send_key:^v"]
    assert actions(repeat) == []
    assert repeat[0] is True  # yutma devam eder


# ---- `~` gecirgen onek: fare dugmesi ----


def test_gecirgen_onek_yutulmaz():
    """LButton yutulsaydi hicbir yere tiklayamazdik. AHK: ~LButton & F16"""
    box = make_dispatcher()
    assert feed(box, LBUTTON, True, 0.0) == (False, [])


def test_gecirgen_onek_uzerine_kombo_calisir():
    box = make_dispatcher()
    feed(box, LBUTTON, True, 0.0)
    combo = feed(box, F16, True, 0.05)
    assert combo[0] is True  # F16 yutulur, LButton yutulmaz
    assert actions(combo) == ["send_key:^v"]


def test_gecirgen_onek_birakilinca_geri_gonderilmez():
    """Yutmadik ki geri verelim -- tik zaten uygulamaya gitti."""
    box = make_dispatcher()
    feed(box, LBUTTON, True, 0.0)
    feed(box, F16, True, 0.05)
    feed(box, F16, False, 0.06)
    assert feed(box, LBUTTON, False, 0.10) == (False, [])


def test_kombosuz_gecirgen_onek_sessiz_kalir():
    box = make_dispatcher()
    feed(box, LBUTTON, True, 0.0)
    assert feed(box, LBUTTON, False, 0.05) == (False, [])


# ---- basili tutma ----


def test_basili_tutma_esikte_calisir():
    """AHK cascadeCaret: kisa basim `^` yazar, basili tutma menu acar.

    Esik BIRAKMA aninda olculuyor (dispatch.tick degil, PrefixTracker.key_up):
    tus basiliyken tetiklemek jesti ortasindan kesiyordu.
    """
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    assert actions(feed(box, CARET, False, 0.4)) == ["menu.clip"]


def test_esik_altinda_birakinca_caret_yazilir():
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    assert actions(feed(box, CARET, False, 0.2)) != ["menu.clip"]  # esik 350 ms


def test_basili_tutmadan_sonra_caret_yazilmaz():
    """Menu acilinca `^` ekrana DUSMEMELI: iki eylem birden calismasin."""
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    assert actions(feed(box, CARET, False, 0.4)) == ["menu.clip"]


def test_kombo_yapilinca_basili_tutma_calismaz():
    box = make_dispatcher()
    feed(box, CARET, True, 0.0)
    feed(box, ONE, True, 0.05)
    assert box.tick(0.6) == []


# ---- surukleyince baska is yapan onek (F14) ----


def make_drag_dispatcher() -> Dispatcher:
    """F14: kimildatmadan birakinca menu, surukleyince ekran secimi."""
    table = (
        HotkeyTable()
        .add("F14", "menu.slots", "kisa: slot menusu")
        .prefix("F14", drag_action="select.start", desc="surukle: sec")
    )
    return Dispatcher(
        machine=CascadeMachine(),
        hotkeys=table,
        gestures=HotVectors(),
        actions=queue.Queue(),
        seen=queue.Queue(),
        menu_open=lambda: False,
    )


class _Mouse:
    """_drag_check'in okudugu alanlar."""

    def __init__(self, x: int, y: int) -> None:
        self.x, self.y = x, y
        self.t = 0.0


def test_kimildatmadan_birakilinca_tap_eylemi_calisir():
    """F14'e basip birakmak menuyu acar -- secim baslamaz."""
    box = make_drag_dispatcher()
    feed(box, F14, True, 0.0)
    box._prefix_at = (500, 500)
    release = feed(box, F14, False, 0.1)
    assert actions(release) == ["menu.slots"]


def test_titreme_suruklemeye_sayilmaz():
    """Tusa basarken imlec bir iki piksel oynar; secim baslamamali."""
    box = make_drag_dispatcher()
    feed(box, F14, True, 0.0)
    box._prefix_at = (500, 500)
    box._drag_check(_Mouse(503, 502))
    assert _drain(box.actions) == []
    assert actions(feed(box, F14, False, 0.1)) == ["menu.slots"]


def test_surukleyince_drag_eylemi_calisir_ve_menu_acilmaz():
    box = make_drag_dispatcher()
    feed(box, F14, True, 0.0)
    box._prefix_at = (500, 500)
    box._drag_check(_Mouse(560, 540))
    assert [a.action for a in _drain(box.actions)] == ["select.start"]
    # Surukleme "kombo" sayildi: birakinca menu acilmaz.
    assert actions(feed(box, F14, False, 0.3)) == []


def test_surukleme_bir_kez_tetiklenir():
    """Fare surdukce her harekette yeni secim baslatmaz."""
    box = make_drag_dispatcher()
    feed(box, F14, True, 0.0)
    box._prefix_at = (500, 500)
    box._drag_check(_Mouse(560, 540))
    box._drag_check(_Mouse(600, 580))
    assert len(_drain(box.actions)) == 1


# ---- onek + kaskad tusu cakismasi ----


def make_dispatcher_with_cascade() -> Dispatcher:
    """F15 hem kaskad tusu hem de `F13 & F15` kombosunun yancisi."""
    from cascade.core.builder import KeyBuilder, PressType

    f15_def = (
        KeyBuilder("F15", short=350)
        .main_key(PressType.SHORT, "send_key:^y")
        .show_menu(False)
        .build()
    )
    table = (
        HotkeyTable()
        .add("F13", "tip:F13", "ipucu")
        .add("F13 & F15", "slot.paste:6", "slot 6")
    )
    return Dispatcher(
        machine=CascadeMachine({f15_def.key: f15_def}),
        hotkeys=table,
        gestures=HotVectors(),
        actions=queue.Queue(),
        seen=queue.Queue(),
        menu_open=lambda: False,
    )


class _Key:
    """key_filter'in okudugu alanlar -- gercek KeyEvent kurmaya gerek yok."""

    def __init__(self, vk: int, down: bool, t: float) -> None:
        self.vk, self.down, self.t = vk, down, t
        self.ours = False
        #: Enjekte girdi (bizim gonderdigimiz tuslar) fiziksel sayilmaz --
        #: dispatch.key_filter bunu okuyor.
        self.injected = False


def test_onek_basiliyken_kaskad_tusu_tablo_kombosu_olur():
    """`F13 & F15`: once tablo denenir, F15 kendi kaskadini baslatmaz."""
    box = make_dispatcher_with_cascade()
    F15 = 0x7E
    assert box.key_filter(_Key(F13, True, 0.0)) is True
    assert box.key_filter(_Key(F15, True, 0.05)) is True
    fired = [a.action for a in _drain(box.actions)]
    assert fired == ["slot.paste:6"]
    # Makine hic devreye girmedi: F15 birakilinca kaskad eylemi de yok.
    assert box.key_filter(_Key(F15, False, 0.10)) is True
    assert [a.action for a in _drain(box.actions)] == []


def test_onek_yokken_kaskad_tusu_normal_calisir():
    box = make_dispatcher_with_cascade()
    F15 = 0x7E
    assert box.key_filter(_Key(F15, True, 0.0)) is True  # makine yuttu
    box.key_filter(_Key(F15, False, 0.1))
    fired = [a.action for a in _drain(box.actions)]
    assert "send_key:^y" in fired  # kisa basim eylemi makineden geldi


# ---- tekerlek ----


def test_tekerlek_onek_uzerinde_calisir():
    box = make_dispatcher()
    feed(box, F13, True, 0.0)
    wheel = feed(box, VK_WHEEL_UP, True, 0.05, momentary=True)
    assert wheel[0] is True
    assert actions(wheel) == ["send_key:#NumpadAdd"]


def test_tekerlek_basili_kalmaz():
    """Birakma olayi olmadigi icin elle temizlenmezse sonraki tuslara onek
    olurdu."""
    box = make_dispatcher()
    feed(box, F13, True, 0.0)
    feed(box, VK_WHEEL_UP, True, 0.05, momentary=True)
    assert VK_WHEEL_UP not in box.tracker.held
    assert VK_WHEEL_UP not in box._hk_swallowed


def test_tekerlek_kombosu_onegin_kendi_eylemini_iptal_eder():
    box = make_dispatcher()
    feed(box, F13, True, 0.0)
    feed(box, VK_WHEEL_UP, True, 0.05, momentary=True)
    assert actions(feed(box, F13, False, 0.20)) == []


def test_modifier_basiliyken_onek_devreye_girmez():
    """Alt+Tab / Ctrl+Tab bozulmasin: modifierli basimda onek yolu kapali.

    Onek yolu acik olsaydi tus yutulur, birakilinca DUZ hali geri
    gonderilirdi -- pencere/sekme degistirme calismazdi.
    """
    box = make_dispatcher()
    feed(box, CTRL, True, 0.0)
    swallow, acts = feed(box, CARET, True, 0.01)
    assert swallow is False
    assert acts == []
    assert box.prefixes.held == ()


def test_izlenen_tusun_birakilmasi_ui_acikken_de_gorulur():
    """F14 ile secim: ui_open acikken bile tusun BIRAKILMASI ogrenilmeli.

    GetAsyncKeyState burada ise yaramiyor -- yutulan keydown Windows'un
    tus durumu tablosunu guncellemiyor (bkz. ui/snip.py `_poll_key`).
    """
    from cascade.win32.hook import KeyEvent

    box = make_dispatcher()
    feed(box, CARET, True, 0.0)  # secimi baslatan tus basili
    box.watch(CARET)
    box.ui_open = True
    assert box.watch_held() is True
    box.key_filter(
        KeyEvent(
            vk=CARET,
            scan=0,
            down=False,
            extended=False,
            injected=False,
            ours=False,
            time_ms=0,
            t=0.2,
        )
    )
    assert box.watch_held() is False


def _lclick(t: float, down: bool = True):
    from cascade.core.mouse import WM_LBUTTONDOWN, WM_LBUTTONUP
    from cascade.win32.hook import MouseEvent

    return MouseEvent(
        message=WM_LBUTTONDOWN if down else WM_LBUTTONUP, x=0, y=0, data=0,
        injected=False, ours=False, time_ms=0, t=t,
    )


def test_arizali_farenin_cift_basimi_yutulur():
    """AHK: `A_TimeSincePriorHotkey < 70` -> LButton yutulur.

    Yipranmis mikro anahtar tek basimi iki basim yapiyor; 70 ms'nin
    altindaki ikinci basim insan eli degil.
    """
    box = make_dispatcher()
    assert box.mouse_filter(_lclick(1.00)) is False
    assert box.mouse_filter(_lclick(1.03)) is True  # 30 ms: ariza
    assert [a.action.split(":")[0] for a in _drain(box.actions)] == ["click.bounce"]
    # Yutulan basimin BIRAKMASI da yutulur: uygulamaya tek basina giden bir
    # "birakma" surukleme isini yarida biraktiriyordu.
    assert box.mouse_filter(_lclick(1.04, down=False)) is True
    assert box.mouse_filter(_lclick(1.40)) is False  # gercek ikinci tik
    assert box.mouse_filter(_lclick(1.45, down=False)) is False


def _tr_box(layout: int):
    box = make_dispatcher()
    box.turkish_keys = {0x43: "c"}
    box.turkish.enabled = True
    box.turkish.layout = layout
    return box


def _press(vk: int, t: float):
    from cascade.win32.hook import KeyEvent

    return KeyEvent(
        vk=vk, scan=0, down=True, extended=False,
        injected=False, ours=False, time_ms=0, t=t,
    )


def test_turkce_asamasi_harfi_yutar_ve_metin_uretir():
    """ScrollLock acikken 'c' dispatch'in ILK asamasinda cozulur."""
    box = _tr_box(1)
    assert box.key_filter(_press(0x43, 0.0)) is True
    assert [a.action for a in _drain(box.actions)] == ["send_text:c"]


def test_turkce_asamasi_dizilim2de_haritasiz_tusa_dokunmaz():
    """Dizilim 2'de 'c' yok (DIRECT haritasinda degil): tus serbest gecer."""
    box = _tr_box(2)
    assert box.key_filter(_press(0x43, 0.0)) is False


def test_turkce_asamasi_onek_basiliyken_atlanir():
    """Sira: onek > kaskad > Turkce. `F13 & c` Turkce harfe yem olmamali."""
    box = _tr_box(1)
    feed(box, F13, True, 0.0)
    assert box.key_filter(_press(0x43, 0.1)) is False
    assert _drain(box.actions) == []


def test_tilde_ile_yazilan_tus_yutulmaz_ama_eylem_calisir():
    """`~MButton` -- orta tus her yerde isini gorur, eylem de calisir."""
    box = make_dispatcher()
    box.hotkeys.add("~MButton", "memslots.paste:middle")
    swallow, acts = feed(box, MBUTTON, True, 0.0)
    assert swallow is False
    assert [a.action for a in acts] == ["memslots.paste:middle"]
    # Birakma da yutulmaz: basim listemize hic girmedi.
    assert feed(box, MBUTTON, False, 0.1)[0] is False
