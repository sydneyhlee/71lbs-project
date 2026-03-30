"""
Output data models for the PDF ingestion pipeline.

These are intentionally decoupled from the pricing models in models/.
They represent the intermediate structured form of a document — what was
extracted and how it was classified — before any domain-specific parsing.

Hierarchy:
    StructuredDocument
    └── Section[]
        └── Block[]   (TextBlock | TableBlock)
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class BlockType(str, Enum):
    HEADER = "HEADER"         # Section title or heading line
    PARAGRAPH = "PARAGRAPH"   # Body text block
    TABLE = "TABLE"           # Tabular data


class SectionType(str, Enum):
    PRICING = "PRICING"         # Rate tables, discount schedules
    SURCHARGE = "SURCHARGE"     # Accessorial charges and fees
    TERMS = "TERMS"             # Contract terms and conditions
    BOILERPLATE = "BOILERPLATE" # Legal filler, definitions, recitals
    UNKNOWN = "UNKNOWN"         # Could not confidently classify


class ExtractionMethod(str, Enum):
    DIGITAL = "digital"   # Text extracted directly from PDF layer
    OCR = "ocr"           # Text obtained via optical character recognition
    MIXED = "mixed"       # Some pages digital, some OCR


# ---------------------------------------------------------------------------
# Blocks — atomic content units within a section
# ---------------------------------------------------------------------------

class TextBlock(BaseModel):
    block_type: Literal[BlockType.HEADER, BlockType.PARAGRAPH]
    text: Annotated[str, Field(min_length=1)]
    page_number: int
    # Font metadata — available for digital pages, None for OCR pages
    font_size: float | None = None
    is_bold: bool = False


class TableBlock(BaseModel):
    block_type: Literal[BlockType.TABLE] = BlockType.TABLE
    page_number: int
    # First row is treated as the header row when header_row=True
    header_row: bool = True
    # Rows are lists of cell strings; None cells represent empty/merged cells
    rows: Annotated[list[list[str | None]], Field(min_length=1)]

    @property
    def headers(self) -> list[str | None]:
        return self.rows[0] if self.header_row and self.rows else []

    @property
    def data_rows(self) -> list[list[str | None]]:
        return self.rows[1:] if self.header_row else self.rows

    def to_dicts(self) -> list[dict[str, str | None]]:
        """Return table rows as dicts keyed by header values (best-effort)."""
        hdrs = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(self.headers)]
        return [dict(zip(hdrs, row)) for row in self.data_rows]


Block = Union[TextBlock, TableBlock]


# ---------------------------------------------------------------------------
# Section — a coherent chunk of the document with a single purpose
# ---------------------------------------------------------------------------

class Section(BaseModel):
    """
    A contiguous group of blocks that share a common topic or function.

    Sections are bounded by header blocks: when the classifier encounters a
    new header, it starts a new section. The section_type is assigned by
    SectionClassifier based on keyword analysis of the title and content.
    """

    section_type: SectionType
    title: str | None = None          # Text of the header block that opened this section
    page_start: int
    page_end: int
    blocks: list[Block] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    """Classifier confidence that section_type is correct (0–1)."""

    @property
    def full_text(self) -> str:
        """Concatenated plain text of all text blocks in this section."""
        parts: list[str] = []
        for block in self.blocks:
            if isinstance(block, TextBlock):
                parts.append(block.text)
            elif isinstance(block, TableBlock):
                # Flatten table rows for text search purposes
                for row in block.rows:
                    parts.append("  ".join(cell or "" for cell in row))
        return "\n".join(parts)

    @property
    def tables(self) -> list[TableBlock]:
        return [b for b in self.blocks if isinstance(b, TableBlock)]

    @property
    def text_blocks(self) -> list[TextBlock]:
        return [b for b in self.blocks if isinstance(b, TextBlock)]


# ---------------------------------------------------------------------------
# StructuredDocument — root output of the pipeline
# ---------------------------------------------------------------------------

class StructuredDocument(BaseModel):
    """
    The fully processed output of the PDF ingestion pipeline.

    Sections are ordered by their appearance in the document.
    pages_ocr lists page numbers (1-indexed) that required OCR fallback.
    """

    source_path: str
    page_count: int
    extraction_method: ExtractionMethod
    pages_ocr: list[int] = Field(
        default_factory=list,
        description="1-indexed page numbers that were processed via OCR.",
    )
    sections: list[Section] = Field(default_factory=list)

    def sections_of_type(self, section_type: SectionType) -> list[Section]:
        return [s for s in self.sections if s.section_type == section_type]

    @property
    def pricing_sections(self) -> list[Section]:
        return self.sections_of_type(SectionType.PRICING)

    @property
    def surcharge_sections(self) -> list[Section]:
        return self.sections_of_type(SectionType.SURCHARGE)
