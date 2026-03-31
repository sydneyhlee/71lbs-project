"""
PDF ingestion pipeline (Parsing Team).

Usage:
    from ingestion import ingest_pdf
    from ingestion.document import SectionType

    doc = ingest_pdf("path/to/contract.pdf")

    for section in doc.pricing_sections:
        print(section.title, section.page_start)
        for table in section.tables:
            print(table.to_dicts())
"""

from .document import (
    Block,
    BlockType,
    ExtractionMethod,
    Section,
    SectionType,
    StructuredDocument,
    TableBlock,
    TextBlock,
)
from .layout_parser import parse_layout
from .pdf_reader import read_pdf
from .section_classifier import classify_sections


def ingest_pdf(pdf_path: str) -> StructuredDocument:
    """
    Full pipeline: PDF file -> StructuredDocument.

    Steps:
      1. read_pdf        - extract raw pages (digital or OCR per page)
      2. parse_layout    - detect headers, tables, paragraphs
      3. classify_sections - group blocks into typed sections
    """
    raw_pages = read_pdf(pdf_path)

    ocr_pages = [p.page_number for p in raw_pages if p.is_ocr]
    extraction_method = (
        ExtractionMethod.OCR if len(ocr_pages) == len(raw_pages)
        else ExtractionMethod.MIXED if ocr_pages
        else ExtractionMethod.DIGITAL
    )

    pages_blocks = parse_layout(raw_pages)
    sections = classify_sections(pages_blocks)

    return StructuredDocument(
        source_path=str(pdf_path),
        page_count=len(raw_pages),
        extraction_method=extraction_method,
        pages_ocr=ocr_pages,
        sections=sections,
    )


__all__ = [
    "ingest_pdf",
    "Block",
    "BlockType",
    "ExtractionMethod",
    "Section",
    "SectionType",
    "StructuredDocument",
    "TableBlock",
    "TextBlock",
]
