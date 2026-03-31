"""
Normalization layer.

Applies the three normalization functions to StructuredDocument table rows,
producing typed + validated values alongside the raw extracted strings.

Pipeline position:
    ingest_pdf() -> StructuredDocument -> normalize_document() -> NormalizedDocument

Import strategy:
    normalization.py depends on contract_parser.models.VendorType.
    We inject a minimal stub for that module so the file loads cleanly
    without the rest of contract_parser.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import types
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ingestion.document import SectionType, StructuredDocument, TableBlock


# ---------------------------------------------------------------------------
# Minimal stub so normalization.py can import VendorType
# ---------------------------------------------------------------------------

class VendorType(Enum):
    FEDEX = "FEDEX"
    UPS = "UPS"
    UNKNOWN = "UNKNOWN"


def _inject_vendor_stub() -> None:
    if "contract_parser" not in sys.modules:
        stub_pkg = types.ModuleType("contract_parser")
        stub_models = types.ModuleType("contract_parser.models")
        stub_models.VendorType = VendorType  # type: ignore[attr-defined]
        sys.modules["contract_parser"] = stub_pkg
        sys.modules["contract_parser.models"] = stub_models


_inject_vendor_stub()

# Load normalization.py directly — bypasses __init__.py (which pulls in
# parsers.py and its hard contract_parser dependency).
_NORM_PATH = (
    Path(__file__).parent
    / "normalize/contract_pipeline_refined/normalize/normalization.py"
)
_spec = importlib.util.spec_from_file_location("_normalization_impl", _NORM_PATH)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

normalize_percent = _mod.normalize_percent
normalize_weight_range = _mod.normalize_weight_range
normalize_service_name = _mod.normalize_service_name


# ---------------------------------------------------------------------------
# Column classification helpers
# ---------------------------------------------------------------------------

_PERCENT_HEADER = re.compile(
    r"%|percent|pct|\bdiscount\s*%|\brate\s*%|\bsurcharge\s*%",
    re.I,
)
_WEIGHT_HEADER = re.compile(
    r"\blbs?\b|\bpounds?\b|\bkg\b|\bkilograms?\b|\bweight\b",
    re.I,
)
_SERVICE_HEADER = re.compile(
    r"\bservice\b|\bservice\s+type\b|\bproduct\b",
    re.I,
)


def _detect_vendor(doc: StructuredDocument) -> VendorType:
    """Infer carrier from source filename or section text."""
    src = doc.source_path.lower()
    if "fdx" in src or "fedex" in src or "fed_ex" in src:
        return VendorType.FEDEX
    if "ups" in src:
        return VendorType.UPS
    # Fall back to keyword scan over section titles
    for section in doc.sections:
        title = (section.title or "").lower()
        if "fedex" in title or "fed ex" in title:
            return VendorType.FEDEX
        if "ups" in title:
            return VendorType.UPS
    return VendorType.UNKNOWN


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------

@dataclass
class NormalizedCell:
    """A single table cell with its raw value and any normalization applied."""
    raw: str | None
    # Only populated when a normalizer ran on this cell
    percent:  dict | None = None   # result of normalize_percent
    weight:   dict | None = None   # result of normalize_weight_range
    service:  tuple | None = None  # (canonical_token, confidence)

    @property
    def best_value(self):
        """
        Return the most confident typed value, falling back to raw.
        Useful for downstream code that just wants a single value.
        """
        if self.percent and (self.percent.get("confidence") or 0) >= 0.65:
            return self.percent["value"]
        if self.weight and (self.weight.get("confidence") or 0) >= 0.6:
            return self.weight
        if self.service and self.service[1] >= 0.7:
            return self.service[0]
        return self.raw


@dataclass
class NormalizedRow:
    """One table row: original header-keyed dict + per-cell normalization."""
    raw: dict[str, str | None]
    cells: dict[str, NormalizedCell] = field(default_factory=dict)


@dataclass
class NormalizedTable:
    """A TableBlock with normalized rows attached."""
    page_number: int
    header_row: bool
    raw_headers: list[str | None]
    rows: list[NormalizedRow]


@dataclass
class NormalizedSection:
    """A Section with its tables normalized."""
    section_type: str
    title: str | None
    page_start: int
    page_end: int
    confidence: float
    # Normalized service name for the section title itself
    service_name: tuple | None   # (canonical_token, confidence) or None
    tables: list[NormalizedTable]
    full_text: str


@dataclass
class NormalizedDocument:
    """Root output: StructuredDocument with normalization applied."""
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
# Core normalization logic
# ---------------------------------------------------------------------------

def _normalize_table(table: TableBlock, vendor: VendorType) -> NormalizedTable:
    raw_rows = table.to_dicts()
    headers = [str(h) if h is not None else "" for h in table.headers]

    normalized_rows: list[NormalizedRow] = []

    for raw_row in raw_rows:
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
    """
    Apply normalization to every table in a StructuredDocument.

    - Percent values extracted from columns whose headers mention %, pct, discount%, rate%
    - Weight values extracted from columns whose headers mention lbs, weight, kg
    - Service names normalized in columns whose headers mention service/product
    - Section titles normalized as service names (useful for contract sections)
    """
    vendor = _detect_vendor(doc)

    normalized_sections: list[NormalizedSection] = []

    for section in doc.sections:
        # Normalize the section title as a service name
        svc = None
        if section.title:
            token, conf = normalize_service_name(section.title, vendor)
            if conf >= 0.45:
                svc = (token, conf)

        norm_tables = [_normalize_table(t, vendor) for t in section.tables]

        normalized_sections.append(NormalizedSection(
            section_type=section.section_type.value,
            title=section.title,
            page_start=section.page_start,
            page_end=section.page_end,
            confidence=section.confidence,
            service_name=svc,
            tables=norm_tables,
            full_text=section.full_text,
        ))

    return NormalizedDocument(
        source_path=doc.source_path,
        page_count=doc.page_count,
        vendor=vendor,
        extraction_method=doc.extraction_method.value,
        sections=normalized_sections,
    )
