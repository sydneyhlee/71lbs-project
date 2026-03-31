"""
PDF text and table extraction with OCR fallback.

Uses pdfplumber for text-based PDFs and pytesseract + pdf2image
for scanned documents. Detects whether OCR is needed automatically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pdfplumber

logger = logging.getLogger(__name__)

# Minimum chars per page to consider text extraction successful
_MIN_TEXT_THRESHOLD = 50


@dataclass
class TableData:
    """A table extracted from a PDF page."""
    page_number: int
    headers: List[str]
    rows: List[List[str]]

    def to_text(self) -> str:
        lines = [" | ".join(self.headers)]
        lines.append("-" * len(lines[0]))
        for row in self.rows:
            lines.append(" | ".join(str(c) for c in row))
        return "\n".join(lines)


@dataclass
class PageContent:
    """Extracted content from a single PDF page."""
    page_number: int
    text: str = ""
    tables: List[TableData] = field(default_factory=list)
    is_ocr: bool = False


@dataclass
class ParsedDocument:
    """Full parsed output from a PDF file."""
    file_path: str
    total_pages: int = 0
    pages: List[PageContent] = field(default_factory=list)
    used_ocr: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(
            f"--- Page {p.page_number} ---\n{p.text}" for p in self.pages
        )


def _extract_with_pdfplumber(pdf_path: Path) -> ParsedDocument:
    """Extract text and tables using pdfplumber (works on text-based PDFs)."""
    doc = ParsedDocument(file_path=str(pdf_path))
    try:
        with pdfplumber.open(pdf_path) as pdf:
            doc.total_pages = len(pdf.pages)
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                tables: List[TableData] = []
                for raw_table in page.extract_tables() or []:
                    if not raw_table or len(raw_table) < 2:
                        continue
                    headers = [str(c or "") for c in raw_table[0]]
                    rows = [
                        [str(c or "") for c in row]
                        for row in raw_table[1:]
                    ]
                    tables.append(TableData(
                        page_number=i, headers=headers, rows=rows
                    ))
                doc.pages.append(PageContent(
                    page_number=i, text=text, tables=tables
                ))
    except Exception as exc:
        doc.errors.append(f"pdfplumber error: {exc}")
        logger.exception("pdfplumber extraction failed for %s", pdf_path)
    return doc


def _needs_ocr(doc: ParsedDocument) -> bool:
    """Check if pdfplumber got enough text or if OCR is needed."""
    if not doc.pages:
        return True
    avg_len = sum(len(p.text) for p in doc.pages) / max(len(doc.pages), 1)
    return avg_len < _MIN_TEXT_THRESHOLD


def _extract_with_ocr(pdf_path: Path) -> ParsedDocument:
    """Fallback: convert pages to images, then OCR with pytesseract."""
    doc = ParsedDocument(file_path=str(pdf_path), used_ocr=True)
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError as exc:
        doc.errors.append(
            f"OCR dependencies missing ({exc}). "
            "Install pytesseract and pdf2image."
        )
        return doc

    try:
        images = convert_from_path(pdf_path)
        doc.total_pages = len(images)
        for i, img in enumerate(images, start=1):
            text = pytesseract.image_to_string(img)
            doc.pages.append(PageContent(
                page_number=i, text=text, is_ocr=True
            ))
    except Exception as exc:
        doc.errors.append(f"OCR error: {exc}")
        logger.exception("OCR extraction failed for %s", pdf_path)
    return doc


def parse_pdf(pdf_path: str | Path) -> ParsedDocument:
    """
    Parse a PDF file, trying text extraction first, falling back to OCR.

    Returns a ParsedDocument with per-page text and table data.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return ParsedDocument(
            file_path=str(pdf_path),
            errors=[f"File not found: {pdf_path}"],
        )

    logger.info("Parsing PDF: %s", pdf_path.name)
    doc = _extract_with_pdfplumber(pdf_path)

    if _needs_ocr(doc):
        logger.info("Text extraction sparse, falling back to OCR for %s", pdf_path.name)
        ocr_doc = _extract_with_ocr(pdf_path)
        if ocr_doc.pages:
            doc = ocr_doc

    logger.info(
        "Parsed %d pages from %s (OCR=%s)",
        doc.total_pages, pdf_path.name, doc.used_ocr,
    )
    return doc
