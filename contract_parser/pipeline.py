from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from contract_parser.layout_parser import parse_layout
from contract_parser.llm_extractor import LLMExtractor, needs_llm
from contract_parser.pdf_ingestion import ingest_pdf
from contract_parser.post_processor import build_contract
from contract_parser.section_classifier import classify_sections
from contract_parser.table_extractor import extract_tables
from contract_parser.types import PipelineOutput
from contract_parser.validator import validate


AGREEMENT_RE = re.compile(r"(agreement|account)\s*(number|#)?\s*[:\-]?\s*([A-Z0-9\-]+)", re.IGNORECASE)
DATE_RE = re.compile(r"(effective\s*date)\s*[:\-]?\s*([0-9/.\-]+)", re.IGNORECASE)


def _extract_metadata(sections: list[dict[str, Any]]) -> dict[str, Any]:
    joined = " ".join(s.get("text_blob", "") for s in sections)
    low = joined.lower()
    carrier = "fedex" if "fedex" in low else "ups" if "ups" in low else "other"

    agreement_number = ""
    m = AGREEMENT_RE.search(joined)
    if m:
        agreement_number = m.group(3)

    effective_date = ""
    m = DATE_RE.search(joined)
    if m:
        effective_date = m.group(2)

    return {
        "carrier": carrier,
        "customer_name": "",
        "agreement_number": agreement_number,
        "effective_date": effective_date,
    }


def run_pipeline(pdf_path: str, llm_call: Callable[[str], str] | None = None) -> dict[str, Any]:
    pages = ingest_pdf(pdf_path)
    with ThreadPoolExecutor() as pool:
        layout_future = pool.submit(parse_layout, pages)
        layout = layout_future.result()

    sections = classify_sections(layout)
    table_rows = extract_tables(sections)

    llm = LLMExtractor(llm_call=llm_call)
    llm_fragments: list[dict[str, Any]] = []
    for section in sections:
        if needs_llm(section):
            llm_fragments.append(llm.extract_section(section))

    metadata = _extract_metadata(sections)
    contract = build_contract(metadata, sections, table_rows, llm_fragments)
    quality = validate(contract)
    output = PipelineOutput(
        contract=contract,
        confidence=quality["confidence"],
        raw_sections=sections,
    )
    return output.model_dump()
