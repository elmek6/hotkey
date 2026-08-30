"""Pano dinleyicisi -- clip_hist.ahk'nin `clipboardWatcher` bolumu.

AHK'de dinleme `OnClipboardChange(...)` ile kuruluyordu; Windows tarafinda
karsiligi `AddClipboardFormatListener` + `WM_CLIPBOARDUPDATE`. Qt bunu zaten
kuruyor ve `QClipboard.dataChanged` olarak veriyor, uzerine bir de mesaj
penceresi acmanin anlami yok. Yani ctypes'a dusen tek is, Qt'de karsiligi
olmayan `GetClipboardSequenceNumber`.

AHK'den aynen tasinan iki ders:

1. **Bildirimin ICINDE panoyu okuma.** Okuyunca pano kilidi bizde olur;
   ayni bildirimi alan Windows pano gecmisi servisi (cbdhsvc) panoyu acamaz
   ve TEKRAR DENEMEDEN vazgecer -- kopyalanan sey Win+V'ye dusmez. Bunun
   "yakaladim" sinyali olmadigi icin tek care okumayi kisa sure ertelemek.
   AHK'de `SetTimer(..., -100)` idi, burada tek atislik QTimer.

2. **Tazelik kontrolu.** Beklerken pano tekrar degistiyse bu cagri bayattir;
   daha yeni bildirim zaten yeni timer kurdu, isi ona birak. Sira numarasi
   yalnizca YAZMADA artar, okumada artmaz -- bu yuzden guvenilir olcu.

AHK'deki `ignoreNextChange` bayragi yerine kendi yazdigimiz metni
karsilastiriyoruz: bayrak, arada baska bir kopya olursa kayiyor.

Her sey Qt ana thread'inde calisir; hook thread'i buraya hic dokunmaz.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from cascade.win32.clipboard import sequence_number

READ_DELAY_MS = 100  # AHK: clipReadDelay (WPF pano API'si de 100 ms kullanir)


class ClipboardWatcher(QObject):
    """Pano degisimini gecikmeli, tazelik kontrollu sekilde bildirir.

    text_copied : metin kopyalandi (gecmise girecek olan)
    other_copied: metin olmayan icerik (gorsel/dosya) -- sadece geri
                  bildirim icin (gorsel pano bilerek port edilmedi)
    """

    text_copied = Signal(str)
    other_copied = Signal()

    # TODO(AHK): GORSEL PANO port edilmedi. AHK'de metin disi kopya
    # `clip_image_store.ahk`e gidiyordu: PNG blob'u 500 MB'lik dairesel
    # `clipimg.dat` icine, 64x64 kucuk resim + metadata sabit slotlu
    # `clipimg.idx` icine yaziliyor, `clip_image_dialog.ahk` bunlari
    # gosteriyordu (gdip_mini.ahk ile). Burada yalniz "gordum" deniyor.
    # TODO(AHK): 1 MB ustu metinler AHK'de `bigclips.bin` icine tasiniyordu;
    # bizde hic alinmiyor (core/clip_history.py MAX_BYTES).

    def __init__(self, delay_ms: int = READ_DELAY_MS, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._delay_ms = delay_ms
        self._pending_seq = 0
        self._own_text: str | None = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._read)

        clipboard = QGuiApplication.clipboard()
        clipboard.dataChanged.connect(self._on_changed)

    # ---- disari ----

    def set_text(self, text: str) -> None:
        """Panoya biz yazariz; donen bildirim gecmise ikinci kez girmez."""
        self._own_text = text
        QGuiApplication.clipboard().setText(text)

    def stop(self) -> None:
        self._timer.stop()
        with_clipboard = QGuiApplication.clipboard()
        if with_clipboard is not None:
            with_clipboard.dataChanged.disconnect(self._on_changed)

    # ---- ic akis ----

    def _on_changed(self) -> None:
        """Bildirim ani: panoya DOKUNMA, sadece sira numarasini not al."""
        self._pending_seq = sequence_number()
        self._timer.start(self._delay_ms)

    def _read(self) -> None:
        if sequence_number() != self._pending_seq:
            return  # beklerken yeni kopya geldi; onun timer'i halleder

        mime = QGuiApplication.clipboard().mimeData()
        if mime is None:
            return
        if not mime.hasText():
            self.other_copied.emit()
            return

        text = mime.text()
        if text and text == self._own_text:
            self._own_text = None  # kendi yazdigimiz; gecmise geri koyma
            return
        self._own_text = None
        if text:
            self.text_copied.emit(text)
