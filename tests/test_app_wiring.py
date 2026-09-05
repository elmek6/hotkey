"""KeyPilot kurulum testi -- `__init__` bastan sona kosuyor mu.

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

from keypilot import app as app_module


class FakeHook:
    def __init__(self, *args, **kwargs) -> None:
        self.started = False
        self.reinstalls = 0
        self.max_callback_ms = 0.0
        self.dropped = 0
        self.last_event = 0.0
        #: Gercek HookThread'de nobetcinin karar GEREKCESI burada durur ve
        #: uyari satirina basilir (bkz. win32/hook.looks_dead).
        self.verdict = "test"
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
def keypilot(qapp, monkeypatch):
    monkeypatch.setattr(app_module, "HookThread", FakeHook)
    monkeypatch.setattr(app_module.KeyPilot, "on_start", lambda self: None)
    instance = app_module.KeyPilot(qapp)
    yield instance
    instance._shutdown()


def test_construction_binds_every_part(keypilot):
    for name in ("clip", "slots", "slot_store", "dispatcher", "machine", "incognito"):
        assert getattr(keypilot, name) is not None, f"kurulumda eksik: {name}"


def test_menu_actions_are_registered(keypilot):
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
        assert action in keypilot.runner.handlers, f"kayitsiz eylem: {action}"


def test_menus_can_be_built(keypilot):
    """Menu kurgusu gercek depolarla uretilebiliyor mu (cagri patlamasin)."""
    assert keypilot.slots.menu_spec()
    assert keypilot.slots.side_menu_spec()
    assert keypilot.clip.menu_items()


def test_kapanista_hata_aboneligi_birakilir(keypilot):
    """`logs.errors` MODUL DUZEYINDE tek ornek: kapanan KeyPilot abone
    kalirsa olu nesnesine hata akmaya devam eder -- ve o nesne kritik
    hatada modal pencere aciyor. Testleri kilitleyen tam olarak buydu.
    """
    from keypilot import logs

    assert keypilot._error_sub in logs.errors._subs
    keypilot._shutdown()
    assert keypilot._error_sub not in logs.errors._subs


def test_kritik_hatalar_tek_pencerede_toplanir(keypilot, monkeypatch):
    """Acilista uc dosya birden bozuk cikabilir. Kayitlar biriktirilip TEK
    pencerede gosteriliyor; ERROR hic pencere acmiyor."""
    acilan: list[list[str]] = []
    monkeypatch.setattr(
        type(keypilot),
        "_flush_critical",
        lambda self: acilan.append(list(self._critical_pending)),
    )
    keypilot._on_error_logged("CRITICAL", "slots.json bozuk")
    keypilot._on_error_logged("CRITICAL", "profiles.json bozuk")
    keypilot._on_error_logged("ERROR", "sadece rozet")

    assert keypilot._critical_pending == ["slots.json bozuk", "profiles.json bozuk"]
    assert keypilot._critical_scheduled  # bir sonraki olay turuna birakildi
    keypilot._flush_critical()
    assert acilan == [["slots.json bozuk", "profiles.json bozuk"]]


def test_tablo_yeniden_kurulunca_calisma_anindaki_tuslar_kalir(keypilot):
    """Sanal fareyi ac/kapa yapmak profil ve alan tuslarini DUSURMEMELI.

    Tabloda yalniz keymap.py yok: profil kisayollari ve alan kurallari
    calisma aninda `claim` ile giriyor. Tablo ciplak kurulup birakilinca
    ikisi de sessizce oluyordu ve program yeniden baslayana kadar geri
    gelmiyordu.
    """
    from keypilot.areas import Area, Rule

    table = keypilot.dispatcher.hotkeys
    table.claim("profile:Test#0", "F4", "send_text:selam", "profil")
    area = Area(name="alan", x=0, y=0, w=10, h=10, rules=[Rule(key="F7")])
    keypilot.snip.store.put(area)
    keypilot._bind_area_rule(area.rule_owner(0), "F7", area.name, 0)

    def sahipler() -> set[str]:
        return {b.owner for b in keypilot.dispatcher.hotkeys.bindings}

    # Profil tanimi dosyadan geliyor; testte elle tutuldugu icin
    # `bind_profile_keys` onu yeniden kuramaz -- alan kurali yeter.
    keypilot.rebuild_hotkeys()
    assert area.rule_owner(0) in sahipler()


def test_sanal_fare_ayari_tabloyu_gunceller(keypilot):
    """Ayar EKRANINDAN degistirmek de tabloyu kurmali: eskiden yalniz
    tepsi/menu yolu (`vmouse.toggle`) kuruyordu, ayar ekranindan acilan
    sanal fare yeniden baslatana kadar olu kaliyordu."""
    from keypilot import keymap

    onceki = len(keypilot.dispatcher.hotkeys.bindings)
    keymap.VIRTUAL_MOUSE.set(True)
    try:
        assert len(keypilot.dispatcher.hotkeys.bindings) > onceki
    finally:
        keymap.VIRTUAL_MOUSE.set(False)
    assert len(keypilot.dispatcher.hotkeys.bindings) == onceki


def test_nobetci_saglam_hook_da_hicbir_sey_yapmaz(keypilot):
    keypilot._watchdog_tick()
    assert keypilot.hook.reinstalls == 0


def test_nobetci_hook_dusunce_yeniden_kurar_ve_durumu_temizler(keypilot):
    """Hook olu gectigi surede BIRAKMA olaylari kayboldu; yeniden kurmak
    yetmez, geride kalan hayalet tuslar da silinmeli."""
    ctrl = 0xA2
    keypilot.dispatcher.tracker.key_down(ctrl, 0.0)
    keypilot.hook.dead = True
    keypilot._watchdog_tick()
    assert keypilot.hook.reinstalls == 1
    assert keypilot.dispatcher.tracker.held == ()


def test_nobetci_kapanmis_programda_susar(keypilot):
    """`_exited` sonrasi hook sokulmus olur; yeniden kurmak onu diriltirdi."""
    keypilot._exited = True
    keypilot.hook.dead = True
    keypilot._watchdog_tick()
    assert keypilot.hook.reinstalls == 0


# ---- yeniden baslatma: cocuk gercekten kalkti mi -------------------------


class FakeChild:
    """Popen yerine gecen sahte surec. `code` None ise hala calisiyor."""

    def __init__(self, code=None) -> None:
        self.returncode = code

    def poll(self):
        return self.returncode


@pytest.fixture
def restartable(keypilot, monkeypatch):
    """`restart` cagrilabilir hale getirir: disk ve Qt'ye dokunulmaz.

    `on_exit` GERCEK dosyalara yaziyor (settings.json, clipboards.bin) --
    testin isi degil. Gozetmen yoklamasi da beklemeden yapiliyor.
    """
    monkeypatch.setattr(app_module.KeyPilot, "on_exit", lambda self, reason="": None)
    monkeypatch.setattr(app_module, "SUPERVISOR_PROBE_SECONDS", 0.0)
    # Gozetmensiz yol: bayrak yoksa cocugu uygulama kendisi aciyor.
    monkeypatch.setattr(app_module.sys, "argv", ["main.py"])
    codes = []
    monkeypatch.setattr(keypilot.app, "exit", codes.append)
    monkeypatch.setattr(keypilot.app, "quit", lambda: codes.append(0))
    spawned = []

    def spawn(self, command):
        spawned.append(command)
        # Ilk cagri gozetmen, ikincisi dogrudan python.
        return FakeChild(1) if len(spawned) == 1 and _is_supervisor(command) else FakeChild()

    monkeypatch.setattr(app_module.KeyPilot, "_spawn", spawn)
    return keypilot, spawned, codes


def _is_supervisor(command) -> bool:
    return any(str(part).lower().endswith(".vbs") for part in command)


def test_gozetmen_aninda_olurse_dogrudan_python_ile_denenir(restartable):
    """ARIZA: "yeniden baslat" dedin, program kapandi ve geri gelmedi.

    Gozetmen (wscript) uygulama boyunca ayakta kalmali. Aninda olduyse
    cocugu hic baslatamamis demektir; eskiden bu sessizce gecilirdi ve
    geriye hicbir sey kalmazdi.
    """
    keypilot, spawned, _codes = restartable
    keypilot.restart()
    assert len(spawned) == 2, "gozetmen olunce dogrudan python denenmeli"
    assert _is_supervisor(spawned[0])
    assert not _is_supervisor(spawned[1])
    assert spawned[1][1].endswith("main.py")


def test_gozetmen_ayaktaysa_ikinci_surec_baslatilmaz(keypilot, monkeypatch):
    monkeypatch.setattr(app_module.KeyPilot, "on_exit", lambda self, reason="": None)
    monkeypatch.setattr(app_module, "SUPERVISOR_PROBE_SECONDS", 0.0)
    monkeypatch.setattr(app_module.sys, "argv", ["main.py"])
    monkeypatch.setattr(keypilot.app, "exit", lambda _code: None)
    monkeypatch.setattr(keypilot.app, "quit", lambda: None)
    spawned = []
    monkeypatch.setattr(
        app_module.KeyPilot,
        "_spawn",
        lambda self, command: (spawned.append(command), FakeChild())[1],
    )
    keypilot.restart()
    assert len(spawned) == 1


def test_bekci_altindayken_HIC_SUREC_BASLATILMAZ(keypilot, monkeypatch):
    """TEK BEKCI. Gozetmen kapida bekliyorsa yeniden baslatma sadece bir
    cikis kodu: programi ayni bekci tekrar calistirir.

    Eskiden yerimize YENI bir `wscript hotkey.vbs` aciliyordu ve bir sure
    iki bekci birden yasiyordu -- ikisi de ayni konsol gunlugunu yazmak
    isteyince cmd "dosya kullanimda" deyip cocugu hic baslatmiyordu.
    """
    monkeypatch.setattr(app_module.KeyPilot, "on_exit", lambda self, reason="": None)
    monkeypatch.setattr(app_module.sys, "argv", ["main.py", "--supervised"])
    codes: list[int] = []
    monkeypatch.setattr(keypilot.app, "exit", codes.append)
    spawned: list[list[str]] = []
    monkeypatch.setattr(
        app_module.KeyPilot, "_spawn", lambda self, cmd: spawned.append(cmd)
    )
    keypilot.restart()
    assert spawned == [], "bekci varken surec baslatilmamali"
    assert codes == [app_module.EXIT_RESTART]
