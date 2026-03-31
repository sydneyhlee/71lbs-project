"""
FastAPI routes for the contract extraction API.

Endpoints:
- POST   /api/upload         Upload and process a PDF
- GET    /api/extractions     List all extractions
- GET    /api/extractions/{id}  Get a single extraction
- PUT    /api/extractions/{id}/review   Submit review edits
- POST   /api/extractions/{id}/approve  Approve extraction
- POST   /api/extractions/{id}/reject   Reject extraction
- GET    /api/extractions/{id}/export   Export approved JSON
- DELETE /api/extractions/{id}          Delete extraction
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.models.schema import (
    BulkReviewUpdate,
    ContractExtraction,
    ExtractionStatus,
)
from app.pipeline.ingestion import ingest_pdf
from app.storage.store import (
    approve_extraction,
    delete_extraction,
    list_extractions,
    load_extraction,
    reject_extraction,
    update_extraction,
)
from app.pipeline.confidence import score_extraction

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["extractions"])


@router.post("/upload", response_model=ContractExtraction)
async def upload_pdf(file: UploadFile = File(...)):
    """Upload a contract PDF and run the full extraction pipeline."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    # Save uploaded file to temp location, then ingest
    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        extraction = ingest_pdf(tmp_path)
    except Exception as exc:
        logger.exception("Ingestion failed")
        raise HTTPException(500, f"Extraction failed: {exc}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return extraction


@router.get("/extractions", response_model=List[ContractExtraction])
async def get_extractions(
    status: Optional[ExtractionStatus] = Query(None, description="Filter by status"),
):
    """List all contract extractions."""
    return list_extractions(status_filter=status)


@router.get("/extractions/{extraction_id}", response_model=ContractExtraction)
async def get_extraction(extraction_id: str):
    """Get a single extraction by ID."""
    extraction = load_extraction(extraction_id)
    if not extraction:
        raise HTTPException(404, "Extraction not found")
    return extraction


@router.put("/extractions/{extraction_id}/review", response_model=ContractExtraction)
async def submit_review(extraction_id: str, body: BulkReviewUpdate):
    """
    Submit review edits for an extraction.

    Field paths use dot notation, e.g.:
    - "metadata.customer_name" for top-level metadata
    - "service_terms[0].discount_percentage" for list items
    """
    extraction = load_extraction(extraction_id)
    if not extraction:
        raise HTTPException(404, "Extraction not found")

    for update in body.updates:
        _apply_field_update(extraction, update.field_path, update.corrected_value)

    if body.notes:
        extraction.review_notes = body.notes

    # Re-score after edits
    extraction = score_extraction(extraction)

    if body.approve:
        extraction.status = ExtractionStatus.APPROVED
    elif body.reject:
        extraction.status = ExtractionStatus.REJECTED

    update_extraction(extraction)
    return extraction


@router.post("/extractions/{extraction_id}/approve", response_model=ContractExtraction)
async def approve(extraction_id: str):
    """Approve an extraction, moving it to the approved directory."""
    result = approve_extraction(extraction_id)
    if not result:
        raise HTTPException(404, "Extraction not found")
    return result


@router.post("/extractions/{extraction_id}/reject", response_model=ContractExtraction)
async def reject(extraction_id: str):
    """Reject an extraction."""
    result = reject_extraction(extraction_id)
    if not result:
        raise HTTPException(404, "Extraction not found")
    return result


@router.get("/extractions/{extraction_id}/export")
async def export_extraction(extraction_id: str):
    """Export an approved extraction as clean JSON."""
    extraction = load_extraction(extraction_id)
    if not extraction:
        raise HTTPException(404, "Extraction not found")
    return extraction.model_dump()


@router.delete("/extractions/{extraction_id}")
async def remove_extraction(extraction_id: str):
    """Delete an extraction."""
    if delete_extraction(extraction_id):
        return {"status": "deleted", "id": extraction_id}
    raise HTTPException(404, "Extraction not found")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_field_update(extraction: ContractExtraction, path: str, value) -> None:
    """
    Apply a reviewer correction to a field using dot-notation path.

    Supports paths like:
    - metadata.customer_name
    - service_terms[0].discount_percentage
    - surcharges[1].surcharge_name
    """
    import re

    parts = re.split(r"\.|(?=\[)", path)
    obj = extraction
    for i, part in enumerate(parts[:-1]):
        # Handle array index like [0]
        match = re.match(r"\[(\d+)\]", part)
        if match:
            obj = obj[int(match.group(1))]
        elif hasattr(obj, part):
            obj = getattr(obj, part)
        elif isinstance(obj, dict):
            obj = obj[part]
        else:
            logger.warning("Cannot navigate path: %s (stuck at %s)", path, part)
            return

    last_part = parts[-1]
    match = re.match(r"\[(\d+)\]", last_part)
    if match:
        obj[int(match.group(1))].reviewer_override = value
    elif hasattr(obj, last_part):
        field = getattr(obj, last_part)
        if hasattr(field, "reviewer_override"):
            field.reviewer_override = value
    elif isinstance(obj, dict) and last_part in obj:
        if isinstance(obj[last_part], dict) and "reviewer_override" in obj[last_part]:
            obj[last_part]["reviewer_override"] = value
