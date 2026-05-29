"""PDF / DOCX → plain text.

Mirrors cv-estimator/extractors/document.py — pypdf for PDFs (no
pdfplumber dependency), python-docx for DOCX. Language detection is a
cheap Czech-vs-English heuristic; good enough for the demo.
"""

import io
import re
from pathlib import Path

from docx import Document
from pypdf import PdfReader


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Dispatch by extension. Returns the concatenated text content."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(file_bytes)
    if suffix == ".docx":
        return _read_docx(file_bytes)
    if suffix == ".txt":
        return file_bytes.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported file type: {suffix} (expected .pdf, .docx, .txt)")


def _read_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _read_docx(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text)


_CS_HINTS = re.compile(r"[áčďéěíňóřšťúůýž]", re.IGNORECASE)


def detect_language(text: str) -> str:
    """Return 'cs' if the text contains Czech diacritics, else 'en'."""
    return "cs" if _CS_HINTS.search(text) else "en"
