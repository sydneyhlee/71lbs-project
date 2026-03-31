"""
ParsedDocument dataclasses — shared interface between ingestion/adapter.py
and the extraction_v2 pipeline.

Parsing is handled by ingestion/ — these dataclasses are the contract
between those two layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


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
    """Full parsed output — produced by ingestion/adapter.py."""
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
