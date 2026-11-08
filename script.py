"""Guion en español a partir de las frases más informativas del texto."""

from __future__ import annotations

import re
from dataclasses import dataclass

from historia.analyze import Analysis, analyze, fold, select_sentences
from historia.errors import HistoriaError

LEADS = (
    "Empecemos por el contexto que ayuda a entender el origen del tema.",
    "Estos hechos marcan cómo avanzaron los acontecimientos.",
    "Conviene detenerse en las personas y las decisiones que cambiaron el rumbo.",
    "Más adelante, el proceso dejó estas consecuencias.",
    "Hay otro punto del relato que no conviene pasar por alto.",
)
FALLBACK_HEADINGS = (
    "Causas y contexto",
    "Hechos principales",
    "Protagonistas y decisiones",
    "Consecuencias",
    "Otro momento clave",
)


@dataclass
class Slide:
    heading: str
    narration: str
    bullets: list[str]


@dataclass
class Script:
    title: str
    slides: list[Slide]
    markdown: str
    mode: str


def _shorten(text: str, limit: int = 150) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rsplit(" ", 1)[0]
    return (clipped or text[: limit - 1]).rstrip(".,;:") + "…"


def bullets_from_text(text: str, limit: int = 4) -> list[str]:
    parts = re.split(r"(?<=[\.!\?…])\s+", text.strip())
    bullets: list[str] = []
    for part in parts:
        part = part.strip(" -\t")
        if len(part) < 8:
            continue
        bullets.append(_shorten(part))
        if len(bullets) >= limit:
            break
    if bullets:
        return bullets
    cleaned = re.sub(r"\s+", " ", text).strip()
    return [_shorten(cleaned)] if cleaned else []


def render_markdown(title: str, slides: list[Slide]) -> str:
    lines = [f"# {title}", ""]
    for slide in slides:
        lines.append(f"## {slide.heading}")
        lines.append(slide.narration.strip())
        lines.append("")
        for bullet in slide.bullets:
            lines.append(f"- {bullet}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def parse_markdown(markdown: str) -> tuple[str, list[Slide]]:
    title = "Tema de historia"
    slides: list[Slide] = []
    heading: str | None = None
    body: list[str] = []
    bullets: list[str] = []

    def flush() -> None:
        nonlocal heading, body, bullets
        narration = " ".join(line.strip() for line in body if line.strip()).strip()
        items = [item.strip() for item in bullets if item.strip()]
        if not narration and items:
            narration = " ".join(items)
        if not items and narration:
            items = bullets_from_text(narration)
        if narration:
            slides.append(
                Slide(heading=heading or "Idea principal", narration=narration, bullets=items[:5])
            )
        heading = None
        body = []
        bullets = []

    for line in markdown.splitlines():
        if line.startswith("# "):
            flush()
            title = line[2:].strip() or title
        elif line.startswith("## "):
            flush()
            heading = line[3:].strip() or "Sección"
        elif line.startswith("- "):
            bullets.append(line[2:].strip())
        else:
            body.append(line)
    flush()
    if not slides:
        text = markdown.strip()
        if text:
            slides.append(Slide(heading=title, narration=text, bullets=bullets_from_text(text)))
    return title, slides


def _section_heading(blob: str, analysis: Analysis, used: set[str], index: int) -> str:
    folded_blob = fold(blob)
    for name in analysis.names:
        key = fold(name)
        if key in folded_blob and key not in used:
            used.add(key)
            return name
    for date in analysis.full_dates:
        key = fold(date)
        if key in folded_blob and key not in used:
            used.add(key)
            return date[:1].upper() + date[1:] if date else date
    heading = FALLBACK_HEADINGS[index % len(FALLBACK_HEADINGS)]
    used.add(fold(heading))
    return heading


def build_script(text: str) -> Script:
    cleaned = (text or "").strip()
    if len(cleaned) < 40:
        raise HistoriaError(
            "El texto es demasiado corto para preparar un guion. Añade más contenido.",
            "The text is too short to build a script.",
        )
    found = analyze(cleaned)
    chosen = select_sentences(found, limit=6)
    if not chosen:
        raise HistoriaError(
            "No pude encontrar frases suficientes para el guion.",
            "Could not find enough sentences to build a script.",
        )

    keywords = ", ".join(found.keywords[:4]) or found.title
    dates = ", ".join(found.dates[:5]) or "las referencias temporales del texto"
    names = ", ".join(found.names[:4]) or "los protagonistas que aparecen en el relato"
    slides = [
        Slide(
            heading="Introducción",
            narration=(
                f"Hoy vamos a estudiar {found.title}. "
                "La idea de esta lección es seguir causas, hechos y consecuencias sin perder las fechas "
                "ni los protagonistas. "
                f"Mientras escuchas, fíjate en ideas como {keywords}. "
                f"También van a aparecer referencias como {dates}."
            ),
            bullets=[
                found.title,
                f"Ideas clave: {keywords}",
                f"Referencias: {dates}",
            ],
        )
    ]

    groups = [chosen[index : index + 2] for index in range(0, len(chosen), 2)]
    used_headings: set[str] = set()
    for index, group in enumerate(groups):
        blob = " ".join(sentence.text for sentence in group)
        heading = _section_heading(blob, found, used_headings, index)
        lead = LEADS[index % len(LEADS)]
        narration = lead + " " + " ".join(sentence.text for sentence in group)
        slides.append(
            Slide(
                heading=heading,
                narration=narration,
                bullets=[_shorten(sentence.text, 160) for sentence in group],
            )
        )

    slides.append(
        Slide(
            heading="Conclusión",
            narration=(
                f"Para concluir, {found.title} se entiende mejor si unimos el contexto, "
                "los hechos y lo que cambió después. "
                f"Conviene recordar a {names}. "
                f"Entre las referencias más útiles para repasar están {dates}. "
                "Cuando pases al examen, responde en inglés y apóyate en estos datos del texto, "
                "sin inventar fechas ni nombres que no hayas visto."
            ),
            bullets=[
                f"Protagonistas: {names}",
                f"Para repasar: {dates}",
                "Une causas, hechos y consecuencias",
            ],
        )
    )
    markdown = render_markdown(found.title, slides)
    return Script(title=found.title, slides=slides, markdown=markdown, mode="offline")
