"""OCR de fotos de apuntes: Tesseract en español y, si hay clave, un modelo de visión."""

from __future__ import annotations

import hashlib
import io
import re
import shutil
from collections import OrderedDict

from PIL import Image, ImageOps

from historia.errors import HistoriaError

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
MAX_PHOTOS = 8
_CACHE: OrderedDict[str, str] = OrderedDict()
_HEIF_READY = False


def register_heif() -> None:
    global _HEIF_READY
    if _HEIF_READY:
        return
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return
    register_heif_opener()
    _HEIF_READY = True


def tesseract_status() -> tuple[bool, str]:
    if shutil.which("tesseract") is None:
        return (
            False,
            "No está Tesseract. En el ordenador: sudo apt install tesseract-ocr tesseract-ocr-spa. "
            "En Streamlit Community Cloud lo instala packages.txt.",
        )
    try:
        import pytesseract
    except ImportError:
        return False, "Falta el paquete pytesseract. Instálalo con pip."
    try:
        languages = set(pytesseract.get_languages(config=""))
    except Exception as exc:  # noqa: BLE001
        return False, f"Tesseract no responde: {exc}"
    if "spa" not in languages:
        return (
            False,
            "Tesseract no tiene el idioma español. Instala tesseract-ocr-spa y vuelve a intentarlo.",
        )
    return True, ""


def load_image(data: bytes) -> Image.Image:
    register_heif()
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001
        raise HistoriaError(
            f"No pude abrir la foto ({exc}). Usa jpg, png, heic o webp.",
            f"Could not open the photo ({exc}).",
        ) from exc
    transposed = ImageOps.exif_transpose(image)
    if transposed is None:
        transposed = image
    return transposed


def _limit_size(image: Image.Image, longest: int = 1600) -> Image.Image:
    image = image.convert("RGB")
    width, height = image.size
    longest_side = max(width, height)
    if longest_side > longest:
        scale = longest / longest_side
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
        width, height = image.size
    if min(width, height) < 700:
        image = image.resize((width * 2, height * 2), Image.Resampling.LANCZOS)
    return image


def _correct_osd(image: Image.Image) -> Image.Image:
    """Gira la página si Tesseract ve el texto de lado. El valor Rotate se aplica en sentido horario."""
    try:
        import pytesseract
    except ImportError:
        return image
    try:
        osd = pytesseract.image_to_osd(image)
    except Exception:
        return image
    match = re.search(r"Rotate:\s+(\d+)", osd)
    if not match:
        return image
    angle = int(match.group(1)) % 360
    if angle == 0:
        return image
    return image.rotate(-angle, expand=True, fillcolor="white")


def _otsu(gray: Image.Image) -> Image.Image:
    histogram = gray.histogram()
    total = sum(histogram)
    if total == 0:
        return gray
    total_sum = sum(index * count for index, count in enumerate(histogram))
    background_sum = 0
    background_weight = 0
    best_variance = -1.0
    threshold = 127
    for index, count in enumerate(histogram):
        background_weight += count
        if background_weight == 0:
            continue
        foreground_weight = total - background_weight
        if foreground_weight == 0:
            break
        background_sum += index * count
        mean_background = background_sum / background_weight
        mean_foreground = (total_sum - background_sum) / foreground_weight
        variance = background_weight * foreground_weight * (mean_background - mean_foreground) ** 2
        if variance > best_variance:
            best_variance = variance
            threshold = index
    return gray.point(lambda pixel, limit=threshold: 255 if pixel > limit else 0)


def _prepare(image: Image.Image) -> tuple[Image.Image, Image.Image]:
    limited = _limit_size(image)
    upright = _correct_osd(limited)
    gray = ImageOps.autocontrast(ImageOps.grayscale(upright))
    return _otsu(gray), gray


def _read(image: Image.Image) -> str:
    import pytesseract

    text = pytesseract.image_to_string(image, lang="spa", config="--psm 6")
    return re.sub(r"[ \t]+\n", "\n", text).strip()


def ocr_tesseract_bytes(data: bytes) -> str:
    ready, message = tesseract_status()
    if not ready:
        raise HistoriaError(message, message)
    digest = hashlib.sha256(data).hexdigest()
    cached = _CACHE.get(digest)
    if cached is not None:
        _CACHE.move_to_end(digest)
        return cached
    binary, gray = _prepare(load_image(data))
    text = _read(binary)
    if len(text) < 25:
        alternative = _read(gray)
        if len(alternative) > len(text):
            text = alternative
    _CACHE[digest] = text
    while len(_CACHE) > 8:
        _CACHE.popitem(last=False)
    return text


def ocr_tesseract_many(photos: list[tuple[str, bytes]]) -> str:
    if not photos:
        raise HistoriaError("No hay fotos para leer.", "There are no photos to read.")
    if len(photos) > MAX_PHOTOS:
        photos = photos[:MAX_PHOTOS]
    pages: list[str] = []
    for _name, data in photos:
        text = ocr_tesseract_bytes(data).strip()
        if text:
            pages.append(text)
    if not pages:
        raise HistoriaError(
            "No pude leer texto en las fotos. Prueba con más luz, la página derecha y el idioma español instalado.",
            "Could not read text from the photos.",
        )
    return "\n\n".join(pages)


def clear_ocr_cache() -> None:
    _CACHE.clear()
