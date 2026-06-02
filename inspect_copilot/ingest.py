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

import re
from collections import Counter
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


# --- boilerplate stripping -------------------------------------------------
# Publisher / agency back-matter tokens. A line containing one of these is the
# report author's own contact information (hotline, media contact, website,
# mailing address) — never a description of an inspected building. We drop
# such lines before extraction so the LLM can't mistake e.g. the GSA OIG's
# letterhead address "1800 F Street NW, Washington, DC 20405" for the address
# of the building under inspection. (That exact confusion linked a child-care
# center to the Clinton Federal Building in an earlier run.)
_CONTACT_MARKERS = re.compile(
    r"(gsaig\.gov"                       # OIG website + the address rides this line
    r"|fraudnet"
    r"|report\s+fraud,?\s+waste"
    r"|for\s+media\s+inquiries"
    r"|inspector\s+general"
    r"|hotline"
    r"|mailing\s+list)",
    re.IGNORECASE,
)
# Signals used only to decide a line sits inside a contact block (so the
# address/phone drops below stay scoped to back-matter, never body prose).
_CONTACT_SIGNAL = re.compile(
    r"(gsaig\.gov|fraudnet|report\s+fraud|media\s+inquiries|inspector\s+general"
    r"|hotline|\(?\d{3}\)?[\s.-]?\d{3}-\d{4})",
    re.IGNORECASE,
)
_POSTAL_LINE = re.compile(r",\s*[A-Z]{2}\.?\s+\d{5}\b")        # "..., DC 20405"
_PHONE_LINE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}-\d{4}")     # (800) 424-5210


def _norm_line(s: str) -> str:
    return " ".join(s.split()).lower()


def _strip_boilerplate(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Remove publisher boilerplate from a document's pages.

    Two complementary passes, both deliberately conservative so report content
    is never touched:

    1. Running headers/footers — short lines repeated on most pages (only for
       documents long enough for the signal to be reliable).
    2. Agency contact block — lines carrying contact markers are always
       dropped; postal-address and phone lines are dropped only on pages that
       look like a contact block (>=2 contact signals), so a genuine building
       address in body prose is never removed.
    """
    if not pages:
        return pages

    # Pass 1: detect repeated short lines across pages.
    line_pages: Counter[str] = Counter()
    for _, text in pages:
        for ln in {_norm_line(l) for l in text.splitlines() if l.strip()}:
            line_pages[ln] += 1
    n = len(pages)
    repeated = {
        ln
        for ln, c in line_pages.items()
        if n >= 4 and c >= max(3, int(0.6 * n)) and len(ln.split()) <= 8
    }

    out: list[tuple[int, str]] = []
    for page_no, text in pages:
        lines = text.splitlines()
        in_contact_block = sum(bool(_CONTACT_SIGNAL.search(l)) for l in lines) >= 2
        kept = []
        for l in lines:
            if not l.strip():
                continue
            if _norm_line(l) in repeated:
                continue
            if _CONTACT_MARKERS.search(l):
                continue
            if in_contact_block and (_POSTAL_LINE.search(l) or _PHONE_LINE.search(l)):
                continue
            kept.append(l)
        out.append((page_no, "\n".join(kept).strip()))
    return out


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
    pages: list[tuple[int, str]] = []
    ocr_used = False

    for i, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if len(text) < min_chars:           # no/poor text layer -> scanned page
            text = _ocr_page(page).strip()
            if text:
                ocr_used = True
        if len(text) < min_chars:
            continue                          # genuinely empty page, skip
        pages.append((i, text))

    doc.close()

    # Drop publisher boilerplate (running headers/footers, agency contact block)
    # before chunking, then skip any page left empty by the strip.
    pages = _strip_boilerplate(pages)
    chunks = [
        RawChunk(page=p, language=_detect_lang(t), text=t)
        for p, t in pages
        if len(t) >= min_chars
    ]
    return chunks, ocr_used
