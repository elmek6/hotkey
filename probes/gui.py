"""Canli olay izleyici -- ekranda gorunen sondaj.

Ayni zamanda planin en kritik mimari varsayiminin provasi: Qt event loop ana
thread'de, LL hook ayri thread'de, aralarinda queue.Queue. Hook callback'i
hicbir Qt nesnesine dokunmaz; kuyruga yazar, ana thread QTimer ile bosaltir.

Calistir:  uv run python -m probes.gui
"""

from __future__ import annotations

import queue
import sys
import time

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from keypilot.core.combo import ComboTracker, Thresholds
from keypilot.core.keynames import MODIFIER_VKS, key_name
from keypilot.win32 import consts as C
from keypilot.win32.hook import PASS, SWALLOW, HookThread, KeyEvent, MouseEvent

VK_CAPSLOCK = 0x14
VK_XBUTTON2 = 0x06
MAX_ROWS = 400

BUTTON_VK = {
    C.WM_LBUTTONDOWN: (0x01, True),
    C.WM_LBUTTONUP: (0x01, False),
    C.WM_RBUTTONDOWN: (0x02, True),
    C.WM_RBUTTONUP: (0x02, False),
    C.WM_MBUTTONDOWN: (0x04, True),
    C.WM_MBUTTONUP: (0x04, False),
}

# Hook thread'i okur, GUI thread'i yazar. Tek bool -> kilit gerekmez.
swallow_capslock = True
swallow_xbutton2 = True

_hook_state = ComboTracker()


def _mouse_button(event: MouseEvent) -> tuple[int | None, bool]:
    if event.message in BUTTON_VK:
        return BUTTON_VK[event.message]
    if event.message == C.WM_XBUTTONDOWN:
        return (0x05 if event.data == 1 else 0x06), True
    if event.message == C.WM_XBUTTONUP:
        return (0x05 if event.data == 1 else 0x06), False
    return None, False


def key_filter(event: KeyEvent) -> bool:
    if event.ours:
        return PASS
    if event.down:
        _hook_state.key_down(event.vk, event.t)
    else:
        _hook_state.key_up(event.vk, event.t)
    if not swallow_capslock:
        return PASS
    if event.vk == VK_CAPSLOCK:
        return SWALLOW
    if _hook_state.is_down(VK_CAPSLOCK) and event.vk not in MODIFIER_VKS:
        return SWALLOW
    return PASS


def mouse_filter(event: MouseEvent) -> bool:
    if event.ours:
        return PASS
    vk, down = _mouse_button(event)
    if vk is None:
        return PASS
    if down:
        _hook_state.key_down(vk, event.t)
    else:
        _hook_state.key_up(vk, event.t)
    if vk == VK_XBUTTON2 and swallow_xbutton2:
        return SWALLOW
    return PASS


class Monitor(QWidget):
    COLUMNS = ["t", "tur", "olay", "kombo / detay", "sure", "durum"]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KeyPilot - canli olay izleyici")
        self.resize(940, 640)

        self.events: queue.Queue = queue.Queue(maxsize=8192)
        self.hook = HookThread(self.events, key_filter=key_filter, mouse_filter=mouse_filter)
        self.view = ComboTracker(Thresholds(short_ms=200, long_ms=500))
        self.counters = {"klavye": 0, "fare": 0, "yutulan": 0}
        self.latencies: list[float] = []
        self.started = time.perf_counter()

        self._build_ui()
        self.hook.start()

        self.drain = QTimer(self)
        self.drain.timeout.connect(self._drain_queue)
        self.drain.start(16)

        self.ticker = QTimer(self)
        self.ticker.timeout.connect(self._update_stats)
        self.ticker.start(400)

    # ---- arayuz ----

    def _build_ui(self) -> None:
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)

        self.combo_label = QLabel("bir tusa bas")
        big = QFont(mono)
        big.setPointSize(22)
        big.setBold(True)
        self.combo_label.setFont(big)
        self.combo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.combo_label.setMinimumHeight(64)

        self.stats_label = QLabel()
        self.stats_label.setFont(mono)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setFont(mono)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        cb_caps = QCheckBox("CapsLock yutulsun (prefix tusuna donsun)")
        cb_caps.setChecked(True)
        cb_caps.toggled.connect(self._set_caps)
        cb_x2 = QCheckBox("XButton2 yutulsun (tarayicida ileri gitmesin)")
        cb_x2.setChecked(True)
        cb_x2.toggled.connect(self._set_x2)
        clear = QPushButton("Listeyi temizle")
        clear.clicked.connect(lambda: self.table.setRowCount(0))

        controls = QHBoxLayout()
        controls.addWidget(cb_caps)
        controls.addWidget(cb_x2)
        controls.addStretch(1)
        controls.addWidget(clear)

        live = QWidget()
        live_layout = QVBoxLayout(live)
        live_layout.addWidget(self.combo_label)
        live_layout.addWidget(self.stats_label)
        live_layout.addWidget(self.table, 1)
        live_layout.addLayout(controls)

        self.test_output = QPlainTextEdit()
        self.test_output.setReadOnly(True)
        self.test_output.setFont(mono)
        self.test_output.setPlainText("Testleri calistir dugmesine bas.\n")
        self.run_tests_btn = QPushButton("Testleri calistir  (pytest)")
        self.run_tests_btn.clicked.connect(self._run_tests)

        tests = QWidget()
        tests_layout = QVBoxLayout(tests)
        tests_layout.addWidget(self.run_tests_btn)
        tests_layout.addWidget(self.test_output, 1)

        tabs = QTabWidget()
        tabs.addTab(live, "Canli olaylar")
        tabs.addTab(tests, "Birim testleri")

        root = QVBoxLayout(self)
        root.addWidget(tabs)

        self._update_stats()

    def _set_caps(self, on: bool) -> None:
        global swallow_capslock
        swallow_capslock = on

    def _set_x2(self, on: bool) -> None:
        global swallow_xbutton2
        swallow_xbutton2 = on

    def _add_row(self, cells: list[str], swallowed: bool) -> None:
        if self.table.rowCount() >= MAX_ROWS:
            self.table.removeRow(0)
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if swallowed:
                item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, col, item)
        self.table.scrollToBottom()

    # ---- kuyruk bosaltma, ana thread ----

    def _drain_queue(self) -> None:
        for _ in range(200):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return
            if event.ours:
                continue
            self.latencies.append((time.perf_counter() - event.t) * 1000.0)
            if isinstance(event, KeyEvent):
                self._on_key(event)
            elif isinstance(event, MouseEvent):
                self._on_mouse(event)

    def _stamp(self, event) -> str:
        return f"{event.t - self.started:7.2f}"

    def _on_key(self, event: KeyEvent) -> None:
        self.counters["klavye"] += 1
        swallowed = swallow_capslock and (
            event.vk == VK_CAPSLOCK
            or (self.view.is_down(VK_CAPSLOCK) and event.vk not in MODIFIER_VKS)
        )
        if swallowed:
            self.counters["yutulan"] += 1
        durum = "YUTULDU" if swallowed else ""

        if event.down:
            chord = self.view.key_down(event.vk, event.t)
            if chord is None:
                self._add_row(
                    [self._stamp(event), "tus", key_name(event.vk), "modifier basildi", "", durum],
                    swallowed,
                )
                return
            if chord.repeat:
                return
            self.combo_label.setText(chord.text)
            tur = "prefix" if chord.prefix is not None else "kombo"
            self._add_row(
                [self._stamp(event), tur, key_name(event.vk), chord.text, "", durum],
                swallowed,
            )
        else:
            press = self.view.key_up(event.vk, event.t)
            if press is None or event.vk in MODIFIER_VKS:
                return
            detay = "prefix olarak kullanildi" if press.was_prefix else ""
            self._add_row(
                [
                    self._stamp(event),
                    "birak",
                    press.text,
                    detay,
                    f"{press.ms:.0f} ms -> {press.kind.label}",
                    durum,
                ],
                swallowed,
            )

    def _on_mouse(self, event: MouseEvent) -> None:
        self.counters["fare"] += 1
        if event.message in (C.WM_MOUSEWHEEL, C.WM_MOUSEHWHEEL):
            eksen = "WheelH" if event.message == C.WM_MOUSEHWHEEL else "WheelV"
            onek = "+".join(key_name(k) for k in self.view.held)
            detay = f"{onek} & {eksen}" if onek else eksen
            self.combo_label.setText(detay)
            self._add_row(
                [self._stamp(event), "teker", eksen, detay, f"delta {event.data:+d}", ""],
                False,
            )
            return

        vk, down = _mouse_button(event)
        if vk is None:
            return
        swallowed = vk == VK_XBUTTON2 and swallow_xbutton2
        if swallowed:
            self.counters["yutulan"] += 1
        durum = "YUTULDU" if swallowed else ""

        if down:
            chord = self.view.key_down(vk, event.t)
            text = chord.text if chord else key_name(vk)
            self.combo_label.setText(text)
            self._add_row(
                [
                    self._stamp(event),
                    "fare",
                    key_name(vk),
                    text,
                    f"({event.x},{event.y})",
                    durum,
                ],
                swallowed,
            )
        else:
            press = self.view.key_up(vk, event.t)
            if press is None:
                return
            detay = "prefix olarak kullanildi" if press.was_prefix else ""
            self._add_row(
                [
                    self._stamp(event),
                    "birak",
                    press.text,
                    detay,
                    f"{press.ms:.0f} ms -> {press.kind.label}",
                    durum,
                ],
                swallowed,
            )

    # ---- istatistik ----

    def _update_stats(self) -> None:
        p50 = p99 = 0.0
        if self.latencies:
            ordered = sorted(self.latencies[-2000:])
            p50 = ordered[len(ordered) // 2]
            p99 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]
        self.stats_label.setText(
            f"klavye {self.counters['klavye']:<6} fare {self.counters['fare']:<6} "
            f"yutulan {self.counters['yutulan']:<6} dusen {self.hook.dropped:<4}   |   "
            f"en uzun hook callback {self.hook.max_callback_ms:6.3f} ms (sinir 300)   "
            f"gecikme p50 {p50:5.2f} / p99 {p99:5.2f} ms"
        )

    # ---- birim testleri ----

    def _run_tests(self) -> None:
        self.run_tests_btn.setEnabled(False)
        self.test_output.setPlainText("pytest calisiyor...\n\n")
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._test_output_ready)
        self.proc.finished.connect(lambda *_: self.run_tests_btn.setEnabled(True))
        self.proc.start(sys.executable, ["-m", "pytest", "-v", "--color=no", "tests"])

    def _test_output_ready(self) -> None:
        chunk = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        cursor = self.test_output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.test_output.setTextCursor(cursor)
        self.test_output.insertPlainText(chunk)

    def closeEvent(self, event) -> None:
        self.drain.stop()
        self.ticker.stop()
        self.hook.stop()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = Monitor()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
