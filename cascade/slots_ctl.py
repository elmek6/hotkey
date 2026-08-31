"""Slot denetleyicisi -- AHK `clip_slot.ahk`in tamami.

app.py'den ayrildi: orada slot yapistirma, grup yonetimi ve F14 menusu
pano/snip/incognito ile ayni sinifin icinde duruyordu. Burasi SlotStore ile
kullanici arasindaki tek katman; app.py yalnizca nesneyi kurar ve
eylemlerini kayit defterine baglar.

Disariya bagimliliklar ELDEN VERILIYOR (ipucu, menu, yapistirma, panoya
yazma, filtreli liste). Boylece denetleyici sahte nesnelerle test edilebilir:
Qt kutulari (ad sorma, silme onayi) disinda hicbir yerde global yok.
"""

from __future__ import annotations

import html
import subprocess
from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QInputDialog, QMessageBox

from cascade import keymap
from cascade.core.filter import FilterItem
from cascade.store import PASSWORD_SLOT, SlotStore, slot_display
from cascade.ui.preview import preview_html, shorten


class SlotController:
    def __init__(
        self,
        store: SlotStore,
        *,
        tip_html: Callable[[str, int], None],
        show_menu: Callable[[tuple], None],
        paste_text: Callable[..., None],
        set_clipboard: Callable[..., None],
        show_filter: Callable[[tuple[FilterItem, ...], str], None],
        send_key: Callable[[str], None],
    ) -> None:
        self.store = store
        self._tip = tip_html
        self._menu = show_menu
        self._paste = paste_text
        self._clipboard = set_clipboard
        self._filter = show_filter
        self._send_key = send_key

    def register(self, runner) -> None:
        """Eylem kimlikleri -- AHK'de bunlar dogrudan fonksiyon referansiydi."""
        runner.register("slot.paste", self.paste_slot)
        runner.register("slot.paste_group", self.paste_slot_of)
        runner.register("slot.paste_side", self.paste_side_slot)
        runner.register("slot.paste_enter", self.paste_slot_then_enter)
        runner.register("slots.copy", self.copy_slot)
        runner.register("slots.save", self.save_to_slot)
        runner.register("slots.rename", self.rename_slot)
        runner.register("slots.group_new", lambda _: self.new_group())
        runner.register("slots.group_select", self.select_group)
        runner.register("slots.group_delete", self.delete_group)
        runner.register("slots.search", lambda _: self.show_filter())
        runner.register("slots.edit_file", lambda _: self.open_in_notepad())
        runner.register("menu.slots", lambda _: self.show_menu())
        runner.register("menu.base_slots", lambda _: self.show_base_menu())
        runner.register("menu.side_slots", lambda _: self.show_side_menu())

    # ---- yapistirma ----

    def paste_slot(self, argument: str) -> None:
        """`F13 & F20` -> slots.json varsayilan grubunun 1. slotu. 1 tabanli.

        Slotlar her basimda diskten taze okunur: dosya kucuk ve AHK tarafi
        ya da elle duzenleme ayni dosyayi degistirmis olabilir.
        """
        try:
            index = int(argument)
        except ValueError:
            return
        self.store.load()
        group = self.store.slots(self.store.default_group)
        if not 1 <= index <= len(group):
            return
        slot = group[index - 1]
        if not slot.content:
            self._tip(f"⚠️ <b>{html.escape(slot.name)}</b> bos", 1200)
            return
        self._slot_tip(index, slot.content)
        self._paste(slot.content, private=index == PASSWORD_SLOT)

    def paste_slot_of(self, argument: str) -> None:
        """`slot.paste_group:is/3` -- ISTENEN gruptan yapistirir."""
        group, index = self.split(argument)
        self.store.load()
        values = self.store.slots(group)
        if not 1 <= index <= len(values) or not values[index - 1].content:
            self._tip("⚠️ <b>slot bos</b>", 1200)
            return
        slot = values[index - 1]
        # Ipucu `paste_slot` ile ayni: Caret & 1 ve Tab & 1 yollari
        # sessizdi, yalniz F13 kombolari ne yapistirdigini soyluyordu.
        self._slot_tip(index, slot.content)
        self._paste(slot.content, private=index == PASSWORD_SLOT)

    def paste_side_slot(self, argument: str) -> None:
        """`Tab & 3` -- YALNIZ yan grup (defaultGroup) slotlarindan yapistirir.

        Yan grup secili degilken base gruba dusmuyor: Tab kombolari secili
        olan grubun degerini getirmeli, secim yoksa hicbir sey getirmemeli.
        """
        side = self.store.default_group
        if not side:
            self._tip("\U0001f9f0 <b>yan grup secili degil</b>", 1200)
            return
        self.paste_slot_of(f"{side}/{argument}")

    def paste_slot_then_enter(self, argument: str) -> None:
        """`slot.paste_enter:/10` -- slotu yapistirip Enter yollar (AHK:
        loadFromSlot + Sleep(200) + Send("{Enter}")). Enter GECIKMELI:
        yapistirma hedefe varmadan gonderilirse bos alan onaylanir."""
        self.paste_slot_of(argument)
        QTimer.singleShot(220, lambda: self._send_key("send_key:Enter"))

    def copy_slot(self, argument: str) -> None:
        """AHK yan grup menusu: oge tiklaninca icerik PANOYA konur."""
        group, index = self.split(argument)
        self.store.load()
        values = self.store.slots(group)
        if not 1 <= index <= len(values) or not values[index - 1].content:
            self._tip("⚠️ <b>slot bos</b>", 1200)
            return
        secret = index == PASSWORD_SLOT
        self._clipboard(values[index - 1].content, private=secret)
        self._tip("\U0001f4cb <b>kopyalandi</b>", 1200)

    def _slot_tip(self, index: int, content: str) -> None:
        """Yapistirilan slotu ipucunda gosterir: YALNIZ ICERIK.

        Slot adi ve numarasi yazilmiyor -- hangi tusa bastigini zaten
        biliyorsun, gormek istedigin sey ne yapistirildigi. Sifre slotunda
        icerik GORUNMEZ (store.slot_display).
        """
        self._tip(preview_html(slot_display(index, content)), 1200)

    @staticmethod
    def split(argument: str) -> tuple[str, int]:
        """`"is/3"` -> ("is", 3). Grup adi bos olabilir (`"/3"`)."""
        group, _, index = argument.rpartition("/")
        return group, int(index) if index.isdigit() else 0

    # ---- kaydetme / gruplar ----

    def save_to_slot(self, argument: str) -> None:
        """AHK `promptAndSaveSlot`: panodaki metni slota yazar, adini sorar."""
        group, index = self.split(argument)
        self.store.load()
        content = QGuiApplication.clipboard().text()
        if not content:
            self._tip("⚠️ <b>pano bos</b>, kaydedilmedi", 1500)
            return
        values = self.store.slots(group)
        current = values[index - 1].name if 1 <= index <= len(values) else ""
        name, ok = QInputDialog.getText(
            None, "Slota kaydet", f"Slot {index % 10} adi:", text=current
        )
        if not ok:
            return
        self.store.set_slot_content(group, index, content)
        self.store.set_slot_name(group, index, name)
        self._tip(f"\U0001f4be <b>{html.escape(name or f'Slot {index}')}</b>", 1500)

    def rename_slot(self, argument: str) -> None:
        """AHK `setName`: yalniz ADI degistirir, icerige dokunmaz."""
        group, index = self.split(argument)
        self.store.load()
        values = self.store.slots(group)
        current = values[index - 1].name if 1 <= index <= len(values) else ""
        name, ok = QInputDialog.getText(
            None, "Slot adi", f"Slot {index % 10} yeni adi:", text=current
        )
        if ok:
            self.store.set_slot_name(group, index, name)

    def new_group(self) -> None:
        """AHK `promptNewGroup`: grup acar ve HEMEN yan grup olarak secer."""
        name, ok = QInputDialog.getText(None, "Yeni grup", "Grup adi:")
        if not ok or not name.strip():
            return
        self.store.load()
        if not self.store.add_group(name):
            self._tip("⚠️ <b>grup zaten var</b>", 1500)
            return
        self.store.set_default_group(name.strip())
        self._tip(f"\U0001f9f0 <b>{html.escape(name.strip())}</b> olusturuldu", 1500)

    def select_group(self, name: str) -> None:
        """AHK `setDefaultGroup`: yan grup secimi (bos ad = yan grup yok)."""
        self.store.load()
        if not self.store.set_default_group(name):
            return
        self._tip(
            f"\U0001f9f0 <b>{html.escape(name)}</b> secildi"
            if name
            else "\U0001f9f0 yan grup yok",
            1200,
        )

    def delete_group(self, name: str) -> None:
        """AHK: MsgBox YesNo -- silme sorulur, sessizce silinmez."""
        if not name:
            return
        answer = QMessageBox.question(
            None, "Grup sil", f"'{name}' grubunu silmek istiyor musun?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.load()
        if self.store.delete_group(name):
            self._tip(f"\U0001f5d1️ <b>{html.escape(name)}</b> silindi", 1500)

    def open_in_notepad(self) -> None:
        subprocess.Popen(["notepad.exe", str(self.store.path)])  # noqa: S603,S607

    # ---- arama ----

    def show_filter(self) -> None:
        """Slotlarda arama -- AHK `showSlotsSearch`. Pano gecmisiyle AYNI
        pencere: base grup ve (varsa) yan grup slotlari tek listede.

        Sifre slotu listeye HIC girmiyor: pencere icerigi acikca gosteriyor.
        """
        self.store.load()
        groups = [""] + [g for g in self.store.group_names() if g]
        items: list[FilterItem] = []
        for group in groups:
            for index, slot in enumerate(self.store.slots(group)[:10], start=1):
                if index == PASSWORD_SLOT or not slot.content:
                    continue
                name = slot.name or f"Slot {index}"
                items.append(
                    FilterItem(
                        name=f"{group}/{index % 10} {name}" if group else f"{index % 10} {name}",
                        content=slot.content,
                        key=len(items) + 1,
                    )
                )
        if not items:
            self._tip("\U0001f9f0 <b>slot yok</b>", 1500)
            return
        self._filter(tuple(items), "Slotlar")

    # ---- menuler ----

    def items(self, group: str, action: str, prefix: str = "") -> tuple:
        """Bir grubun on slotu, menu ogesi olarak (AHK: addSlotItems).

        `action` her ogeye uygulanacak eylem kimligi: yapistirma, panoya
        kopyalama, uzerine kaydetme ya da ad degistirme. Etiket AHK ile ayni
        duzende: tus numarasi (10 -> "0"), slot adi, icerik onizlemesi.
        Sifre slotunun icerigi maskeli (store.slot_display).
        """
        result: list = []
        for index, slot in enumerate(self.store.slots(group)[:10], start=1):
            text = " ".join(slot.content.split())
            shown = slot_display(index, text, lambda t: shorten(t, 40)) if text else "(bos)"
            label = f"{prefix}{index % 10}  {slot.name or f'Slot {index}'}: {shown}"
            result.append((label, f"{action}:{group}/{index}"))
        return tuple(result)

    def side_menu_spec(self) -> tuple:
        """AHK `buildSideSlotMenu`: gruplar, secim, ekle/sil, Notepad."""
        result: list = [
            ("Yeni grup ekle", "slots.group_new"),
            ("Notepad ile ac", "slots.edit_file"),
            None,
            ("No side slot", "slots.group_select:"),
        ]
        for name in self.store.group_names():
            mark = "● " if name == self.store.default_group else ""
            result.append(
                (
                    f"{mark}{name}",
                    (
                        ("Select this group", f"slots.group_select:{name}"),
                        None,
                        # AHK'de bu ogeler icerigi PANOYA koyuyordu
                        # (yapistirmiyordu); ayni davranis.
                        *self.items(name, "slots.copy"),
                        None,
                        ("Rename slot", tuple(self.items(name, "slots.rename"))),
                        ("Save clipboard to slot", tuple(self.items(name, "slots.save"))),
                        None,
                        ("Delete this group", f"slots.group_delete:{name}"),
                    ),
                )
            )
        return tuple(result)

    def show_base_menu(self) -> None:
        """`^` basili tutunca: BASE grubun (defaultGroup == "") slotlari.

        Kombolarla (`^ & 1..0`) ayni kaynak, ayni sira -- menu o kombolarin
        gorunur halinden ibaret. Sifre slotunun icerigi maskeli.
        """
        self.store.load()
        self._menu(self.items("", "slot.paste_group"))

    def show_side_menu(self) -> None:
        """Tab basili tutunca: SECILI yan grubun slotlari (`Tab & 1..0` ile
        ayni kaynak). Grup secili degilse secim menusu aciliyor."""
        self.store.load()
        side = self.store.default_group
        if not side:
            self._menu(self.side_menu_spec())
            return
        self._menu(self.items(side, "slot.paste_group", prefix="⇥ "))

    def menu_spec(self) -> tuple:
        """F14 kisa basim -- AHK `showF14menu` + `showQuickSlotsMenu`.

        Kolon yapisi AHK ile ayni: 1. kolon eylemler ve alt menuler, 2.
        kolon varsayilan grubun slotlari, 3. kolon "yan grup" (secili grup
        varsa onun slotlari da aciliyor). Slotlar diskten TAZE okunuyor --
        dosyayi AHK tarafi ya da elle duzenleme degistirmis olabilir.
        """
        self.store.load()
        side = self.store.default_group
        spec: tuple = (
            ("Unformatted paste", "send_key:^+v"),
            None,
            # TODO(AHK): macro_recorder.ahk port edilmedi.
            ("Macro recorder", "yok:macro_recorder.ahk"),
            ("Hafiza bloklari", "memslots.start", "res:30"),  # bellek cubugu
            None,
            ("System", keymap.SYSTEM_MENU),
            ("Special keys", keymap.SPECIAL_KEYS_MENU),
            keymap.COLUMN,
            ("Search in slots", "slots.search"),
            None,
            *self.items("", "slot.paste_group"),
            None,
            # AHK showF14menu: kolonun sonu "Save to ^ slot" -- ad degistirme
            # ayri bir madde degil, kaydetme kutusunda soruluyor.
            ("Save to ^ slot", self.items("", "slots.save")),
            keymap.COLUMN,
            (f"Side slot{f' [{side}]' if side else ''}", self.side_menu_spec()),
        )
        if side and side in self.store.groups:
            spec += (
                None,
                *self.items(side, "slot.paste_group", prefix="⇥ "),
                None,
                (f"Save to ⇥{side}", self.items(side, "slots.save")),
            )
        return spec

    def show_menu(self) -> None:
        self._menu(self.menu_spec())
