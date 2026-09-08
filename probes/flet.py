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

Cikis: konsolda Ctrl+C ya da bu sondajin kendi penceresini kapat.
Paneller kapatilinca GIZLENIYOR (gercekte de oyle) -- `flet.exe` ayakta
kalir ve sondaj cikarken kapatilir.
"""

from __future__ import annotations

import sys
import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from keypilot.core.mouse import MouseSeen
from keypilot.fui.key_map import KeyMapPanel
from keypilot.fui.log_view import LogPanel
from keypilot.fui.monitor import MonitorPanel
from keypilot.fui.pause import PausePanel
from keypilot.fui.qr import QrPanel
from keypilot.fui.slot_edit import SlotEditPanel
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
        super().closeEvent(event)


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    app = QApplication(sys.argv)
    probe = Probe(only)
    probe.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
