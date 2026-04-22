"""
Ingestion orchestrator: ties together the full extraction pipeline.

Upload PDF -> Parse -> Extract (v2) -> Validate -> Score -> Resolve -> Store
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.config import UPLOADS_DIR
from app.models.schema import ContractExtraction
from app.pipeline.pdf_parser import parse_pdf
from app.pipeline.confidence import score_extraction
from app.pipeline.dedupe import dedupe_service_terms
from app.pipeline.llm_verifier import verify_extraction_with_llm
from app.pipeline.resolver import resolve_active_terms
from app.storage.store import save_extraction
from extraction.extractor import extract_contract_v2
from validation.validators import validate_extraction, summarize_issues
from validation.confidence import compute_confidence

logger = logging.getLogger(__name__)


def ingest_pdf(source_path: str | Path) -> ContractExtraction:
    """
    Run the full extraction pipeline on a PDF file.

    Steps:
    1. Copy file to uploads directory
    2. Parse PDF (text + OCR fallback)
    3. Extract structured data via deterministic parser pipeline
    4. Verify/correct fields using LLM (non-hallucinating corrections)
    5. Validate extraction and flag issues
    6. Score confidence and flag low-confidence fields
    7. Resolve amendments into active terms snapshot
    8. Save extraction result

    Returns the complete ContractExtraction.
    """
    source_path = Path(source_path)
    dest_path = UPLOADS_DIR / source_path.name

    if source_path.resolve() != dest_path.resolve():
        shutil.copy2(source_path, dest_path)
        logger.info("Copied %s to uploads", source_path.name)

    # Step 1: Parse
    logger.info("Step 1/6: Parsing PDF")
    doc = parse_pdf(dest_path)
    if doc.errors:
        logger.warning("Parse warnings: %s", doc.errors)

    # Step 2: Extract (v2 deterministic parser-first)
    logger.info("Step 2/6: Extracting structured data")
    extraction = extract_contract_v2(
        doc=doc,
        file_name=source_path.name,
        file_path=str(dest_path),
    )

    # Step 3: Stage-2 LLM verification
    logger.info("Step 3/6: Verifying extraction with LLM")
    extraction = verify_extraction_with_llm(extraction, doc)
    extraction = dedupe_service_terms(extraction)

    # Step 4: Validate
    logger.info("Step 4/6: Validating extraction")
    issues = validate_extraction(extraction)
    summary = summarize_issues(issues)
    confidence = compute_confidence(extraction, issues)
    logger.info(
        "Validation: %d issues (%d errors, %d warnings, %d info), confidence=%.2f",
        summary.total_issues, summary.errors, summary.warnings, summary.infos,
        confidence.aggregate,
    )

    # Step 5: Score confidence (field-level)
    logger.info("Step 5/6: Scoring field-level confidence")
    extraction = score_extraction(extraction)

    # Step 6: Resolve amendments
    logger.info("Step 6/6: Resolving amendments")
    extraction = resolve_active_terms(extraction)

    # Step 6: Save
    save_extraction(extraction)
    logger.info(
        "Ingestion complete: id=%s, confidence=%.2f, review_fields=%d",
        extraction.id, extraction.overall_confidence,
        extraction.fields_needing_review,
    )
    return extraction
