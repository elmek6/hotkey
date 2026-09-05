"""Ertelenen yedegin sozlesmesi (incognito.py "yedek" bolumu).

enable() agir yedegi bir isci thread'ine birakip donuyor. Bu hizli, ama iki
seyi yanlis yaparsan SESSIZCE veri kaybettiriyor:

  * Kilitlenen klasorun yedegi ERTELENEMEZ. Kilit paylasimsiz aciliyor,
    kilitlendikten sonra dosyayi kendimiz de okuyamiyoruz -- paket bos kalir
    ve kapanista "oturumda dogmus" sanilan gercek jump list'ler silinir.
  * Yedege dokunan her yol once beklemek ZORUNDA. Beklemeyen bir yol yarim
    yedekle geri yukleme demek.

Buradaki testler ikisini de kilitliyor. Isci thread'i uyutulmuyor, bir
Event'le duruyor: makine yavaslasa da sonuc degismesin.
"""

from __future__ import annotations

import os
import threading

import pytest

from keypilot import incognito as inc_module
from keypilot.incognito import Incognito
from keypilot.tracestore import FileGlobStore, TraceStore


class SpyStore(TraceStore):
    """Ertelenebilir depo -- `gate` acilana kadar yedegini bitirmez."""

    def __init__(self, name: str, log: list[tuple[str, str]], gate: threading.Event) -> None:
        super().__init__(name)
        self.log = log
        self.gate = gate

    def snapshot(self, root) -> bool:
        self.gate.wait(5)
        self.log.append(("snap", self.name))
        (root / f"{self.name}.json").write_bytes(b"{}")
        return True

    def restore(self, root) -> bool:
        self.log.append(("restore", self.name))
        return True

    def snapshot_paths(self, root) -> list:
        return [root / f"{self.name}.json"]

    def start_watch(self) -> None:
        self.log.append(("watch", self.name))

    def stop_watch(self) -> None:
        self.log.append(("stop", self.name))

    def has_changed(self) -> bool:
        return True


class SpyGlob(FileGlobStore):
    """Kilitlenen klasordeki depo -- yedegi kilitten ONCE bitmek zorunda."""

    def __init__(self, name: str, directory, log: list[tuple[str, str]]) -> None:
        super().__init__(name, directory, "*.bin")
        self.log = log

    def snapshot(self, root) -> bool:
        self.log.append(("snap", self.name))
        return super().snapshot(root)

    def start_watch(self) -> None:  # FileGlobStore'da gozcu yok, sira icin
        self.log.append(("watch", self.name))


@pytest.fixture
def kurulum(tmp_path, monkeypatch):
    """Incognito + biri kilitli biri ertelenebilir iki depo."""
    locked_dir = tmp_path / "jumplist"
    locked_dir.mkdir()
    (locked_dir / "ornek.bin").write_bytes(b"veri")
    monkeypatch.setattr(inc_module, "_LOCKED_DIRS", frozenset({locked_dir}))

    log: list[tuple[str, str]] = []
    gate = threading.Event()
    inc = Incognito()
    inc.snap_dir = tmp_path / "snap"
    inc.snap_dir.mkdir()
    inc.stores = [SpyGlob("Kilitli", locked_dir, log), SpyStore("Ertelenen", log, gate)]
    yield inc, log, gate
    gate.set()
    inc._finish_snapshot()


def test_kilitlenen_depo_senkron_ertelenebilir_arkada(kurulum):
    """Kilit bagi olan yedek _begin_snapshot donmeden bitmis olmali."""
    inc, log, gate = kurulum
    inc._begin_snapshot()

    assert (inc.snap_dir / "Kilitli.pack").exists()  # kilitten once bitti
    assert not (inc.snap_dir / "Ertelenen.json").exists()  # hala kapida
    assert inc._finish_snapshot(wait=False) is False  # yoklamak bloklamaz

    gate.set()
    assert inc._finish_snapshot() is True
    assert (inc.snap_dir / "Ertelenen.json").exists()
    assert inc._snap_thread is None  # biten isci toplandi


def test_gozculer_ertelenen_depo_icin_de_once_kurulur(kurulum):
    """Gozcu yedekten SONRA kurulursa aradaki iz kacar ve depo
    "dokunulmamis" sayilip geri yuklenmeden atlanir."""
    inc, log, gate = kurulum
    gate.set()
    inc._begin_snapshot()
    inc._finish_snapshot()

    ilk_yedek = next(i for i, (ne, _) in enumerate(log) if ne == "snap")
    gozculer = [i for i, (ne, _) in enumerate(log) if ne == "watch"]
    assert len(gozculer) == 2  # ertelenen depo dahil
    assert max(gozculer) < ilk_yedek


@pytest.mark.parametrize(
    "yol",
    ["_clear_snap_payload", "_restore_all", "_discard_snapshot", "_drop_snapshot"],
)
def test_yedege_dokunan_yollar_once_bekler(kurulum, monkeypatch, yol):
    """Sozlesme: snap_dir'e dokunan her ic metot _finish_snapshot cagirir."""
    inc, log, gate = kurulum
    gate.set()
    cagrildi: list[bool] = []
    monkeypatch.setattr(
        inc, "_finish_snapshot", lambda wait=True: (cagrildi.append(True), True)[1]
    )

    metot = getattr(inc, yol)
    metot(inc.stores[1]) if yol == "_drop_snapshot" else metot()
    assert cagrildi, f"{yol} ertelenen yedegi beklemiyor"


def test_paket_gidis_donus(tmp_path):
    """`scandir`e gecen yol jump list'i bozuyor mu?

    Bu depoda bir hata, kapanista GERCEK jump list dosyalarini siler ya da
    yanlis icerikle yazar (AHK tarafinda bir kez 49 dosya sifirlandi). O
    yuzden yedek/geri yukleme burada ucunden tutuluyor: degisen dosya,
    silinen dosya, oturumda dogan dosya.
    """
    klasor = tmp_path / "jl"
    klasor.mkdir()
    (klasor / "a.bin").write_bytes(b"eski-a")
    (klasor / "b.bin").write_bytes(b"eski-b")
    os.utime(klasor / "a.bin", (1_700_000_000, 1_700_000_000))

    store = FileGlobStore("JL", klasor, "*.bin")
    root = tmp_path / "snap"
    root.mkdir()
    assert store.snapshot(root)
    assert store.count() == 2

    (klasor / "a.bin").write_bytes(b"OTURUMDA DEGISTI")
    (klasor / "b.bin").unlink()
    (klasor / "yeni.bin").write_bytes(b"oturumda dogdu")

    assert store.restore(root)
    assert (klasor / "a.bin").read_bytes() == b"eski-a"  # degisen geri alindi
    assert (klasor / "b.bin").read_bytes() == b"eski-b"  # silinen geri geldi
    assert not (klasor / "yeni.bin").exists()  # oturumda dogan silindi
    # Damga "simdi"de kalirsa kendisi bir iz olur.
    assert abs((klasor / "a.bin").stat().st_mtime - 1_700_000_000) < 2
