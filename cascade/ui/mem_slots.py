"""Hafiza slotlari -- AHK'deki `Lib/memory_slots.ahk` (singleMemorySlot).

On tane elle doldurulan slot ve panonun son on kaydi yan yana. Pencere
acikken pano MOD DEGISTIRIR (ClipboardMode.MEM_SLOTS): kopyalanan sey
gecmise degil ilk bos slota duser. Kapaninca eski mod geri gelir.

AHK'den birebir gelenler:

    * on slot, ilk bos slota otomatik doldurma, dolunca basa donme
    * "veri tekrarini kabul et" kutusu (`ignoreSameValue`)
    * iki liste ve aralarinda gezinen "aktif liste" kavrami; baslik seridi
      hangisinin aktif oldugunu renkle soyler
    * baslik seridine tiklayinca listeyi TERS cevirme
    * cift tiklama: slot listesinde panoya kopyalar, gecmiste yapistirir
    * akilli yapistirma (`smartPaste`): orta fare tusu / `Insert` ile
      yapistirir ve siradaki kayda gecer ("Orta tus" kutusu ile kapanir);
      tus kombosuyla gelindiginde secim yerinde kalir -- AHK ile ayni ayrim
    * satiri disari surukleyip birakma (`OleDragSource`): tabloda kisaltilmis
      onizleme yazar, surukleme TAM icerigi tasir
    * sifre slotu: 10. slot ("Slot 0") listede ve menude maskeli gorunur,
      yapistirmasi normal calisir

AHK'den AYRILAN iki yer, ikisi de mimari yuzunden:

1. **Basim turleri.** AHK `detectPressType` ile BLOKE EDEREK kisa/uzun/cift
   basimi ayiriyordu. Bizde bloke eden dongu yok; kisa/orta/uzun zaten
   CascadeMachine'de var ve F1..F10 oraya calisma aninda ekleniyor
   (keymap.py `memslots_defs`). Cift basim yerine UZUN basim kullaniliyor:

        kisa  -> slotu yapistir      orta -> gecmisi yapistir
        uzun  -> panoyu o slota kaydet

2. **Panoyu okuma.** AHK `SendInput("^c")` sonrasi `ClipWait` ile bloke
   okuyordu. Burada pano dinleyicisi asenkron (ui/clipboard.py): `^c`
   gonderilir, gelen ILK metin bekleyen slota yazilir (`_pending_slot`).

Slotlarin kendisi `Files/slots.json` icinde yasiyor (store.SlotStore,
clip_slot.ahk bicimi): memory_slots.ahk her acilista sifirdan basliyordu,
biz kalici tutuyoruz.

Pencere panoyu kendisi yazmaz, sinyal gonderir -- ArrayFilter'daki kural.

Port EDILMEYENLER:

TODO(AHK): clip_slot.ahk `showSlotsSearch` -- butun gruplarin dolu
    slotlarinda arama. Grup yonetiminin geri kalani portlandi: yan grup
    secimi, grup ekle/sil ve "slota kaydet" F14 menusunde (app.py
    `_side_slot_menu`), slot adi bu penceredeki "Ad" sutununda.

Bu pencere HANGI grubu gosterir: secili yan grubu (`SlotStore.
default_group`) -- AHK'de de kaskad slotlari `defaultGroupName` uzerinden
yukleniyordu.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QMimeData, Qt, Signal
from PySide6.QtGui import QDrag, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cascade.store import PASSWORD_SLOT, slot_display

SLOT_COUNT = 10  # AHK: Loop 10
PREVIEW_LIMIT = 60  # AHK: _makePreview -> SubStr(preview, 1, 60)

ACTIVE_SLOTS_BG = "#2196f3"  # AHK: Background0x2196F3
ACTIVE_HIST_BG = "#4caf50"  # AHK: Background0x4CAF50
IDLE_BG = "#808080"


class DragTable(QTableWidget):
    """Satiri disari surukleyebilen tablo -- AHK `OleDragSource.attachListView`.

    Tabloda KISALTILMIS onizleme yaziyor; surukleyip birakilan sey ise
    slotun TAM icerigi olmali (AHK'de de oyleydi: `(row) => this.slots[row]`).
    O yuzden mime verisi satir numarasindan uretiliyor, hucre metninden
    degil. Sifre slotunda maske yaziyor -- surukleme gercek parolayi
    tasir, ekranda gorunmez.
    """

    def __init__(self, columns: int, text_for_row) -> None:
        super().__init__(0, columns)
        self._text_for_row = text_for_row
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def startDrag(self, actions) -> None:
        """Suruklemeyi BASTAN KURAR -- yalniz `text/plain` tasinir.

        Qt'nin kendi suruklemesi model verisini de
        (`application/x-qabstractitemmodeldatalist`) ve secili HUCRELERIN
        metnini koyuyor; hedef uygulama onu alinca satirin tamami
        (slot no + ad + onizleme, sekmeli) dusuyordu. `mimeData()`
        gecersiz kilmak yetmiyor cunku surukleme MODELDEN baslıyor.
        Notepad'den metin surukler gibi tek bir metin birakilmali.
        """
        rows = {index.row() for index in self.selectedIndexes()}
        if not rows:
            return
        text = self._text_for_row(min(rows) + 1)
        if not text:
            return
        data = QMimeData()
        data.setText(text)
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.exec(Qt.DropAction.CopyAction)


def preview(text: str, limit: int = PREVIEW_LIMIT) -> str:
    """AHK: _makePreview -- satir sonlari bosluga iner, uzunsa kirpilir."""
    flat = " ".join(text.split())
    if not flat:
        return "(Bos)"
    return flat if len(flat) <= limit else flat[: limit - 1] + "..."


class MemSlots(QWidget):
    """Slot penceresi."""

    #: panoya yaz ve Ctrl+V gonder
    #: (metin, gizli mi) -- gizli olan sifre slotudur: pano gecmisine
    #: (bizimkine de Windows'unkine de) yazilmaz.
    paste_text = Signal(str, bool)
    #: panoya yaz, yapistirma
    #: (metin, gizli mi) -- sifre slotu panoya GIZLI konur.
    copy_text = Signal(str, bool)
    #: (slot no, yeni ad) -- ad penceredeyken degistirildi (AHK setName)
    name_changed = Signal(int, str)
    #: hedef uygulamadan Ctrl+C iste (secili metni slota alacagiz)
    grab_clip = Signal()
    #: kisa ipucu (HTML)
    tip = Signal(str)
    #: F1..F10 kisayollari acildi / kapandi
    fkeys_toggled = Signal(bool)
    closed = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowTitle("\U0001f9fe Hafiza Slotlari")

        self.slots: list[str] = [""] * SLOT_COUNT
        #: slot adlari -- clip_slot.ahk `values[i]["name"]`. Dosyadan gelir,
        #: "Ad" sutunundan duzenlenir, dosyaya geri yazilir (AHK: setName).
        self.names: list[str] = [f"Slot {index}" for index in range(1, SLOT_COUNT + 1)]
        self.history: list[str] = []
        self.slot_index = 1  # 1 tabanli, AHK ile ayni
        self.hist_index = 1
        self._slots_active = False  # AHK: activeList -- acilista gecmis aktif
        # Bir kez bile acildi mi. Kapanista slotlari diske yazan taraf buna
        # bakiyor: hic acilmadiysa elimizde BOS varsayilan slotlar var ve
        # onlari dosyaya yazmak kullanicinin slotlarini silerdi.
        self.opened = False
        self._pending_slot: int | None = None  # `^c` bekleyen slot
        self._loading = False  # tabloyu programla doldururken sinyal yutulur

        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)

        # AHK: fKeysEnabled -- default KAPALI. F1..F10 sistem geneli
        # kisayollar; kullanici istemeden ele gecirmiyoruz.
        self.fkeys = QCheckBox("F1-F10:  kisa=slot  orta=gecmis  uzun=kaydet")
        self.fkeys.toggled.connect(self._on_fkeys)

        self.allow_repeat = QCheckBox("Veri tekrarini kabul et")

        # AHK: middlePasteCheck -- varsayilan ACIK. Orta fare tusu (ve
        # Insert) aktif kayitti yapistirir, sonra siradakine gecer.
        self.middle_paste = QCheckBox("Orta tus / Insert: aktif kaydi yapistir")
        self.middle_paste.setChecked(True)

        clear_button = QPushButton("\U0001f5d1️ Slotlari temizle")
        clear_button.clicked.connect(self.clear_slots)

        self.slots_header = QLabel("\U0001f986 Hafiza slotlari")
        self.hist_header = QLabel("\U0001f4cb Pano gecmisi")
        for header in (self.slots_header, self.hist_header):
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.setCursor(Qt.CursorShape.PointingHandCursor)
            header.installEventFilter(self)

        # Slot tablosunda UC sutun: AHK slotlarin ADINI da tutuyor
        # (clip_slot.ahk "Slot 1" / "fan ow" gibi), o ad dosyada duruyor ve
        # burada gorunmezse kullanici neyin ne oldugunu bilemez.
        self.slot_table = self._make_table(("Slot", "Ad", "Icerik"), mono, self._slot)
        self.slot_table.itemSelectionChanged.connect(self._on_slot_selected)
        self.slot_table.doubleClicked.connect(lambda _index: self._slot_double())
        # AHK `setName`: slot adi duzenlenebilir. YALNIZ "Ad" sutunu --
        # icerik sutunu elle yazilirsa slot ile listedeki metin ayrisirdi
        # (listede kisaltilmis onizleme var, tam icerik degil).
        self.slot_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.slot_table.itemChanged.connect(self._on_slot_item_changed)
        self.slot_table.setRowCount(SLOT_COUNT)
        for row in range(SLOT_COUNT):
            self.slot_table.setItem(row, 0, QTableWidgetItem(f"F{row + 1:02}"))
            name_item = QTableWidgetItem(f"Slot {row + 1}")
            name_item.setToolTip("Cift tiklayarak adini degistir")
            self.slot_table.setItem(row, 1, name_item)
            content_item = QTableWidgetItem("")
            content_item.setFlags(content_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.slot_table.setItem(row, 2, content_item)
            self.slot_table.item(row, 0).setFlags(
                self.slot_table.item(row, 0).flags() & ~Qt.ItemFlag.ItemIsEditable
            )

        self.hist_table = self._make_table(("#", "Icerik"), mono, self._history_text)
        self.hist_table.itemSelectionChanged.connect(self._on_hist_selected)
        self.hist_table.doubleClicked.connect(lambda _index: self._hist_double())

        top = QHBoxLayout()
        top.addWidget(self.fkeys, 1)
        top.addWidget(self.allow_repeat)
        top.addWidget(self.middle_paste)
        top.addWidget(clear_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.slots_header)
        layout.addWidget(self.slot_table, 1)
        layout.addWidget(self.hist_header)
        layout.addWidget(self.hist_table, 1)

        self.resize(560, 680)
        self._paint_headers()

    def _make_table(self, columns: tuple[str, ...], font: QFont, text_for_row) -> QTableWidget:
        table = DragTable(len(columns), text_for_row)
        table.setHorizontalHeaderLabels(list(columns))
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setFont(font)
        header = table.horizontalHeader()
        for index in range(len(columns) - 1):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(index, 56 if index == 0 else 110)
        header.setSectionResizeMode(len(columns) - 1, QHeaderView.ResizeMode.Stretch)
        return table

    # ---- disari ----

    def load_slots(self, values: list[tuple[str, str]]) -> None:
        """Diskten gelen (ad, icerik) ciftleri -- store.SlotStore.

        AHK'de slotlar `slots.json` icinde yasiyordu ve oturumlar arasi
        kaliciydi; memory_slots.ahk ise her acilista sifirdan basliyordu.
        Ikisini birlestiriyoruz: pencere ayni, icerik kalici.
        """
        self._loading = True
        try:
            for index in range(SLOT_COUNT):
                name, content = values[index] if index < len(values) else ("", "")
                self.names[index] = name or f"Slot {index + 1}"
                self.slots[index] = content
                self.slot_table.item(index, 1).setText(self.names[index])
                self.slot_table.item(index, 2).setText(
                    slot_display(index + 1, content, preview)
                )
        finally:
            self._loading = False

    def slot_values(self) -> list[tuple[str, str]]:
        """Diske yazilacak (ad, icerik) ciftleri."""
        return list(zip(self.names, self.slots, strict=True))

    def start(self, history: tuple[str, ...] | list[str]) -> None:
        """AHK: start(). Gecmisin ilk on kaydiyla acilir."""
        self.opened = True
        self.history = list(history)[:SLOT_COUNT]
        self._fill_history()
        self.select_history(1)
        self.show()
        self.raise_()
        self.activateWindow()

    def on_clip(self, text: str) -> None:
        """Pano degisti (mod MEM_SLOTS iken app.py buraya verir).

        AHK: clipboardWatcher + _autoFillSlot. `^c` ile biz istediysek
        bekleyen slota, degilse ilk bos slota yazilir.
        """
        if not text:
            return
        pending, self._pending_slot = self._pending_slot, None
        if pending is not None:
            self._write_slot(pending, text)
            self.select_slot(pending)
            self.tip.emit(f"\U0001f4be <b>Slot {pending}</b> kaydedildi")
            return
        if not self.allow_repeat.isChecked() and text in self.slots:
            return  # AHK: _isClipInSlots
        index = self._first_free()  # AHK: dolunca basa doner, ustune yazar
        self._write_slot(index, text)
        self.select_slot(index)

    # ---- F1..F10 eylemleri (app.py cagirir) ----

    def paste_slot(self, index: int) -> None:
        """Kisa basim. AHK: pasteFromSlot."""
        text = self._slot(index)
        if not text:
            self.tip.emit(f"⚠️ <b>Slot {index}</b> bos")
            return
        self.select_slot(index)
        self.paste_text.emit(text, index == PASSWORD_SLOT)

    def paste_history(self, index: int) -> None:
        """Orta basim. AHK: _pasteFromHistory."""
        if not 1 <= index <= len(self.history):
            self.tip.emit(f"⚠️ <b>Gecmis {index}</b> yok")
            return
        self.select_history(index)
        self.paste_text.emit(self.history[index - 1], False)

    def save_slot(self, index: int) -> None:
        """Uzun basim (AHK'de cift basim). Once `^c`, gelen metin slota."""
        if not 1 <= index <= SLOT_COUNT:
            return
        self._pending_slot = index
        self.grab_clip.emit()

    def smart_paste(self, middle: bool = False) -> None:
        """AHK: smartPaste(middlePressed) -- aktif listeden yapistir.

        Ayrim AHK'den birebir: ORTA TUS ile gelindiyse yapistirdiktan sonra
        siradaki kayda gecilir (arka arkaya basmak listeyi gezdirir); tus
        kombosuyla gelindiyse yalnizca yapistirir, secim yerinde kalir.
        Pencere kapaliyken hicbir sey olmaz -- orta tus her yerde calisan
        bir tus, yalniz bu pencere acikken anlam kazanir.
        """
        if not self.isVisible():
            return
        if middle and not self.middle_paste.isChecked():
            return
        if self._slots_active:
            self.paste_slot(self.slot_index)
            if middle:
                self.select_slot(self._next(self.slot_index, self._used_slots()))
        else:
            self.paste_history(self.hist_index)
            if middle:
                self.select_history(self._next(self.hist_index, len(self.history)))

    def clear_slots(self) -> None:
        """AHK: _clearSlots"""
        self.slots = [""] * SLOT_COUNT
        for row in range(SLOT_COUNT):
            self.slot_table.item(row, 2).setText("")
        self.select_slot(1)

    # ---- ic yardimcilar ----

    def _history_text(self, row: int) -> str:
        """Surukleme icin gecmis satirinin TAM metni (1 tabanli)."""
        return self.history[row - 1] if 1 <= row <= len(self.history) else ""

    def _slot(self, index: int) -> str:
        return self.slots[index - 1] if 1 <= index <= SLOT_COUNT else ""

    def _used_slots(self) -> int:
        """AHK: slotsLength -- sondan geriye dogru ilk dolu slot."""
        count = SLOT_COUNT
        while count >= 1 and not self.slots[count - 1]:
            count -= 1
        return count

    def _first_free(self) -> int:
        used = self._used_slots()
        return used + 1 if used < SLOT_COUNT else 1

    @staticmethod
    def _next(index: int, limit: int) -> int:
        return index + 1 if index < limit else 1

    def _write_slot(self, index: int, text: str) -> None:
        self.slots[index - 1] = text
        self._loading = True
        try:
            self.slot_table.item(index - 1, 2).setText(slot_display(index, text, preview))
        finally:
            self._loading = False

    def _fill_history(self) -> None:
        """AHK: _populateHistory"""
        self.hist_table.setRowCount(len(self.history))
        for row, text in enumerate(self.history):
            self.hist_table.setItem(row, 0, QTableWidgetItem(f"F{row + 1:02}"))
            self.hist_table.setItem(row, 1, QTableWidgetItem(preview(text)))

    def select_slot(self, index: int) -> None:
        """AHK: _selectSlotViewer"""
        self.slot_index = max(1, min(index, SLOT_COUNT))
        self._slots_active = True
        self.slot_table.selectRow(self.slot_index - 1)
        self.hist_table.clearSelection()
        self._paint_headers()

    def select_history(self, index: int) -> None:
        """AHK: _selectHistoryViewer"""
        if not self.history:
            return
        self.hist_index = max(1, min(index, len(self.history)))
        self._slots_active = False
        self.hist_table.selectRow(self.hist_index - 1)
        self.slot_table.clearSelection()
        self._paint_headers()

    def _paint_headers(self) -> None:
        """AHK: _activeViewerBackground -- aktif liste renkli."""
        style = "color: white; font-weight: bold; padding: 4px; background: %s;"
        self.slots_header.setStyleSheet(
            style % (ACTIVE_SLOTS_BG if self._slots_active else IDLE_BG)
        )
        self.hist_header.setStyleSheet(
            style % (IDLE_BG if self._slots_active else ACTIVE_HIST_BG)
        )

    def _reverse_slots(self) -> None:
        """AHK: _reverseSlotsOrder -- yalniz dolu kisim ters cevrilir."""
        used = self._used_slots()
        self.slots[:used] = list(reversed(self.slots[:used]))
        self.names[:used] = list(reversed(self.names[:used]))  # ad icerikle gitsin
        for index in range(1, SLOT_COUNT + 1):
            self._write_slot(index, self.slots[index - 1])
            self._loading = True
            try:
                self.slot_table.item(index - 1, 1).setText(self.names[index - 1])
            finally:
                self._loading = False
        self.select_slot(1)

    def _reverse_history(self) -> None:
        """AHK: _reverseHistoryOrder"""
        self.history.reverse()
        self._fill_history()
        self.select_history(1)

    # ---- olaylar ----

    def _on_fkeys(self, checked: bool) -> None:
        self.fkeys_toggled.emit(checked)
        self.tip.emit("\U0001f539 <b>F1-F10</b> " + ("acik" if checked else "kapali"))

    def _on_slot_selected(self) -> None:
        row = self.slot_table.currentRow()
        if row >= 0 and self.slot_table.selectedItems():
            self.slot_index = row + 1
            self._slots_active = True
            self._paint_headers()

    def _on_hist_selected(self) -> None:
        row = self.hist_table.currentRow()
        if row >= 0 and self.hist_table.selectedItems():
            self.hist_index = row + 1
            self._slots_active = False
            self._paint_headers()

    def _on_slot_item_changed(self, item) -> None:
        """Ad sutunu duzenlendi: adi bellege al (diske kapanista yazilir).

        Yukleme sirasinda da tetikleniyor; `load_slots` bayragi ile ayirt
        ediliyor, yoksa dosyadan gelen ad kendini yeniden yazardi.
        """
        if self._loading or item.column() != 1:
            return
        row = item.row()
        self.names[row] = item.text().strip() or f"Slot {row + 1}"
        self.name_changed.emit(row + 1, self.names[row])

    def _slot_double(self) -> None:
        """AHK: _onSlotDoubleClick -- panoya kopyalar, yapistirmaz."""
        if self.slot_table.currentColumn() == 1:
            return  # ad sutunu: cift tiklama DUZENLEMEYE giriyor
        index = self.slot_table.currentRow() + 1
        text = self._slot(index)
        if not text:
            return
        # Sifre slotunda ipucu icerigi GOSTERMEZ.
        secret = index == PASSWORD_SLOT
        self.copy_text.emit(text, secret)
        self.tip.emit(
            "\U0001f4cb kopyalandi" if secret else f"\U0001f4cb {preview(text, 40)}"
        )

    def _hist_double(self) -> None:
        """AHK: _onHistoryDoubleClick -- dogrudan yapistirir."""
        row = self.hist_table.currentRow()
        if 0 <= row < len(self.history):
            self.select_history(row + 1)
            self.paste_text.emit(self.history[row], False)

    def eventFilter(self, watched, event: QEvent) -> bool:
        """Baslik seridine tiklama: aktif degilse aktif yapar, aktifse listeyi
        TERS cevirir. AHK'de de ayni cift islevli tiklama vardi."""
        if event.type() == QEvent.Type.MouseButtonPress:
            if watched is self.slots_header:
                if self._slots_active:
                    self._reverse_slots()
                else:
                    self.select_slot(self.slot_index)
                return True
            if watched is self.hist_header:
                if self._slots_active:
                    self.select_history(self.hist_index)
                else:
                    self._reverse_history()
                return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event) -> None:
        """AHK: _destroy -- F tuslari birakilir, pano modu geri alinir
        (modu app.py `closed` sinyalinde geri aliyor)."""
        if self.fkeys.isChecked():
            self.fkeys.setChecked(False)  # fkeys_toggled(False) yayar
        super().closeEvent(event)
        self.closed.emit()
