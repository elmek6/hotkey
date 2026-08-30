"""Turkce klavye eklentisi -- turkish_layout_addon.ahk portu (SAF katman).

ScrollLock ACIKKEN Turkce harfler klavyede olmayan bir duzenden yazilir.
Iki dizilim var, ScrollLock'u BASILI TUTMAK ikisi arasinda gecer:

    dizilim 1 (uzun basim)  c s i g  tuslari uzun basilinca  c s i g
                            -> once harfin kendisi yazilir, tus 400 ms'den
                               uzun tutulup birakilirsa BackSpace ile geri
                               alinip Turkce harf yazilir
    dizilim 2 (dogrudan)    u->g  o->s  ,->o  .->c  i->i  y<->z ...

Neden "once yaz sonra geri al"? AHK'de de oyleydi: karar tus BIRAKILINCA
veriliyor, ama o ana kadar beklenirse hizli yazarken harfler geride kalir.
Once dogrusunu yazmak, uzun basimda tek BackSpace ile duzeltmek yaziyi
akici tutuyor.

Bu modul Win32'ye DOKUNMAZ: girdi olarak tus kodu + basili modifierlar
alir, cikti olarak eylem kimlikleri (`send_text:...`) dondurur. Gonderme
isi dispatch/app tarafinda. Boylece dizilim kurallari testten gecebiliyor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Dizilim 1: tusun kendi harfi -> uzun basimda yazilacak Turkce harf.
#: AHK: `$c:: _HandleTurkish("c", "c", "c", "C")` satirlari.
LONG_PRESS = {
    "c": ("ç", "Ç"),
    "s": ("ş", "Ş"),
    "i": ("ı", "İ"),
    "g": ("ğ", "Ğ"),
}

#: Dizilim 2: tusun uzerindeki harf -> dogrudan yazilacak harf.
#: AHK'deki `_TkDirect` satirlarinin aynisi (Alman duzeni tuslariyla
#: yazilmisti; burada tusun URETTIGI karakterle eslesiyor).
DIRECT = {
    "ü": ("ğ", "Ğ"),
    "ö": ("ş", "Ş"),
    "ä": ("i", "İ"),
    ",": ("ö", "Ö"),
    ".": ("ç", "Ç"),
    "i": ("ı", "I"),
    "y": ("z", "Z"),
    "z": ("y", "Y"),
}

#: AHK: `KeyWait(key, "T0.4")` -- bu sureden uzun basim "Turkce harf" demek.
LONG_MS = 400.0


@dataclass
class TurkishLayout:
    """Dizilim durumu + tus kararlari.

    `enabled` ScrollLock'un karsiligi (AHK: `GetKeyState("ScrollLock","T")`),
    `layout` 1 ya da 2.
    """

    enabled: bool = False
    layout: int = 1
    #: Dizilim 1'de basili duran tuslar: karakter -> (basim ani, buyuk mu)
    _held: dict[str, tuple[float, bool]] = field(default_factory=dict)

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        self._held.clear()
        return self.enabled

    def switch_layout(self) -> int:
        self.layout = 2 if self.layout == 1 else 1
        self._held.clear()
        return self.layout

    def reset(self) -> None:
        self._held.clear()

    def feed(
        self, char: str, down: bool, t: float, upper: bool
    ) -> tuple[bool, list[str]]:
        """Bir tus olayi. `(yutulsun mu, eylemler)` doner.

        `char` tusun duzendeki KUCUK harfi (dispatch cozer), `upper` ise
        "buyuk yazilacak mi" -- AHK: `isCaps ? !isShift : isShift`.
        """
        if not self.enabled:
            return False, []
        if self.layout == 2:
            return self._direct(char, down, upper)
        return self._long_press(char, down, t, upper)

    # ---- dizilim 2: dogrudan ----

    def _direct(self, char: str, down: bool, upper: bool) -> tuple[bool, list[str]]:
        pair = DIRECT.get(char)
        if pair is None:
            return False, []
        if not down:
            return True, []  # basimi yuttuk, birakmasi da yutulmali
        return True, [f"send_text:{pair[1] if upper else pair[0]}"]

    # ---- dizilim 1: uzun basim ----

    def _long_press(
        self, char: str, down: bool, t: float, upper: bool
    ) -> tuple[bool, list[str]]:
        pair = LONG_PRESS.get(char)
        if pair is None:
            return False, []
        if down:
            if char in self._held:
                return True, []  # Windows'un tus tekrari: harf bir kez yazilir
            self._held[char] = (t, upper)
            return True, [f"send_text:{char.upper() if upper else char}"]

        start = self._held.pop(char, None)
        if start is None:
            return True, []
        began, was_upper = start
        if (t - began) * 1000.0 < LONG_MS:
            return True, []  # kisa basim: yazilan harf dogru, is bitti
        # Uzun basim: yazdigimiz harfi geri al, yerine Turkcesini koy.
        return True, ["send_key:Backspace", f"send_text:{pair[1] if was_upper else pair[0]}"]
