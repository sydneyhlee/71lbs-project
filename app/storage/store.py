"""
JSON file-based storage for contract extractions.

Each extraction is saved as a JSON file named by its ID.
Simple and sufficient for MVP — swap for a database later.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import List, Optional

from app.config import EXTRACTED_DIR, APPROVED_DIR
from app.models.schema import ContractExtraction, ExtractionStatus
from app.pipeline.dedupe import dedupe_service_terms
from app.pipeline.resolver import resolve_active_terms

logger = logging.getLogger(__name__)


def _path_for(extraction_id: str, directory: Path) -> Path:
    return directory / f"{extraction_id}.json"


def save_extraction(extraction: ContractExtraction) -> Path:
    """Save an extraction result to the extracted directory."""
    path = _path_for(extraction.id, EXTRACTED_DIR)
    path.write_text(
        extraction.model_dump_json(indent=2),
        encoding="utf-8",
    )
    logger.info("Saved extraction %s to %s", extraction.id, path)
    return path


def load_extraction(extraction_id: str) -> Optional[ContractExtraction]:
    """Load an extraction by ID from either extracted or approved directory."""
    for directory in [EXTRACTED_DIR, APPROVED_DIR]:
        path = _path_for(extraction_id, directory)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return ContractExtraction(**data)
    return None


def list_extractions(
    status_filter: Optional[ExtractionStatus] = None,
) -> List[ContractExtraction]:
    """List all extractions, optionally filtered by status."""
    results = []
    for directory in [EXTRACTED_DIR, APPROVED_DIR]:
        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                extraction = ContractExtraction(**data)
                if status_filter and extraction.status != status_filter:
                    continue
                results.append(extraction)
            except Exception as exc:
                logger.warning("Failed to load %s: %s", path, exc)
    # Deduplicate by ID (in case file exists in both dirs)
    seen = set()
    deduped = []
    for e in results:
        if e.id not in seen:
            seen.add(e.id)
            deduped.append(e)
    return sorted(deduped, key=lambda e: e.extraction_timestamp, reverse=True)


def approve_extraction(extraction_id: str) -> Optional[ContractExtraction]:
    """Move an extraction to approved status and directory."""
    extraction = load_extraction(extraction_id)
    if not extraction:
        return None

    # Final pre-approval normalization: dedupe + resolved snapshot.
    extraction = dedupe_service_terms(extraction)
    extraction = resolve_active_terms(extraction)
    extraction.status = ExtractionStatus.APPROVED
    approved_path = _path_for(extraction_id, APPROVED_DIR)
    approved_path.write_text(
        extraction.model_dump_json(indent=2),
        encoding="utf-8",
    )

    # Remove from extracted dir if present
    extracted_path = _path_for(extraction_id, EXTRACTED_DIR)
    if extracted_path.exists():
        extracted_path.unlink()

    logger.info("Approved extraction %s", extraction_id)
    return extraction


def reject_extraction(extraction_id: str) -> Optional[ContractExtraction]:
    """Mark an extraction as rejected (keeps in extracted dir)."""
    extraction = load_extraction(extraction_id)
    if not extraction:
        return None

    extraction.status = ExtractionStatus.REJECTED
    save_extraction(extraction)
    logger.info("Rejected extraction %s", extraction_id)
    return extraction


def update_extraction(extraction: ContractExtraction) -> Path:
    """Update an existing extraction (e.g., after review edits)."""
    # Remove from old location if status changed
    for directory in [EXTRACTED_DIR, APPROVED_DIR]:
        old_path = _path_for(extraction.id, directory)
        if old_path.exists():
            old_path.unlink()

    if extraction.status == ExtractionStatus.APPROVED:
        target_dir = APPROVED_DIR
    else:
        target_dir = EXTRACTED_DIR

    path = _path_for(extraction.id, target_dir)
    path.write_text(
        extraction.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return path


def delete_extraction(extraction_id: str) -> bool:
    """Delete an extraction from all directories."""
    deleted = False
    for directory in [EXTRACTED_DIR, APPROVED_DIR]:
        path = _path_for(extraction_id, directory)
        if path.exists():
            path.unlink()
            deleted = True
    return deleted
