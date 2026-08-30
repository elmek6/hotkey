"""Windows OCR -- AHK'deki OCR.ahk'nin (1800 satir COM cagrisi) karsiligi.

Ayni motor: Windows.Media.Ocr (isletim sistemiyle gelen, cevrimdisi).
AHK butun WinRT tesisatini elle kuruyordu; burada pywinrt paketleri
(winrt-runtime + projeksiyonlar) ayni isi ~60 satirda yapiyor.

`recognize` BLOKLAYICIDIR (motor tipik olarak 50-300 ms). Qt ana
thread'inden CAGIRMA -- app.py bunu ayri bir thread'de kosturup sonucu
sinyalle geri aliyor.

Dil, kullanicinin Windows dil listesinden secilir
(`try_create_from_user_profile_languages`). Turkce tanima icin Windows'a
Turkce dil paketinin (OCR ozelligiyle) kurulu olmasi gerekir; degilse motor
eldeki dille calisir ve Turkce karakterleri yanlis okuyabilir.
"""

from __future__ import annotations

import asyncio

from PySide6.QtGui import QImage

try:
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter

    _IMPORT_ERROR: str | None = None
except ImportError as exc:  # paket kurulmamis: menu ogesi uyari verir
    _IMPORT_ERROR = str(exc)


def available() -> bool:
    return _IMPORT_ERROR is None


def recognize(image: QImage) -> str:
    """Goruntudeki metni satir satir dondurur. Bos metin = bulunamadi.

    RuntimeError: motor yok (dil paketi eksik) ya da paket kurulmamis.
    """
    if _IMPORT_ERROR is not None:
        raise RuntimeError(f"winrt paketleri kurulu degil: {_IMPORT_ERROR}")
    if image.isNull():
        return ""

    # Motorun boyut siniri (10000 px); asan kenar sigacak sekilde kuculur.
    limit = OcrEngine.max_image_dimension
    if image.width() > limit or image.height() > limit:
        image = image.scaled(
            min(image.width(), limit), min(image.height(), limit)
        )

    # ARGB32, little-endian bellekte BGRA sirasidir -- BitmapPixelFormat.BGRA8
    # ile birebir. Satir dolgusu (stride) olabilir; varsa satir satir kirp.
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()
    stride = image.bytesPerLine()
    raw = image.constBits().tobytes()
    if stride != width * 4:
        raw = b"".join(
            raw[row * stride : row * stride + width * 4] for row in range(height)
        )

    return asyncio.run(_recognize(raw, width, height))


async def _recognize(raw: bytes, width: int, height: int) -> str:
    writer = DataWriter()
    writer.write_bytes(raw)
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.BGRA8, width, height
    )
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("OCR motoru yok: Windows'ta OCR'li dil paketi kurulu degil")
    result = await engine.recognize_async(bitmap)
    return "\n".join(line.text for line in result.lines)
