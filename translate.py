"""Traducción al inglés con deep-translator y un respaldo local."""

from __future__ import annotations

import re
import threading

from historia.analyze import fold

_NUMBER = re.compile(r"^[\d\s./-]+$")
_BLANK_TOKEN = "ZXBLANKZX"
_BLANK_PATTERNS = (
    r"ZXBLANKZX",
    r"ZX[\s_\-]*BLANK[\s_\-]*ZX",
)
_ES_HINTS = {
    "el", "la", "los", "las", "de", "del", "que", "en", "un", "una", "por", "con",
    "para", "su", "se", "al", "como", "más", "mas", "fue", "sus", "una", "este",
    "esta", "entre", "sobre", "cuando", "donde",
}
_EN_HINTS = {
    "the", "of", "and", "to", "in", "that", "was", "for", "with", "his", "as",
    "on", "from", "by", "were", "this", "are", "be", "or", "an", "which",
}
# Términos que el traductor automático suele dejar a medias. Coincidencia exacta.
_GLOSSARY = {
    "tercer estado": "Third Estate",
    "estados generales": "Estates-General",
    "asamblea nacional": "National Assembly",
    "declaracion de los derechos del hombre y del ciudadano": "Declaration of the Rights of Man and of the Citizen",
    "juego de pelota": "Tennis Court",
    "comite de salvacion publica": "Committee of Public Safety",
    "ilustracion": "Enlightenment",
    "bastilla": "Bastille",
    "directorio": "Directory",
    "consulado": "Consulate",
    "antiguo regimen": "Ancien Régime",
    "luis xvi": "Louis XVI",
    "maria antonieta": "Marie Antoinette",
    "napoleon bonaparte": "Napoleon Bonaparte",
    "napoleon": "Napoleon",
    "maximilien robespierre": "Maximilien Robespierre",
    "robespierre": "Robespierre",
    "revolucion": "Revolution",
    "republica": "Republic",
    "francia": "France",
    "europa": "Europe",
    "paris": "Paris",
    "versalles": "Versailles",
    "varennes": "Varennes",
}
_BROWSER = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class EnglishTranslator:
    """Traduce al inglés si hay internet. Si falla, las llamadas siguientes no reintentan."""

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self._cache: dict[str, tuple[str, bool]] = {}
        self._disabled = False
        self.reason = ""
        self.engine = ""

    @property
    def available(self) -> bool:
        return not self._disabled

    def warm(self, texts: list[str]) -> None:
        pending: list[str] = []
        seen: set[str] = set()
        for raw in texts:
            text = (raw or "").strip()
            if not text or text in self._cache or text in seen:
                continue
            gloss = _glossary(text)
            if gloss:
                self._cache[text] = (gloss, True)
                continue
            if _NUMBER.fullmatch(text):
                self._cache[text] = (text, True)
                continue
            seen.add(text)
            pending.append(text[:4500])
        if not pending or self._disabled:
            return
        sample = " ".join(pending)[:2500]
        if not _looks_spanish(sample):
            for text in pending:
                self._cache[text] = (text, True)
            return
        translated: list[str] | None = None
        try:
            translated = self._google(pending)
            self.engine = "GoogleTranslator"
        except Exception as exc:  # noqa: BLE001
            self.reason = f"GoogleTranslator: {exc}"
        if translated is None:
            try:
                translated = self._mymemory(pending)
                self.engine = "MyMemoryTranslator"
            except Exception as exc:  # noqa: BLE001
                self._disabled = True
                self.reason = f"{self.reason} | MyMemoryTranslator: {exc}".strip(" |")
                return
        for source, target in zip(pending, translated):
            cleaned = target.strip() if isinstance(target, str) else ""
            if _usable_translation(source, cleaned):
                self._cache[source] = (cleaned, True)
                self._cache[source[:4500]] = (cleaned, True)
            else:
                self._cache[source] = (source, False)

    def to_english(self, text: str) -> tuple[str, bool]:
        cleaned = (text or "").strip()
        if not cleaned:
            return "", False
        gloss = _glossary(cleaned)
        if gloss:
            self._cache[cleaned] = (gloss, True)
            return gloss, True
        if _NUMBER.fullmatch(cleaned):
            return cleaned, True
        cached = self._cache.get(cleaned) or self._cache.get(cleaned[:4500])
        if cached is not None:
            return cached
        if self._disabled:
            return cleaned, False
        self.warm([cleaned])
        cached = self._cache.get(cleaned) or self._cache.get(cleaned[:4500])
        if cached is not None:
            return cached
        return cleaned, False

    def _google(self, texts: list[str]) -> list[str]:
        import requests
        from deep_translator import GoogleTranslator

        original = requests.get

        def wrapped(url, **kwargs):  # noqa: ANN001
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("User-Agent", _BROWSER)
            kwargs["headers"] = headers
            kwargs.setdefault("timeout", self.timeout)
            return original(url, **kwargs)

        requests.get = wrapped
        try:
            translator = GoogleTranslator(source="auto", target="en")
            collected: list[str] = []
            for text in texts:
                result = _call_with_timeout(lambda t=text: translator.translate(t[:4500]), self.timeout)
                collected.append("" if result is None else str(result))
            return collected
        finally:
            requests.get = original

    def _mymemory(self, texts: list[str]) -> list[str]:
        from deep_translator import MyMemoryTranslator

        translator = MyMemoryTranslator(source="spanish", target="english")
        collected: list[str] = []
        for text in texts:
            result = _call_with_timeout(lambda t=text: _mymemory_piece(translator, t), self.timeout)
            collected.append("" if result is None else str(result))
        return collected


def restore_blank(translated: str) -> str | None:
    for pattern in _BLANK_PATTERNS:
        if re.search(pattern, translated, flags=re.IGNORECASE):
            return re.sub(pattern, "____", translated, count=1, flags=re.IGNORECASE)
    return None


def mark_blank(sentence: str, span: str) -> str:
    return re.sub(re.escape(span), _BLANK_TOKEN, sentence, count=1, flags=re.IGNORECASE)


def same_text(left: str, right: str) -> bool:
    return fold(left) == fold(right)


def _glossary(text: str) -> str | None:
    return _GLOSSARY.get(fold(text))


def _looks_spanish(text: str) -> bool:
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", text.lower())
    if not tokens:
        return True
    spanish = sum(token in _ES_HINTS for token in tokens)
    english = sum(token in _EN_HINTS for token in tokens)
    return spanish >= english


def _usable_translation(source: str, translated: str) -> bool:
    if not translated:
        return False
    upper = translated.upper()
    if "MYMEMORY WARNING" in upper or "QUERY LENGTH" in upper:
        return False
    letters = [character for character in translated if character.isalpha()]
    if len(translated) > 3 and letters and all(character.isupper() for character in letters):
        return False
    if len(source) > 80 and fold(source) == fold(translated):
        return False
    return True


def _mymemory_piece(translator, text: str) -> str:
    if len(text) <= 450:
        return str(translator.translate(text))
    parts: list[str] = []
    start = 0
    while start < len(text):
        piece = text[start : start + 450]
        if start + 450 < len(text) and " " in piece:
            piece = piece.rsplit(" ", 1)[0] or piece
        parts.append(str(translator.translate(piece)))
        start += max(len(piece), 1)
    return " ".join(part for part in parts if part)


def _call_with_timeout(func, timeout: float):
    box: dict[str, object] = {}

    def runner() -> None:
        try:
            box["value"] = func()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"la traducción superó {timeout:.0f} s")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box.get("value")
