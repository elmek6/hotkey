"""QR uretimi -- AHK'de karsiligi YOK, bize ozgu. Tasarim: qr-plani.md.

Amaci tek yonlu bir kopru: PC'deki metni telefona gecirmek. Ters yon
(telefon -> PC) slotlarla ve pano gecmisiyle zaten cozulu.

Burasi SAF: Qt yok, pano yok, dosya yok. Sablon -> metin donusumu ve PNG
uretimi. Pencere `ui/qr_view.py`de, o da yalnizca buradaki `Template` ve
`png_bytes`i kullaniyor.

QR **yapi tasimaz**, yalnizca bayt. Telefon tanidigi onekleri kural
olarak bilir (`WIFI:`, `https://`, `mailto:`, `tel:`, `geo:`); JSON
koyarsan telefon onu duz metin gosterir ve hicbir sey yapmaz. Sablon
kavrami bu yuzden var: alanlar dogru oneke ceviriliyor.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import segno

from cascade.settings import Category, setting

#: QR penceresinin slot grubu. Bos deger = adsiz (base) grup.
SLOT_GROUP = setting(
    "qr.slotGroup",
    "QR penceresinin slot grubu",
    default="",
    category=Category.GENERAL,
    tags="qr slot grup kare",
    desc=(
        "QR penceresi acilinca hangi slot grubu secili gelsin. Pencerede "
        "gruptan secim yapinca burasi kendiliginden guncellenir."
    ),
)

#: Kare kenar uzunlugu (piksel) -- ekranda okunur, penceresi buyutmez.
PIXEL_SIZE = 260
#: Sessiz bolge. 4 standart, 3 ekranda yeterli ve yer kazandiriyor.
BORDER = 3
#: Hata duzeltme: "m" (%15). "l" daha kucuk kare verir ama ekrandan
#: okunan QR'da parlama/yansima payi birakmak gerekiyor.
ERROR_LEVEL = "m"
#: Mikro QR KAPALI. segno kisa icerikte kendiliginden mikro kare
#: uretiyor ("M3"), telefon kamerasi cogu zaman onu okumuyor -- kazanc
#: birkac milimetre, bedeli "neden calismiyor" sorusu.
MICRO = False

#: Wifi dizgisinde ANLAMI olan karakterler -- kacirilmazsa parola bolunur.
_WIFI_SPECIAL = "\\;:,\""


@dataclass(frozen=True, slots=True)
class Field:
    """Sablonun bir alani. `secret` olanlar ekranda gizli baslar."""

    key: str
    label: str
    secret: bool = False
    #: Bos ise metin kutusu; dolu ise acilir liste.
    choices: tuple[str, ...] = ()
    default: str = ""


@dataclass(frozen=True, slots=True)
class Template:
    """Bir QR turu: alanlari ve alanlardan metni ureten kural."""

    key: str
    label: str
    fields: tuple[Field, ...] = field(default_factory=tuple)

    def build(self, values: dict[str, str]) -> str:
        return _BUILDERS[self.key](values)


def _build_text(values: dict[str, str]) -> str:
    return values.get("text", "")


def _build_link(values: dict[str, str]) -> str:
    """Sema yoksa `https://` eklenir: semasiz adresi telefon link saymaz."""
    url = values.get("url", "").strip()
    if not url or "://" in url or url.startswith("mailto:"):
        return url
    return f"https://{url}"


def _build_wifi(values: dict[str, str]) -> str:
    """`WIFI:T:WPA;S:ad;P:parola;H:false;;`

    SSID bos ise bos dizgi doner -- yarim wifi karesi telefonu bos bir
    baglanti diyaloguna sokuyor, hic kare olmamasi daha durust.
    """
    ssid = values.get("ssid", "")
    if not ssid:
        return ""
    security = values.get("security", "WPA") or "nopass"
    password = values.get("password", "")
    hidden = "true" if values.get("hidden") == "1" else "false"
    parts = [f"T:{security}", f"S:{_wifi_escape(ssid)}"]
    if security != "nopass":
        parts.append(f"P:{_wifi_escape(password)}")
    parts.append(f"H:{hidden}")
    return "WIFI:" + ";".join(parts) + ";;"


def _wifi_escape(value: str) -> str:
    for char in _WIFI_SPECIAL:
        value = value.replace(char, "\\" + char)
    return value


def _parse_wifi(text: str) -> dict[str, str]:
    """`WIFI:...;;` dizgisini alanlara geri cozer.

    Gerekli: pencere hazir bir wifi karesiyle acilabiliyor (panoda o metin
    varsa). Cozulmezse metnin TAMAMI SSID kutusuna giriyordu ve kacis
    karakterleriyle birlikte ikinci kez kacirilip cop bir kare uretiyordu.
    """
    body = text.strip()[5:]
    if body.endswith(";;"):
        body = body[:-2]
    values: dict[str, str] = {}
    key = ""
    buffer: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            # Kacirilmis karakter: bir sonraki AYNEN icerige girer.
            buffer.append(body[index + 1])
            index += 2
            continue
        if char == ":" and not key:
            key = "".join(buffer).upper()
            buffer = []
        elif char == ";":
            if key:
                values[key] = "".join(buffer)
            key = ""
            buffer = []
        else:
            buffer.append(char)
        index += 1
    if key:
        values[key] = "".join(buffer)
    return {
        "ssid": values.get("S", ""),
        "password": values.get("P", ""),
        "security": values.get("T", "") or "WPA",
        "hidden": "1" if values.get("H", "").lower() == "true" else "0",
    }


def parse(key: str, text: str) -> dict[str, str]:
    """Hazir bir QR icerigini sablonun alanlarina cozer.

    Cozecek kural yoksa metin OLDUGU GIBI ilk alana konur -- eski davranis,
    duz metin ve linkte dogrusu da bu.
    """
    if key == "wifi" and text.strip().lower().startswith("wifi:"):
        return _parse_wifi(text)
    item = template(key)
    return {item.fields[0].key: text} if item.fields else {}


TEMPLATES: tuple[Template, ...] = (
    Template("text", "Metin", (Field("text", "Metin"),)),
    Template("link", "Link", (Field("url", "Adres"),)),
    Template(
        "wifi",
        "Wifi",
        (
            Field("ssid", "SSID"),
            Field("password", "Parola", secret=True),
            Field(
                "security",
                "Guvenlik",
                choices=("WPA", "WEP", "nopass"),
                default="WPA",
            ),
        ),
    ),
)

_BUILDERS = {
    "text": _build_text,
    "link": _build_link,
    "wifi": _build_wifi,
}


def template(key: str) -> Template:
    for item in TEMPLATES:
        if item.key == key:
            return item
    return TEMPLATES[0]


def guess_template(text: str) -> str:
    """Panodan gelen metne bakip sablon secer.

    Tahmin YANILABILIR ve sorun degil: kullanici ustteki dugmelerden
    degistirir. Amaci pencereyi cogu durumda dogru acmak.
    """
    lowered = text.strip().lower()
    if lowered.startswith("wifi:"):
        return "wifi"
    if lowered.startswith(("http://", "https://", "www.")):
        return "link"
    return "text"


def png_bytes(content: str, scale: int = 8) -> bytes:
    """QR'in PNG hali. Bos icerikte bos bayt -- cagiran cizmez."""
    if not content:
        return b""
    buffer = io.BytesIO()
    segno.make(content, error=ERROR_LEVEL, micro=MICRO).save(
        buffer, kind="png", scale=scale, border=BORDER
    )
    return buffer.getvalue()


def version_of(content: str) -> int:
    """QR surumu (1..40). Icerik buyudukce artar; pencerede gosteriliyor
    ki sinira yaklasan kullanici anlasin."""
    if not content:
        return 0
    return int(segno.make(content, error=ERROR_LEVEL, micro=MICRO).version)
