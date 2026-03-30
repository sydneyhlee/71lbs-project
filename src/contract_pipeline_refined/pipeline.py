from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .extract import extract_pdf
from contract_parser.models import ContractDocument, ContractMetadata, ContractSection, ExtractedTable
from .segment import sectionize
from contract_parser.vendors.registry import detect_vendor

from .confidence import compute_confidence
from .models import RefinedContractDocument
from .normalize.parsers import derive_refined_from_section, extract_footnotes, table_to_extracted
from .validation.validators import summarize_issues, validate_document


def parse_contract_pdf_refined(path: str) -> RefinedContractDocument:
    extracted = extract_pdf(path)
    full_text = "\n\n".join(b.text for b in extracted.blocks if b.block_type == "text")
    det = detect_vendor(full_text)

    doc = ContractDocument(
        source_path=path,
        metadata=ContractMetadata(vendor_name=det.vendor_name, vendor_type=det.vendor_type, raw={"detection": asdict(det)}),
        raw={"extraction": {"pages": extracted.pages}, "pipeline": "contract_pipeline_refined"},
    )

    tables_by_page: dict[int, list[ExtractedTable]] = {}
    for t in extracted.tables:
        et = table_to_extracted(t)
        tables_by_page.setdefault(et.span.page, []).append(et)

    candidates = sectionize(extracted.blocks)
    vendor = det.vendor_type

    for cand in candidates:
        raw_text = "\n\n".join(b.text for b in cand.blocks if b.block_type == "text").strip()
        pages = sorted({sp.page for sp in cand.spans})
        sec_tables: list[ExtractedTable] = []
        for p in pages:
            sec_tables.extend(tables_by_page.get(p, []))

        footnotes = extract_footnotes(raw_text, cand.spans)
        pr, st, dt, terms = derive_refined_from_section(
            section_id=cand.id,
            section_text=raw_text,
            section_spans=cand.spans,
            tables=sec_tables,
            vendor=vendor,
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
                raw={"sectionize": {"pages": pages}, "pipeline": "contract_pipeline_refined"},
            )
        )

    if not any(s.raw_text or s.tables for s in doc.sections):
        doc.parse_warnings.append("No extractable text/tables detected; PDF may be scanned or image-only.")

    issues = validate_document(doc)
    summary = summarize_issues(issues)
    conf = compute_confidence(doc, issues)

    return RefinedContractDocument(
        document=doc,
        issues=issues,
        validation_summary=summary,
        confidence=conf,
        normalized_metadata={"vendor_detection": asdict(det)},
    )


def to_machine_readable(result: RefinedContractDocument) -> dict[str, Any]:
    return result.model_dump(mode="json", exclude_none=True)
