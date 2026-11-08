"""Examen en inglés: opción múltiple, respuesta corta y nota sobre 10."""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field

from historia.analyze import DATE_FULL, YEAR, Analysis, analyze, content_tokens, fold
from historia.errors import HistoriaError
from historia.translate import EnglishTranslator, mark_blank, restore_blank

MC_COUNT = 4
SHORT_COUNT = 2
MC_POINTS = 1.5
SHORT_POINTS = 2.0
EXTRA_YEARS = ["1492", "1776", "1815", "1848", "1914", "1945", "1989"]
EXTRA_TERMS = [
    "parlamento",
    "imperio",
    "colonia",
    "tratado",
    "censura",
    "gremio",
    "concordato",
    "virrey",
]


@dataclass
class Question:
    id: str
    kind: str
    prompt: str
    options: list[str]
    answer: str
    keywords: list[str]
    accept: list[list[str]] = field(default_factory=list)
    explanation: str = ""
    points: float = 1.0


@dataclass
class Exam:
    questions: list[Question]
    mode: str
    title: str


@dataclass
class QuestionGrade:
    question_id: str
    awarded: float
    maximum: float
    feedback: str
    status: str
    user_answer: str


@dataclass
class ExamGrade:
    items: list[QuestionGrade]
    score_out_of_10: float
    summary: str


@dataclass
class _McDraft:
    sentence_index: int
    sentence: str
    cloze: str
    marked: str
    answer: str
    distractors: list[str]
    family: str


@dataclass
class _ShortDraft:
    sentence_index: int
    term: str
    sentence: str
    keywords: list[str]


def _unique(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = re.sub(r"\s+", " ", item).strip()
        key = fold(cleaned)
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _seeded(text: str) -> random.Random:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:8], 16))


def _once(sentence: str, span: str) -> bool:
    return len(re.findall(re.escape(span), sentence, flags=re.IGNORECASE)) == 1


def _contains(answer: str, keyword: str) -> bool:
    needle = fold(keyword).strip()
    if not needle:
        return False
    haystack = fold(answer)
    if " " in needle or len(needle) >= 5:
        return needle in haystack
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def _distractors(answer: str, family: str, analysis: Analysis, cloze: str) -> list[str]:
    if family == "date_full":
        pool = list(analysis.full_dates)
        extra: list[str] = []
    elif family == "year":
        pool = list(analysis.years)
        extra = list(EXTRA_YEARS)
    elif family == "name":
        pool = list(analysis.names)
        extra = list(analysis.keywords)
    else:
        pool = list(analysis.keywords) + list(analysis.names)
        extra = list(EXTRA_TERMS)
    picked: list[str] = []
    seen = {fold(answer)}
    cloze_fold = fold(cloze)
    answer_fold = fold(answer)

    def consider(items: list[str]) -> None:
        for item in items:
            key = fold(item)
            if not key or key in seen:
                continue
            if answer_fold and (answer_fold in key or key in answer_fold):
                continue
            if key in cloze_fold:
                continue
            seen.add(key)
            picked.append(item)
            if len(picked) == 3:
                return

    consider(pool)
    if len(picked) < 3:
        consider(extra)
    return picked


def _spans(sentence: str, analysis: Analysis) -> dict[str, list[str]]:
    grouped = {"date_full": [], "year": [], "name": [], "term": []}
    for match in DATE_FULL.finditer(sentence):
        grouped["date_full"].append(re.sub(r"\s+", " ", match.group(1)).strip())
    full = " ".join(grouped["date_full"])
    for match in YEAR.finditer(sentence):
        year = match.group(1)
        if year in full:
            continue
        grouped["year"].append(year)
    folded = fold(sentence)
    for name in analysis.names:
        if fold(name) in folded:
            grouped["name"].append(name)
    title_words = {fold(part) for part in analysis.title.split() if len(part) > 2}
    for term in analysis.keywords:
        if fold(term) in title_words or analysis.keyword_freq.get(fold(term), 0) < 2:
            continue
        if len(term) > 4 and re.search(rf"\b{re.escape(term)}\b", sentence, flags=re.IGNORECASE):
            grouped["term"].append(term)
    return {key: _unique(value) for key, value in grouped.items()}


def _pick_mc(analysis: Analysis) -> list[_McDraft]:
    drafts: list[_McDraft] = []
    used_answers: set[str] = set()
    for sentence in analysis.sentences:
        grouped = _spans(sentence.text, analysis)
        chosen: _McDraft | None = None
        for family in ("date_full", "year", "name", "term"):
            for span in grouped[family]:
                if fold(span) in used_answers or not _once(sentence.text, span):
                    continue
                cloze = re.sub(re.escape(span), "____", sentence.text, count=1, flags=re.IGNORECASE)
                distractors = _distractors(span, family, analysis, cloze)
                if len(distractors) < 3:
                    continue
                chosen = _McDraft(
                    sentence_index=sentence.index,
                    sentence=sentence.text,
                    cloze=cloze,
                    marked=mark_blank(sentence.text, span),
                    answer=span,
                    distractors=distractors[:3],
                    family=family,
                )
                break
            if chosen:
                break
        if chosen is None:
            continue
        drafts.append(chosen)
        used_answers.add(fold(chosen.answer))
        if len(drafts) >= MC_COUNT:
            break
    return drafts


def _keywords_for(sentence: str, analysis: Analysis, term: str) -> list[str]:
    keys: list[str] = []
    seen = {fold(term)}
    folded = fold(sentence)
    for item in list(analysis.dates) + list(analysis.names) + list(analysis.keywords):
        key = fold(item)
        if not key or key in seen or key not in folded or key == fold(term):
            continue
        seen.add(key)
        keys.append(item)
        if len(keys) >= 4:
            return keys
    for token in content_tokens(sentence):
        key = fold(token)
        if key in seen or len(token) < 5:
            continue
        seen.add(key)
        keys.append(token)
        if len(keys) >= 4:
            break
    return keys or [term]


def _pick_short(analysis: Analysis, used_sentences: set[int]) -> list[_ShortDraft]:
    drafts: list[_ShortDraft] = []
    people: list[str] = []
    dated: list[str] = []
    places: list[str] = []
    words: list[str] = []
    for term in _unique(list(analysis.names) + list(analysis.full_dates) + list(analysis.keywords)):
        parts = term.split()
        roman = bool(parts) and bool(re.fullmatch(r"[IVXLC]{1,6}", parts[-1]))
        if term in analysis.names and (len(parts) > 1 or roman):
            people.append(term)
        elif term in analysis.full_dates:
            dated.append(term)
        elif term in analysis.names:
            places.append(term)
        else:
            words.append(term)
    for term in people + dated + places + words:
        host = None
        for sentence in analysis.sentences:
            if sentence.index in used_sentences:
                continue
            if fold(term) in fold(sentence.text):
                host = sentence
                break
        if host is None:
            for sentence in analysis.sentences:
                if fold(term) in fold(sentence.text):
                    host = sentence
                    break
        if host is None:
            continue
        drafts.append(
            _ShortDraft(
                sentence_index=host.index,
                term=term,
                sentence=host.text,
                keywords=_keywords_for(host.text, analysis, term),
            )
        )
        used_sentences.add(host.index)
        if len(drafts) >= SHORT_COUNT:
            break
    return drafts


def _as_english(text: str, translator: EnglishTranslator, family: str) -> tuple[str, bool]:
    if family == "year" or text.strip().isdigit():
        return text.strip(), True
    return translator.to_english(text)


def _forms(keyword: str, translator: EnglishTranslator) -> tuple[list[str], str]:
    family = "year" if keyword.strip().isdigit() else "term"
    translated, ok = _as_english(keyword, translator, family)
    display = translated if ok else keyword
    forms = [display, keyword]
    forms.extend(YEAR.findall(keyword))
    if ok:
        forms.extend(YEAR.findall(translated))
    # Conserva el orden y quita duplicados.
    unique_forms: list[str] = []
    seen: set[str] = set()
    for form in forms:
        key = fold(form)
        if key and key not in seen:
            seen.add(key)
            unique_forms.append(form)
    return unique_forms, display


def _assemble_mc(index: int, draft: _McDraft, translator: EnglishTranslator) -> Question:
    originals = [draft.answer, *draft.distractors]
    translated: list[str] = []
    seen: set[str] = set()
    for option in originals:
        text, ok = _as_english(option, translator, draft.family)
        if not ok:
            text = option
        if fold(text) in seen:
            text = option
        if fold(text) in seen:
            continue
        seen.add(fold(text))
        translated.append(text)
    marked_en, marked_ok = translator.to_english(draft.marked)
    restored = restore_blank(marked_en) if marked_ok else None
    sentence_en, sentence_ok = translator.to_english(draft.sentence)
    use_translation = bool(restored) and marked_ok and len(translated) >= 4
    rng = _seeded(draft.sentence + "\n" + draft.answer)
    if use_translation:
        options = list(translated)
        answer = translated[0]
        prompt = f"Which option correctly completes the sentence?\n\n{restored}"
    else:
        options = list(originals)
        answer = draft.answer
        prompt = (
            "Which option correctly fills the blank in this sentence from the study text?\n\n"
            f"\"{draft.cloze}\""
        )
    rng.shuffle(options)
    if sentence_ok:
        explanation = f"The study text says: {sentence_en}"
    elif use_translation:
        explanation = f"The expected completion is “{answer}”."
    else:
        explanation = (
            "Machine translation was unavailable, so the sentence stays in the source language. "
            f"The expected completion is “{answer}”."
        )
    return Question(
        id=f"q{index}",
        kind="mc",
        prompt=prompt,
        options=options,
        answer=answer,
        keywords=[],
        accept=[[answer]],
        explanation=explanation,
        points=MC_POINTS,
    )


def _assemble_short(index: int, draft: _ShortDraft, translator: EnglishTranslator) -> Question:
    term_en, term_ok = _as_english(draft.term, translator, "year" if draft.term.isdigit() else "term")
    sentence_en, sentence_ok = translator.to_english(draft.sentence)
    accept: list[list[str]] = []
    display: list[str] = []
    for keyword in draft.keywords:
        forms, label = _forms(keyword, translator)
        accept.append(forms)
        display.append(label)
    if term_ok:
        prompt = f"In a few sentences, explain the historical importance of {term_en} in this topic."
    else:
        prompt = (
            "In a few sentences, explain the historical importance of the following point "
            "from the study text.\n\n"
            f"Focus: {draft.term}\n\"{draft.sentence}\""
        )
    ideas = ", ".join(display)
    if sentence_ok:
        explanation = f"A strong answer mentions ideas from this passage: {sentence_en} Expected ideas: {ideas}."
    else:
        explanation = (
            "Translation was unavailable. A strong answer covers these ideas from the source: "
            f"{ideas}."
        )
    return Question(
        id=f"q{index}",
        kind="short",
        prompt=prompt,
        options=[],
        answer=sentence_en if sentence_ok else draft.sentence,
        keywords=display,
        accept=accept,
        explanation=explanation,
        points=SHORT_POINTS,
    )


def build_exam(text: str, translator: EnglishTranslator | None = None) -> Exam:
    cleaned = (text or "").strip()
    if len(cleaned) < 40:
        raise HistoriaError(
            "No hay suficiente texto para crear un examen.",
            "There is not enough text to build an exam.",
        )
    found = analyze(cleaned)
    if not found.sentences:
        raise HistoriaError(
            "No hay frases suficientes para crear un examen.",
            "There are not enough sentences to build an exam.",
        )
    translator = translator or EnglishTranslator()
    multiple = _pick_mc(found)
    shorts = _pick_short(found, {item.sentence_index for item in multiple})
    strings: list[str] = []
    for item in multiple:
        strings.extend([item.marked, item.sentence, item.answer, *item.distractors])
    for item in shorts:
        strings.extend([item.term, item.sentence, *item.keywords])
    warmer = getattr(translator, "warm", None)
    if callable(warmer):
        warmer(strings)
    questions: list[Question] = []
    for draft in multiple:
        questions.append(_assemble_mc(len(questions) + 1, draft, translator))
    for draft in shorts:
        questions.append(_assemble_short(len(questions) + 1, draft, translator))
    if not questions:
        raise HistoriaError(
            "No pude armar preguntas con este texto. Añade fechas, nombres o frases más claras.",
            "Could not build questions from this text. Add clearer dates, names, or sentences.",
        )
    return Exam(questions=questions, mode="offline", title=found.title)


def _status(awarded: float, maximum: float, user: str) -> str:
    if not user.strip():
        return "unanswered"
    if awarded <= 1e-9:
        return "incorrect"
    if awarded >= maximum - 1e-9:
        return "correct"
    return "partial"


def grade_mc(question: Question, user: str) -> QuestionGrade:
    cleaned = (user or "").strip()
    correct = False
    if cleaned:
        if fold(cleaned) == fold(question.answer):
            correct = True
        elif len(cleaned) == 1 and cleaned.upper() in "ABCD":
            index = ord(cleaned.upper()) - ord("A")
            if 0 <= index < len(question.options) and fold(question.options[index]) == fold(question.answer):
                correct = True
    awarded = question.points if correct else 0.0
    if not cleaned:
        feedback = "You did not answer this question."
    elif correct:
        feedback = f"Correct. {question.explanation}"
    else:
        feedback = f"Incorrect. The expected answer is “{question.answer}”. {question.explanation}"
    return QuestionGrade(
        question_id=question.id,
        awarded=awarded,
        maximum=question.points,
        feedback=feedback,
        status=_status(awarded, question.points, cleaned),
        user_answer=cleaned,
    )


def grade_short_keywords(question: Question, user: str) -> QuestionGrade:
    cleaned = (user or "").strip()
    groups = question.accept or [[keyword] for keyword in question.keywords]
    if not cleaned:
        return QuestionGrade(
            question_id=question.id,
            awarded=0.0,
            maximum=question.points,
            feedback="You did not answer this question.",
            status="unanswered",
            user_answer="",
        )
    hits: list[str] = []
    misses: list[str] = []
    for group in groups:
        label = group[0]
        if any(_contains(cleaned, form) for form in group):
            hits.append(label)
        else:
            misses.append(label)
    ratio = len(hits) / len(groups) if groups else 0.0
    awarded = question.points * ratio
    status = _status(awarded, question.points, cleaned)
    if status == "correct":
        feedback = (
            f"Correct. Your answer covers the expected ideas ({', '.join(hits)}). {question.explanation}"
        )
    elif status == "partial":
        feedback = (
            f"Partial credit. You mentioned: {', '.join(hits)}. "
            f"Missing ideas: {', '.join(misses)}. {question.explanation}"
        )
    else:
        shown = ", ".join(misses) or ", ".join(question.keywords)
        feedback = f"Incorrect. The answer does not mention the expected ideas: {shown}. {question.explanation}"
    return QuestionGrade(
        question_id=question.id,
        awarded=awarded,
        maximum=question.points,
        feedback=feedback,
        status=status,
        user_answer=cleaned,
    )


def score_out_of_10(items: list[QuestionGrade]) -> float:
    maximum = sum(item.maximum for item in items)
    if maximum <= 0:
        return 0.0
    raw = sum(item.awarded for item in items)
    if raw >= maximum - 1e-9:
        return 10.0
    if raw <= 1e-9:
        return 0.0
    return round(raw / maximum * 10, 1)


def summary_for(score: float) -> str:
    if score >= 9:
        return "Excellent. You have a strong grasp of this topic."
    if score >= 7:
        return "Good work. Review the questions you missed and try them again."
    if score >= 5:
        return "Fair. Reread the lesson and use the feedback under each question."
    return "Keep studying. The feedback under each question shows what to review."


def grade_exam(exam: Exam, answers: dict[str, str], short_grader=None) -> ExamGrade:
    items: list[QuestionGrade] = []
    for question in exam.questions:
        raw = answers.get(question.id, "")
        user = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
        if question.kind == "mc":
            items.append(grade_mc(question, user))
            continue
        if short_grader is not None and user.strip():
            try:
                awarded, feedback = short_grader(question, user.strip())
                awarded = max(0.0, min(float(awarded), question.points))
                feedback = (feedback or "Reviewed.").strip()
                items.append(
                    QuestionGrade(
                        question_id=question.id,
                        awarded=awarded,
                        maximum=question.points,
                        feedback=feedback,
                        status=_status(awarded, question.points, user),
                        user_answer=user.strip(),
                    )
                )
                continue
            except Exception:
                # Si el modelo no responde, se califica por palabras clave.
                pass
        items.append(grade_short_keywords(question, user))
    score = score_out_of_10(items)
    return ExamGrade(items=items, score_out_of_10=score, summary=summary_for(score))
