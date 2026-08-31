"""Makro kaydi -- veri katmani + kaydedici + oynatici.

AHK'de bu bolum hic test edilemiyordu: kayit gercek hook'a, oynatma ikinci
bir AutoHotkey surecine bagliydi. Burada saat, gonderici ve uyku disaridan
verildigi icin hepsi insansiz kosuyor.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cascade import macro


@pytest.fixture(autouse=True)
def files_dir(tmp_path, monkeypatch):
    """`Files/` yerine tmp_path -- testler gercek kayitlarin uzerine yazmasin."""
    monkeypatch.setattr(macro.paths, "FILES", tmp_path)
    monkeypatch.setattr(macro.paths, "ensure_files_dir", lambda: tmp_path)
    return tmp_path


@dataclass
class FakeKey:
    """`hook.KeyEvent`in test karsiligi -- yalniz kaydedicinin baktigi alanlar."""

    vk: int
    down: bool = True
    t: float = 0.0
    injected: bool = False
    ours: bool = False


@dataclass
class FakeMouse:
    """`hook.MouseEvent`in test karsiligi."""

    message: int
    x: int = 0
    y: int = 0
    data: int = 0
    t: float = 0.0
    injected: bool = False
    ours: bool = False


class FakeSender:
    def __init__(self):
        self.calls: list[tuple] = []

    def key_down(self, vk):
        self.calls.append(("down", vk))

    def key_up(self, vk):
        self.calls.append(("up", vk))

    def type_text(self, text):
        self.calls.append(("text", text))

    def set_cursor_pos(self, x, y):
        self.calls.append(("pos", x, y))

    def move_relative(self, dx, dy):
        self.calls.append(("rel", dx, dy))

    def button_down(self, vk):
        self.calls.append(("btn_down", vk))

    def button_up(self, vk):
        self.calls.append(("btn_up", vk))

    def wheel(self, delta, horizontal=False):
        self.calls.append(("wheel", delta, horizontal))


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


# ---- dosya bicimi ----


def test_yazilan_okunur(files_dir):
    events = [{"dt": 0, "e": "key", "vk": 65, "down": True}]
    macro.write(macro.slot_path(1), events, "deneme")
    name, okunan = macro.read(macro.slot_path(1))
    assert name == "deneme"
    assert okunan == events


def test_dosya_yoksa_bos(files_dir):
    assert macro.read(macro.slot_path(2)) == ("", [])


def test_bozuk_satir_atlanir_kalan_okunur(files_dir):
    path = macro.slot_path(1)
    macro.write(path, [{"dt": 0, "e": "key", "vk": 65, "down": True}], "x")
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"dt": 5, "e": "key"\n')  # yarim kalmis satir (kayit sirasinda cokme)
        fh.write('{"dt": 7, "e": "key", "vk": 66, "down": false}\n')
    name, events = macro.read(path)
    assert name == "x"
    assert [e["vk"] for e in events] == [65, 66]


def test_slot_adi_degistirince_olaylar_durur(files_dir):
    macro.write(macro.slot_path(1), [{"dt": 0, "e": "key", "vk": 65, "down": True}], "eski")
    macro.set_slot_name(1, "yeni")
    name, events = macro.read(macro.slot_path(1))
    assert name == "yeni"
    assert len(events) == 1


def test_olmayan_slotun_adi_yazilmaz(files_dir):
    macro.set_slot_name(3, "yok")
    assert not macro.slot_path(3).exists()


def test_slot_etiketi(files_dir):
    assert macro.slot_label(1) == "rec1.jsonl"
    macro.write(macro.slot_path(1), [], "notlar")
    assert macro.slot_label(1) == "rec1.jsonl  -  notlar"


# ---- kayit ----


def test_tus_kaydedilir():
    rec = macro.Recorder()
    rec.start()
    rec.feed_key(FakeKey(vk=65, down=True))
    rec.feed_key(FakeKey(vk=65, down=False))
    assert [(e["vk"], e["down"]) for e in rec.events] == [(65, True), (65, False)]


def test_kendi_gonderdigimiz_tus_kaydedilmez():
    """Oynatirken kaydin kendisi yeniden kaydedilmemeli."""
    rec = macro.Recorder()
    rec.start()
    rec.feed_key(FakeKey(vk=65, injected=True, ours=True))
    rec.feed_key(FakeKey(vk=66, injected=True))
    assert rec.events == []


def test_esc_kaydi_durdurur():
    rec = macro.Recorder()
    rec.start()
    rec.feed_key(FakeKey(vk=macro.VK_ESCAPE))
    assert not rec.recording
    assert rec.events == []
    rec.feed_key(FakeKey(vk=65))
    assert rec.events == []


def test_kisa_bosluk_yazilmaz_uzun_bosluk_yazilir():
    clock = Clock()
    rec = macro.Recorder(clock=clock)
    rec.start()
    clock.t = 0.05
    rec.feed_key(FakeKey(vk=65, t=clock.t))
    clock.t = 0.9
    rec.feed_key(FakeKey(vk=66, t=clock.t))
    assert [e["dt"] for e in rec.events] == [0, 850]


def test_olay_siniri_kaydi_durdurur():
    rec = macro.Recorder()
    rec.start()
    for _ in range(macro.MAX_EVENTS + 5):
        rec.feed_key(FakeKey(vk=65))
    assert not rec.recording
    assert len(rec.events) == macro.MAX_EVENTS


def test_pencere_ayar_kapaliyken_kaydedilmez():
    rec = macro.Recorder()
    rec.start()
    rec.feed_window("Notepad", "Adsiz")
    assert rec.events == []


def test_pencere_ayar_acikken_bir_kez_kaydedilir():
    macro.RECORD_WINDOW.set(True)
    try:
        rec = macro.Recorder()
        rec.start()
        rec.feed_window("Notepad", "Adsiz")
        rec.feed_window("Notepad", "Adsiz")  # ayni pencere: tekrar yazilmaz
        rec.feed_window("Chrome", "Sekme")
        assert [e["class"] for e in rec.events] == ["Notepad", "Chrome"]
    finally:
        macro.RECORD_WINDOW.set(False)


def test_bos_kayit_dosyaya_yazilmaz(files_dir):
    macro.write(macro.slot_path(1), [{"dt": 0, "e": "key", "vk": 65, "down": True}], "eski")
    rec = macro.Recorder()
    rec.start()
    assert rec.save(1) is None
    assert macro.read(macro.slot_path(1))[1]  # eski kayit yerinde


def test_kayit_kaydedilip_geri_okunur(files_dir):
    rec = macro.Recorder()
    rec.start()
    rec.feed_key(FakeKey(vk=65))
    assert rec.save(1, "ad") == macro.slot_path(1)
    assert macro.read(macro.slot_path(1)) == ("ad", rec.events)


# ---- oynatma ----


def test_tus_ve_metin_oynatilir():
    sender = FakeSender()
    player = macro.Player(sender=sender, sleep=lambda _ms: None)
    events = [
        {"dt": 0, "e": "key", "vk": 65, "down": True},
        {"dt": 0, "e": "key", "vk": 65, "down": False},
        {"dt": 0, "e": "text", "s": "merhaba"},
    ]
    assert player.play(events) == 3
    assert sender.calls == [("down", 65), ("up", 65), ("text", "merhaba")]


def test_bilinmeyen_olay_atlanir():
    """Eski surum, yeni kaydi acabilmeli."""
    sender = FakeSender()
    player = macro.Player(sender=sender, sleep=lambda _ms: None)
    events = [
        {"dt": 0, "e": "gelecek-surum", "ne": "bilinmiyor"},
        {"dt": 0, "e": "window", "class": "Notepad", "title": "Adsiz"},
        {"dt": 0, "e": "key", "vk": 65, "down": True},
    ]
    assert player.play(events) == 3
    assert sender.calls == [("down", 65)]


def test_speedup_beklemeyi_carpar():
    uykular: list[float] = []
    macro.SPEED_UP.set(2.0)
    macro.KEY_DELAY.set(0)
    try:
        player = macro.Player(sender=FakeSender(), sleep=uykular.append)
        player.play([{"dt": 100, "e": "key", "vk": 65, "down": True}])
    finally:
        macro.SPEED_UP.set(macro.SPEED_UP.default)
        macro.KEY_DELAY.set(macro.KEY_DELAY.default)
    assert uykular == [200.0, 0]


def test_speedup_sifirken_beklemesiz():
    uykular: list[float] = []
    macro.KEY_DELAY.set(0)
    try:
        player = macro.Player(sender=FakeSender(), sleep=uykular.append)
        player.play([{"dt": 5000, "e": "key", "vk": 65, "down": True}])
    finally:
        macro.KEY_DELAY.set(macro.KEY_DELAY.default)
    assert uykular == [0.0, 0]


def test_panik_tusu_oynatmayi_keser():
    sender = FakeSender()
    kesildi = {"v": False}
    player = macro.Player(sender=sender, sleep=lambda _ms: None, stop=lambda: kesildi["v"])
    events = [{"dt": 0, "e": "key", "vk": v, "down": True} for v in (65, 66, 67)]

    def sender_gecince_kes(vk):
        sender.calls.append(("down", vk))
        kesildi["v"] = True

    sender.key_down = sender_gecince_kes
    assert player.play(events) == 1
    assert sender.calls == [("down", 65)]


def test_repeat_kaydi_tekrarlar():
    sender = FakeSender()
    player = macro.Player(sender=sender, sleep=lambda _ms: None)
    assert player.play([{"dt": 0, "e": "key", "vk": 65, "down": True}], repeat=3) == 3
    assert sender.calls == [("down", 65)] * 3


def test_play_slot_dosyadan_oynatir(files_dir):
    macro.write(macro.slot_path(1), [{"dt": 0, "e": "key", "vk": 65, "down": True}], "x")
    sender = FakeSender()
    assert macro.play_slot(1, sender=sender, sleep=lambda _ms: None) == 1
    assert sender.calls == [("down", 65)]


def test_slot_listesi_ayara_uyar(files_dir):
    macro.SLOT_COUNT.set(2)
    try:
        assert [n for n, _ in macro.iter_slots()] == [1, 2]
    finally:
        macro.SLOT_COUNT.set(macro.SLOT_COUNT.default)


# ---- kayit turu (AHK recType) ----


def test_key_modunda_fare_kaydedilmez():
    rec = macro.Recorder(rect=lambda: (0, 0, 0, 0))
    rec.start(macro.KEY)
    rec.feed_mouse(FakeMouse(message=0x0201, x=10, y=20))
    assert rec.events == []


def test_mouse_modunda_klavye_kaydedilmez():
    rec = macro.Recorder(rect=lambda: (0, 0, 0, 0))
    rec.start(macro.MOUSE)
    rec.feed_key(FakeKey(vk=65))
    rec.feed_mouse(FakeMouse(message=0x0201, x=10, y=20))
    assert [e["e"] for e in rec.events] == ["mouse"]


def test_hybrid_modunda_ikisi_de_kaydedilir():
    rec = macro.Recorder(rect=lambda: (0, 0, 0, 0))
    rec.start(macro.HYBRID)
    rec.feed_key(FakeKey(vk=65))
    rec.feed_mouse(FakeMouse(message=0x0201, x=10, y=20))
    assert [e["e"] for e in rec.events] == ["key", "mouse"]


def test_mouse_modunda_esc_yine_durdurur():
    """Panik tusu kayit turunden bagimsiz olmali."""
    rec = macro.Recorder(rect=lambda: (0, 0, 0, 0))
    rec.start(macro.MOUSE)
    rec.feed_key(FakeKey(vk=macro.VK_ESCAPE))
    assert not rec.recording


# ---- fare kaydi ----


def test_tiklama_uc_koordinatla_kaydedilir():
    """Mod degistiginde eski kayit bozulmasin diye ucu birden yazilir."""
    rec = macro.Recorder(rect=lambda: (100, 50, 900, 700))
    rec.start(macro.HYBRID)
    rec.feed_mouse(FakeMouse(message=0x0201, x=300, y=250))
    rec.feed_mouse(FakeMouse(message=0x0202, x=310, y=240))
    ilk, ikinci = rec.events
    assert (ilk["btn"], ilk["down"]) == ("left", True)
    assert (ilk["x"], ilk["y"]) == (300, 250)
    assert (ilk["wx"], ilk["wy"]) == (200, 200)  # pencere sol-ustune goreli
    assert (ilk["dx"], ilk["dy"]) == (0, 0)  # ilk tiklamanin oncesi yok
    assert (ikinci["dx"], ikinci["dy"]) == (10, -10)
    assert ikinci["down"] is False


def test_xbutton_numarasiyla_ayrilir():
    rec = macro.Recorder(rect=lambda: (0, 0, 0, 0))
    rec.start(macro.MOUSE)
    rec.feed_mouse(FakeMouse(message=0x020B, data=2))
    assert rec.events[0]["btn"] == "x2"


def test_tekerlek_kaydedilir():
    rec = macro.Recorder(rect=lambda: (0, 0, 0, 0))
    rec.start(macro.MOUSE)
    rec.feed_mouse(FakeMouse(message=0x020A, data=-120))
    assert rec.events[0] == {"e": "wheel", "delta": -120, "horizontal": False, "dt": 0}


def test_fare_hareketi_kaydedilmez():
    """Ara hareket dosyayi sisirir, oynatmada bir sey kazandirmaz."""
    rec = macro.Recorder(rect=lambda: (0, 0, 0, 0))
    rec.start(macro.HYBRID)
    rec.feed_mouse(FakeMouse(message=0x0200, x=5, y=5))
    assert rec.events == []


def test_kendi_gonderdigimiz_tiklama_kaydedilmez():
    rec = macro.Recorder(rect=lambda: (0, 0, 0, 0))
    rec.start(macro.HYBRID)
    rec.feed_mouse(FakeMouse(message=0x0201, injected=True, ours=True))
    assert rec.events == []


# ---- fare oynatma ----


def tiklama(**kwargs) -> dict:
    event = {
        "dt": 0,
        "e": "mouse",
        "btn": "left",
        "down": True,
        "x": 300,
        "y": 250,
        "wx": 200,
        "wy": 200,
        "dx": 10,
        "dy": -10,
    }
    event.update(kwargs)
    return event


def oynat(mode: str, sender, **kwargs):
    macro.MOUSE_MODE.set(mode)
    macro.KEY_DELAY.set(0)
    try:
        macro.Player(sender=sender, sleep=lambda _ms: None, **kwargs).play([tiklama()])
    finally:
        macro.MOUSE_MODE.set(macro.MOUSE_MODE.default)
        macro.KEY_DELAY.set(macro.KEY_DELAY.default)


def test_screen_modu_ekran_noktasini_kullanir():
    sender = FakeSender()
    oynat("screen", sender)
    assert sender.calls == [("pos", 300, 250), ("btn_down", 0x01)]


def test_window_modu_o_anki_pencereye_gore_hesaplar():
    """Pencere tasinmis: kayittaki ekran noktasi degil, goreli nokta gecerli."""
    sender = FakeSender()
    oynat("window", sender, rect=lambda: (500, 400, 1200, 900))
    assert sender.calls == [("pos", 700, 600), ("btn_down", 0x01)]


def test_relative_modu_sapma_gonderir():
    sender = FakeSender()
    oynat("relative", sender)
    assert sender.calls == [("rel", 10, -10), ("btn_down", 0x01)]


def test_tekerlek_oynatilir():
    sender = FakeSender()
    macro.KEY_DELAY.set(0)
    try:
        player = macro.Player(sender=sender, sleep=lambda _ms: None)
        player.play([{"dt": 0, "e": "wheel", "delta": 120, "horizontal": True}])
    finally:
        macro.KEY_DELAY.set(macro.KEY_DELAY.default)
    assert sender.calls == [("wheel", 120, True)]


# ---- pencere aktiflestirme ----


def pencere_oynat(**kwargs) -> list:
    gorulen: list = []
    player = macro.Player(
        sender=FakeSender(),
        sleep=lambda _ms: None,
        find_window=lambda c, t: (gorulen.append((c, t)), 42)[1],
        activate=lambda h: bool(gorulen.append(("activate", h))) or True,
        **kwargs,
    )
    player.play([{"dt": 0, "e": "window", "class": "Notepad", "title": "Adsiz"}])
    return gorulen


def test_ayar_kapaliyken_pencere_aktiflestirilmez():
    """Varsayilan: olay dosyada durur ama oynatmada bir sey yapmaz."""
    assert pencere_oynat() == []


def test_ayar_acikken_pencere_one_getirilir():
    macro.ACTIVATE_WINDOW.set(True)
    try:
        assert pencere_oynat() == [("Notepad", "Adsiz"), ("activate", 42)]
    finally:
        macro.ACTIVATE_WINDOW.set(False)


def test_pencere_bulunamazsa_oynatma_surer():
    macro.ACTIVATE_WINDOW.set(True)
    try:
        sender = FakeSender()
        player = macro.Player(
            sender=sender,
            sleep=lambda _ms: None,
            find_window=lambda _c, _t: 0,
        )
        events = [
            {"dt": 0, "e": "window", "class": "Yok", "title": "Yok"},
            {"dt": 0, "e": "key", "vk": 65, "down": True},
        ]
        assert player.play(events) == 2
        assert sender.calls == [("down", 65)]
    finally:
        macro.ACTIVATE_WINDOW.set(False)
