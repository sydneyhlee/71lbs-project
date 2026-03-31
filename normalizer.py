"""
Normalization layer.

Applies normalize_percent, normalize_weight_range, and normalize_service_name
to every table row in a StructuredDocument, producing typed values alongside
the raw extracted strings.

Pipeline position:
    ingest_pdf() -> StructuredDocument -> normalize_document() -> NormalizedDocument
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ingestion.document import SectionType, StructuredDocument, TableBlock
from ingestion.normalization import (
    VendorType,
    normalize_percent,
    normalize_service_name,
    normalize_weight_range,
)


# ---------------------------------------------------------------------------
# Column classification
# ---------------------------------------------------------------------------

_PERCENT_HEADER = re.compile(r"%|percent|pct|\bdiscount\s*%|\brate\s*%|\bsurcharge\s*%", re.I)
_WEIGHT_HEADER = re.compile(r"\blbs?\b|\bpounds?\b|\bkg\b|\bweight\b", re.I)
_SERVICE_HEADER = re.compile(r"\bservice\b|\bservice\s+type\b|\bproduct\b", re.I)


def _detect_vendor(doc: StructuredDocument) -> VendorType:
    src = doc.source_path.lower()
    if "fdx" in src or "fedex" in src:
        return VendorType.FEDEX
    if "ups" in src:
        return VendorType.UPS
    for section in doc.sections:
        title = (section.title or "").lower()
        if "fedex" in title:
            return VendorType.FEDEX
        if "ups" in title:
            return VendorType.UPS
    return VendorType.UNKNOWN


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------

@dataclass
class NormalizedCell:
    raw: str | None
    percent:  dict | None = None
    weight:   dict | None = None
    service:  tuple | None = None

    @property
    def best_value(self):
        if self.percent and (self.percent.get("confidence") or 0) >= 0.65:
            return self.percent["value"]
        if self.weight and (self.weight.get("confidence") or 0) >= 0.6:
            return self.weight
        if self.service and self.service[1] >= 0.7:
            return self.service[0]
        return self.raw


@dataclass
class NormalizedRow:
    raw: dict[str, str | None]
    cells: dict[str, NormalizedCell] = field(default_factory=dict)


@dataclass
class NormalizedTable:
    page_number: int
    header_row: bool
    raw_headers: list[str | None]
    rows: list[NormalizedRow]


@dataclass
class NormalizedSection:
    section_type: str
    title: str | None
    page_start: int
    page_end: int
    confidence: float
    service_name: tuple | None
    tables: list[NormalizedTable]
    full_text: str


@dataclass
class NormalizedDocument:
    source_path: str
    page_count: int
    vendor: VendorType
    extraction_method: str
    sections: list[NormalizedSection]

    def sections_of_type(self, section_type: SectionType) -> list[NormalizedSection]:
        return [s for s in self.sections if s.section_type == section_type.value]

    @property
    def pricing_sections(self) -> list[NormalizedSection]:
        return self.sections_of_type(SectionType.PRICING)

    @property
    def surcharge_sections(self) -> list[NormalizedSection]:
        return self.sections_of_type(SectionType.SURCHARGE)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _normalize_table(table: TableBlock, vendor: VendorType) -> NormalizedTable:
    normalized_rows: list[NormalizedRow] = []
    for raw_row in table.to_dicts():
        cells: dict[str, NormalizedCell] = {}
        for header, raw_value in raw_row.items():
            cell = NormalizedCell(raw=raw_value)
            val = raw_value or ""
            if _PERCENT_HEADER.search(header):
                cell.percent = normalize_percent(val)
            if _WEIGHT_HEADER.search(header):
                cell.weight = normalize_weight_range(val)
            if _SERVICE_HEADER.search(header) and val:
                cell.service = normalize_service_name(val, vendor)
            cells[header] = cell
        normalized_rows.append(NormalizedRow(raw=raw_row, cells=cells))

    return NormalizedTable(
        page_number=table.page_number,
        header_row=table.header_row,
        raw_headers=list(table.headers),
        rows=normalized_rows,
    )


def normalize_document(doc: StructuredDocument) -> NormalizedDocument:
    """Apply normalization to every table in a StructuredDocument."""
    vendor = _detect_vendor(doc)
    normalized_sections: list[NormalizedSection] = []

    for section in doc.sections:
        svc = None
        if section.title:
            token, conf = normalize_service_name(section.title, vendor)
            if conf >= 0.45:
                svc = (token, conf)

        normalized_sections.append(NormalizedSection(
            section_type=section.section_type.value,
            title=section.title,
            page_start=section.page_start,
            page_end=section.page_end,
            confidence=section.confidence,
            service_name=svc,
            tables=[_normalize_table(t, vendor) for t in section.tables],
            full_text=section.full_text,
        ))

    return NormalizedDocument(
        source_path=doc.source_path,
        page_count=doc.page_count,
        vendor=vendor,
        extraction_method=doc.extraction_method.value,
        sections=normalized_sections,
    )
