"""
Document chunker for splitting parsed PDFs into LLM-friendly segments.

Identifies section boundaries and groups content for extraction.
Handles multi-page tables by merging adjacent table-heavy pages.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from app.pipeline.pdf_parser import ParsedDocument, PageContent

logger = logging.getLogger(__name__)

# Patterns that likely indicate section headers in carrier contracts
_SECTION_PATTERNS = [
    re.compile(r"^(SECTION|ARTICLE|PART|SCHEDULE|EXHIBIT|APPENDIX|AMENDMENT)\s", re.IGNORECASE),
    re.compile(r"^\d+\.\s+[A-Z]"),
    re.compile(r"^[A-Z][A-Z\s]{5,}$"),  # ALL CAPS lines
]

# Target chunk size in characters (fits comfortably in LLM context)
_TARGET_CHUNK_SIZE = 6000
_MAX_CHUNK_SIZE = 10000


@dataclass
class DocumentChunk:
    """A segment of the document ready for LLM extraction."""
    chunk_index: int
    text: str
    page_numbers: List[int] = field(default_factory=list)
    section_header: Optional[str] = None
    has_tables: bool = False

    @property
    def char_count(self) -> int:
        return len(self.text)


def _detect_section_header(text: str) -> Optional[str]:
    """Try to identify a section header from the first few lines of text."""
    lines = text.strip().split("\n")[:5]
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        for pattern in _SECTION_PATTERNS:
            if pattern.match(stripped):
                return stripped
    return None


def _merge_table_text(page: PageContent) -> str:
    """Combine page text with formatted table data."""
    parts = [page.text]
    for table in page.tables:
        parts.append(f"\n[TABLE on page {table.page_number}]\n{table.to_text()}")
    return "\n".join(parts)


def chunk_document(doc: ParsedDocument) -> List[DocumentChunk]:
    """
    Split a parsed PDF into chunks suitable for LLM extraction.

    Strategy:
    1. Group pages by detected section boundaries
    2. Merge small adjacent sections up to target chunk size
    3. Split oversized sections into sub-chunks
    """
    if not doc.pages:
        return []

    raw_sections: List[dict] = []
    current: dict = {"text": "", "pages": [], "header": None, "has_tables": False}

    for page in doc.pages:
        page_text = _merge_table_text(page)
        header = _detect_section_header(page_text)

        if header and current["text"]:
            raw_sections.append(current)
            current = {
                "text": "", "pages": [], "header": header,
                "has_tables": False,
            }

        current["text"] += f"\n\n--- Page {page.page_number} ---\n{page_text}"
        current["pages"].append(page.page_number)
        if page.tables:
            current["has_tables"] = True
        if not current["header"] and header:
            current["header"] = header

    if current["text"]:
        raw_sections.append(current)

    # Merge small adjacent sections
    merged: List[dict] = []
    for sec in raw_sections:
        if merged and len(merged[-1]["text"]) + len(sec["text"]) < _TARGET_CHUNK_SIZE:
            merged[-1]["text"] += sec["text"]
            merged[-1]["pages"].extend(sec["pages"])
            merged[-1]["has_tables"] = merged[-1]["has_tables"] or sec["has_tables"]
        else:
            merged.append(sec)

    # Split oversized chunks
    chunks: List[DocumentChunk] = []
    idx = 0
    for sec in merged:
        text = sec["text"].strip()
        if len(text) <= _MAX_CHUNK_SIZE:
            chunks.append(DocumentChunk(
                chunk_index=idx, text=text,
                page_numbers=sec["pages"],
                section_header=sec.get("header"),
                has_tables=sec["has_tables"],
            ))
            idx += 1
        else:
            # Split on double-newlines or at max size boundaries
            paragraphs = text.split("\n\n")
            sub_text = ""
            for para in paragraphs:
                if len(sub_text) + len(para) > _TARGET_CHUNK_SIZE and sub_text:
                    chunks.append(DocumentChunk(
                        chunk_index=idx, text=sub_text.strip(),
                        page_numbers=sec["pages"],
                        section_header=sec.get("header"),
                        has_tables=sec["has_tables"],
                    ))
                    idx += 1
                    sub_text = ""
                sub_text += "\n\n" + para
            if sub_text.strip():
                chunks.append(DocumentChunk(
                    chunk_index=idx, text=sub_text.strip(),
                    page_numbers=sec["pages"],
                    section_header=sec.get("header"),
                    has_tables=sec["has_tables"],
                ))
                idx += 1

    logger.info("Chunked document into %d segments", len(chunks))
    return chunks
