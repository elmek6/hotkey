"""Profil yoneticisi -- `app_shorts.ahk` `showManagerGui()` portu.

Duzen AHK ile ayni, uc kolon:

    Profiller          | Aksiyonlar      | Aksiyon detayi
    ad / sinif / baslik| (yukari/asagi)  | ad / aciklama / tuslar
    Yeni Guncelle Sil  |                 | Yeni Guncelle Sil

AHK'DEN AYRILAN YERLER:

  * `Record Macro` dugmesi YOK. `macro_recorder.ahk` port edilmedi; calisan
    bir butona benzeyip hicbir sey yapmayan dugme koymaktansa hic koymuyoruz.
  * Liste secimi ADLA degil KONUMLA eslenmiyor, `UserRole`da profilin
    konumu duruyor. AHK'de listeye 'Sort' konulmamasinin sebebi tam da
    buydu (kod icinde yazili): sirali gorunum index'i kaydirip yanlis
    profili sectiriyordu. Konumu veriyle tasiyinca sorun kokten kalkiyor.
  * Kaydetme ANINDA diske yaziyor -- AHK'de de oyleydi ("Çalışırken kaydet").

`AppProfile` ve `ShortCut` dondurulmus (frozen) veri siniflari: duzenleme
yerinde degistirerek degil `replace` ile YENISINI kurarak yapiliyor. Bu,
"yarim guncellenmis profil" diye bir ara durumun olusmamasini garanti eder.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from cascade import theme
from cascade.app_shorts import AppProfile, ShortCut, ShortcutStore, stroke_kind
from cascade.ui.place import center_on_cursor_screen

YENI = -1


class ProfilesView(QWidget):
    """Tek ornek: app.py saklayip yeniden gosteriyor."""

    def __init__(self, store: ShortcutStore) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("\U0001f9e9 Profiller ve Kisayollar")
        self.store = store
        self._profile_index = YENI
        self._action_index = YENI

        # ---- 1. kolon: profiller ----
        self.profile_list = QListWidget()
        self.profile_list.currentItemChanged.connect(lambda *_: self._on_profile())
        self.name_edit = QLineEdit()
        self.class_edit = QLineEdit()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("baslikta GECEN bir parca")

        profile_form = QGridLayout()
        for row, (label, widget) in enumerate(
            (
                ("Profil adi", self.name_edit),
                ("Pencere sinifi", self.class_edit),
                ("Baslik (parca)", self.title_edit),
            )
        ):
            profile_form.addWidget(QLabel(label), row, 0)
            profile_form.addWidget(widget, row, 1)
        profile_form.setColumnStretch(1, 1)

        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        left_box.addWidget(QLabel("Profiller"))
        left_box.addWidget(self.profile_list, 1)
        left_box.addLayout(profile_form)
        left_box.addLayout(
            self._buttons(
                ("➕ Yeni", self.new_profile),
                ("\U0001f4be Kaydet", self.save_profile),
                ("\U0001f5d1️ Sil", self.delete_profile),
            )
        )
        # AHK'de bu bilgi yoktu; eslesme kurali gorunmezdi ve "neden bu
        # profil acilmiyor" sorusunun cevabi ancak koda bakinca bulunuyordu.
        self.rule = QLabel("")
        self.rule.setWordWrap(True)
        theme.muted(self.rule)
        left_box.addWidget(self.rule)

        # ---- 2. kolon: aksiyonlar ----
        self.action_list = QListWidget()
        self.action_list.currentItemChanged.connect(lambda *_: self._on_action())
        middle = QWidget()
        middle_box = QVBoxLayout(middle)
        middle_box.setContentsMargins(0, 0, 0, 0)
        middle_box.addWidget(QLabel("Aksiyonlar"))
        middle_box.addWidget(self.action_list, 1)
        middle_box.addLayout(
            self._buttons(("▲ Yukari", lambda: self.move_action(-1)),
                          ("▼ Asagi", lambda: self.move_action(1)))
        )

        # ---- 3. kolon: aksiyon detayi ----
        self.action_name = QLineEdit()
        self.action_desc = QLineEdit()
        self.strokes_edit = QPlainTextEdit()
        self.strokes_edit.setPlaceholderText("her satir bir tus dizisi:\n^+t\nmerhaba")

        action_form = QGridLayout()
        for row, (label, widget) in enumerate(
            (("Aksiyon adi", self.action_name), ("Aciklama", self.action_desc))
        ):
            action_form.addWidget(QLabel(label), row, 0)
            action_form.addWidget(widget, row, 1)
        action_form.setColumnStretch(1, 1)

        right = QWidget()
        right_box = QVBoxLayout(right)
        right_box.setContentsMargins(0, 0, 0, 0)
        right_box.addLayout(action_form)
        right_box.addWidget(QLabel("Tus dizileri (her satir bir tane)"))
        right_box.addWidget(self.strokes_edit, 1)
        # Hangi satirin kisayol hangisinin duz metin sayildigi EKRANDA
        # gorunsun: `abc` ile `^+t` arasindaki fark dosyada gorunmuyordu ve
        # "neden harfleri tek tek yaziyor" sorusuna sebep oluyordu.
        self.stroke_hint = QLabel("")
        self.stroke_hint.setWordWrap(True)
        theme.muted(self.stroke_hint)
        self.strokes_edit.textChanged.connect(self._update_stroke_hint)
        right_box.addWidget(self.stroke_hint)
        right_box.addLayout(
            self._buttons(
                ("➕ Yeni", self.new_action),
                ("\U0001f4be Kaydet", self.save_action),
                ("\U0001f5d1️ Sil", self.delete_action),
            )
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)
        for widget in (left, middle, right):
            splitter.addWidget(widget)
        splitter.setSizes([330, 250, 400])
        splitter.setStretchFactor(2, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        self.status = QLabel("")
        theme.muted(self.status)
        layout.addWidget(self.status)
        self.resize(1000, 600)

    @staticmethod
    def _buttons(*pairs) -> QHBoxLayout:
        box = QHBoxLayout()
        for label, slot in pairs:
            button = QPushButton(label)
            button.clicked.connect(slot)
            box.addWidget(button)
        box.addStretch(1)
        return box

    # ---- disari ----

    def open(self, profile_name: str = "") -> None:
        """AHK `showManagerGui(selectedProfile)`: verilen profil secili acilir.

        Ad verilmezse (ya da bulunamazsa) ilk profil secilir -- AHK burada
        hicbir seyi secmiyordu ve pencere bos aciliyordu.
        """
        self.store.load()
        self._fill_profiles()
        if profile_name:
            self._select_profile_named(profile_name)
        elif self.profile_list.count():
            self.profile_list.setCurrentRow(0)
        center_on_cursor_screen(self)
        self.show()
        self.raise_()
        self.activateWindow()

    # ---- profil listesi ----

    def _fill_profiles(self) -> None:
        keep = self._profile_index
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for index, profile in enumerate(self.store.profiles):
            row = QListWidgetItem(profile.name or "(adsiz)")
            row.setData(Qt.ItemDataRole.UserRole, index)
            self.profile_list.addItem(row)
        self.profile_list.blockSignals(False)
        if 0 <= keep < self.profile_list.count():
            self.profile_list.setCurrentRow(keep)
        self.status.setText(
            f"{len(self.store.profiles)} profil, "
            f"{sum(len(p.shortcuts) for p in self.store.profiles)} aksiyon"
        )

    def _select_profile_named(self, name: str) -> None:
        for index, profile in enumerate(self.store.profiles):
            if profile.name == name:
                self.profile_list.setCurrentRow(index)
                return

    def _current_profile(self) -> AppProfile | None:
        if 0 <= self._profile_index < len(self.store.profiles):
            return self.store.profiles[self._profile_index]
        return None

    def _on_profile(self) -> None:
        row = self.profile_list.currentItem()
        self._profile_index = (
            row.data(Qt.ItemDataRole.UserRole) if row is not None else YENI
        )
        profile = self._current_profile()
        if profile is None:
            return
        self.name_edit.setText(profile.name)
        self.class_edit.setText(profile.class_name)
        self.title_edit.setText(profile.title)
        self._update_rule()
        self._fill_actions()
        self.new_action()

    def _update_rule(self) -> None:
        """Eslesme kuralini duz Turkce yazar (app_shorts.AppProfile.matches)."""
        class_name = self.class_edit.text().strip()
        title = self.title_edit.text().strip()
        parts = []
        if class_name:
            parts.append(f"sinifi TAM olarak `{class_name}`")
        if title:
            parts.append(f"basliginda `{title}` GECEN")
        if not parts:
            self.rule.setText(
                "⚠️ Sinif da baslik da bos: bu profil HER pencereye uyar ve "
                "listede kendinden sonrakileri golgeler."
            )
            return
        self.rule.setText("Eslesme: " + " ve ".join(parts) + " pencere.")

    def new_profile(self) -> None:
        """AHK `_newProfile`: alanlari bosaltir, kayit `Kaydet`te olusur."""
        self._profile_index = YENI
        self.profile_list.setCurrentRow(-1)
        for widget in (self.name_edit, self.class_edit, self.title_edit):
            widget.clear()
        self.action_list.clear()
        self.new_action()
        self._update_rule()
        self.name_edit.setFocus()

    def save_profile(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Profiller", "Profil adi zorunlu.")
            self.name_edit.setFocus()
            return
        class_name = self.class_edit.text().strip()
        title = self.title_edit.text().strip()
        profile = self._current_profile()
        if profile is None:
            self.store.profiles.append(
                AppProfile(name=name, class_name=class_name, title=title)
            )
            self._profile_index = len(self.store.profiles) - 1
        else:
            self.store.profiles[self._profile_index] = replace(
                profile, name=name, class_name=class_name, title=title
            )
        self._update_rule()
        self._write()

    def delete_profile(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        if not self._confirm(f"Profil silinsin mi?\n\n{profile.name}"):
            return
        del self.store.profiles[self._profile_index]
        self._profile_index = YENI
        self._write()
        self.new_profile()

    # ---- aksiyonlar ----

    def _fill_actions(self) -> None:
        profile = self._current_profile()
        self.action_list.blockSignals(True)
        self.action_list.clear()
        if profile is not None:
            for shortcut in profile.shortcuts:
                self.action_list.addItem(shortcut.name or "(adsiz)")
        self.action_list.blockSignals(False)

    def _on_action(self) -> None:
        profile = self._current_profile()
        self._action_index = self.action_list.currentRow()
        if profile is None or not 0 <= self._action_index < len(profile.shortcuts):
            return
        shortcut = profile.shortcuts[self._action_index]
        self.action_name.setText(shortcut.name)
        self.action_desc.setText(shortcut.description)
        self.strokes_edit.setPlainText("\n".join(shortcut.strokes))

    def new_action(self) -> None:
        self._action_index = YENI
        self.action_list.setCurrentRow(-1)
        self.action_name.clear()
        self.action_desc.clear()
        self.strokes_edit.clear()

    def _read_strokes(self) -> tuple[str, ...]:
        """AHK `StrSplit(... , "\\n", "\\r")` + bos satir eleme."""
        return tuple(
            line.strip()
            for line in self.strokes_edit.toPlainText().split("\n")
            if line.strip()
        )

    def _update_stroke_hint(self) -> None:
        strokes = self._read_strokes()
        if not strokes:
            self.stroke_hint.setText("")
            return
        parts = [
            f"`{stroke}` → {'kisayol' if stroke_kind(stroke) == 'key' else 'duz metin'}"
            for stroke in strokes
        ]
        self.stroke_hint.setText("  ·  ".join(parts))

    def save_action(self) -> None:
        profile = self._current_profile()
        if profile is None:
            QMessageBox.warning(self, "Profiller", "Once profil sec ya da kaydet.")
            return
        name = self.action_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Profiller", "Aksiyon adi zorunlu.")
            self.action_name.setFocus()
            return
        shortcut = ShortCut(
            name=name, description=self.action_desc.text().strip(), strokes=self._read_strokes()
        )
        shortcuts = list(profile.shortcuts)
        if 0 <= self._action_index < len(shortcuts):
            shortcuts[self._action_index] = shortcut
        else:
            shortcuts.append(shortcut)
            self._action_index = len(shortcuts) - 1
        self.store.profiles[self._profile_index] = replace(
            profile, shortcuts=tuple(shortcuts)
        )
        self._write()
        self._fill_actions()
        self.action_list.setCurrentRow(self._action_index)

    def delete_action(self) -> None:
        profile = self._current_profile()
        if profile is None or not 0 <= self._action_index < len(profile.shortcuts):
            return
        shortcut = profile.shortcuts[self._action_index]
        if not self._confirm(f"Aksiyon silinsin mi?\n\n{shortcut.name}"):
            return
        shortcuts = list(profile.shortcuts)
        del shortcuts[self._action_index]
        self.store.profiles[self._profile_index] = replace(
            profile, shortcuts=tuple(shortcuts)
        )
        self._action_index = YENI
        self._write()
        self._fill_actions()
        self.new_action()

    def move_action(self, delta: int) -> None:
        """AHK `_moveAction`: sira F13 menusundeki siradir, onemli."""
        profile = self._current_profile()
        if profile is None:
            return
        source = self._action_index
        target = source + delta
        if not (0 <= source < len(profile.shortcuts) and 0 <= target < len(profile.shortcuts)):
            return
        shortcuts = list(profile.shortcuts)
        shortcuts[source], shortcuts[target] = shortcuts[target], shortcuts[source]
        self.store.profiles[self._profile_index] = replace(
            profile, shortcuts=tuple(shortcuts)
        )
        self._action_index = target
        self._write()
        self._fill_actions()
        self.action_list.setCurrentRow(target)

    # ---- ortak ----

    def _confirm(self, question: str) -> bool:
        return (
            QMessageBox.question(
                self,
                "Profiller",
                question,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def _write(self) -> None:
        if not self.store.save():
            QMessageBox.critical(self, "Profiller", "profiles.json yazilamadi -- log'a bak.")
            return
        self._fill_profiles()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
