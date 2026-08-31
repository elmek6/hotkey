"""Makro kayit ekrani -- AHK `macro_recorder.ahk` `showButtons()` portu.

Duzen AHK ile ayni tutuldu (slot listesi, kayit turu, ad, 🛑 ⏹️ ▶️), iki
fark var:

  * Kayit sirasinda pencere KAPANMIYOR, kucuk kalip durumu gosteriyor.
    AHK'de oynatmadan once pencere yok ediliyordu cunku oynatma ikinci bir
    AHK surecinde kosuyordu; bizde oynatma kendi thread'imizde, pencere de
    tek duraklama noktasi -- durdurma dugmesi elinin altinda kalsin.
  * Secenekler (pencere kaydi / pencereyi one getirme) checkbox olarak
    burada. AHK bunlari `mouseMode`a bagli yorum satirlariyla hallediyordu;
    gorunmeyen bir kural yerine acikca isaretlenen bir kutu.

Bu ekran KARAR VERMEZ: kayit/oynatma islerini app.py'deki denetleyiciye
(`MacroController`) birakir, kendisi yalnizca durum gosterir. Sebep,
oynatmanin ayri bir thread'de kosmasi -- Qt widget'ina baska thread'den
dokunulmamali.
"""

from __future__ import annotations

import subprocess

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cascade import macro, theme
from cascade.ui.place import center_on_cursor_screen

#: Kayit suresi/olay sayaci bu araliktan tazelenir.
POLL_MS = 200


class MacroView(QWidget):
    """Tek ornek app.py'de tutulur."""

    #: (slot, kayit turu) -- kayda basildi
    record_requested = Signal(int, str)
    #: (slot, ad) -- durdur ve kaydet
    stop_requested = Signal(int, str)
    #: slot -- oynat
    play_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("⏺️ Macro Recorder")

        self.slots = QComboBox()
        self.slots.currentIndexChanged.connect(self._on_slot_change)

        self.types = QComboBox()
        for kind in macro.REC_TYPES:
            self.types.addItem(macro.RECORD_TYPE.label_for(kind), kind)
        self.types.setCurrentIndex(macro.REC_TYPES.index(str(macro.RECORD_TYPE.get())))

        top = QHBoxLayout()
        top.addWidget(self.slots, 1)
        top.addWidget(self.types)

        self.name = QLineEdit()
        self.name.setPlaceholderText("Kaydin adi (dosyanin ilk satirinda durur)")
        self.name.editingFinished.connect(self._commit_name)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Ad:"))
        name_row.addWidget(self.name, 1)

        self.record_button = QPushButton("\U0001f6d1 Kaydet")
        self.record_button.clicked.connect(self._on_record)
        self.stop_button = QPushButton("⏹️ Durdur")
        self.stop_button.clicked.connect(self._on_stop)
        self.play_button = QPushButton("▶️ Oynat")
        self.play_button.clicked.connect(self._on_play)

        buttons = QHBoxLayout()
        for button in (self.record_button, self.stop_button, self.play_button):
            buttons.addWidget(button)

        # Ayarin KENDISI degistiriliyor (ayar ekraniyla ayni deger): iki
        # yerde iki ayri "acik mi" bayragi tutmak, birinden degistirince
        # otekinin yalan soylemesi demek.
        self.record_window = self._option(macro.RECORD_WINDOW)
        self.activate_window = self._option(macro.ACTIVATE_WINDOW)

        self.status = QLabel("Hazir")
        theme.muted(self.status)

        self.open_button = QPushButton("\U0001f4dd Not defterinde ac")
        self.open_button.clicked.connect(self._on_open_file)
        self.close_button = QPushButton("Kapat")
        self.close_button.clicked.connect(self.close)

        tail = QHBoxLayout()
        tail.addWidget(self.open_button)
        tail.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(name_row)
        layout.addLayout(buttons)
        layout.addWidget(self.record_window)
        layout.addWidget(self.activate_window)
        layout.addWidget(self.status)
        layout.addLayout(tail)
        self.resize(430, 250)

        self._recording = False
        self._playing = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)

    def _option(self, item) -> QCheckBox:
        box = QCheckBox(item.name)
        box.setToolTip(item.desc)
        box.setChecked(bool(item.get()))
        box.toggled.connect(item.set)
        return box

    # ---- disari ----

    def open(self) -> None:
        self.reload()
        # Konumu Qt'ye birakmiyoruz: coklu monitorde pencere gorunmez bir
        # yere acilabiliyor (gerekcesi ui/place.py'nin basinda).
        center_on_cursor_screen(self)
        self.show()
        self.raise_()
        self.activateWindow()
        self._timer.start(POLL_MS)

    def reload(self) -> None:
        """Slot listesini diskten tazeler; secim KORUNUR."""
        current = self.slot()
        self.slots.blockSignals(True)
        self.slots.clear()
        for number, label in macro.iter_slots():
            self.slots.addItem(label, number)
        index = self.slots.findData(current)
        self.slots.setCurrentIndex(max(0, index))
        self.slots.blockSignals(False)
        self.name.setText(macro.slot_name(self.slot()))
        self.record_window.setChecked(bool(macro.RECORD_WINDOW.get()))
        self.activate_window.setChecked(bool(macro.ACTIVATE_WINDOW.get()))

    def slot(self) -> int:
        return int(self.slots.currentData() or 1)

    def set_state(self, recording: bool, playing: bool, note: str = "") -> None:
        """Denetleyici durumu degistikce cagirir."""
        self._recording, self._playing = recording, playing
        self.record_button.setEnabled(not playing)
        self.record_button.setText("⏺️ Kayitta" if recording else "\U0001f6d1 Kaydet")
        self.play_button.setEnabled(not recording and not playing)
        self.types.setEnabled(not recording and not playing)
        self.slots.setEnabled(not recording and not playing)
        if note:
            self.status.setText(note)
        if not recording and not playing:
            self.reload()

    # ---- ic ----

    def _on_slot_change(self) -> None:
        self.name.setText(macro.slot_name(self.slot()))

    def _commit_name(self) -> None:
        macro.set_slot_name(self.slot(), self.name.text())

    def _on_record(self) -> None:
        if self._recording:
            self._on_stop()
            return
        self._commit_name()
        kind = str(self.types.currentData())
        macro.RECORD_TYPE.set(kind)
        self.record_requested.emit(self.slot(), kind)

    def _on_stop(self) -> None:
        """AHK'de durdurma yalnizca panik tusuydu; burada dugme de var --
        oynatma sirasinda klavye kullanicinin elinden ciktigi icin fareyle
        ulasilabilen bir cikis lazim (Esc yine calisiyor)."""
        self.stop_requested.emit(self.slot(), self.name.text())

    def _on_play(self) -> None:
        self._commit_name()
        self.play_requested.emit(self.slot())

    def _on_open_file(self) -> None:
        path = macro.slot_path(self.slot())
        if not path.exists():
            self.status.setText(f"Dosya yok: {path.name}")
            return
        subprocess.Popen(["notepad.exe", str(path)])

    def _refresh_status(self) -> None:
        if self._recording or self._playing:
            return
        self.status.setText("Hazir")

    def closeEvent(self, event) -> None:  # noqa: N802 -- Qt adi
        self._commit_name()
        self.stop_requested.emit(self.slot(), self.name.text())
        self._timer.stop()
        super().closeEvent(event)
