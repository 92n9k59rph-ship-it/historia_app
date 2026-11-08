"""Modo opcional con un modelo compatible con la API de OpenAI."""

from __future__ import annotations

import base64
import io
import json
import re

from historia.analyze import analyze, content_tokens, fold
from historia.errors import HistoriaError
from historia.exam import MC_POINTS, SHORT_POINTS, Exam, Question
from historia.script import Script, parse_markdown, render_markdown
from historia.settings import GenerationSettings

SCRIPT_SYSTEM = """Eres un profesor de historia y preparas una lección hablada para estudiantes de secundaria.
Escribe en español claro, cercano y preciso.
Usa solo datos que estén en el texto fuente. No inventes fechas, nombres, cifras ni causas.
Si falta información, no la rellenes.
Devuelve únicamente markdown con esta estructura:
# Título breve
## Introducción
Párrafo para narrar en voz alta, de 4 a 6 frases.
- viñeta breve
- viñeta breve
## Un título de sección concreto
Párrafo narrado.
- viñeta breve
## Conclusión
Párrafo de cierre.
- viñeta breve
Incluye entre 4 y 6 secciones, contando la introducción y la conclusión."""

EXAM_SYSTEM = """You write fair secondary-school history exams in English.
Use only facts from the source text. Do not invent dates, names, or causes.
Return JSON only, with no markdown fence, in this shape:
{"questions":[
  {"kind":"mc","prompt":"...","options":["...","...","...","..."],"answer":"...","explanation":"...","keywords":[]},
  {"kind":"short","prompt":"...","options":[],"answer":"a model answer","explanation":"...","keywords":["...","..."]}
]}
Include 4 multiple-choice questions and 2 short-answer questions.
For multiple choice, "answer" must be copied exactly from "options".
Short-answer keywords are 3 to 6 facts a good answer should mention.
Every prompt, option, explanation, keyword, and model answer must be in English."""

GRADE_SYSTEM = """You grade one short history answer.
Return JSON only: {"score": <number>, "feedback": "<two sentences in English>"}.
The score uses the point scale given in the user message, from 0 to the maximum.
Do not use a 0-10 scale unless the maximum is 10.
Give full marks when the idea is right even if the wording differs.
Give partial credit when only some expected facts are present.
Be specific and kind in the feedback."""


def safe_detail(exc: BaseException, secret: str) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    if secret:
        text = text.replace(secret, "••••")
    return re.sub(r"\s+", " ", text)[:400]


def extract_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise HistoriaError(
                "No se pudo leer el JSON del modelo.",
                "Could not parse the model JSON.",
            )
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise HistoriaError(
                "No se pudo leer el JSON del modelo.",
                "Could not parse the model JSON.",
            ) from exc
    if isinstance(data, list):
        return {"questions": data}
    if not isinstance(data, dict):
        raise HistoriaError(
            "El JSON del modelo no tiene el formato esperado.",
            "Unexpected model JSON.",
        )
    return data


def chat(settings: GenerationSettings, system: str, user: str) -> str:
    if not settings.key:
        raise HistoriaError(
            "Falta la clave API.",
            "Missing API key.",
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise HistoriaError(
            "Falta el paquete openai. Instálalo con pip.",
            "The openai package is not installed.",
        ) from exc
    client = OpenAI(api_key=settings.key, base_url=settings.url, timeout=90.0)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        response = client.chat.completions.create(
            model=settings.model_name,
            messages=messages,
            temperature=0.4,
        )
    except Exception as exc:
        lowered = str(exc).lower()
        if "temperature" not in lowered and "unsupported" not in lowered:
            detail = safe_detail(exc, settings.key)
            raise HistoriaError(detail, detail) from exc
        try:
            response = client.chat.completions.create(
                model=settings.model_name,
                messages=messages,
            )
        except Exception as retry_exc:
            detail = safe_detail(retry_exc, settings.key)
            raise HistoriaError(detail, detail) from retry_exc
    content = ""
    if response.choices:
        content = response.choices[0].message.content or ""
    if not str(content).strip():
        raise HistoriaError(
            "El modelo devolvió una respuesta vacía.",
            "The model returned an empty response.",
        )
    return str(content)


def _source_block(text: str) -> str:
    clipped = text.strip()
    note = ""
    if len(clipped) > 12000:
        clipped = clipped[:12000]
        note = "\n\n[El texto fuente se recortó por longitud.]\n"
    return clipped + note


def generate_script_llm(text: str, settings: GenerationSettings) -> Script:
    raw = chat(
        settings,
        SCRIPT_SYSTEM,
        "Prepara el guion en español a partir de este texto fuente:\n\n" + _source_block(text),
    )
    title, slides = parse_markdown(raw)
    if len(slides) < 2:
        raise HistoriaError(
            "El modelo no devolvió un guion con secciones.",
            "The model did not return a sectioned script.",
        )
    markdown = render_markdown(title, slides)
    return Script(title=title, slides=slides, markdown=markdown, mode="llm")


def _exam_from_payload(payload: dict, title: str) -> Exam:
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise HistoriaError(
            "El modelo no devolvió preguntas.",
            "The model did not return questions.",
        )
    questions: list[Question] = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or item.get("type") or "").strip().lower()
        if kind in {"multiple_choice", "multiple-choice", "mcq"}:
            kind = "mc"
        if kind in {"open", "short_answer", "short-answer", "sa"}:
            kind = "short"
        prompt = str(item.get("prompt") or item.get("question") or "").strip()
        if kind not in {"mc", "short"} or not prompt:
            continue
        explanation = str(item.get("explanation") or "").strip()
        if kind == "mc":
            options = [str(option).strip() for option in item.get("options") or [] if str(option).strip()]
            answer = str(item.get("answer") or "").strip()
            if re.fullmatch(r"[A-Da-d]", answer) and options:
                index = ord(answer.upper()) - ord("A")
                if index < len(options):
                    answer = options[index]
            matched = next((option for option in options if fold(option) == fold(answer)), None)
            if matched is None:
                continue
            if len(options) > 4:
                others = [option for option in options if fold(option) != fold(matched)]
                options = [matched, *others[:3]]
            if len(options) < 3:
                continue
            questions.append(
                Question(
                    id="",
                    kind="mc",
                    prompt=prompt,
                    options=options,
                    answer=matched,
                    keywords=[],
                    accept=[[matched]],
                    explanation=explanation or f"The expected answer is “{matched}”.",
                    points=MC_POINTS,
                )
            )
        else:
            keywords = [str(keyword).strip() for keyword in item.get("keywords") or [] if str(keyword).strip()]
            model_answer = str(item.get("answer") or item.get("model_answer") or "").strip()
            if len(keywords) < 2 and model_answer:
                keywords = content_tokens(model_answer)[:6]
            if not keywords:
                continue
            questions.append(
                Question(
                    id="",
                    kind="short",
                    prompt=prompt,
                    options=[],
                    answer=model_answer,
                    keywords=keywords,
                    accept=[[keyword] for keyword in keywords],
                    explanation=explanation
                    or f"A strong answer includes: {', '.join(keywords)}.",
                    points=SHORT_POINTS,
                )
            )
        if len(questions) >= 8:
            break
    kinds = {question.kind for question in questions}
    if "mc" not in kinds or "short" not in kinds:
        raise HistoriaError(
            "El examen del modelo debe incluir opción múltiple y respuesta corta.",
            "The model exam must include multiple choice and short answer questions.",
        )
    for index, question in enumerate(questions, start=1):
        question.id = f"q{index}"
    return Exam(questions=questions, mode="llm", title=title)


def generate_exam_llm(text: str, settings: GenerationSettings) -> Exam:
    title = analyze(text).title
    raw = chat(
        settings,
        EXAM_SYSTEM,
        "Write the exam from this source text:\n\n" + _source_block(text),
    )
    return _exam_from_payload(extract_json(raw), title)


def grade_short_llm(settings: GenerationSettings, question: Question, user_answer: str) -> tuple[float, str]:
    if not user_answer.strip():
        return 0.0, "You did not answer this question."
    raw = chat(
        settings,
        GRADE_SYSTEM,
        (
            f"Maximum points: {question.points}\n"
            f"Question: {question.prompt}\n"
            f"Model answer: {question.answer}\n"
            f"Expected keywords: {', '.join(question.keywords)}\n"
            f"Student answer: {user_answer.strip()}"
        ),
    )
    data = extract_json(raw)
    try:
        score = float(data.get("score", 0))
    except (TypeError, ValueError) as exc:
        raise HistoriaError(
            "El modelo no devolvió una nota numérica.",
            "The model did not return a numeric score.",
        ) from exc
    feedback = str(data.get("feedback") or "").strip() or "Reviewed by the language model."
    return score, feedback


def _jpeg_for_vision(data: bytes) -> bytes:
    from PIL import Image

    from historia.ocr import load_image

    image = load_image(data).convert("RGB")
    image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=75)
    return buffer.getvalue()


def ocr_with_vision(photos: list[tuple[str, bytes]], settings: GenerationSettings) -> str:
    """Transcribe fotos con un modelo compatible con la API de OpenAI. Una foto por llamada."""
    if not settings.key:
        raise HistoriaError(
            "El OCR con modelo necesita una clave API en la barra lateral, en OPENAI_API_KEY o en los secretos.",
            "Vision OCR needs an API key.",
        )
    if not photos:
        raise HistoriaError("No hay fotos para leer.", "There are no photos to read.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise HistoriaError("Falta el paquete openai.", "The openai package is not installed.") from exc

    client = OpenAI(api_key=settings.key, base_url=settings.url, timeout=90.0)
    pages: list[str] = []
    for _name, data in photos[:8]:
        encoded = base64.b64encode(_jpeg_for_vision(data)).decode("ascii")
        messages = [
            {
                "role": "system",
                "content": (
                    "Transcribes textbook photos. Return only the text you can read, "
                    "in the original language, keeping paragraphs. Do not invent words."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this page."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                    },
                ],
            },
        ]
        try:
            try:
                response = client.chat.completions.create(
                    model=settings.model_name,
                    temperature=0,
                    messages=messages,
                )
            except Exception as exc:
                if "temperature" not in str(exc).lower():
                    raise
                response = client.chat.completions.create(
                    model=settings.model_name,
                    messages=messages,
                )
        except Exception as exc:
            detail = safe_detail(exc, settings.key)
            raise HistoriaError(
                f"El modelo de visión no pudo leer la foto: {detail}",
                f"The vision model could not read the photo: {detail}",
            ) from exc
        content = ""
        if response.choices:
            content = response.choices[0].message.content or ""
        cleaned = str(content).strip()
        if cleaned:
            pages.append(cleaned)
    if not pages:
        raise HistoriaError(
            "El modelo no devolvió texto.",
            "The model returned no text.",
        )
    return "\n\n".join(pages)
