"""Extracción de texto de txt, pdf y docx."""

from __future__ import annotations

import io
import re
from pathlib import Path

from historia.errors import HistoriaError


def extract_path(path: str | Path) -> str:
    file_path = Path(path)
    try:
        data = file_path.read_bytes()
    except OSError as exc:
        raise HistoriaError(f"No se pudo leer el archivo: {exc}") from exc
    return extract_bytes(file_path.name, data)


def extract_bytes(name: str, data: bytes) -> str:
    suffix = Path(name).suffix.lower()
    if suffix == ".txt":
        return _decode_txt(data)
    if suffix == ".pdf":
        return _extract_pdf(data)
    if suffix == ".docx":
        return _extract_docx(data)
    raise HistoriaError(
        "Formato no admitido. Sube un archivo .txt, .pdf o .docx.",
        "Unsupported file type. Upload a .txt, .pdf, or .docx file.",
    )


def _decode_txt(data: bytes) -> str:
    if not data.strip():
        raise HistoriaError("El archivo de texto está vacío.", "The text file is empty.")
    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise HistoriaError("El archivo de texto está vacío.", "The text file is empty.")
    return text


def _text_quality(text: str) -> int:
    if not text or not text.strip():
        return 0
    cid = len(re.findall(r"\(cid:\d+\)", text))
    letters = sum(character.isalpha() for character in text)
    return letters - cid * 40


def _extract_pdf(data: bytes) -> str:
    errors: list[str] = []
    plumber_text = _pdf_pdfplumber(data, errors)
    pypdf_text = _pdf_pypdf(data, errors)
    # pdfplumber a veces devuelve «(cid:243)» en fuentes estándar; pypdf lee esos acentos.
    text = plumber_text
    if _text_quality(pypdf_text) > _text_quality(plumber_text):
        text = pypdf_text
    if not text:
        detail = " ".join(errors).strip()
        extra = f" Detalle técnico: {detail}" if detail else ""
        raise HistoriaError(
            "No se pudo extraer texto del PDF. Si es una foto o un escaneo, "
            "súbelo como imagen (jpg, png, heic o webp) para leerlo con OCR."
            + extra,
            "Could not extract text from the PDF. Upload a photo and use OCR instead."
            + extra,
        )
    return text


def _pdf_pdfplumber(data: bytes, errors: list[str]) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        errors.append(f"pdfplumber no está instalado ({exc}).")
        return ""
    try:
        pages: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        return "\n".join(pages).strip()
    except Exception as exc:  # noqa: BLE001 - queremos el respaldo con pypdf
        errors.append(f"pdfplumber: {exc}")
        return ""


def _pdf_pypdf(data: bytes, errors: list[str]) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        errors.append(f"pypdf no está instalado ({exc}).")
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"pypdf: PDF cifrado ({exc}).")
                return ""
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(pages).strip()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pypdf: {exc}")
        return ""


def _extract_docx(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise HistoriaError(
            "Falta el paquete python-docx. Instala las dependencias con pip.",
            "python-docx is not installed.",
        ) from exc
    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise HistoriaError(
            f"No se pudo leer el documento de Word: {exc}",
            f"Could not read the Word document: {exc}",
        ) from exc
    parts: list[str] = []
    for paragraph in document.paragraphs:
        cleaned = paragraph.text.strip()
        if cleaned:
            parts.append(cleaned)
    for table in document.tables:
        for row in table.rows:
            cells = []
            seen: set[str] = set()
            for cell in row.cells:
                cleaned = cell.text.strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    cells.append(cleaned)
            if cells:
                parts.append(" | ".join(cells))
    text = "\n".join(parts).strip()
    if not text:
        raise HistoriaError(
            "El documento de Word no contiene texto.",
            "The Word document has no text.",
        )
    return text
