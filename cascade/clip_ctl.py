"""Pano denetleyicisi -- AHK `clip_hist.ahk` + `clip_image_store.ahk`.

app.py'den ayrildi. Panonun UC parcasi burada bir arada duruyor, cunku
ucu de ayni olaya (bir sey kopyalandi) bagli:

  * DURUM  -- hangi mod (gecmis / hafiza bloklari / kapali)
  * GECMIS -- metin kayitlari (bellekte ClipHistory, diskte ClipStore)
  * GORSEL -- metin disi kopyalar (ClipImageStore + pencere)

Hafiza bloklari moduna dusen metin buraya DEGIL app.py'nin verdigi
`to_mem_slots` geri aramasina gider: bloklar panonun degil ayri bir
pencerenin isi, denetleyici onu tanimasin.
"""

from __future__ import annotations

import html
import logging
import time
from collections.abc import Callable
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QImage

from cascade.core.clip_history import ClipHistory
from cascade.core.filter import FilterItem
from cascade.core.state import ClipboardState
from cascade.imgstore import ClipImageStore
from cascade.store import ClipStore
from cascade.ui.clip_images import ClipImages
from cascade.ui.clipboard import ClipboardWatcher
from cascade.ui.preview import preview_html, shorten

log = logging.getLogger("cascade.clip")


class ClipController:
    def __init__(
        self,
        *,
        tip_html: Callable[[str, int], None],
        tip_menu: Callable[..., None],
        show_menu: Callable[[tuple], None],
        show_filter: Callable[[tuple, str], None],
        send_key: Callable[[str], None],
        to_mem_slots: Callable[[str], None],
        directory: Path | None = None,  # test icin; varsayilan Files/
    ) -> None:
        self._tip = tip_html
        self._tip_menu = tip_menu
        self._menu = show_menu
        self._filter = show_filter
        self._send_key = send_key
        self._to_mem_slots = to_mem_slots

        # Durum (hangi mod) ile liste (ne saklandi) ayri duruyor; dinleme
        # tek yerde, ui/clipboard.py icinde. AHK'de de boyleydi.
        self.state = ClipboardState()
        self.history = ClipHistory()
        self.store = ClipStore(directory)
        # AHK clip_image_store.ahk + clip_image_dialog.ahk. Dosya bicimi
        # AHK ile ayni (clipimg.idx / clipimg.dat), pencere de ayni islevde.
        self.image_store = ClipImageStore(directory)
        self.images = ClipImages(self.image_store)
        self.images.copied.connect(self._on_image_copied)
        self.watcher = ClipboardWatcher()
        self.watcher.text_copied.connect(self.on_text)
        self.watcher.other_copied.connect(self.on_other)

    def register(self, runner) -> None:
        runner.register("clip.show", lambda _: self.show_history())
        runner.register("clip.filter", lambda _: self.show_filter())
        runner.register("clip.paste", self.paste_history)
        runner.register("menu.clip", lambda _: self.show_menu())
        runner.register("clip.images", lambda _: self.show_images())

    # ---- gelen kopya ----

    def on_text(self, text: str) -> None:
        """AHK: processClipboard'in gecmise ekleyen kismi.

        Mod kontrolu AHK'deki `if (!State.Clipboard.isHistory()) return`
        ile ayni yerde: dinleyici her zaman dinler, kaydi durum belirler.
        """
        if self.state.is_mem_slots():
            # AHK: mod MEM_SLOTS iken kopyalanan sey gecmise DEGIL slota
            # gider. Tek dinleyici + mod, iki dinleyiciden ongorulebilir.
            self._to_mem_slots(text)
            return
        if not self.state.is_history():
            return
        entry = self.history.add(text, time.time())
        if entry is None:
            return  # bos, cok buyuk ya da zaten en ustteki kayit
        # Sira numarasi YOK: kopyalarken listedeki yerini degil ne
        # kopyalandigini gormek istiyorsun.
        self._tip(f"\U0001f4cb {preview_html(entry.text)}", 1200)

    def on_other(self) -> None:
        """Metin disi kopya -- AHK: App.ClipImages.saveFromClipboard().

        Panoda gorsel varsa gorsel deposuna dusuyor (clipimg.dat/idx).
        Gorsel degilse (dosya listesi vb.) yalniz "gordum" deniyor.
        """
        image = QGuiApplication.clipboard().image()
        if image.isNull():
            self._tip("⛵ <span style='color:#8b949e;'>metin disi kopya</span>", 900)
            return
        if self.save_image(image) < 0:
            self._tip("⚠️ <b>gorsel kaydedilemedi</b>", 1200)
            return
        self._tip(f"\U0001f5bc️ <b>gorsel</b> {image.width()}x{image.height()}", 1200)

    def save_image(self, image: QImage) -> int:
        """QImage -> gorsel deposu. Slot no doner, basarisizsa -1.

        QImage'i PIL'e ham RGBA baytlariyla geciriyoruz: iki kutuphane
        arasinda dosya uzerinden gitmek gereksiz bir kodlama turu olurdu.
        """
        try:
            converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
            width, height = converted.width(), converted.height()
            stride = converted.bytesPerLine()
            raw = converted.constBits().tobytes()
            if stride != width * 4:  # satir dolgusu varsa kirp
                raw = b"".join(
                    raw[row * stride : row * stride + width * 4] for row in range(height)
                )
            pil = Image.frombytes("RGBA", (width, height), raw)
            return self.image_store.save_image(pil)
        except (OSError, ValueError):
            log.exception("pano gorseli kaydedilemedi")
            return -1

    def show_images(self) -> None:
        """AHK: App.ClipImageDlg.show()"""
        self.images.open()

    def _on_image_copied(self, detail: str) -> None:
        if not detail:
            self._tip("⚠️ <b>panoya konulamadi</b>", 1200)
        elif detail.startswith("kaydedildi:"):
            self._tip(f"\U0001f4be <b>{html.escape(shorten(detail, 60))}</b>", 1800)
        else:
            self._tip(f"\U0001f4cb <b>goruntu panoda</b> {detail}", 1200)

    # ---- yapistirma ----

    def paste_text(self, text: str, private: bool = False) -> None:
        """AHK: ArrayFilter.sendText -- panoya yaz, kisa bekle, Ctrl+V.

        Bekleme sus payi degil: panoya yazmak asenkron bitiyor ve hedef
        uygulama Ctrl+V'yi ayni anda alirsa eski icerigi yapistiriyor.
        AHK'de de Sleep(50) vardi. Kendi yazdigimiz metin gecmise ikinci kez
        girmiyor -- ClipboardWatcher.set_text bunu biliyor.

        `private=True` sifre slotu icin: pano gecmisi (bizimki de Windows'un
        Win+V'si de) bu kopyayi HIC kaydetmez.
        """
        if not text:
            return
        self.watcher.set_text(text, private=private)
        QTimer.singleShot(60, lambda: self._send_key("send_key:^v"))

    def copy_to_history(self, text: str) -> None:
        """Panoya oyle yaz ki pano dinleyicisi NORMAL kopya sansin: metin
        gecmise de girer (watcher.set_text kendi yazdigimizi gecmis disi
        tutar, burada tam tersi isteniyor)."""
        if text:
            QGuiApplication.clipboard().setText(text)

    def paste_history(self, argument: str) -> None:
        """`^ & 1` -> gecmisin 1. kaydi. 1 tabanli, AHK ile ayni."""
        try:
            index = int(argument)
        except ValueError:
            return
        entry = self.history.get(index)
        if entry is None:
            self._tip(
                f"\U0001f4cb <b>{index}.</b> "
                "<span style='color:#8b949e;'>kayit yok</span>",
                1200,
            )
            return
        # Sira numarasi YOK, yalniz icerik -- CapsLock & 3'e basan zaten
        # kacinci kaydi istedigini biliyor, gormek istedigi sey ne geldigi.
        self._tip(preview_html(entry.text), 1200)
        self.paste_text(entry.text)

    # ---- listeler ----

    def show_filter(self) -> None:
        """Pano gecmisini filtreli listede acar -- array_filter.ahk'nin
        pano icin kullanildigi yer. Liste veriye cevrilir; pencere panoyu
        bilmez, sadece FilterItem gosterir."""
        entries = self.history.entries
        if not entries:
            self._tip("\U0001f4cb <b>pano gecmisi bos</b>", 1500)
            return
        items = tuple(
            FilterItem(
                name=f"{index}" + (f" x{entry.count}" if entry.count > 1 else ""),
                content=entry.text,
                key=index,
            )
            for index, entry in enumerate(entries, start=1)
        )
        self._filter(items, "Pano gecmisi")  # sayiyi pencere ekler

    def show_menu(self) -> None:
        """Pano gecmisinin hizli menusu -- AHK showQuickHistoryMenu.

        Filtreli listeden farki: arama yok, tek tiklamada yapistirir.
        Onek tusunu basili tutunca acilan sey bu.
        """
        entries = self.history.entries[:9]
        if not entries:
            self._tip("\U0001f4cb <b>pano gecmisi bos</b>", 1500)
            return
        spec = tuple(
            (f"{index}  {shorten(entry.preview, 48)}", f"clip.paste:{index}")
            for index, entry in enumerate(entries, start=1)
        )
        self._menu((*spec, None, ("\U0001f50d Ara...", "clip.filter")))

    def show_history(self) -> None:
        entries = self.history.entries[:9]
        if not entries:
            self._tip("\U0001f4cb <b>pano gecmisi bos</b>", 1500)
            return
        items = tuple(
            (
                str(index),
                html.escape(shorten(entry.preview))
                + (
                    f" <span style='color:#8b949e;'>x{entry.count}</span>"
                    if entry.count > 1
                    else ""
                ),
            )
            for index, entry in enumerate(entries, start=1)
        )
        self._tip_menu(
            f"\U0001f4cb Pano gecmisi ({len(self.history)})",
            items,
            footer="",
            ms=4000,
        )

    def menu_items(self) -> tuple:
        """AHK `ClipHist.buildHistoryMenu()`: arama, son 30 kayit, temizle.

        F13'te gecmis dogrudan acilan bir liste degil ALT MENU -- ogeler
        onizlemeye kirpiliyor, tiklanan kayit yapistiriliyor.
        """
        items: list = [("Search on history", "clip.filter"), None]
        for index, entry in enumerate(self.history.entries[:30], start=1):
            items.append((f"Clip {index}: {shorten(entry.preview, 55)}", f"clip.paste:{index}"))
        if len(items) == 2:
            items.append(("(pano gecmisi bos)", "clip.filter"))
        return tuple(items)

    # ---- disk / kapanis ----

    def load(self) -> int:
        count = self.history.load(self.store.load_entries())
        log.info("%d pano kaydi diskten okundu (%s)", count, self.store.path)
        return count

    def save(self) -> bool:
        return self.store.save_entries(self.history.entries)

    def close(self) -> None:
        self.watcher.stop()
        self.images.close()
        self.image_store.close()
