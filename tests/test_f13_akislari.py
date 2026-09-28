"""F13 akislari UCTAN UCA -- gercek KeyPilot, gercek keymap, gercek dispatcher.

Birim testleri parcalari tek tek kuruyor; burada tus olayi hook'un
gordugu bicimde dispatcher'a veriliyor ve zincirin sonuna kadar
izleniyor: yut/birak karari -> kuyruk -> `_drain` -> eylem -> pencere.

Sahte olanlar yalnizca DISARIYA dokunan uclar:

  * `win32.send`   gercek tus/fare girdisi URETILMEZ, cagrilar kaydedilir
  * `paths.*`      Files/ yerine gecici klasor -- kullanicinin verisine
                   yazilmaz
  * Win32 menusu   `track` secimi dondurmez, gosterilen tanimi kaydeder
  * modal kutular  QInputDialog / QMessageBox / QFileDialog bloklamaz
  * buyutec, incognito, pencere sabitleme -- sistem durumunu degistirir

Her akisin sonunda ayni soru soruluyor: IS BITTI MI? Onek basili
kalmadi, jest izleyicisi kapandi, bekleyen kisa basim yok, hook
susturulmus (`ui_open`) kalmadi.
"""

from __future__ import annotations

import logging
import time

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox, QPushButton

from keypilot import actions as actions_module
from keypilot import app as app_module
from keypilot import paths
from keypilot.commands import Cmd
from keypilot.core.cascade import Phase
from keypilot.core.keynames import vk_from_name
from keypilot.core.mouse import WM_MOUSEMOVE
from keypilot.ui import overview as overview_module
from keypilot.win32 import menu as win32_menu
from keypilot.win32 import send
from keypilot.win32.hook import KeyEvent, MouseEvent
from keypilot.win32.window import Pin

F13 = 0x7C
F14 = 0x7D
CURSOR = (500, 500)

#: Calistirilmasi SUREC ya da OTURUM degistiren eylemler -- menude var mi
#: diye bakilir ama kosturulmaz.
UNSAFE = {Cmd.App.RESTART, Cmd.App.RESTART_DEV_OFF, Cmd.App.EXIT}


class FakeHook:
    def __init__(self, *args, **kwargs) -> None:
        self.reinstalls = 0
        self.max_callback_ms = 0.0
        self.dropped = 0
        self.errors = 0
        self.last_error = ""
        self.last_event = 0.0
        self.verdict = ""

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def ensure_alive(self, _now: float) -> bool:
        return False


class Rig:
    """Kurulu KeyPilot + disari giden her seyin kaydi."""

    def __init__(self, pilot, sent: list, menus: list) -> None:
        self.pilot = pilot
        self.sent = sent
        self.menus = menus

    @property
    def dispatcher(self):
        return self.pilot.dispatcher

    def key(self, vk: int, down: bool, t: float) -> bool:
        event = KeyEvent(
            vk=vk, scan=0, down=down, extended=False, injected=False, ours=False,
            time_ms=0, t=t,
        )
        return self.dispatcher.key_filter(event)

    def move(self, x: int, y: int, t: float) -> bool:
        event = MouseEvent(
            message=WM_MOUSEMOVE, x=x, y=y, data=0, injected=False, ours=False,
            time_ms=0, t=t,
        )
        return self.dispatcher.mouse_filter(event)

    def pump(self, now: float) -> None:
        """Ana thread'in iki zamanlayicisi: kuyruk + bekleyen eylemler."""
        self.pilot._drain()
        for _vk, action in self.dispatcher.tick(now):
            self.pilot.runner.run(action)
        self.pilot._drain()

    def assert_idle(self) -> None:
        """Akis BITTI: geride hicbir yari durum kalmadi."""
        box = self.dispatcher
        assert box.prefixes.held == (), f"onek basili kaldi: {box.prefixes.held}"
        assert box.tracker.held == (), f"tus basili kaldi: {box.tracker.held}"
        assert not box.gestures.watching, "jest izleyicisi acik kaldi"
        assert box._pending_tap == {}, "bekleyen kisa basim kaldi"
        assert box._freeze_at is None, "imlec dondurmasi kaldi"
        assert not box._hk_swallowed, f"yutulan tus kaydi kaldi: {box._hk_swallowed}"
        assert box.machine.phase == Phase.IDLE
        assert not box.ui_open, "hook susturulmus kaldi (ui_open)"


@pytest.fixture
def rig(qapp, monkeypatch, tmp_path, caplog):
    # ---- disk: kullanicinin Files/ klasorune DOKUNMA ----
    monkeypatch.setattr(paths, "FILES", tmp_path)
    monkeypatch.setattr(paths, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(paths, "REPOSITORY", tmp_path / "repository.md")
    monkeypatch.setattr(paths, "CAPTURES", tmp_path / "captures")
    monkeypatch.setattr(paths, "PAINT", tmp_path / "paint")

    # ---- girdi: gercek tus/fare URETME ----
    sent: list = []
    monkeypatch.setattr(send, "tap", lambda vk, *mods, delay_ms=0: sent.append(("tap", vk, mods)))
    monkeypatch.setattr(send, "click", lambda button="left": sent.append(("click", button)))
    monkeypatch.setattr(send, "type_text", lambda text: sent.append(("text", text)))
    for name in ("key_down", "key_up", "button_down", "button_up"):
        monkeypatch.setattr(send, name, lambda vk, _n=name: sent.append((_n, vk)))
    monkeypatch.setattr(send, "move_relative", lambda dx, dy: sent.append(("move", dx, dy)))
    monkeypatch.setattr(send, "set_cursor_pos", lambda x, y: None)
    monkeypatch.setattr(send, "cursor_pos", lambda: CURSOR)
    monkeypatch.setattr(send, "held_modifiers", frozenset)
    monkeypatch.setattr(send, "is_down", lambda _vk: False)
    monkeypatch.setattr(actions_module.winsound, "Beep", lambda _f, _d: None)

    # ---- pencere / odak / menu ----
    menus: list = []
    monkeypatch.setattr(win32_menu, "track", lambda spec, title="": menus.append(spec))
    monkeypatch.setattr(overview_module, "force_foreground", lambda _hwnd: None)
    monkeypatch.setattr(app_module, "window_at", lambda _x, _y: 4444)
    monkeypatch.setattr(
        app_module, "force_foreground", lambda hwnd: sent.append(("activate", hwnd))
    )
    monkeypatch.setattr(app_module, "foreground_window", lambda: 4242)
    monkeypatch.setattr(app_module, "window_class", lambda _h: "Chrome_WidgetWin_1")
    monkeypatch.setattr(app_module, "window_title", lambda _h: "Test - Google Chrome")
    monkeypatch.setattr(app_module, "topmost_windows", lambda: (Pin(4343, "Sabit pencere"),))

    # ---- modal kutular bloklamasin ----
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))

    # ---- kurulum ----
    monkeypatch.setattr(app_module, "HookThread", FakeHook)
    monkeypatch.setattr(app_module.KeyPilot, "on_start", lambda self: None)
    pilot = app_module.KeyPilot(qapp)

    # Sistem durumunu degistirenler.
    monkeypatch.setattr(pilot.magnifier, "_spawn", lambda work: sent.append(("magnifier",)))
    monkeypatch.setattr(pilot.incognito, "enable", lambda: None)
    monkeypatch.setattr(pilot.pins, "toggle", lambda hwnd=0, title="": None)
    # Kisa F13 once imlecin altindaki pencereyi one aliyor
    # (keymap.F13_ACTIVATE_UNDER_CURSOR); sahte `force_foreground` kaydediyor.

    (tmp_path / "profiles.json").write_text(
        '{"projectName": "ProfileManager", "profiles": [{"profileName": "Chrome",'
        ' "className": "Chrome_WidgetWin_1", "title": "Google Chrome", "shortCuts": ['
        '{"shortCutName": "Kapanan sekme", "keyDescription": "", "keyStrokes": ["^+t"]},'
        '{"shortCutName": "Selam", "keyDescription": "metin", "keyStrokes": ["selam"]}]}]}',
        encoding="utf-8",
    )
    pilot.shorts.load()
    for index, text in enumerate(("ilk kopya", "ikinci kopya", "ucuncu kopya")):
        pilot.clip.history.add(text, 1000.0 + index)

    caplog.set_level(logging.WARNING, logger="keypilot")
    yield Rig(pilot, sent, menus)
    pilot._shutdown()
    for widget in QApplication.topLevelWidgets():
        widget.close()


def _problems(caplog) -> list[str]:
    """Eylem kosucusunun yuttugu hatalar ve bilinmeyen eylemler."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "keypilot.actions" and record.levelno >= logging.WARNING
    ]


def _leaves(spec) -> list[str]:
    """Menu taniminin tiklanabilir UCLARI (alt menuler acilarak)."""
    found: list[str] = []
    for entry in spec:
        if entry is None or isinstance(entry, str):
            continue  # ayrac / kolon
        _label, target, *_extras = entry
        if isinstance(target, tuple):
            found += _leaves(target)
        elif target:
            found.append(str(target))
    return found


def _registered(rig, action: str) -> bool:
    return action.partition(":")[0] in rig.pilot.runner.handlers


def _run_all(rig, caplog, leaves) -> None:
    """Her ucu calistirir; acilan pencereleri kapatir; is bitti mi bakar."""
    for action in leaves:
        name = action.partition(":")[0]
        if name in UNSAFE:
            continue
        rig.pilot.runner.run(action)
        rig.pilot._drain()
        # Eylemin actigi pencereler kapatiliyor: filtre listesi ve tus
        # haritasi `ui_open`i kapanista geri indirmeli.
        for widget in QApplication.topLevelWidgets():
            if widget.isVisible() and widget is not rig.pilot.tip:
                widget.close()
        assert not rig.dispatcher.ui_open, f"{action}: pencere kapandi, hook susuk kaldi"
    assert _problems(caplog) == []


# ---- kisa F13: genel bakis katmani ----------------------------------------


def _short_f13(rig) -> float:
    before = rig.pilot._overview
    t = time.perf_counter()
    assert rig.key(F13, True, t) is True  # onek: basim YUTULUR
    assert rig.key(F13, False, t + 0.08) is True
    # Cift basim tanimli: kisa basim `double_ms` kadar BEKLETILIR.
    rig.pump(t + 0.1)
    assert rig.pilot._overview is before, "cift basim penceresi dolmadan acildi"
    rig.pump(t + 1.0)
    assert rig.pilot._overview is not before, "kisa F13 genel bakisi acmadi"
    return t


def test_kisa_f13_genel_bakisi_acar_ve_durum_temiz_kalir(rig, caplog):
    _short_f13(rig)
    panel = rig.pilot._overview
    assert panel is not None and panel.isVisible()
    # F13_ACTIVATE_UNDER_CURSOR: tik YOK, pencere dogrudan one alinir.
    assert ("activate", 4444) in rig.sent
    assert ("click", "middle") not in rig.sent
    # On plandaki pencerenin profili: iki kisayol seritte.
    assert panel.shorts.list.count() == 2
    assert panel.clips.list.count() == 3
    rig.assert_idle()
    assert _problems(caplog) == []


def test_genel_bakistan_secim_katmani_kapatir_ve_eylemi_calistirir(rig, caplog):
    _short_f13(rig)
    panel = rig.pilot._overview
    row = panel.clips.list.item(0)
    panel._on_click(row)  # listeden ilk pano kaydi
    assert not panel.isVisible(), "secimden sonra katman acik kaldi"
    # Yapistirma: panoya yaz + 60 ms sonra Ctrl+V.
    QApplication.processEvents()
    time.sleep(0.08)
    QApplication.processEvents()
    ctrl_v = ("tap", vk_from_name("V"), (0xA2,))
    assert ctrl_v in rig.sent
    rig.assert_idle()
    assert _problems(caplog) == []


def test_genel_bakisin_butun_maddeleri_kayitli_ve_calisiyor(rig, caplog):
    """Seritler, listeler, hover dugmeleri, alt satirlar ve profil menusu:
    katmanda tiklanabilen HER seyin eylemi kayitli ve hatasiz calisiyor."""
    _short_f13(rig)
    panel = rig.pilot._overview
    leaves: list[str] = []
    for section in (panel.shorts, panel.clips, panel.slots):
        for index in range(section.list.count()):
            item = section.list.item(index)
            if value := item.data(0x0100):  # UserRole
                leaves.append(str(value))
            # hover dugmeleri: (etiket, eylem, ipucu [, renk])
            alts = item.data(overview_module.ALT_ROLE) or ()
            leaves += [str(alt[1]) for alt in alts]
    leaves += _leaves(rig.pilot._overview_menus())
    leaves += _leaves(rig.pilot._overview_buttons())
    leaves += _leaves(rig.pilot._pin_menu_items())
    leaves += [str(action) for _label, action, *_ in app_module.keymap.OVERVIEW_KEYS]
    leaves.append(Cmd.Clip.FILTER)
    # Dugmeler de sayildi mi: alt satirlar ve hep-ustte.
    buttons = [b for b in panel.findChildren(QPushButton) if b.text()]
    assert len(buttons) >= len(app_module.keymap.OVERVIEW_KEYS) + 6

    missing = [action for action in leaves if not _registered(rig, action)]
    assert missing == [], f"kayitsiz eylem: {missing}"
    _run_all(rig, caplog, leaves)
    rig.assert_idle()


def test_genel_bakis_esc_ile_kapanir_ve_ikinci_acilis_yeni_katman(rig):
    _short_f13(rig)
    first = rig.pilot._overview
    first.close()
    assert not first.isVisible()
    _short_f13(rig)
    assert rig.pilot._overview is not first
    assert rig.pilot._overview.isVisible()
    rig.assert_idle()


def test_genel_bakis_kapat_dugmesi_ustune_gelince_kapatir(rig):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent

    _short_f13(rig)
    panel = rig.pilot._overview
    point = QPointF(1, 1)
    panel.close_button.enterEvent(QEnterEvent(point, point, point))
    assert not panel.isVisible(), "kapat dugmesi ustune gelince katman kapanmadi"
    rig.assert_idle()


def test_imlec_kapat_dugmesinin_ustundeyse_dugme_ayarlarin_yanina_kacar(rig):
    _short_f13(rig)
    panel = rig.pilot._overview
    button = panel.close_button
    assert button.width() > 0, "acilista yerlesim henuz kurulmamis"
    panel._dodge_cursor(button.mapToGlobal(button.rect().topLeft()) + QPoint(900, 900))
    assert panel._windows.indexOf(button) == -1, "imlec uzaktayken dugme tasindi"
    panel._dodge_cursor(button.mapToGlobal(button.rect().center()))
    assert panel._windows.indexOf(button) == panel._windows.count() - 1, (
        "imlec ustundeyken dugme ayarlarin yanina gecmedi"
    )
    assert panel.isVisible()


# ---- basili F13: pano menusu -----------------------------------------------


def test_basili_f13_pano_menusunu_acar_ve_hook_geri_acilir(rig, caplog):
    t = time.perf_counter()
    rig.key(F13, True, t)
    rig.pump(t + 0.2)
    rig.key(F13, False, t + 0.5)  # hold_ms (350) gecti
    rig.pump(t + 0.6)
    assert len(rig.menus) == 1, "pano menusu acilmadi"
    spec = rig.menus[0]
    leaves = _leaves(spec)
    assert Cmd.Clip.PASTE(1) in leaves and Cmd.Clip.FILTER in leaves
    assert rig.pilot._overview is None, "basili tutma kisa basim eylemini de calistirdi"
    rig.assert_idle()
    _run_all(rig, caplog, leaves)


def test_basili_f13_jest_overlayini_gosterir_ama_birakinca_kapatir(rig):
    t = time.perf_counter()
    rig.key(F13, True, t)
    rig.pump(t + 0.4)  # short (350) gecti: P fazi
    overlay = rig.pilot.gesture_overlay
    assert overlay.isVisible(), "basili tutmada jest overlay'i acilmadi"
    rig.key(F13, False, t + 0.5)
    rig.pump(t + 0.6)
    assert not overlay.isVisible(), "birakinca overlay kapanmadi"
    rig.assert_idle()


# ---- cift F13: gecmiste arama ----------------------------------------------


def test_cift_f13_arama_penceresini_acar_ve_kapaninca_hook_acilir(rig, caplog):
    t = time.perf_counter()
    rig.key(F13, True, t)
    rig.key(F13, False, t + 0.05)
    rig.key(F13, True, t + 0.10)  # double_ms (180) icinde ikinci basim
    rig.key(F13, False, t + 0.15)
    rig.pump(t + 1.0)
    window = rig.pilot.filter_window
    assert window.isVisible(), "cift basimda arama penceresi acilmadi"
    assert rig.pilot._overview is None, "cift basim kisa basimi da calistirdi"
    assert rig.dispatcher.ui_open, "arama penceresi acikken hook susmali"
    window.close()
    rig.assert_idle()
    assert _problems(caplog) == []


# ---- F13 jesti -------------------------------------------------------------


@pytest.mark.parametrize(
    ("dx", "dy", "key"),
    [(0, -40, "NumpadAdd"), (0, 40, "NumpadSub"), (40, 0, "Volume_Up"), (-40, 0, "Volume_Down")],
)
def test_f13_jesti_eylemi_calistirir_birakinca_menu_acmaz(rig, caplog, dx, dy, key):
    t = time.perf_counter()
    rig.key(F13, True, t)
    assert rig.move(CURSOR[0] + dx, CURSOR[1] + dy, t + 0.05) is True  # hareket yutulur
    rig.key(F13, False, t + 0.3)
    rig.pump(t + 1.0)
    vk = vk_from_name(key)
    taps = [item for item in rig.sent if item[0] == "tap" and item[1] == vk]
    assert len(taps) == 40 // 14, f"{key}: adim sayisi kadar tetiklenmeli"
    assert rig.pilot._overview is None, "jestten sonra kisa basim eylemi calisti"
    assert rig.menus == [], "jestten sonra pano menusu acildi"
    assert not rig.pilot.gesture_overlay.isVisible()
    rig.assert_idle()
    assert _problems(caplog) == []


def test_f13_titremesi_jest_sayilmaz_kisa_basim_calisir(rig):
    t = time.perf_counter()
    rig.key(F13, True, t)
    rig.move(CURSOR[0] + 3, CURSOR[1] - 2, t + 0.02)  # lock_px (8) altinda
    rig.key(F13, False, t + 0.08)
    rig.pump(t + 1.0)
    assert rig.pilot._overview is not None, "titreme kisa basimi yuttu"
    rig.assert_idle()


# ---- F13 kombolari ---------------------------------------------------------


def test_f13_f14_buyuteci_cevirir_onek_eylemi_calismaz(rig):
    t = time.perf_counter()
    rig.key(F13, True, t)
    rig.key(F14, True, t + 0.05)
    rig.key(F14, False, t + 0.1)
    rig.key(F13, False, t + 0.15)
    rig.pump(t + 1.0)
    assert ("magnifier",) in rig.sent
    assert rig.pilot._overview is None
    rig.assert_idle()


def test_orta_tus_tekerlek_zoom_yapar(rig):
    """~MButton & WheelUp -> Ctrl + NumpadAdd (sayfa zoom'u). F13 & Wheel
    kaldirildi: F13 basiliyken tekerlek artik yutulmuyor."""
    from keypilot.core.mouse import WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MOUSEWHEEL

    def mouse(message: int, t: float, data: int = 0) -> MouseEvent:
        return MouseEvent(
            message=message, x=CURSOR[0], y=CURSOR[1], data=data, injected=False,
            ours=False, time_ms=0, t=t,
        )

    t = time.perf_counter()
    rig.dispatcher.mouse_filter(mouse(WM_MBUTTONDOWN, t))
    assert rig.dispatcher.mouse_filter(mouse(WM_MOUSEWHEEL, t + 0.05, 120)) is True
    rig.dispatcher.mouse_filter(mouse(WM_MBUTTONUP, t + 0.1))
    rig.pump(t + 1.0)
    add = vk_from_name("NumpadAdd")
    taps = [mods for kind, vk, *rest in rig.sent if kind == "tap" and vk == add for mods in rest]
    ctrl = {0x11, 0xA2, 0xA3}
    assert taps and all(set(mods) & ctrl and 0x5B not in mods for mods in taps), rig.sent
    rig.assert_idle()


# ---- eski F13 menusu (`´` > 7) ---------------------------------------------


def test_eski_f13_menusunun_butun_maddeleri_calisiyor(rig, caplog):
    rig.pilot.runner.run(Cmd.Menu.F13)
    assert len(rig.menus) == 1
    leaves = _leaves(rig.menus[0])
    assert Cmd.Shorts.PLAY("Chrome/0") in leaves, "on plandaki profilin kisayolu yok"
    assert any(action.startswith(Cmd.Window.PIN) for action in leaves)
    missing = [action for action in leaves if not _registered(rig, action)]
    assert missing == [], f"kayitsiz eylem: {missing}"
    rig.menus.clear()
    _run_all(rig, caplog, leaves)
    rig.assert_idle()


def test_sistem_ve_slot_menulerindeki_her_eylem_kayitli(rig):
    """`´` ve F14 menuleri: surec kapatanlar hariç her uc bir koşucuya gider."""
    rig.pilot.runner.run(Cmd.Menu.SYS)
    rig.pilot.runner.run(Cmd.Menu.SLOTS)
    rig.pilot.runner.run(Cmd.Menu.SIDE_SLOTS)
    assert len(rig.menus) == 3
    leaves = [action for spec in rig.menus for action in _leaves(spec)]
    missing = [action for action in leaves if not _registered(rig, action)]
    assert missing == [], f"kayitsiz eylem: {missing}"
    rig.assert_idle()


# ---- kisayol yakalama kutusu -----------------------------------------------


def test_kisayol_kutusu_tus_beklerken_hook_susar_f13_yakalanir(rig):
    """Kutu "tusa bas..." derken F13 KISAYOL OLARAK islenmemeli: genel
    bakisi acmak yerine kutuya "F13" yazilmali. Yakalama bitince hook
    geri acilmali."""
    from keypilot.ui.key_capture import KeyCapture

    box = KeyCapture("")
    box.show()
    box.click()  # yakalamayi baslatir
    assert rig.dispatcher.ui_open, "yakalama sirasinda hook susmali"
    t = time.perf_counter()
    assert rig.key(F13, True, t) is False, "F13 yutuldu, kutuya ulasamaz"
    rig.key(F13, False, t + 0.05)
    rig.pump(t + 1.0)
    assert rig.pilot._overview is None, "yakalama sirasinda F13 genel bakisi acti"
    box._disarm()
    assert not rig.dispatcher.ui_open, "yakalama bitti, hook susuk kaldi"
    box.close()
    rig.assert_idle()
