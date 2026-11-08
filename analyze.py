"""Resumen extractivo: frases, fechas, nombres y términos frecuentes."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "setiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
MONTH_SET = set(MONTHS)
MONTH_PATTERN = "|".join(MONTHS)

STOPWORDS = {
    "a", "al", "algo", "algunas", "algunos", "ante", "antes", "aquel", "aquella",
    "aquellas", "aquellos", "aqui", "aquí", "asi", "así", "aunque", "cada", "como",
    "cómo", "con", "contra", "cual", "cuál", "cuando", "cuándo", "de", "del", "desde",
    "donde", "dónde", "durante", "e", "el", "ella", "ellas", "ellos", "en", "entre",
    "era", "eran", "es", "esa", "esas", "ese", "eso", "esos", "esta", "está", "estaba",
    "estan", "están", "estas", "este", "esto", "estos", "fue", "fueron", "ha", "habia",
    "había", "han", "hasta", "hay", "la", "las", "le", "les", "lo", "los", "mas", "más",
    "me", "mi", "mis", "mucho", "muy", "no", "nos", "o", "para", "pero", "poco", "por",
    "porque", "que", "qué", "se", "ser", "si", "sí", "sin", "sobre", "son", "su", "sus",
    "tambien", "también", "te", "tiene", "tienen", "todo", "todos", "tu", "tus", "un",
    "una", "unas", "uno", "unos", "y", "ya", "the", "of", "and", "to", "in", "an",
    "for", "on", "with", "as", "by", "from", "that", "this", "it", "was", "were", "be",
    "or", "at", "is", "are", "his", "her", "their", "which", "into", "its", "after",
    "before", "not", "had", "have", "who", "what", "when",
}

NAME_STOP = {
    "La", "El", "Los", "Las", "En", "Entre", "Antes", "Este", "Esta", "Estos", "Estas",
    "Ese", "Esa", "Esos", "Esas", "Su", "Sus", "Con", "Por", "Para", "Durante", "Según",
    "Como", "Un", "Una", "Unos", "Unas", "Al", "Del", "Tras", "Sobre", "Hasta", "Desde",
    "Cuando", "Donde", "Aunque", "Pero", "También", "Además", "Finalmente", "Después",
    "Luego", "Mientras", "Porque", "Hacia", "Contra", "Mediante", "Hoy", "Aquí", "Allí",
    "Esto", "Eso", "Aquel", "Aquella", "The", "A", "An", "In", "On", "Of", "And", "For",
    "After", "Before", "During", "Between", "Miles", "Estos", "Estas", "Otro", "Otra",
    "Otros", "Otras", "Cada", "Todo", "Toda", "Todos", "Todas", "Sin", "Bajo", "Sobre",
    "Hacia", "Según", "Cabe", "Son", "Fue", "Era", "Hay",
}

DATE_FULL = re.compile(
    rf"\b(\d{{1,2}}\s+de\s+(?:{MONTH_PATTERN})(?:\s+de\s+\d{{3,4}})?|"
    rf"(?:{MONTH_PATTERN})\s+de\s+\d{{3,4}})\b",
    re.IGNORECASE,
)
YEAR = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
SENTENCE_SPLIT = re.compile(r"(?<=[\.!\?…])\s+(?=[A-ZÁÉÍÓÚÜÑ¿¡0-9\"“])")
NAME_RE = re.compile(
    r"\b([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+(?:\s+(?:[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+|[IVXLC]{1,6}))*)\b"
)
ROMAN = re.compile(r"[IVXLC]{1,6}")
TOKEN_RE = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")


@dataclass
class Sentence:
    index: int
    text: str


@dataclass
class Analysis:
    title: str
    sentences: list[Sentence]
    keywords: list[str]
    dates: list[str]
    names: list[str]
    keyword_freq: dict[str, int] = field(default_factory=dict)

    @property
    def full_dates(self) -> list[str]:
        return [item for item in self.dates if not item.isdigit()]

    @property
    def years(self) -> list[str]:
        return [item for item in self.dates if item.isdigit()]


def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.casefold()


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def content_tokens(text: str) -> list[str]:
    return [token for token in tokenize(text) if token not in STOPWORDS and len(token) > 2]


def split_sentences(text: str) -> list[Sentence]:
    clean = re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()
    if not clean:
        return []
    parts = SENTENCE_SPLIT.split(clean)
    sentences: list[Sentence] = []
    for part in parts:
        part = part.strip(" \t\"“”")
        if len(part) < 25:
            continue
        sentences.append(Sentence(index=len(sentences), text=part))
    if not sentences and len(clean) >= 40:
        sentences.append(Sentence(index=0, text=clean[:2000]))
    return sentences


def infer_title(raw_text: str) -> str:
    lines = [line.strip(" #\t") for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return "Tema de historia"
    first = lines[0]
    words = first.split()
    if (
        len(lines) > 1
        and len(first) <= 80
        and 1 <= len(words) <= 6
        and not first.endswith((".", "!", "?"))
        and not YEAR.search(first)
    ):
        return first
    sentences = split_sentences(raw_text)
    if sentences:
        words = sentences[0].text.split()
        return " ".join(words[:8]).rstrip(".,;:")
    return first[:80]


def _body_without_title(raw_text: str, title: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if lines and lines[0].strip(" #\t") == title:
        return "\n".join(lines[1:])
    return raw_text


def extract_dates(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    occupied: list[tuple[int, int]] = []
    for match in DATE_FULL.finditer(text):
        value = re.sub(r"\s+", " ", match.group(1)).strip()
        key = fold(value)
        occupied.append(match.span())
        if key not in seen:
            seen.add(key)
            found.append(value)
    for match in YEAR.finditer(text):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        value = match.group(1)
        if value not in seen:
            seen.add(value)
            found.append(value)
    return found


def _is_sentence_initial(text: str, start: int) -> bool:
    previous = text[:start].rstrip()
    if not previous:
        return True
    return previous[-1] in ".!?\n¡¿:;\"“”"


def _keep_name_shape(name: str) -> bool:
    if name in NAME_STOP or name.lower() in STOPWORDS:
        return False
    if len(name) < 3:
        return False
    if fold(name) in MONTH_SET:
        return False
    if all(fold(part) in MONTH_SET or part in NAME_STOP for part in name.split()):
        return False
    return True


def extract_names(text: str) -> list[str]:
    """Nombres y lugares a lo largo de todo el texto, no solo los del primer párrafo."""
    grouped: dict[str, dict[str, object]] = {}
    for match in NAME_RE.finditer(text):
        parts = re.sub(r"\s+", " ", match.group(1)).strip().split()
        while parts and parts[0] in NAME_STOP:
            parts = parts[1:]
        name = " ".join(parts)
        if not _keep_name_shape(name):
            continue
        key = fold(name)
        bucket = grouped.setdefault(key, {"name": name, "starts": []})
        bucket["starts"].append(match.start())  # type: ignore[union-attr]
        if name[0].isupper():
            bucket["name"] = name
    for key in list(grouped):
        if any(other != key and other.startswith(key + " ") for other in grouped):
            del grouped[key]
    candidates: list[tuple[str, list[int], bool]] = []
    for bucket in grouped.values():
        name = str(bucket["name"])
        starts = list(bucket["starts"])  # type: ignore[arg-type]
        parts = name.split()
        has_roman = bool(parts) and bool(ROMAN.fullmatch(parts[-1]))
        multi = len(parts) > 1 or has_roman
        non_initial = any(not _is_sentence_initial(text, start) for start in starts)
        if multi or non_initial or len(starts) >= 2:
            candidates.append((name, starts, multi))
    if not candidates:
        return []
    length = max(len(text), 1)
    bands: list[list[tuple[str, list[int], bool]]] = [[], [], []]
    for name, starts, multi in candidates:
        band = min(2, int(starts[0] / length * 3))
        bands[band].append((name, starts, multi))
    chosen: list[tuple[int, str]] = []
    seen: set[str] = set()
    for band in bands:
        band.sort(key=lambda item: (-len(item[1]), 0 if item[2] else 1, item[1][0]))
        for name, starts, _multi in band[:7]:
            key = fold(name)
            if key in seen:
                continue
            seen.add(key)
            chosen.append((starts[0], name))
    chosen.sort()
    return [name for _start, name in chosen]


def top_keywords(text: str, names: list[str], limit: int = 12) -> tuple[list[str], dict[str, int]]:
    blocked = {fold(name) for name in names}
    blocked.update(fold(part) for name in names for part in name.split())
    surface: dict[str, str] = {}
    freq: dict[str, int] = {}
    for raw in TOKEN_RE.findall(text):
        token = raw.lower()
        if token in STOPWORDS or len(token) <= 2 or token.isdigit():
            continue
        if token.endswith("ó") or token.endswith("aron") or token.endswith("ieron"):
            continue
        key = fold(token)
        if key in blocked or key in MONTH_SET:
            continue
        freq[key] = freq.get(key, 0) + 1
        current = surface.get(key)
        if current is None or (raw[0].isupper() and current[0].islower()):
            surface[key] = raw
    ranked = sorted(freq.items(), key=lambda item: (-item[1], item[0]))
    keywords = [surface[key] for key, _count in ranked[:limit]]
    return keywords, freq


def score_sentence(sentence: str, freq: dict[str, int], dates: list[str], names: list[str]) -> float:
    tokens = [fold(token) for token in content_tokens(sentence)]
    if not tokens:
        return 0.0
    base = sum(freq.get(token, 0) for token in tokens) / len(tokens)
    folded = fold(sentence)
    bonus = 0.0
    if any(fold(date) in folded for date in dates):
        bonus += 3.0
    if any(fold(name) in folded for name in names):
        bonus += 2.0
    words = len(sentence.split())
    if 12 <= words <= 45:
        bonus += 1.0
    return base + bonus


def analyze(text: str) -> Analysis:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    title = infer_title(cleaned)
    body = _body_without_title(cleaned, title)
    sentences = split_sentences(body if body.strip() else cleaned)
    if not sentences:
        sentences = split_sentences(cleaned)
    dates = extract_dates(cleaned)
    names = extract_names(body if body.strip() else cleaned)
    title_folds = {fold(part) for part in title.split() if len(part) > 2}
    names = [
        name
        for name in names
        if fold(name) not in title_folds
        and not all(fold(part) in title_folds for part in name.split())
    ]
    keywords, freq = top_keywords(cleaned, names)
    return Analysis(
        title=title,
        sentences=sentences,
        keywords=keywords,
        dates=dates,
        names=names,
        keyword_freq=freq,
    )


def select_sentences(analysis: Analysis, limit: int = 6) -> list[Sentence]:
    """Elige frases repartidas a lo largo del texto, no solo las del principio."""
    sentences = analysis.sentences
    if len(sentences) <= limit:
        return list(sentences)
    buckets: list[list[Sentence]] = [[] for _ in range(limit)]
    for index, sentence in enumerate(sentences):
        bucket = min(limit - 1, index * limit // len(sentences))
        buckets[bucket].append(sentence)
    chosen: list[Sentence] = []
    for bucket in buckets:
        if not bucket:
            continue
        best = max(
            bucket,
            key=lambda sentence: (
                score_sentence(sentence.text, analysis.keyword_freq, analysis.dates, analysis.names),
                -sentence.index,
            ),
        )
        chosen.append(best)
    chosen.sort(key=lambda sentence: sentence.index)
    return chosen
