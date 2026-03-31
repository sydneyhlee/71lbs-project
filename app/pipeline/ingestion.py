"""
Ingestion orchestrator: ties together the full extraction pipeline.

Upload PDF → Parse → Chunk → Extract → Score → Resolve → Store
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.config import UPLOADS_DIR
from app.models.schema import ContractExtraction
from app.pipeline.pdf_parser import parse_pdf
from app.pipeline.chunker import chunk_document
from app.pipeline.extractor import extract_contract
from app.pipeline.confidence import score_extraction
from app.pipeline.resolver import resolve_active_terms
from app.storage.store import save_extraction

logger = logging.getLogger(__name__)


def ingest_pdf(source_path: str | Path) -> ContractExtraction:
    """
    Run the full extraction pipeline on a PDF file.

    Steps:
    1. Copy file to uploads directory
    2. Parse PDF (text + OCR fallback)
    3. Chunk document into LLM-sized segments
    4. Extract structured data via LLM
    5. Score confidence and flag low-confidence fields
    6. Resolve amendments into active terms snapshot
    7. Save extraction result

    Returns the complete ContractExtraction.
    """
    source_path = Path(source_path)
    dest_path = UPLOADS_DIR / source_path.name

    # Copy to uploads if not already there
    if source_path.resolve() != dest_path.resolve():
        shutil.copy2(source_path, dest_path)
        logger.info("Copied %s to uploads", source_path.name)

    # Step 1: Parse
    logger.info("Step 1/5: Parsing PDF")
    doc = parse_pdf(dest_path)
    if doc.errors:
        logger.warning("Parse warnings: %s", doc.errors)

    # Step 2: Chunk
    logger.info("Step 2/5: Chunking document")
    chunks = chunk_document(doc)
    if not chunks:
        logger.warning("No chunks produced — document may be empty or unreadable")

    # Step 3: Extract
    logger.info("Step 3/5: Extracting structured data")
    extraction = extract_contract(
        chunks=chunks,
        file_name=source_path.name,
        file_path=str(dest_path),
    )

    # Step 4: Score confidence
    logger.info("Step 4/5: Scoring confidence")
    extraction = score_extraction(extraction)

    # Step 5: Resolve amendments
    logger.info("Step 5/5: Resolving amendments")
    extraction = resolve_active_terms(extraction)

    # Save
    save_extraction(extraction)
    logger.info(
        "Ingestion complete: id=%s, confidence=%.2f, review_fields=%d",
        extraction.id, extraction.overall_confidence,
        extraction.fields_needing_review,
    )
    return extraction
