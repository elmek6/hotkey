"""Flet'e tasinan panelleri PROGRAMI CALISTIRMADAN dene.

Gecis boyunca gereken sondaj: gercek KeyPilot'u baslatmak tuslari
devraliyor ve calisan ornegi kapatiyor (`SingleInstance` "yeni kazanir").
Bu sondaj yalnizca bir `QApplication` kurup panelleri sahte veriyle
aciyor -- hook yok, tepsi yok, tuslara dokunulmuyor.

Ayni zamanda gecisin mimari provasi: panel FLET thread'inde koser, Qt
ana thread'i bos kalir. Alt satirdaki sayac Qt dongusunun aksamadigini
gosteriyor; panel bir sinyal gonderdiginde hangi thread'de alindigi da
yaziliyor (`MainThread` olmali -- bkz. flet-plan.md).

Calistir:  uv run python -m probes.flet
           uv run python -m probes.flet pause     (yalniz duraklatma)
           uv run python -m probes.flet keymap    (yalniz kisayol haritasi)
           uv run python -m probes.flet slot      (yalniz slot duzenleme)
           uv run python -m probes.flet log       (yalniz log penceresi)
           uv run python -m probes.flet qr        (yalniz QR penceresi)
           uv run python -m probes.flet monitor   (yalniz olay izleyici)
           uv run python -m probes.flet macro     (yalniz makro kayit ekrani)
           uv run python -m probes.flet ocr       (yalniz OCR sonuc paneli)
           uv run python -m probes.flet repo      (yalniz kod parcasi deposu)

Cikis: konsolda Ctrl+C ya da bu sondajin kendi penceresini kapat.
Paneller kapatilinca GIZLENIYOR (gercekte de oyle) -- `flet.exe` ayakta
kalir ve sondaj cikarken kapatilir.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from keypilot import paths
from keypilot.core.mouse import MouseSeen
from keypilot.core.ocr_layout import Word
from keypilot.fui.key_map import KeyMapPanel
from keypilot.fui.log_view import LogPanel
from keypilot.fui.macro import MacroPanel
from keypilot.fui.monitor import MonitorPanel
from keypilot.fui.ocr import OcrPanel
from keypilot.fui.pause import PausePanel
from keypilot.fui.qr import QrPanel
from keypilot.fui.repository import RepositoryPanel
from keypilot.fui.slot_edit import SlotEditPanel
from keypilot.repository import Repository
from keypilot.store import PASSWORD_SLOT, SlotStore
from keypilot.win32.hook import KeyEvent

#: Kisayol haritasi icin sahte satirlar: (sahip, tus, aciklama, eylem,
#: catisiyor_mu). Ilk iki satir BILEREK ayni tusta -- catisma
#: gosteriminin (kirmizi zemin, ustte siralama) calistigi gorulsun.
ROWS = (
    ("area:kur#0", "F4", "kurulum alani", "area.run:kur#0", True),
    ("macro:derle", "F4", "derleme makrosu", "macro.run:derle", True),
    ("keymap", "F13", "", "menu.open", False),
    ("keymap", "F14", "", "select.start", False),
    ("keymap", "F15", "", "clip.history", False),
    ("keypilot", "F16", "+Ctrl +Shift", "tap: pano, hold: gecmis", False),
    ("profile:oyun", "F6", "oyun profili", "profile.switch:oyun", False),
    ("area:test#1", "Ctrl+Alt+T", "test alani", "area.run:test#1", False),
    ("macro:rapor", "Ctrl+Alt+R", "haftalik rapor", "macro.run:rapor", False),
) * 6

#: Slot kutusundaki "eski" satiri icin: satir sonlari ve fazla bosluk
#: TEK bosluga eziliyor, 160 karakterden sonrasi kirpiliyor mu?
LONG_CONTENT = (
    "ilk satir\n\n   ikinci satirda fazladan bosluklar   \n"
    + "uzun bir icerik, kirpilma sinirini gecsin diye tekrar ediyor. " * 4
)


#: Olay izleyicinin sahte akisi. Bu panelin tek yeni sorusu SUREKLI
#: GUNCELLEME oldugu icin sondaj onu zorluyor: saniyede ~40 olay, yani
#: hizli yazan birinin iki katindan fazlasi.
FEED_MS = 50
FEED_BURST = 2

#: Akista donen tuslar. Biri en uzun ad (Media_Play_Pause -- sutun
#: genisligi sinavi), biri bilinmeyen VK (VKxxSCxxx bicimi), sonuncusu
#: fare olayina isaret: `sc` sutununda tarama kodu degil imlec konumu.
FEED_KEYS = (0x5B, 0x70, 0x4D, 0xB3, 0x1B, 0xFE, 0xFF)


#: OCR paneli icin sahte kelime kutulari: UC SUTUNLU bir tablo (uc satir).
#: Kolon esigi ve tablo bicimi ancak boyle sinaniyor -- kutular ekranda
#: nerede duruyorsa dizilim ondan cikiyor (core/ocr_layout.py).
OCR_ROWS = (
    ("Urun", "Adet", "Fiyat"),
    ("Kalem", "12", "45,00"),
    ("Defter", "3", "120,50"),
    ("Silgi", "7", "9,90"),
)
#: Sutunlarin sol kenarlari (piksel) -- aralarindaki bosluk kolon
#: ayracinin bulunmasi gereken yer.
OCR_COLUMNS = (40, 300, 520)
OCR_ROW_H = 34


def ocr_words() -> tuple[Word, ...]:
    return tuple(
        Word(text=cell, x=float(OCR_COLUMNS[column]), y=float(20 + row * OCR_ROW_H),
             w=float(len(cell) * 11), h=22.0)
        for row, cells in enumerate(OCR_ROWS)
        for column, cell in enumerate(cells)
    )


#: Depo sondaji GERCEK repository.md'yi KOPYALIYOR: gorunum gercek
#: veriyle sinansin ama "Sil"/"Kaydet" kullanicinin dosyasina dokunmasin
#: (bu panelde iki dugme de diske yaziyor). Dosya yoksa asagidaki ornek.
REPO_SAMPLE = """===
uuid: ornek-1
title: doorbell
category: iot
tags: tuya, zigbee
---
tuya doorbell, iki yonlu ses
===
uuid: ornek-2
title: kamera
category: iot
tags: tuya
---
rtsp akisi
===
uuid: ornek-3
title: git rebase
category: git
tags: gunluk
---
git rebase -i HEAD~3
===
uuid: ornek-4
title: kategorisiz not
---
suzgeclerde parantezsiz gorunmeli
"""


def probe_repository() -> Repository:
    """Sondajin yazabilecegi GECICI depo (gercek dosyanin kopyasi)."""
    path = Path(tempfile.gettempdir()) / "keypilot-sondaj-repository.md"
    if not path.exists():
        source = paths.REPOSITORY
        text = source.read_text(encoding="utf-8-sig") if source.exists() else REPO_SAMPLE
        path.write_text(text, encoding="utf-8")
    repo = Repository(path)
    repo.load()
    return repo


#: "Durum" sekmesi icin sahte sayaclar -- app.py `_diagnostics` bicimi.
STATS = [
    ("hook: en uzun callback", "12.480 ms (sinir 300)"),
    ("hook: dusen olay", "0"),
    ("hook: yeniden kurulum", "1 kez"),
    ("hayalet tus", "3 dusuruldu"),
    ("pano kaydi", "50"),
    ("yutulan cift tik", "7 (arizali fare)"),
    ("gelistirme modu", "kapali"),
]


class Probe(QWidget):
    """Panelleri acan dugmeler + gelen sinyallerin dokumu."""

    def __init__(self, only: str = "") -> None:
        super().__init__()
        self.setWindowTitle("Flet panel sondaji")
        self.resize(560, 420)
        layout = QVBoxLayout(self)

        self.key_map = KeyMapPanel()
        self.key_map.closed.connect(lambda: self._note("key_map", "closed"))

        self.pause = PausePanel()
        self.pause.resume.connect(lambda: self._note("pause", "resume"))
        self.pause.restart.connect(lambda: self._note("pause", "restart"))
        self.pause.restart_nosave.connect(lambda: self._note("pause", "restart_nosave"))
        self.pause.exit_app.connect(lambda: self._note("pause", "exit_app"))

        # Gercekte diske yaziyor (`slots_ctl._store_slot`); sondajda
        # yalnizca ne geldigi yaziliyor.
        self.slot = SlotEditPanel()
        self.slot.saved.connect(
            lambda name, content: self._note("slot_edit", f"saved ad={name!r} icerik={content!r}")
        )

        # GERCEK log dosyasini okuyor (Files/log.txt) -- sahte veri yok.
        # "Log temizle" gercekten siliyor, dikkat.
        self.log = LogPanel()
        self.log.closed.connect(lambda: self._note("log", "closed"))

        # GERCEK slots.json'u okuyor: grup kutusu ve slot listesi dolu
        # gelsin. Grup secimi ayara yaziliyor (gercekte de oyle).
        self.qr = QrPanel(SlotStore())
        self.qr.closed.connect(lambda: self._note("qr", "closed"))

        # Tek CANLI panel: asagidaki zamanlayici sahte olay besliyor.
        # Gercekte besleyen app.py `_drain`.
        self.monitor = MonitorPanel()
        self.monitor.closed.connect(lambda: self._note("monitor", "closed"))
        self._feed = 0

        # GERCEK rec*.jsonl slotlarini okuyor: slot listesi ve ad dolu
        # gelsin. Ad kutusu diske YAZIYOR (gercekte de oyle). Kayit ve
        # oynatma YOK -- onlari `macro_ctl.py` yapiyor; sondaj yalnizca
        # sinyali yaziyor ve durumu elle geri besliyor.
        self.macro = MacroPanel()
        self.macro.record_requested.connect(
            lambda slot, kind: self._on_record(slot, kind)
        )
        self.macro.stop_requested.connect(
            lambda slot, name: self._on_stop(slot, name)
        )
        self.macro.play_requested.connect(lambda slot: self._on_play(slot))

        # SAHTE OCR sonucu: gercekte kelime kutulari Windows.Media.Ocr'dan
        # geliyor (app.py `_on_ocr_done`). "Yenile" ve olcek degisimi
        # gercekte yeniden OCR baslatiyor; sondajda ayni sonucu geri
        # veriyor -- bakilan sey panelin DURUM yazmasi ve dizilim.
        self.ocr = OcrPanel()
        self.ocr.copy_text.connect(
            lambda text: self._note("ocr", f"copy_text ({len(text)} karakter)")
        )
        self.ocr.reocr_requested.connect(lambda scale: self._on_reocr(scale))
        self.ocr.refresh_requested.connect(self._on_refresh)
        self.ocr.closed.connect(lambda: self._note("ocr", "closed"))

        # Depo: GECICI dosya uzerinde calisiyor (bkz. `probe_repository`).
        # Kaydet/Sil GERCEKTEN yaziyor -- ama kopyaya.
        self.repository = RepositoryPanel(probe_repository())
        self.repository.closed.connect(lambda: self._note("repository", "closed"))

        buttons = [
            ("Kisayol haritasi (keys.map)", lambda: self.key_map.show_rows(ROWS), "keymap"),
            ("Duraklatma kutusu", lambda: self.pause.show_paused(), "pause"),
            (
                "Duraklatma + kritik hata metni",
                lambda: self.pause.show_paused(
                    "Pano dosyasi okunamadi: clip.json bozuk gorunuyor."
                ),
                "pause",
            ),
            # Uc slot durumu: dolu, bos ve sifre slotu (eski deger maskeli).
            (
                "Slot duzenle -- dolu slot (3)",
                lambda: self.slot.show_slot(3, "imza", LONG_CONTENT, "panodan gelen metin"),
                "slot",
            ),
            (
                "Slot duzenle -- bos slot (5)",
                lambda: self.slot.show_slot(5, "", "", ""),
                "slot",
            ),
            (
                f"Slot duzenle -- SIFRE slotu ({PASSWORD_SLOT})",
                lambda: self.slot.show_slot(PASSWORD_SLOT, "parola", "hunter2", ""),
                "slot",
            ),
            ("Log penceresi (gercek log.txt)", self._show_log, "log"),
            # Uc giris: duz metin, link ve hazir bir wifi dizgisi --
            # ucu de baska bir sablon tahmin ettiriyor.
            ("Olay izleyici (sahte akis)", self.monitor.show_monitor, "monitor"),
            ("Makro kayit ekrani", self.macro.open, "macro"),
            ("OCR sonuc paneli (sahte tablo)", self._show_ocr, "ocr"),
            ("Kod parcasi deposu (gecici kopya)", self.repository.open, "repo"),
            ("QR -- duz metin", lambda: self.qr.show_text("merhaba dunya"), "qr"),
            ("QR -- link", lambda: self.qr.show_text("https://flet.dev"), "qr"),
            (
                "QR -- hazir wifi dizgisi",
                lambda: self.qr.show_text("WIFI:T:WPA;S:Ev Agi;P:parola123;;"),
                "qr",
            ),
        ]
        for label, slot, group in buttons:
            if only and group != only:
                continue
            button = QPushButton(label, self)
            button.setMinimumHeight(34)
            button.clicked.connect(slot)
            layout.addWidget(button)

        self._log = QPlainTextEdit(self)
        self._log.setReadOnly(True)
        layout.addWidget(self._log)

        self._beat = QLabel("", self)
        layout.addWidget(self._beat)
        self._ticks = 0
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(1000)

        feeder = QTimer(self)
        feeder.timeout.connect(self._feed_monitor)
        feeder.start(FEED_MS)

        self._note("sondaj", f"hazir -- {len(ROWS)} sahte kisayol satiri")

    def _feed_monitor(self) -> None:
        """Sahte olay akisi -- gercekte `app.py` `_drain` besliyor.

        "Pencere acik mi" sorusu ANA THREAD'deki bir bayraga soruluyor
        (`visible`), gercek programdaki gibi: kapaliyken hicbir sey
        yapilmiyor.
        """
        if not self.monitor.visible:
            return
        for _ in range(FEED_BURST):
            self._feed += 1
            vk = FEED_KEYS[self._feed % len(FEED_KEYS)]
            down = self._feed % 2 == 0
            now = time.perf_counter()
            event = (
                MouseSeen(vk=0x05, down=down, t=now, x=1920, y=1080)
                if vk == 0xFF
                else KeyEvent(
                    vk=vk,
                    scan=0x1D,
                    down=down,
                    extended=False,
                    injected=False,
                    ours=False,
                    time_ms=0,
                    t=now,
                )
            )
            # Her yedincisi YUTULDU: kirmizi satir da gorunsun.
            self.monitor.add(event, swallowed=self._feed % 7 == 0)

    # ---- makro: `macro_ctl.py`nin yerine gecen sahte denetleyici ----
    #
    # Gercekte durumu denetleyici yaziyor (`set_state`); sondajda ayni
    # cagrilar burada, ayni thread'de (ANA THREAD) yapiliyor.

    def _on_record(self, slot: int, kind: str) -> None:
        self._note("macro", f"record slot={slot} tur={kind}")
        self.macro.set_state(True, False, f"Kayitta -- rec{slot}.jsonl (Esc: durdur)")

    def _on_stop(self, slot: int, name: str) -> None:
        self._note("macro", f"stop slot={slot} ad={name!r}")
        self.macro.set_state(False, False, f"12 olay -> rec{slot}.jsonl")

    def _on_play(self, slot: int) -> None:
        self._note("macro", f"play slot={slot}")
        self.macro.set_state(False, True, f"Oynatiliyor -- rec{slot}.jsonl")
        # Oynatma gercekte ayri thread'de kosup sinyalle donuyor; sondajda
        # tek atimlik bir zamanlayici ayni gecikmeyi taklit ediyor.
        QTimer.singleShot(
            2000, lambda: self.macro.set_state(False, False, "Bitti -- 12 olay")
        )

    # ---- OCR: `app.py`nin yerine gecen sahte akis ----

    def _show_ocr(self) -> None:
        self.ocr.show_result(ocr_words(), tuple(" ".join(r) for r in OCR_ROWS), 84.0)

    def _on_reocr(self, scale: int) -> None:
        self._note("ocr", f"reocr_requested olcek={scale}")
        # Gercekte yeniden OCR ayri thread'de kosup sonucu ana thread'e
        # donduruyor; sondaj ayni gecikmeyi taklit ediyor.
        QTimer.singleShot(800, self._show_ocr)

    def _on_refresh(self) -> None:
        self._note("ocr", "refresh_requested")
        QTimer.singleShot(800, self._show_ocr)

    def _show_log(self) -> None:
        # app.py `show_errors` ile ayni sira: once sayaclar, sonra pencere.
        self.log.set_stats(STATS)
        self.log.show_log()

    def _tick(self) -> None:
        self._ticks += 1
        # Bu sayac DURURSA Qt ana dongusu Flet yuzunden bloklanmis
        # demektir; gecisin en temel varsayimi cokmus olur.
        self._beat.setText(f"Qt ana dongusu: {self._ticks} tik (durursa mimari kirik)")

    def _note(self, source: str, event: str) -> None:
        # Alici thread YAZILIYOR: Flet paneli sinyali kendi thread'inden
        # gonderiyor, Qt kuyruga alip ana thread'de teslim etmeli.
        self._log.appendPlainText(
            f"[{source}] {event}  (alici thread: {threading.current_thread().name})"
        )

    def closeEvent(self, event) -> None:
        # Gercek programda bunu `app.py` `on_exit` yapiyor. Yapilmazsa
        # `flet.exe` gorev cubugunda sahipsiz kaliyor.
        self.key_map.shutdown()
        self.pause.shutdown()
        self.slot.shutdown()
        self.log.shutdown()
        self.qr.shutdown()
        self.monitor.shutdown()
        self.macro.shutdown()
        self.ocr.shutdown()
        self.repository.shutdown()
        super().closeEvent(event)


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    app = QApplication(sys.argv)
    probe = Probe(only)
    probe.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
