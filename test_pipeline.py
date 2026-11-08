"""Pruebas del modo local: extracción, guion, examen y vídeo sin servicios externos."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from historia.analyze import analyze, fold
from historia.errors import HistoriaError
from historia.exam import Question, build_exam, grade_exam
from historia.extract import extract_bytes, extract_path
from historia.script import build_script, parse_markdown
from historia.service import generate_script
from historia.settings import GenerationSettings
from historia.translate import EnglishTranslator
from historia.video import generate_video, probe_streams, synthesize_speech

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / "ejemplo_tema.txt").read_text(encoding="utf-8")
FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class IdentityTranslator:
    def warm(self, texts) -> None:
        return None

    def to_english(self, text: str) -> tuple[str, bool]:
        return text, True


class OfflineTranslator:
    def to_english(self, text: str) -> tuple[str, bool]:
        return text, False


def _pdf_escape(text: str) -> str:
    encoded = text.encode("latin-1", "replace").decode("latin-1")
    return encoded.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_simple_pdf(path: Path, text: str) -> None:
    lines: list[str] = []
    for paragraph in text.splitlines():
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if len(trial) <= 90:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    operations = ["BT", "/F1 12 Tf", "54 760 Td", "16 TL"]
    for index, line in enumerate(lines):
        if index:
            operations.append("T*")
        operations.append(f"({_pdf_escape(line)}) Tj")
    operations.append("ET")
    stream = "\n".join(operations).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload += f"{number} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
    xref = len(payload)
    payload += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    payload += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        payload += f"{offset:010d} 00000 n \n".encode("ascii")
    payload += (
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(payload)


def write_docx(path: Path, text: str, heading: str | None = "La Revolución francesa", with_table: bool = True) -> None:
    from docx import Document

    document = Document()
    if heading:
        document.add_heading(heading, level=1)
    for paragraph in [block.strip() for block in text.split("\n\n") if block.strip()]:
        document.add_paragraph(paragraph)
    if with_table:
        table = document.add_table(rows=2, cols=2)
        table.rows[0].cells[0].text = "Fecha"
        table.rows[0].cells[1].text = "Acontecimiento"
        table.rows[1].cells[0].text = "14 de julio de 1789"
        table.rows[1].cells[1].text = "Toma de la Bastilla"
    document.save(path)


def silent_synth(text: str, dest: Path, engine: str):
    dest.parent.mkdir(parents=True, exist_ok=True)
    wav_path = dest.with_suffix(".wav")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            "0.6",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ],
        check=True,
    )
    return wav_path, "silent", []


def test_sample_finds_dates_names_and_script_sections():
    found = analyze(SAMPLE)
    assert found.title == "La Revolución francesa"
    assert any("1789" in date for date in found.dates)
    assert any("14 de julio de 1789" in fold(date) for date in found.dates)
    assert any("Robespierre" in name for name in found.names)
    assert any("Bastilla" in name for name in found.names)
    script = build_script(SAMPLE)
    assert "## Introducción" in script.markdown
    assert "## Conclusión" in script.markdown
    assert "vamos a estudiar" in script.markdown
    title, slides = parse_markdown(script.markdown)
    assert title == "La Revolución francesa"
    assert len(slides) >= 4
    assert slides[0].heading == "Introducción"
    assert slides[-1].heading == "Conclusión"


def test_offline_service_does_not_need_an_api_key():
    script, warnings = generate_script(SAMPLE, GenerationSettings(use_llm=False))
    assert script.mode == "offline"
    assert warnings == []
    assert "Luis XVI" in script.markdown or "Robespierre" in script.markdown


def test_exam_perfect_zero_and_english_fallback():
    exam = build_exam(SAMPLE, translator=IdentityTranslator())
    kinds = [question.kind for question in exam.questions]
    assert kinds.count("mc") >= 2
    assert kinds.count("short") >= 1
    for question in exam.questions:
        assert question.prompt
        lowered = question.prompt.lower()
        assert "which option" in lowered or "explain the historical importance" in lowered
        if question.kind == "mc":
            assert "____" in question.prompt
            assert any(fold(question.answer) == fold(option) for option in question.options)
            assert len(question.options) >= 4
    perfect = {}
    for question in exam.questions:
        if question.kind == "mc":
            perfect[question.id] = question.answer
        else:
            perfect[question.id] = " ".join(form for group in question.accept for form in group)
    perfect_grade = grade_exam(exam, perfect)
    assert perfect_grade.score_out_of_10 == 10.0
    assert all(item.status == "correct" for item in perfect_grade.items)

    blank = {}
    for question in exam.questions:
        if question.kind == "mc":
            blank[question.id] = next(
                option for option in question.options if fold(option) != fold(question.answer)
            )
        else:
            blank[question.id] = ""
    zero = grade_exam(exam, blank)
    assert zero.score_out_of_10 == 0.0

    fallback = build_exam(SAMPLE, translator=OfflineTranslator())
    multiple = next(question for question in fallback.questions if question.kind == "mc")
    assert "study text" in multiple.prompt.lower()
    assert "translation was unavailable" in multiple.explanation.lower()


def test_short_answer_partial_credit_and_letter_choice():
    short = Question(
        id="s1",
        kind="short",
        prompt="Explain the Bastille.",
        options=[],
        answer="The Bastille was stormed in 1789.",
        keywords=["Bastille", "1789"],
        accept=[["Bastilla", "Bastille"], ["1789"]],
        explanation="It was a fortress in Paris.",
        points=2.0,
    )
    choice = Question(
        id="m1",
        kind="mc",
        prompt="Year?",
        options=["1789", "1776", "1815", "1914"],
        answer="1789",
        keywords=[],
        accept=[["1789"]],
        explanation="The study text says 1789.",
        points=1.5,
    )
    from historia.exam import Exam

    exam = Exam(questions=[choice, short], mode="offline", title="Prueba")
    grade = grade_exam(exam, {"m1": "A", "s1": "People attacked the Bastille."})
    assert grade.items[0].status == "correct"
    assert grade.items[1].status == "partial"
    assert grade.items[1].awarded == 1.0
    assert "1789" in grade.items[1].feedback
    assert grade.score_out_of_10 == 7.1


def test_translation_fallback_without_calling_the_network(monkeypatch: pytest.MonkeyPatch):
    translator = EnglishTranslator()
    assert translator.to_english("Bastilla") == ("Bastille", True)

    def blocked(self, texts):  # noqa: ANN001
        raise RuntimeError("429")

    def memory(self, texts):  # noqa: ANN001
        return [f"EN {text}" for text in texts]

    monkeypatch.setattr(EnglishTranslator, "_google", blocked)
    monkeypatch.setattr(EnglishTranslator, "_mymemory", memory)
    spanish = EnglishTranslator()
    text, ok = spanish.to_english("El pueblo de París tomó la Bastilla en julio.")
    assert ok is True
    assert text.startswith("EN ")
    assert spanish.engine == "MyMemoryTranslator"

    monkeypatch.setattr(EnglishTranslator, "_mymemory", blocked)
    failed = EnglishTranslator()
    original, translated = failed.to_english("La asamblea debatió el decreto durante la sesión.")
    assert translated is False
    assert "asamblea" in original

    untouched = EnglishTranslator()
    english, ok = untouched.to_english("The assembly debated the decree during the session.")
    assert ok is True
    assert english.startswith("The assembly")


def test_txt_docx_and_pdf_extraction(tmp_path: Path):
    txt_path = tmp_path / "tema.txt"
    txt_path.write_bytes("La Bastilla cayó en 1789.\n".encode("latin-1"))
    assert "Bastilla" in extract_path(txt_path)
    paragraph = (
        "El 14 de julio de 1789 el pueblo de París tomó la Bastilla. "
        "Robespierre dirigió el Terror."
    )
    docx_path = tmp_path / "tema.docx"
    write_docx(docx_path, paragraph)
    docx_text = extract_path(docx_path)
    assert "Robespierre" in docx_text
    assert "14 de julio de 1789" in docx_text
    assert "Bastilla" in docx_text
    pdf_path = tmp_path / "tema.pdf"
    write_simple_pdf(pdf_path, paragraph)
    pdf_text = extract_path(pdf_path)
    assert "1789" in pdf_text
    assert "Bastilla" in pdf_text
    with pytest.raises(HistoriaError):
        extract_bytes("apuntes.doc", b"no es un docx")


def test_tts_fallback_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def fail(text: str, dest: Path) -> None:
        raise RuntimeError("servicio no disponible")

    def ok(text: str, dest: Path) -> None:
        dest.write_bytes(b"a" * 240)

    monkeypatch.setattr("historia.video._write_edge", fail)
    monkeypatch.setattr("historia.video._write_gtts", ok)
    _path, engine, warnings = synthesize_speech("Hola, clase.", tmp_path / "voz.mp3", "edge")
    assert engine == "gtts"
    assert warnings

    monkeypatch.setattr("historia.video._write_gtts", fail)
    monkeypatch.setattr("historia.video._write_edge", ok)
    _path, engine, warnings = synthesize_speech("Hola, clase.", tmp_path / "voz2.mp3", "gtts")
    assert engine == "edge"
    assert warnings

    monkeypatch.setattr("historia.video._write_edge", fail)
    monkeypatch.setattr("historia.video._write_gtts", fail)
    with pytest.raises(HistoriaError, match="internet"):
        synthesize_speech("Hola, clase.", tmp_path / "voz3.mp3", "gtts")


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
def test_video_has_h264_and_aac(tmp_path: Path):
    markdown = """# Prueba

## Introducción
Esta es una narración breve para comprobar el vídeo educativo.
- Idea inicial

## Conclusión
Cerramos la lección con una idea final que también se escucha.
- Idea final
"""
    output = tmp_path / "leccion.mp4"
    result = generate_video(markdown, output, engine="gtts", synth=silent_synth)
    assert result.path.is_file()
    assert result.path.stat().st_size > 1000
    streams = probe_streams(result.path)
    video = next(stream for stream in streams if stream.get("codec_type") == "video")
    audio = next(stream for stream in streams if stream.get("codec_type") == "audio")
    assert video["codec_name"] == "h264"
    assert video["width"] == 1280
    assert video["height"] == 720
    assert video["pix_fmt"] == "yuv420p"
    rate = video.get("avg_frame_rate", "0/1")
    numerator, denominator = rate.split("/")
    fps = float(numerator) / float(denominator)
    assert abs(fps - 30) < 0.2
    assert audio["codec_name"] == "aac"
    duration = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(result.path),
        ],
        text=True,
    )
    assert float(duration.strip()) > 0.5


def test_missing_ffmpeg_is_explained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("historia.video.shutil.which", lambda _name: None)
    with pytest.raises(HistoriaError, match="ffmpeg"):
        generate_video("# Tema\n\n## Idea\nTexto suficiente para narrar la lección.\n", tmp_path / "x.mp4")
