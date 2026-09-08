"""send_keys dizisi: modifier her tusa gitmeli.

Gercek hata: `^a ^c` dizisinde ikinci tus Ctrl'siz gidiyordu. Sebep,
basili modifier'in HER tus icin yeniden sorulmasiydi -- ilk tusun Ctrl-up'i
ham girdi thread'inde daha islenmemisken GetAsyncKeyState "Ctrl basili"
diyor, kod da "kullanici tutuyor, tekrar gondermeyeyim" deyip atliyordu.
Word'de sonuc: hepsi secilir, sonra duz `c` yazilip secim silinirdi.
"""

from __future__ import annotations

from keypilot import actions as actions_module
from keypilot.actions import ActionRunner

LCTRL, RCTRL = 0xA2, 0xA3
A, C_KEY = 0x41, 0x43


def _kaydedici(monkeypatch, held):
    gonderilen: list[tuple] = []
    monkeypatch.setattr(actions_module.KEY_DELAY, "get", lambda: 0)
    monkeypatch.setattr(
        actions_module.send, "tap",
        lambda vk, *mods, delay_ms=0: gonderilen.append((vk, mods)),
    )
    monkeypatch.setattr(actions_module.send, "held_modifiers", lambda: frozenset(held))
    return gonderilen


def test_dizideki_her_tus_kendi_modifierini_alir(monkeypatch):
    gonderilen = _kaydedici(monkeypatch, held=())
    ActionRunner().run("send_keys:^a ^c")
    assert gonderilen == [(A, (LCTRL,)), (C_KEY, (LCTRL,))]


def test_enjeksiyon_sirasinda_degisen_tus_durumu_diziyi_bozmaz(monkeypatch):
    """Basili modifier goruntusu dizinin BASINDA bir kez alinmali."""
    gonderilen = _kaydedici(monkeypatch, held=())
    cagri = {"n": 0}

    def kayan_goruntu():
        # ikinci tusta "Ctrl basili" diyen eski davranisin taklidi
        cagri["n"] += 1
        return frozenset() if cagri["n"] == 1 else frozenset({LCTRL})

    monkeypatch.setattr(actions_module.send, "held_modifiers", kayan_goruntu)
    ActionRunner().run("send_keys:^a ^c")
    assert gonderilen == [(A, (LCTRL,)), (C_KEY, (LCTRL,))]
    assert cagri["n"] == 1


def test_kullanici_ctrl_tutuyorsa_tekrar_gonderilmez(monkeypatch):
    gonderilen = _kaydedici(monkeypatch, held=(RCTRL,))
    ActionRunner().run("send_keys:^a ^c")
    assert gonderilen == [(A, ()), (C_KEY, ())]


# ---- tek tus: kendi enjeksiyonumuzu "kullanici tutuyor" sanmamak ----


def test_kendi_ctrlimiz_bayatken_basili_sayilmaz(monkeypatch):
    """Art arda F19 (tek `^c`): ikinci basimda Ctrl DUSMEMELI.

    Birinci basimin Ctrl-up'i ham girdi thread'inde henuz islenmemisken
    GetAsyncKeyState "basili" diyor; o cevap bizim kendi olayimiz.
    """
    from keypilot.win32 import send

    monkeypatch.setattr(send, "is_down", lambda vk: vk == LCTRL)
    monkeypatch.setattr(send, "_injected_release", {LCTRL: send.time.perf_counter()})
    assert LCTRL not in send.held_modifiers()


def test_kullanicinin_tuttugu_ctrl_gorulur(monkeypatch):
    from keypilot.win32 import send

    monkeypatch.setattr(send, "is_down", lambda vk: vk == LCTRL)
    monkeypatch.setattr(send, "_injected_release", {})
    assert send.held_modifiers() == frozenset({LCTRL})


def test_eski_enjeksiyon_pencereyi_gecince_gecerliligini_yitirir(monkeypatch):
    """Isaret SURELI: bir saniye once gonderdigimiz Ctrl, kullanici simdi
    tutuyorsa onu gizlememeli."""
    from keypilot.win32 import send

    monkeypatch.setattr(send, "is_down", lambda vk: vk == LCTRL)
    eski = send.time.perf_counter() - (send.STALE_MS / 1000.0) - 1.0
    monkeypatch.setattr(send, "_injected_release", {LCTRL: eski})
    assert send.held_modifiers() == frozenset({LCTRL})
