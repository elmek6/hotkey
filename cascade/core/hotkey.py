"""Kisayol dizgisi (AHK sozdizimi) -- ayristirma ve eslestirme.

Iki ayri sey var, AHK'de de oyle:

**Modifier kombosu** -- Ctrl/Alt/Shift/Win basili tutulur:

    ^z          Ctrl+Z
    ^!k         Ctrl+Alt+K
    <^z         yalniz SOL Ctrl
    >!e         yalniz SAG Alt (AltGr)
    *^z         yildiz: fazladan modifier basiliysa da tetikle

**Onek (prefix) kombosu** -- modifier OLMAYAN normal bir tus onek olur.
AHK'deki `A & B::` yazimi; bu scriptin asil kullandigi bicim:

    Caret & 1    `^` tusu basiliyken 1
    F13 & F14    fare yan tusu basiliyken oteki yan tus
    ~F13 & i     tilde: onek YUTULMAZ, alttaki uygulamaya da gider
    ~LButton & F16   sol tik basiliyken F16 -- tilde sart, yoksa tiklayamazsin

Onek tusu basildigi anda YUTULUR, cunku kombo mu olacagi henuz belli
degildir. Tek basina birakilirsa orijinal tus geri gonderilir (AHK'nin
`~` isareti olmadan yaptigi sey degil -- AHK oneki hic yutmaz ve `~` ile
gecirir; burada yutup geri gondermek zorundayiz, cunku LL hook keydown
aninda cevap vermek zorunda).

Insan tarafindan yazilan "Ctrl+Shift+S" bicimi de kabul edilir.

Saf Python: Win32 import'u yok, zaman yok. Eslestirme sadece sozluk/kume
islemi -- hook callback'inin icinden cagrilacak kadar ucuz.

Eslesme kurali AHK ile ayni: istenen her modifier basili OLMALI ve
istenmeyen hicbir modifier basili OLMAMALI. `*` oneki ikinci sarti kaldirir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cascade.core.keynames import MODIFIER_VKS, key_name, vk_from_name
from cascade.core.prefix import DEFAULT_HOLD_MS, PrefixDef

# Sembol -> (kanonik ad, (sol VK, sag VK))
MOD_SYMBOLS: dict[str, tuple[str, tuple[int, int]]] = {
    "^": ("Ctrl", (0xA2, 0xA3)),
    "!": ("Alt", (0xA4, 0xA5)),
    "+": ("Shift", (0xA0, 0xA1)),
    "#": ("Win", (0x5B, 0x5C)),
}

# "Ctrl+Shift+S" yazimindaki modifier adlari.
MOD_WORDS: dict[str, tuple[str, tuple[int, ...]]] = {
    "ctrl": ("Ctrl", (0xA2, 0xA3)),
    "control": ("Ctrl", (0xA2, 0xA3)),
    "alt": ("Alt", (0xA4, 0xA5)),
    "shift": ("Shift", (0xA0, 0xA1)),
    "win": ("Win", (0x5B, 0x5C)),
    "lctrl": ("LCtrl", (0xA2,)),
    "rctrl": ("RCtrl", (0xA3,)),
    "lalt": ("LAlt", (0xA4,)),
    "ralt": ("RAlt", (0xA5,)),
    "altgr": ("RAlt", (0xA5,)),
    "lshift": ("LShift", (0xA0,)),
    "rshift": ("RShift", (0xA1,)),
    "lwin": ("LWin", (0x5B,)),
    "rwin": ("RWin", (0x5C,)),
}


@dataclass(frozen=True, slots=True)
class Hotkey:
    """Ayristirilmis kisayol. `mods` her modifier icin KABUL EDILEN VK'lar."""

    vk: int
    mods: tuple[tuple[int, ...], ...] = ()
    prefix: int | None = None
    passthrough: bool = False  # AHK `~`: onek yutulmaz
    wildcard: bool = False
    text: str = ""

    @property
    def allowed(self) -> frozenset[int]:
        return frozenset(vk for group in self.mods for vk in group)

    def matches(
        self,
        vk: int,
        held: tuple[int, ...] | frozenset[int] = (),
        prefix: int | None = None,
    ) -> bool:
        """`held`: basili modifier VK'lari, `prefix`: basili onek tusu.

        Ikisi de ComboTracker.Chord'dan gelir. Onek eslesmesi tam olmak
        zorunda: onek istemeyen bir tanim, onek basiliyken tetiklenmez --
        yoksa `Caret & 1` calisirken sade `1` tanimi da patlardi.
        """
        if vk != self.vk or prefix != self.prefix:
            return False
        down = frozenset(held) & MODIFIER_VKS
        for group in self.mods:
            if not down.intersection(group):
                return False
        if self.wildcard:
            return True
        return not (down - self.allowed)  # istenmeyen modifier basiliysa eslesmez


def parse_hotkey(spec: str) -> Hotkey:
    """ "^!k" / "Ctrl+Alt+K" / "Caret & 1" / "F13" -> Hotkey.

    Bilinmeyen tus adinda ValueError.
    """
    text = spec.strip()
    if not text:
        raise ValueError("bos kisayol")
    if "&" in text:
        head, _, tail = text.partition("&")
        head = head.strip()
        passthrough = head.startswith("~")  # AHK: ~LButton & F16
        prefix = _resolve(head.lstrip("~").strip())
        hotkey = parse_hotkey(tail)
        return Hotkey(
            vk=hotkey.vk,
            mods=hotkey.mods,
            prefix=prefix,
            passthrough=passthrough,
            wildcard=hotkey.wildcard,
            text=f"{'~' if passthrough else ''}{key_name(prefix)} & {hotkey.text}",
        )
    if text.startswith("~"):
        # AHK `~MButton`: eylem calisir ama tus YUTULMAZ. Kombolarda `~`
        # onegin yutulmamasi demekti (`~LButton & F16`); tek basina bir
        # tusta ise tusun kendisinin uygulamaya gecmesi demek. Orta tus /
        # Insert gibi her yerde isi olan tuslara boyle eylem baglanabiliyor.
        inner = parse_hotkey(text[1:])
        return Hotkey(
            vk=inner.vk,
            mods=inner.mods,
            prefix=inner.prefix,
            passthrough=True,
            wildcard=inner.wildcard,
            text=f"~{inner.text}",
        )
    if text[0] in MOD_SYMBOLS or text[0] in "*<>":
        return _parse_symbols(text)
    if "+" in text:
        return _parse_words(text)
    return _hotkey(_resolve(text), [])


def _parse_symbols(spec: str) -> Hotkey:
    mods: list[tuple[str, tuple[int, ...]]] = []
    wildcard = False
    side: int | None = None
    index = 0
    while index < len(spec):
        char = spec[index]
        if char == "*":
            wildcard = True
        elif char == "<":
            side = 0
        elif char == ">":
            side = 1
        elif char in MOD_SYMBOLS:
            name, pair = MOD_SYMBOLS[char]
            if side is None:
                mods.append((name, pair))
            else:
                mods.append((("L" if side == 0 else "R") + name, (pair[side],)))
            side = None
        else:
            break
        index += 1
    key = spec[index:].strip()
    if not key:
        raise ValueError(f"kisayolda tus yok: {spec!r}")
    return _hotkey(_resolve(key), mods, wildcard)


def _parse_words(spec: str) -> Hotkey:
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    mods: list[tuple[str, tuple[int, ...]]] = []
    for part in parts[:-1]:
        word = MOD_WORDS.get(part.lower())
        if word is None:
            raise ValueError(f"bilinmeyen modifier: {part!r}")
        mods.append(word)
    return _hotkey(_resolve(parts[-1]), mods)


def _hotkey(vk: int, mods: list[tuple[str, tuple[int, ...]]], wildcard: bool = False) -> Hotkey:
    label = "*" if wildcard else ""
    label += "+".join([name for name, _ in mods] + [key_name(vk)])
    return Hotkey(
        vk=vk,
        mods=tuple(group for _, group in mods),
        wildcard=wildcard,
        text=label,
    )


def _resolve(name: str) -> int:

    vk = vk_from_name(name)
    if vk is None:
        raise ValueError(f"bilinmeyen tus adi: {name!r}")
    return vk


@dataclass(frozen=True, slots=True)
class Binding:
    hotkey: Hotkey
    action: str
    desc: str = ""


@dataclass
class HotkeyTable:
    """AHK'nin statik `^!k::` tanimlarinin karsiligi: dizgi -> eylem kimligi.

    `match` en cok modifier iceren tanimi once dener; boylece `^+z` tanimi
    `^z` tanimini golgede birakmaz (AHK'de de daha ozgul olan kazanir).
    """

    bindings: list[Binding] = field(default_factory=list)
    _keys: set[int] = field(default_factory=set, init=False, repr=False)
    _prefix_defs: dict[int, PrefixDef] = field(default_factory=dict, init=False, repr=False)

    def add(self, spec: str, action: str, desc: str = "") -> HotkeyTable:
        hotkey = parse_hotkey(spec)
        self.bindings.append(Binding(hotkey, action, desc))
        # Once onekli, sonra cok modifierli tanim denenir: ozgul olan kazanir.
        self.bindings.sort(
            key=lambda b: (b.hotkey.prefix is not None, len(b.hotkey.mods)), reverse=True
        )
        self._keys.add(hotkey.vk)
        if hotkey.prefix is not None:
            self._touch_prefix(hotkey.prefix, passthrough=hotkey.passthrough)
        return self

    def prefix(
        self,
        spec: str,
        *,
        passthrough: bool = False,
        hold_action: str = "",
        hold_ms: float = DEFAULT_HOLD_MS,
        drag_action: str = "",
        desc: str = "",
    ) -> HotkeyTable:
        """Onek tusuna basili-tutma davranisi ekler.

        AHK'de bu KeyBuilder'in `mainKey(pt)` switch'iydi: `^` kisa basinca
        kendini yazar, basili tutunca menu acar. Kisa basim eylemi normal
        tablo satiri (`table.add("Caret", ...)`); burasi yalniz basili tutma.
        Kombo tanimi olmayan bir tus da onek yapilabilir -- boylece sadece
        "basili tut" davranisi olan tuslar da yazilabiliyor.
        """
        vk = _resolve(spec.lstrip("~").strip())
        self._touch_prefix(
            vk,
            passthrough=passthrough or spec.strip().startswith("~"),
            hold_action=hold_action,
            hold_ms=hold_ms,
            drag_action=drag_action,
            desc=desc,
        )
        return self

    def _touch_prefix(
        self,
        vk: int,
        *,
        passthrough: bool = False,
        hold_action: str = "",
        hold_ms: float = DEFAULT_HOLD_MS,
        drag_action: str = "",
        desc: str = "",
    ) -> None:
        """Onek tanimini olustur/birlestir. Tanim birden cok satirdan parca
        parca gelir: `~F13 & i` gecirgenligi, `.prefix("F13", hold_action=...)`
        basili-tutmayi soyler; ikisi de ayni tanima yazilir."""
        old = self._prefix_defs.get(vk)
        self._prefix_defs[vk] = PrefixDef(
            vk=vk,
            passthrough=passthrough or (old.passthrough if old else False),
            hold_action=hold_action or (old.hold_action if old else ""),
            hold_ms=hold_ms if hold_action else (old.hold_ms if old else hold_ms),
            drag_action=drag_action or (old.drag_action if old else ""),
            desc=desc or (old.desc if old else ""),
        )

    def owns(self, vk: int) -> bool:
        """Modifier durumuna bakmadan hizli eleme -- callback'in sicak yolu."""
        return vk in self._keys

    @property
    def prefixes(self) -> frozenset[int]:
        """Onek olarak kullanilan tuslar."""
        return frozenset(self._prefix_defs)

    @property
    def prefix_defs(self) -> dict[int, PrefixDef]:
        """PrefixTracker'a verilecek tanimlar."""
        return dict(self._prefix_defs)

    def match(
        self,
        vk: int,
        held: tuple[int, ...] | frozenset[int] = (),
        prefix: int | None = None,
    ) -> Binding | None:
        if vk not in self._keys:
            return None
        for binding in self.bindings:
            if binding.hotkey.matches(vk, held, prefix):
                return binding
        return None

    @property
    def tips(self) -> tuple[tuple[str, str], ...]:
        """Ipucu penceresinde gosterilecek 'kisayol: aciklama' listesi."""
        return tuple((b.hotkey.text, b.desc) for b in self.bindings if b.desc)
