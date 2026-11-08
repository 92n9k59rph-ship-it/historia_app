"""OCR de fotos en español y el camino foto → guion → vídeo → examen."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from historia.exam import build_exam, grade_exam
from historia.ocr import clear_ocr_cache, ocr_tesseract_bytes, ocr_tesseract_many
from historia.script import build_script
from historia.video import generate_video, probe_streams
from tests.test_pipeline import FFMPEG, silent_synth

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
PAGE_ONE = (
    "La Revolucion francesa empezo en 1789. "
    "El 14 de julio de 1789 el pueblo de Paris tomo la Bastilla."
)
PAGE_TWO = (
    "El 21 de enero de 1793 Luis XVI fue guillotinado. "
    "Robespierre dirigio el Terror entre 1793 y 1794."
)


def _page(text: str, width: int = 1500, height: int = 360) -> Image.Image:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT, 42)
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= width - 80:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    y = 50
    for line in lines:
        draw.text((40, y), line, fill="black", font=font)
        y += 64
    return image


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_ocr_reads_a_normal_spanish_page():
    clear_ocr_cache()
    text = ocr_tesseract_bytes(_png_bytes(_page(PAGE_ONE)))
    assert "1789" in text
    assert "Bastilla" in text


def test_ocr_reads_an_exif_rotated_page_and_keeps_order():
    clear_ocr_cache()
    upright = _page(PAGE_TWO)
    sideways = upright.transpose(Image.Transpose.ROTATE_270)
    exif = sideways.getexif()
    exif[274] = 8
    rotated = io.BytesIO()
    sideways.save(rotated, format="JPEG", quality=95, exif=exif.tobytes())
    webp = io.BytesIO()
    _page(PAGE_ONE).save(webp, format="WEBP", quality=95)
    text = ocr_tesseract_many(
        [
            ("pagina1.webp", webp.getvalue()),
            ("pagina2.jpg", rotated.getvalue()),
        ]
    )
    assert text.index("Bastilla") < text.index("Robespierre")
    assert "1793" in text
    # La segunda lectura de los mismos bytes sale de la caché y no cambia el texto.
    again = ocr_tesseract_bytes(webp.getvalue())
    assert "Bastilla" in again


def test_heic_roundtrip_if_the_encoder_exists():
    clear_ocr_cache()
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()
    buffer = io.BytesIO()
    try:
        _page(PAGE_ONE).save(buffer, format="HEIF", quality=90)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"este Pillow no escribe HEIC: {exc}")
    text = ocr_tesseract_bytes(buffer.getvalue())
    assert "Bastilla" in text
    assert "1789" in text


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
def test_photos_become_a_lesson_video_and_an_exam(tmp_path: Path):
    clear_ocr_cache()
    text = ocr_tesseract_many(
        [
            ("uno.png", _png_bytes(_page(PAGE_ONE))),
            ("dos.png", _png_bytes(_page(PAGE_TWO, height=420))),
        ]
    )
    assert "1789" in text and "1793" in text
    script = build_script(text)
    assert "## Introducción" in script.markdown
    assert "## Conclusión" in script.markdown
    exam = build_exam(text)
    assert any(question.kind == "mc" for question in exam.questions)
    assert any(question.kind == "short" for question in exam.questions)
    perfect = {}
    for question in exam.questions:
        if question.kind == "mc":
            perfect[question.id] = question.answer
        else:
            perfect[question.id] = " ".join(form for group in question.accept for form in group)
    assert grade_exam(exam, perfect).score_out_of_10 == 10.0
    video = tmp_path / "desde_fotos.mp4"
    result = generate_video(script.markdown, video, synth=silent_synth)
    streams = probe_streams(result.path)
    assert any(stream.get("codec_type") == "video" and stream.get("codec_name") == "h264" for stream in streams)
    assert any(stream.get("codec_type") == "audio" and stream.get("codec_name") == "aac" for stream in streams)
    assert (Path(__file__).resolve().parents[1] / "packages.txt").read_text(encoding="utf-8").find("tesseract-ocr-spa") >= 0
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "ffmpeg" in dockerfile and "tesseract-ocr-spa" in dockerfile
