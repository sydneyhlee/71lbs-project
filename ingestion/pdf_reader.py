"""
PDF Reader — raw page extraction layer.

Strategy:
  1. Open with pdfplumber (handles digital/text-layer PDFs).
  2. For each page, attempt digital extraction.
  3. A page is considered "digital" if it yields enough meaningful characters
     (threshold: MIN_CHARS_DIGITAL). Pages below this threshold are likely
     scanned images and fall back to OCR.
  4. OCR uses pdf2image to render the page to a PIL image, then pytesseract
     to extract text. Font metadata is not available for OCR pages.

Output: list[RawPage] — one entry per PDF page, consumed by LayoutParser.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from pdfplumber.page import Page as PdfPage

logger = logging.getLogger(__name__)

# A digital page must yield at least this many non-whitespace characters
# before we trust the text layer. Below this, OCR kicks in.
MIN_CHARS_DIGITAL = 20


@dataclass
class RawChar:
    """A single character with its font metadata from a digital page."""
    text: str
    font_size: float
    font_name: str      # e.g. "Arial-BoldMT", "TimesNewRomanPSMT"
    x0: float           # left edge
    y0: float           # bottom edge (pdfplumber coordinate space)
    x1: float
    y1: float


@dataclass
class RawTable:
    """A table extracted by pdfplumber's table-finder."""
    rows: list[list[str | None]]  # None = empty/merged cell


@dataclass
class RawPage:
    """All raw content extracted from one PDF page."""
    page_number: int          # 1-indexed
    width: float
    height: float
    chars: list[RawChar]      # Empty for OCR pages
    tables: list[RawTable]
    ocr_text: str | None      # Set only for OCR-fallback pages
    is_ocr: bool = False
    _pdf_path: str = ""       # Source file path (used by layout_parser for text-strategy tables)


def _extract_digital(pdf_page: PdfPage, page_number: int) -> RawPage:
    """Extract text and tables from a digital (text-layer) PDF page."""
    raw_chars: list[RawChar] = []
    for ch in pdf_page.chars:
        raw_chars.append(RawChar(
            text=ch.get("text", ""),
            font_size=ch.get("size", 0.0),
            font_name=ch.get("fontname", ""),
            x0=ch.get("x0", 0.0),
            y0=ch.get("y0", 0.0),
            x1=ch.get("x1", 0.0),
            y1=ch.get("y1", 0.0),
        ))

    return RawPage(
        page_number=page_number,
        width=pdf_page.width,
        height=pdf_page.height,
        chars=raw_chars,
        tables=[],      # Tables extracted later in layout_parser using text-strategy
        ocr_text=None,
        is_ocr=False,
    )


def _has_enough_text(raw_page: RawPage) -> bool:
    text = "".join(ch.text for ch in raw_page.chars)
    return len(text.strip()) >= MIN_CHARS_DIGITAL


def _extract_ocr(pdf_path: Path, page_number: int, pdf_page: PdfPage) -> RawPage:
    """
    Render a page to an image and run Tesseract OCR on it.
    Requires: tesseract binary, pdf2image, pytesseract, Pillow.
    """
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "OCR dependencies not installed. Run: pip install pdf2image pytesseract Pillow\n"
            "Also install the tesseract binary: https://tesseract-ocr.github.io/tessdoc/Installation.html"
        ) from exc

    # Render only this page (1-indexed for pdf2image)
    images = convert_from_path(
        str(pdf_path),
        first_page=page_number,
        last_page=page_number,
        dpi=300,
    )
    if not images:
        raise RuntimeError(f"pdf2image returned no images for page {page_number}.")

    text = pytesseract.image_to_string(images[0], lang="eng")
    logger.info("Page %d processed via OCR (%d chars extracted).", page_number, len(text.strip()))

    return RawPage(
        page_number=page_number,
        width=pdf_page.width,
        height=pdf_page.height,
        chars=[],           # No char-level data from OCR
        tables=[],          # Table detection from OCR text is handled downstream
        ocr_text=text,
        is_ocr=True,
    )


def read_pdf(pdf_path: str | Path) -> list[RawPage]:
    """
    Extract all pages from a PDF, using digital extraction where possible
    and OCR as a fallback for scanned pages.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        A list of RawPage objects, one per page, in document order.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    pages: list[RawPage] = []

    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        logger.info("Opening '%s' (%d pages).", path.name, total)

        for pdf_page in pdf.pages:
            page_num = pdf_page.page_number  # pdfplumber is 1-indexed

            raw = _extract_digital(pdf_page, page_num)

            if _has_enough_text(raw):
                logger.debug("Page %d: digital extraction (%d chars).",
                             page_num, len(raw.chars))
            else:
                logger.info("Page %d: insufficient text layer, falling back to OCR.", page_num)
                raw = _extract_ocr(path, page_num, pdf_page)

            raw._pdf_path = str(path)
            pages.append(raw)

    return pages
