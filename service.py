"""Une el modo local y el modo con modelo para la interfaz y las pruebas."""

from __future__ import annotations

from historia.errors import HistoriaError
from historia.exam import Exam, ExamGrade, grade_exam
from historia.llm import generate_exam_llm, generate_script_llm, grade_short_llm, safe_detail
from historia.script import Script, build_script
from historia.settings import GenerationSettings

MAX_CHARS = 40000


def prepare_text(text: str, lang: str = "es") -> tuple[str, list[str]]:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(cleaned) < 40:
        raise HistoriaError(
            "Añade un texto más largo en la pestaña «Subir tema».",
            "Add a longer topic text in the Upload tab before continuing.",
        )
    warnings: list[str] = []
    if len(cleaned) > MAX_CHARS:
        cleaned = cleaned[:MAX_CHARS]
        message_es = (
            f"El texto supera {MAX_CHARS} caracteres y se recortó para esta lección."
        )
        message_en = f"The source was longer than {MAX_CHARS} characters and was trimmed."
        warnings.append(message_en if lang == "en" else message_es)
    return cleaned, warnings


def generate_script(text: str, settings: GenerationSettings) -> tuple[Script, list[str]]:
    cleaned, warnings = prepare_text(text, "es")
    if settings.use_llm:
        if not settings.key:
            raise HistoriaError(
                "El modo con modelo necesita una clave API. Escríbela en la barra lateral "
                "o define la variable OPENAI_API_KEY.",
                "Language-model mode needs an API key in the sidebar or in OPENAI_API_KEY.",
            )
        try:
            return generate_script_llm(cleaned, settings), warnings
        except Exception as exc:  # noqa: BLE001
            warnings.append(
                "No se pudo usar el modelo de lenguaje ("
                + safe_detail(exc, settings.key)
                + "). El guion se preparó con las reglas locales."
            )
    script = build_script(cleaned)
    if any("modelo" in warning for warning in warnings):
        script.mode = "offline (respaldo)"
    return script, warnings


def generate_exam(text: str, settings: GenerationSettings) -> tuple[Exam, list[str]]:
    cleaned, warnings = prepare_text(text, "en")
    if settings.use_llm:
        if not settings.key:
            raise HistoriaError(
                "El modo con modelo necesita una clave API.",
                "Language-model mode needs an API key in the sidebar or in OPENAI_API_KEY.",
            )
        try:
            exam = generate_exam_llm(cleaned, settings)
            return exam, warnings
        except Exception as exc:  # noqa: BLE001
            warnings.append(
                "The language model was unavailable ("
                + safe_detail(exc, settings.key)
                + "). This exam was built offline from the source text."
            )
    exam = build_exam_offline(cleaned)
    if any("language model" in warning for warning in warnings):
        exam.mode = "offline (fallback)"
    return exam, warnings


def build_exam_offline(text: str) -> Exam:
    from historia.exam import build_exam

    return build_exam(text)


def grade_answers(exam: Exam, answers: dict[str, str], settings: GenerationSettings) -> ExamGrade:
    grader = None
    if settings.use_llm and settings.key:
        def grader(question, user_answer):  # noqa: ANN001
            return grade_short_llm(settings, question, user_answer)

    return grade_exam(exam, answers, short_grader=grader)
