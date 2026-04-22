"""
Canonical schema for extracted shipping contract data.

Designed for FedEx initially, extensible to UPS / DHL / 3PL / freight.
Every extracted field is wrapped in ExtractedValue to carry provenance
(page number, source text snippet) and a confidence score.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Carrier(str, Enum):
    FEDEX = "FedEx"
    UPS = "UPS"
    USPS = "USPS"
    DHL = "DHL"
    OTHER = "Other"


class ExtractionStatus(str, Enum):
    PENDING = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Provenance & extracted-value wrapper
# ---------------------------------------------------------------------------

class ExtractedValue(BaseModel):
    """Wraps any extracted field with provenance and confidence metadata."""
    value: Any = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_page: Optional[int] = None
    source_text: Optional[str] = None
    needs_review: bool = False
    reviewer_override: Optional[Any] = None

    def effective(self) -> Any:
        """Return reviewer-corrected value if present, else raw extraction."""
        if self.reviewer_override is not None:
            return self.reviewer_override
        return self.value


def ev(value: Any = None, confidence: float = 0.0,
       source_page: int | None = None, source_text: str | None = None,
       needs_review: bool = False) -> ExtractedValue:
    """Shorthand factory for creating ExtractedValue instances."""
    return ExtractedValue(
        value=value, confidence=confidence,
        source_page=source_page, source_text=source_text,
        needs_review=needs_review,
    )


# ---------------------------------------------------------------------------
# Contract sub-models
# ---------------------------------------------------------------------------

class ContractMetadata(BaseModel):
    """Core identifiers and dates for the contract."""
    customer_name: ExtractedValue = Field(default_factory=ExtractedValue)
    account_number: ExtractedValue = Field(default_factory=ExtractedValue)
    agreement_number: ExtractedValue = Field(default_factory=ExtractedValue)
    version_number: ExtractedValue = Field(default_factory=ExtractedValue)
    effective_date: ExtractedValue = Field(default_factory=ExtractedValue)
    term_start: ExtractedValue = Field(default_factory=ExtractedValue)
    term_end: ExtractedValue = Field(default_factory=ExtractedValue)
    payment_terms: ExtractedValue = Field(default_factory=ExtractedValue)
    carrier: ExtractedValue = Field(default_factory=ExtractedValue)
    # Offer acceptance deadline — not the contract effective date (see metadata_extractor).
    offer_expiration: ExtractedValue = Field(default_factory=ExtractedValue)
    # True when text references addendum / master agreement / statutory term definition, etc.
    external_term_reference: ExtractedValue = Field(default_factory=ExtractedValue)
    # Document-level list or narrative of services in scope (distinct from per-DIM-rule fields).
    applicable_services: ExtractedValue = Field(default_factory=ExtractedValue)


class ServiceTerm(BaseModel):
    """A pricing term for a specific service type / zone combination."""
    service_type: ExtractedValue = Field(default_factory=ExtractedValue)
    applicable_zones: ExtractedValue = Field(default_factory=ExtractedValue)
    discount_percentage: ExtractedValue = Field(default_factory=ExtractedValue)
    base_rate_adjustment: ExtractedValue = Field(default_factory=ExtractedValue)
    conditions: ExtractedValue = Field(default_factory=ExtractedValue)
    effective_date: ExtractedValue = Field(default_factory=ExtractedValue)


class Surcharge(BaseModel):
    """A surcharge line item with optional discount/modification."""
    surcharge_name: ExtractedValue = Field(default_factory=ExtractedValue)
    application: ExtractedValue = Field(default_factory=ExtractedValue)
    applicable_zones: ExtractedValue = Field(default_factory=ExtractedValue)
    modification: ExtractedValue = Field(default_factory=ExtractedValue)
    discount_percentage: ExtractedValue = Field(default_factory=ExtractedValue)
    effective_date: ExtractedValue = Field(default_factory=ExtractedValue)


class DIMRule(BaseModel):
    """Dimensional weight divisor rule."""
    dim_divisor: ExtractedValue = Field(default_factory=ExtractedValue)
    applicable_services: ExtractedValue = Field(default_factory=ExtractedValue)
    conditions: ExtractedValue = Field(default_factory=ExtractedValue)


class SpecialTerm(BaseModel):
    """Catch-all for non-standard terms (e.g., money-back-guarantee waiver)."""
    term_name: ExtractedValue = Field(default_factory=ExtractedValue)
    term_value: ExtractedValue = Field(default_factory=ExtractedValue)
    conditions: ExtractedValue = Field(default_factory=ExtractedValue)


class Amendment(BaseModel):
    """An amendment that may override terms from a prior version."""
    amendment_number: ExtractedValue = Field(default_factory=ExtractedValue)
    effective_date: ExtractedValue = Field(default_factory=ExtractedValue)
    supersedes_version: ExtractedValue = Field(default_factory=ExtractedValue)
    description: ExtractedValue = Field(default_factory=ExtractedValue)
    modified_service_terms: List[ServiceTerm] = Field(default_factory=list)
    modified_surcharges: List[Surcharge] = Field(default_factory=list)
    modified_dim_rules: List[DIMRule] = Field(default_factory=list)
    modified_special_terms: List[SpecialTerm] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level extraction result
# ---------------------------------------------------------------------------

class ContractExtraction(BaseModel):
    """Complete extraction result for a single contract PDF."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_name: str = ""
    file_path: str = ""
    extraction_timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    status: ExtractionStatus = ExtractionStatus.PENDING

    metadata: ContractMetadata = Field(default_factory=ContractMetadata)
    service_terms: List[ServiceTerm] = Field(default_factory=list)
    surcharges: List[Surcharge] = Field(default_factory=list)
    dim_rules: List[DIMRule] = Field(default_factory=list)
    special_terms: List[SpecialTerm] = Field(default_factory=list)
    amendments: List[Amendment] = Field(default_factory=list)

    overall_confidence: float = 0.0
    fields_needing_review: int = 0
    total_fields_extracted: int = 0
    review_notes: Optional[str] = None

    # Resolved view after amendment processing
    active_terms_snapshot: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# API request / response helpers
# ---------------------------------------------------------------------------

class ReviewUpdate(BaseModel):
    """Payload for submitting human review edits."""
    field_path: str          # dot-notation path, e.g. "metadata.customer_name"
    corrected_value: Any
    reviewer_note: Optional[str] = None


class BulkReviewUpdate(BaseModel):
    updates: List[ReviewUpdate] = Field(default_factory=list)
    approve: bool = False
    reject: bool = False
    notes: Optional[str] = None
