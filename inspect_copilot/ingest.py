"""Ingestion: turn a heterogeneous PDF into language-tagged chunks.

Strategy (per the pdf-reading skill):
  1. Try the text layer (pymupdf). Fast, cheap, works for born-digital PDFs.
  2. If a page has no usable text layer -> it's scanned -> OCR fallback.
  3. Chunk on page boundaries (a deliberately simple, robust default for an
     MVP; section-aware chunking is a documented "3 months" improvement).
  4. Detect language per chunk (Benelux corpus is EN/FR/NL mixed).

We record whether OCR was needed per document in the extraction log / documents
table — that record is the evidence of robustness the README points to.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from langdetect import detect, LangDetectException


@dataclass
class RawChunk:
    page: int
    language: str
    text: str


def _detect_lang(text: str) -> str:
    try:
        return detect(text)
    except LangDetectException:
        return "unknown"


def _ocr_page(page: "fitz.Page") -> str:
    """OCR fallback for scanned pages. Rasterize -> tesseract.

    Imported lazily so the dependency is only needed when a scanned page
    actually shows up.
    """
    import io
    import pytesseract
    from PIL import Image

    pix = page.get_pixmap(dpi=200)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    # English only for the current US-reports MVP. To handle EU reports,
    # change to "eng+fra+nld" and install tesseract-ocr-fra / tesseract-ocr-nld.
    return pytesseract.image_to_string(img, lang="eng")


def ingest(pdf_path: str | Path, min_chars: int = 40) -> tuple[list[RawChunk], bool]:
    """Return (chunks, ocr_used) for one PDF."""
    doc = fitz.open(pdf_path)
    chunks: list[RawChunk] = []
    ocr_used = False

    for i, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if len(text) < min_chars:           # no/poor text layer -> scanned page
            text = _ocr_page(page).strip()
            if text:
                ocr_used = True
        if len(text) < min_chars:
            continue                          # genuinely empty page, skip
        chunks.append(RawChunk(page=i, language=_detect_lang(text), text=text))

    doc.close()
    return chunks, ocr_used
