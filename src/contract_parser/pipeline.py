from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .extract.pdfplumber_extractor import extract_pdf
from .models import ContractDocument, ContractMetadata, ContractSection, ExtractedTable
from .normalize.parsers import derive_structured_from_section, extract_footnotes, table_to_extracted
from .segment.sectionizer import sectionize
from .vendors.registry import detect_vendor


def parse_contract_pdf(path: str) -> ContractDocument:
    extracted = extract_pdf(path)

    # Vendor detection uses all extracted text.
    full_text = "\n\n".join(b.text for b in extracted.blocks if b.block_type == "text")
    det = detect_vendor(full_text)

    doc = ContractDocument(
        source_path=path,
        metadata=ContractMetadata(vendor_name=det.vendor_name, vendor_type=det.vendor_type, raw={"detection": asdict(det)}),
        raw={"extraction": {"pages": extracted.pages}},
    )

    # Convert tables once (canonical-ish).
    tables_by_page: dict[int, list[ExtractedTable]] = {}
    for t in extracted.tables:
        et = table_to_extracted(t)
        tables_by_page.setdefault(et.span.page, []).append(et)

    # Sectionize using interleaved blocks (text + table).
    candidates = sectionize(extracted.blocks)
    for cand in candidates:
        raw_text = "\n\n".join(b.text for b in cand.blocks if b.block_type == "text").strip()
        # Attach tables appearing in the section pages. (Baseline; later we can use bboxes for tighter binding.)
        pages = sorted({sp.page for sp in cand.spans})
        sec_tables: list[ExtractedTable] = []
        for p in pages:
            sec_tables.extend(tables_by_page.get(p, []))

        footnotes = extract_footnotes(raw_text, cand.spans)
        pr, st, dt, terms = derive_structured_from_section(
            section_id=cand.id, section_text=raw_text, section_spans=cand.spans, tables=sec_tables
        )

        doc.sections.append(
            ContractSection(
                id=cand.id,
                title=cand.title,
                type=cand.type,
                spans=cand.spans,
                raw_text=raw_text,
                tables=sec_tables,
                footnotes=footnotes,
                extracted_pricing_rules=pr,
                extracted_surcharge_tables=st,
                extracted_discount_tiers=dt,
                extracted_service_terms=terms,
                raw={"sectionize": {"pages": pages}},
            )
        )

    # Minimal warnings for empty content
    if not any(s.raw_text or s.tables for s in doc.sections):
        doc.parse_warnings.append("No extractable text/tables detected; PDF may be scanned or image-only.")

    return doc


def to_machine_readable(doc: ContractDocument) -> dict[str, Any]:
    """
    Stable, canonical JSON-serializable representation.
    """
    return doc.model_dump(mode="json", exclude_none=True)

