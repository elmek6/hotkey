"""VK kodu <-> isim tablosu. Saf Python, Win32 import'u yok -> pytest buraya.

AHK'nin tus adlandirmasina yakin duruldu (LShift, RCtrl, XButton1 ...) ki
mevcut AHK ayar/profil dosyalari birebir tasinabilsin.
"""

VK_NAMES: dict[int, str] = {
    0x01: "LButton", 0x02: "RButton", 0x04: "MButton",
    0x05: "XButton1", 0x06: "XButton2",
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter",
    0x13: "Pause", 0x14: "CapsLock", 0x1B: "Escape",
    0x20: "Space", 0x21: "PgUp", 0x22: "PgDn",
    0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2C: "PrintScreen", 0x2D: "Insert", 0x2E: "Delete",
    0x5B: "LWin", 0x5C: "RWin", 0x5D: "AppsKey",
    0x60: "Numpad0", 0x61: "Numpad1", 0x62: "Numpad2", 0x63: "Numpad3",
    0x64: "Numpad4", 0x65: "Numpad5", 0x66: "Numpad6", 0x67: "Numpad7",
    0x68: "Numpad8", 0x69: "Numpad9",
    0x6A: "NumpadMult", 0x6B: "NumpadAdd", 0x6D: "NumpadSub",
    0x6E: "NumpadDot", 0x6F: "NumpadDiv",
    0x90: "NumLock", 0x91: "ScrollLock",
    0xA0: "LShift", 0xA1: "RShift",
    0xA2: "LCtrl", 0xA3: "RCtrl",
    0xA4: "LAlt", 0xA5: "RAlt",
    0xBA: "SC027", 0xBB: "SC00D", 0xBC: "SC033", 0xBD: "SC00C",
    0xBE: "SC034", 0xBF: "SC035", 0xC0: "SC029",
    0xDB: "SC01A", 0xDC: "SC02B", 0xDD: "SC01B", 0xDE: "SC028",
}

for _i in range(1, 25):
    VK_NAMES[0x6F + _i] = f"F{_i}"
for _c in range(0x30, 0x3A):
    VK_NAMES[_c] = chr(_c)
for _c in range(0x41, 0x5B):
    VK_NAMES[_c] = chr(_c)
del _i, _c

# Tekerlek yonleri gercek bir VK degil; 0xFF ustunde takma kod aliyorlar ki
# fare ve klavye ayni kisayol tablosunda ayni sekilde yazilabilsin.
# (AHK'de de "WheelUp::" bir hotkey adidir, VK karsiligi yoktur.)
VK_WHEEL_UP = 0x101
VK_WHEEL_DOWN = 0x102
VK_WHEEL_LEFT = 0x103
VK_WHEEL_RIGHT = 0x104

VK_NAMES[VK_WHEEL_UP] = "WheelUp"
VK_NAMES[VK_WHEEL_DOWN] = "WheelDown"
VK_NAMES[VK_WHEEL_LEFT] = "WheelLeft"
VK_NAMES[VK_WHEEL_RIGHT] = "WheelRight"

# Medya tuslari -- AHK'de Volume_Up / Volume_Down / Volume_Mute adlariyla.
VK_NAMES[0xAD] = "Volume_Mute"
VK_NAMES[0xAE] = "Volume_Down"
VK_NAMES[0xAF] = "Volume_Up"
VK_NAMES[0xB0] = "Media_Next"
VK_NAMES[0xB1] = "Media_Prev"
VK_NAMES[0xB3] = "Media_Play_Pause"

MODIFIER_VKS = frozenset({0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C})

MOUSE_VKS = frozenset(
    {0x01, 0x02, 0x04, 0x05, 0x06, VK_WHEEL_UP, VK_WHEEL_DOWN, VK_WHEEL_LEFT, VK_WHEEL_RIGHT}
)

NAME_TO_VK: dict[str, int] = {name.lower(): vk for vk, name in VK_NAMES.items()}


def key_name(vk: int, scan: int = 0, extended: bool = False) -> str:
    """Tusun okunabilir adi. Bilinmeyen VK icin AHK tarzi VKxxSCxxx dondurur."""
    name = VK_NAMES.get(vk)
    if name is not None:
        return name
    return f"VK{vk:02X}SC{scan | (0x100 if extended else 0):03X}"


def vk_from_name(name: str) -> int | None:
    return NAME_TO_VK.get(name.lower())


def register_name(vk: int, name: str) -> None:
    """Duzene bagli bir tusa okunur ad verir.

    `^` tusu her klavye duzeninde baska bir VK'de. Hangisi oldugu ancak
    calisma aninda (VkKeyScanW) bilinir; ogrenildikten sonra buraya
    kaydedilir ve "Caret & 1" gibi kisayol dizgileri yazilabilir.
    """
    VK_NAMES[vk] = name
    NAME_TO_VK[name.lower()] = vk
