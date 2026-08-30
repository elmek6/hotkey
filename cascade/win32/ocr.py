"""Windows OCR -- AHK'deki OCR.ahk + screen_ocr.ahk'nin motor tarafi.

Ayni motor: Windows.Media.Ocr (isletim sistemiyle gelen, cevrimdisi).
AHK butun WinRT tesisatini elle kuruyordu; burada pywinrt paketleri
(winrt-runtime + projeksiyonlar) ayni isi ~100 satirda yapiyor.

`recognize` BLOKLAYICIDIR (motor tipik olarak 50-300 ms). Qt ana
thread'inden CAGRILMAZ -- app.py ayri bir thread'de kosturup sonucu
sinyalle geri aliyor.

AHK'den tasinan iki on isleme (screen_ocr.ahk panelinde ayarlanabilir):

  olcek     OCR oncesi buyutme. 96 DPI'da 8-9 pt arayuz fontlari motorun
            sinirinda kaliyor; 2x buyutmek tanima oranini belirgin artiriyor.
  gri ton   ClearType'in alt-piksel renk izini temizler. Renkli kenarlar
            motoru yaniltabiliyor.

Kelime kutulari (`Word`) da doniyor: kolon/tablo dizilimi bunlarla
yapiliyor (core/ocr_layout.py). Kutular OLCEGE BOLUNUP geri veriliyor,
yani koordinatlar her zaman kaynak goruntunun pikselinde -- panelde
"kolon esigi 40px" dendiginde ekrandaki 40 piksel kastediliyor.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from cascade.core.ocr_layout import Word

try:
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter

    _IMPORT_ERROR: str | None = None
except ImportError as exc:  # paket kurulmamis: menu ogesi uyari verir
    _IMPORT_ERROR = str(exc)

DEFAULT_SCALE = 2
MAX_SCALE = 4


@dataclass(frozen=True, slots=True)
class Result:
    """Bir OCR gecisinin ciktisi. `lines` motorun kendi satir bolmesi."""

    lines: tuple[str, ...]
    words: tuple[Word, ...]
    language: str = ""
    ms: float = 0.0

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def available() -> bool:
    return _IMPORT_ERROR is None


def languages() -> list[tuple[str, str]]:
    """Sistemde OCR yetenegi KURULU diller: (etiket, dil kodu).

    Bos liste = hic dil paketi yok. Kurulum (yonetici PowerShell):
        Get-WindowsCapability -Online -Name "Language.OCR*"
        Add-WindowsCapability -Online -Name "Language.OCR~~~tr-TR~0.0.1.0"
    """
    if _IMPORT_ERROR is not None:
        return []
    try:
        return [
            (language.display_name, language.language_tag)
            for language in OcrEngine.available_recognizer_languages
        ]
    except OSError:
        return []


def recognize(
    image: QImage,
    scale: int = DEFAULT_SCALE,
    grayscale: bool = True,
    language: str = "",
) -> Result:
    """Goruntudeki metni ve kelime kutularini dondurur.

    `grayscale` ve `language` arayuzden SORULMUYOR (bkz. ui/ocr_view.py):
    varsayilanlari dogru cevap. Parametre olarak duruyorlar cunku motor
    ikisini de destekliyor ve gerekirse cagiran verebilir.

    RuntimeError: paket kurulu degil ya da motor olusturulamadi (dil paketi
    eksik).
    """
    if _IMPORT_ERROR is not None:
        raise RuntimeError(f"winrt paketleri kurulu degil: {_IMPORT_ERROR}")
    if image.isNull():
        return Result((), ())

    factor = max(1, min(int(scale), MAX_SCALE))
    prepared = _prepare(image, factor, grayscale)
    raw, width, height = _to_bgra(prepared)
    return asyncio.run(_recognize(raw, width, height, factor, language))


def _prepare(image: QImage, scale: int, grayscale: bool) -> QImage:
    """Olcekleme + gri tonlama. Motorun boyut sinirini asmaz."""
    if grayscale:
        image = image.convertToFormat(QImage.Format.Format_Grayscale8)
    if scale > 1:
        limit = OcrEngine.max_image_dimension
        # Buyutme siniri asacaksa olcegi kirp: motor daha buyugunu reddediyor.
        while scale > 1 and (image.width() * scale > limit or image.height() * scale > limit):
            scale -= 1
        if scale > 1:
            image = image.scaled(
                image.width() * scale,
                image.height() * scale,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    return image


def _to_bgra(image: QImage) -> tuple[bytes, int, int]:
    """ARGB32 -> BGRA8 bayt dizisi. Satir dolgusu (stride) varsa kirpilir."""
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()
    stride = image.bytesPerLine()
    raw = image.constBits().tobytes()
    if stride != width * 4:
        raw = b"".join(raw[row * stride : row * stride + width * 4] for row in range(height))
    return raw, width, height


async def _recognize(
    raw: bytes, width: int, height: int, scale: int, language: str
) -> Result:
    writer = DataWriter()
    writer.write_bytes(raw)
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.BGRA8, width, height
    )

    engine = _engine(language)
    started = time.perf_counter()
    result = await engine.recognize_async(bitmap)
    elapsed = (time.perf_counter() - started) * 1000.0

    lines: list[str] = []
    words: list[Word] = []
    for line in result.lines:
        lines.append(line.text)
        for word in line.words:
            box = word.bounding_rect
            # Kutular olcekli goruntunun pikselinde; kaynak piksele geri cevir.
            words.append(
                Word(
                    text=word.text,
                    x=box.x / scale,
                    y=box.y / scale,
                    w=box.width / scale,
                    h=box.height / scale,
                )
            )
    return Result(
        tuple(lines), tuple(words), engine.recognizer_language.language_tag, elapsed
    )


def _engine(language: str):
    """Istenen dilin motoru; dil bos ya da yoksa kullanici profilinden."""
    if language:
        from winrt.windows.globalization import Language

        engine = OcrEngine.try_create_from_language(Language(language))
        if engine is not None:
            return engine
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("OCR motoru yok: Windows'ta OCR'li dil paketi kurulu degil")
    return engine
