"""Recorre extracción, guion, vídeo real y examen con el ejemplo y con PDF/DOCX."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from historia.analyze import fold  # noqa: E402
from historia.exam import build_exam, grade_exam  # noqa: E402
from historia.extract import extract_path  # noqa: E402
from historia.script import build_script  # noqa: E402
from historia.video import generate_video, probe_streams, synthesize_speech  # noqa: E402
from tests.test_pipeline import write_docx, write_simple_pdf  # noqa: E402


def _perfect_answers(exam) -> dict[str, str]:
    answers = {}
    for question in exam.questions:
        if question.kind == "mc":
            answers[question.id] = question.answer
        else:
            answers[question.id] = " ".join(form for group in question.accept for form in group)
    return answers


def _mixed_answers(exam) -> dict[str, str]:
    answers = {}
    seen_short = False
    multiple = [question for question in exam.questions if question.kind == "mc"]
    for question in exam.questions:
        if question.kind == "mc":
            if question is multiple[-1]:
                answers[question.id] = next(
                    option for option in question.options if fold(option) != fold(question.answer)
                )
            else:
                answers[question.id] = question.answer
        elif not seen_short:
            seen_short = True
            first = question.accept[0][0] if question.accept else question.keywords[0]
            answers[question.id] = f"I remember {first}, but I am unsure about the rest."
        else:
            answers[question.id] = ""
    return answers


def _check_tokens(name: str, text: str, failures: list[str]) -> None:
    for token in ("1789", "Bastilla", "Robespierre"):
        if token.casefold() not in text.casefold():
            failures.append(f"{name}: el texto extraído no contiene {token}")


def _summarize_streams(path: Path) -> str:
    parts = []
    for stream in probe_streams(path):
        kind = stream.get("codec_type")
        codec = stream.get("codec_name")
        if kind == "video":
            rate = stream.get("avg_frame_rate")
            parts.append(
                f"video {codec} {stream.get('width')}x{stream.get('height')} "
                f"{stream.get('pix_fmt')} {rate}"
            )
        elif kind == "audio":
            parts.append(f"audio {codec} {stream.get('sample_rate')} Hz")
    return "; ".join(parts)


def main() -> int:
    sample = (ROOT / "ejemplo_tema.txt").read_text(encoding="utf-8")
    out = ROOT / "output" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    pdf_path = out / "revolucion.pdf"
    docx_path = out / "revolucion.docx"
    write_simple_pdf(pdf_path, sample)
    write_docx(docx_path, sample, heading=None, with_table=False)

    sources = {
        "txt": sample,
        "pdf": extract_path(pdf_path),
        "docx": extract_path(docx_path),
    }
    failures: list[str] = []
    for name, text in sources.items():
        print(f"\n=== {name}: {len(text)} caracteres ===")
        _check_tokens(name, text, failures)
        script = build_script(text)
        script_path = out / f"guion_{name}.txt"
        script_path.write_text(script.markdown, encoding="utf-8")
        print(f"guion: {script.title} · {len(script.slides)} secciones · {script_path.name}")
        exam = build_exam(text)
        print(f"examen: {len(exam.questions)} preguntas · título {exam.title!r}")
        for question in exam.questions:
            preview = " ".join(question.prompt.split())
            print(f"  {question.id} {question.kind}: {preview[:160]}")
            if question.kind == "mc":
                print(f"    opciones: {question.options}")
                print(f"    respuesta: {question.answer}")
        perfect = grade_exam(exam, _perfect_answers(exam))
        mixed = grade_exam(exam, _mixed_answers(exam))
        print(f"nota con respuestas modelo: {perfect.score_out_of_10:.1f} / 10")
        print(f"nota con respuestas mezcladas: {mixed.score_out_of_10:.1f} / 10")
        for item in mixed.items:
            feedback = " ".join(item.feedback.split())
            print(f"  {item.question_id} {item.status} {item.awarded:.2f}/{item.maximum:.2f} · {feedback[:180]}")
        if perfect.score_out_of_10 != 10.0:
            failures.append(f"{name}: la nota perfecta fue {perfect.score_out_of_10}")
        if not 0 < mixed.score_out_of_10 < 10:
            failures.append(f"{name}: la nota mezclada quedó en {mixed.score_out_of_10}")
        video_path = out / f"leccion_{name}.mp4"
        print(f"generando vídeo {video_path.name}…")
        result = generate_video(script.markdown, video_path, engine="gtts")
        summary = _summarize_streams(result.path)
        print(f"vídeo: {summary}")
        print(f"avisos: {result.warnings or 'ninguno'} · motor {result.engine}")
        kinds = {stream.get("codec_type") for stream in probe_streams(result.path)}
        if "video" not in kinds or "audio" not in kinds:
            failures.append(f"{name}: el MP4 no tiene vídeo y audio")

    edge_path = out / "edge_prueba.mp3"
    try:
        synthesize_speech("La Bastilla fue tomada el catorce de julio de 1789.", edge_path, "edge")
        print(f"\nedge-tts: audio de prueba en {edge_path.name} ({edge_path.stat().st_size} bytes)")
    except Exception as exc:  # noqa: BLE001
        print(f"\nedge-tts no completó la prueba (gTTS sigue siendo el respaldo): {exc}")

    if failures:
        print("\nFALLOS:")
        for item in failures:
            print(f"- {item}")
        return 1
    print("\nPipeline completo: texto, PDF, DOCX, guion, vídeo y examen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
