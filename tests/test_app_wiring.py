"""Cascade kurulum testi -- `__init__` bastan sona kosuyor mu.

Bolme sirasinda `self.slot_store` satiri kayboldu ve program acilista
patladi; birim testleri bunu goremezdi cunku denetleyiciler tek tek
kuruluyordu. Burada GERCEK kurulum yapiliyor, yalniz iki sey degistiriliyor:

  * HookThread -- sahte. Gercegi makinenin butun klavyesini dinler.
  * on_start   -- bos. Disk okumasi ve tepsi balonu testin isi degil.

Kalan her sey (pencereler, denetleyiciler, eylem kayitlari, zamanlayicilar)
programdaki gibi kuruluyor.
"""

from __future__ import annotations

import pytest

from cascade import app as app_module


class FakeHook:
    def __init__(self, *args, **kwargs) -> None:
        self.started = False
        self.reinstalls = 0
        self.max_callback_ms = 0.0
        self.dropped = 0
        #: Nobetci testinin cevirdigi dugme: "hook dusmus gibi davran".
        self.dead = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def ensure_alive(self, _now: float) -> bool:
        if not self.dead:
            return False
        self.dead = False
        self.reinstalls += 1
        return True


@pytest.fixture
def cascade(qapp, monkeypatch):
    monkeypatch.setattr(app_module, "HookThread", FakeHook)
    monkeypatch.setattr(app_module.Cascade, "on_start", lambda self: None)
    instance = app_module.Cascade(qapp)
    yield instance
    instance._shutdown()


def test_construction_binds_every_part(cascade):
    for name in ("clip", "slots", "slot_store", "dispatcher", "machine", "incognito"):
        assert getattr(cascade, name) is not None, f"kurulumda eksik: {name}"


def test_menu_actions_are_registered(cascade):
    """Menulerde gecen her eylem kimliginin bir kosucusu olmali."""
    for action in (
        "clip.paste",
        "clip.filter",
        "clip.images",
        "slot.paste",
        "slot.paste_group",
        "slots.edit",
        "slots.search",
        "menu.slots",
        "menu.base_slots",
        "menu.side_slots",
        "incognito.open",
    ):
        assert action in cascade.runner.handlers, f"kayitsiz eylem: {action}"


def test_menus_can_be_built(cascade):
    """Menu kurgusu gercek depolarla uretilebiliyor mu (cagri patlamasin)."""
    assert cascade.slots.menu_spec()
    assert cascade.slots.side_menu_spec()
    assert cascade.clip.menu_items()


def test_kapanista_hata_aboneligi_birakilir(cascade):
    """`logs.errors` MODUL DUZEYINDE tek ornek: kapanan Cascade abone
    kalirsa olu nesnesine hata akmaya devam eder -- ve o nesne kritik
    hatada modal pencere aciyor. Testleri kilitleyen tam olarak buydu.
    """
    from cascade import logs

    assert cascade._error_sub in logs.errors._subs
    cascade._shutdown()
    assert cascade._error_sub not in logs.errors._subs


def test_kritik_hatalar_tek_pencerede_toplanir(cascade, monkeypatch):
    """Acilista uc dosya birden bozuk cikabilir. Kayitlar biriktirilip TEK
    pencerede gosteriliyor; ERROR hic pencere acmiyor."""
    acilan: list[list[str]] = []
    monkeypatch.setattr(
        type(cascade),
        "_flush_critical",
        lambda self: acilan.append(list(self._critical_pending)),
    )
    cascade._on_error_logged("CRITICAL", "slots.json bozuk")
    cascade._on_error_logged("CRITICAL", "profiles.json bozuk")
    cascade._on_error_logged("ERROR", "sadece rozet")

    assert cascade._critical_pending == ["slots.json bozuk", "profiles.json bozuk"]
    assert cascade._critical_scheduled  # bir sonraki olay turuna birakildi
    cascade._flush_critical()
    assert acilan == [["slots.json bozuk", "profiles.json bozuk"]]


def test_tablo_yeniden_kurulunca_calisma_anindaki_tuslar_kalir(cascade):
    """Sanal fareyi ac/kapa yapmak profil ve alan tuslarini DUSURMEMELI.

    Tabloda yalniz keymap.py yok: profil kisayollari ve alan kurallari
    calisma aninda `claim` ile giriyor. Tablo ciplak kurulup birakilinca
    ikisi de sessizce oluyordu ve program yeniden baslayana kadar geri
    gelmiyordu.
    """
    from cascade.areas import Area, Rule

    table = cascade.dispatcher.hotkeys
    table.claim("profile:Test#0", "F4", "send_text:selam", "profil")
    area = Area(name="alan", x=0, y=0, w=10, h=10, rules=[Rule(key="F7")])
    cascade.snip.store.put(area)
    cascade._bind_area_rule(area.rule_owner(0), "F7", area.name, 0)

    def sahipler() -> set[str]:
        return {b.owner for b in cascade.dispatcher.hotkeys.bindings}

    # Profil tanimi dosyadan geliyor; testte elle tutuldugu icin
    # `bind_profile_keys` onu yeniden kuramaz -- alan kurali yeter.
    cascade.rebuild_hotkeys()
    assert area.rule_owner(0) in sahipler()


def test_sanal_fare_ayari_tabloyu_gunceller(cascade):
    """Ayar EKRANINDAN degistirmek de tabloyu kurmali: eskiden yalniz
    tepsi/menu yolu (`vmouse.toggle`) kuruyordu, ayar ekranindan acilan
    sanal fare yeniden baslatana kadar olu kaliyordu."""
    from cascade import keymap

    onceki = len(cascade.dispatcher.hotkeys.bindings)
    keymap.VIRTUAL_MOUSE.set(True)
    try:
        assert len(cascade.dispatcher.hotkeys.bindings) > onceki
    finally:
        keymap.VIRTUAL_MOUSE.set(False)
    assert len(cascade.dispatcher.hotkeys.bindings) == onceki


def test_nobetci_saglam_hook_da_hicbir_sey_yapmaz(cascade):
    cascade._watchdog_tick()
    assert cascade.hook.reinstalls == 0


def test_nobetci_hook_dusunce_yeniden_kurar_ve_durumu_temizler(cascade):
    """Hook olu gectigi surede BIRAKMA olaylari kayboldu; yeniden kurmak
    yetmez, geride kalan hayalet tuslar da silinmeli."""
    ctrl = 0xA2
    cascade.dispatcher.tracker.key_down(ctrl, 0.0)
    cascade.hook.dead = True
    cascade._watchdog_tick()
    assert cascade.hook.reinstalls == 1
    assert cascade.dispatcher.tracker.held == ()


def test_nobetci_kapanmis_programda_susar(cascade):
    """`_exited` sonrasi hook sokulmus olur; yeniden kurmak onu diriltirdi."""
    cascade._exited = True
    cascade.hook.dead = True
    cascade._watchdog_tick()
    assert cascade.hook.reinstalls == 0


# ---- yeniden baslatma: cocuk gercekten kalkti mi -------------------------


class FakeChild:
    """Popen yerine gecen sahte surec. `code` None ise hala calisiyor."""

    def __init__(self, code=None) -> None:
        self.returncode = code

    def poll(self):
        return self.returncode


@pytest.fixture
def restartable(cascade, monkeypatch):
    """`restart` cagrilabilir hale getirir: disk ve Qt'ye dokunulmaz.

    `on_exit` GERCEK dosyalara yaziyor (settings.json, clipboards.bin) --
    testin isi degil. Gozetmen yoklamasi da beklemeden yapiliyor.
    """
    monkeypatch.setattr(app_module.Cascade, "on_exit", lambda self: None)
    monkeypatch.setattr(app_module, "SUPERVISOR_PROBE_SECONDS", 0.0)
    # Gozetmensiz yol: bayrak yoksa cocugu uygulama kendisi aciyor.
    monkeypatch.setattr(app_module.sys, "argv", ["main.py"])
    codes = []
    monkeypatch.setattr(cascade.app, "exit", codes.append)
    monkeypatch.setattr(cascade.app, "quit", lambda: codes.append(0))
    spawned = []

    def spawn(self, command):
        spawned.append(command)
        # Ilk cagri gozetmen, ikincisi dogrudan python.
        return FakeChild(1) if len(spawned) == 1 and _is_supervisor(command) else FakeChild()

    monkeypatch.setattr(app_module.Cascade, "_spawn", spawn)
    return cascade, spawned, codes


def _is_supervisor(command) -> bool:
    return any(str(part).lower().endswith(".vbs") for part in command)


def test_gozetmen_aninda_olurse_dogrudan_python_ile_denenir(restartable):
    """ARIZA: "yeniden baslat" dedin, program kapandi ve geri gelmedi.

    Gozetmen (wscript) uygulama boyunca ayakta kalmali. Aninda olduyse
    cocugu hic baslatamamis demektir; eskiden bu sessizce gecilirdi ve
    geriye hicbir sey kalmazdi.
    """
    cascade, spawned, _codes = restartable
    cascade.restart()
    assert len(spawned) == 2, "gozetmen olunce dogrudan python denenmeli"
    assert _is_supervisor(spawned[0])
    assert not _is_supervisor(spawned[1])
    assert spawned[1][1].endswith("main.py")


def test_gozetmen_ayaktaysa_ikinci_surec_baslatilmaz(cascade, monkeypatch):
    monkeypatch.setattr(app_module.Cascade, "on_exit", lambda self: None)
    monkeypatch.setattr(app_module, "SUPERVISOR_PROBE_SECONDS", 0.0)
    monkeypatch.setattr(app_module.sys, "argv", ["main.py"])
    monkeypatch.setattr(cascade.app, "exit", lambda _code: None)
    monkeypatch.setattr(cascade.app, "quit", lambda: None)
    spawned = []
    monkeypatch.setattr(
        app_module.Cascade,
        "_spawn",
        lambda self, command: (spawned.append(command), FakeChild())[1],
    )
    cascade.restart()
    assert len(spawned) == 1


def test_bekci_altindayken_HIC_SUREC_BASLATILMAZ(cascade, monkeypatch):
    """TEK BEKCI. Gozetmen kapida bekliyorsa yeniden baslatma sadece bir
    cikis kodu: programi ayni bekci tekrar calistirir.

    Eskiden yerimize YENI bir `wscript hotkey.vbs` aciliyordu ve bir sure
    iki bekci birden yasiyordu -- ikisi de ayni konsol gunlugunu yazmak
    isteyince cmd "dosya kullanimda" deyip cocugu hic baslatmiyordu.
    """
    monkeypatch.setattr(app_module.Cascade, "on_exit", lambda self: None)
    monkeypatch.setattr(app_module.sys, "argv", ["main.py", "--supervised"])
    codes: list[int] = []
    monkeypatch.setattr(cascade.app, "exit", codes.append)
    spawned: list[list[str]] = []
    monkeypatch.setattr(
        app_module.Cascade, "_spawn", lambda self, cmd: spawned.append(cmd)
    )
    cascade.restart()
    assert spawned == [], "bekci varken surec baslatilmamali"
    assert codes == [app_module.EXIT_RESTART]
