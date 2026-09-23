"""Ekran koruyucu zamanlayicisi -- kalan sure + dakika girisi."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from keypilot.idle import clock_label
from keypilot.ui.place import center_on_cursor_screen


class IdleDialog(QWidget):
    accepted_minutes = Signal(int)

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowTitle("Zamanlayici")
        self._minutes = 0

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self._label = QLabel(self)
        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("dakika")
        self._edit.setFixedWidth(72)
        self._edit.textChanged.connect(self._on_typed)
        self._edit.returnPressed.connect(self._accept)
        row.addWidget(self._label)
        row.addWidget(self._edit)
        layout.addLayout(row)
        ok = QPushButton("Tamam", self)
        ok.clicked.connect(self._accept)
        layout.addWidget(ok)

    def show_for(self, remaining_minutes: int) -> None:
        self._minutes = max(0, int(remaining_minutes))
        self._edit.blockSignals(True)
        self._edit.clear()
        self._edit.blockSignals(False)
        self._refresh()
        self.adjustSize()
        self.show()
        center_on_cursor_screen(self)
        self.raise_()
        self.activateWindow()
        self._edit.setFocus()

    def _on_typed(self, text: str) -> None:
        raw = text.strip()
        if not raw:
            self._refresh()
            return
        if not raw.isdigit():
            return
        self._minutes = int(raw)
        self._refresh()

    def _refresh(self) -> None:
        self._label.setText(f"Kalan zaman ({clock_label(self._minutes)})")

    def _accept(self) -> None:
        raw = self._edit.text().strip()
        if raw.isdigit():
            self._minutes = int(raw)
        elif not raw:
            pass
        self.accepted_minutes.emit(self._minutes)
        self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
