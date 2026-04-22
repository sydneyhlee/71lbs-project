"""
Canonical schema for extracted shipping contract data.

Designed for FedEx initially, extensible to UPS / DHL / 3PL / freight.
Every extracted field is wrapped in ExtractedValue to carry provenance
(page number, source text snippet) and a confidence score.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
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
    original_parser_value: Optional[Any] = None
    llm_corrected_value: Optional[Any] = None
    was_llm_corrected: bool = False
    correction_reason: Optional[str] = None
    confidence_rationale: Optional[str] = None

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
    # Company-level identity fields used by invoice audit/reporting.
    client_id: Optional[str] = None
    contract_id: Optional[str] = None
    document_type: Optional[str] = None
    effective_date: Optional[str] = None
    expiration_date: Optional[str] = None
    # Optional negotiated terms used by deterministic invoice checks.
    fuel_surcharge: Optional[Dict[str, Any]] = None
    accessorials: Optional[Dict[str, Any]] = None
    gsr_status: Optional[Dict[str, Any]] = None
    earned_discounts: Optional[Dict[str, Any]] = None
    minimum_net_charge: Optional[Dict[str, Any]] = None
    dim_weight: Optional[Dict[str, Any]] = None
    threePL: Optional[Dict[str, Any]] = None
    verifier_diagnostics: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Invoice audit models
# ---------------------------------------------------------------------------

class InvoiceLineItem(BaseModel):
    """Normalized invoice line item for deterministic comparison."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tracking_number: str = ""
    transaction_id: Optional[str] = None
    invoice_id: Optional[str] = None
    ship_date: Optional[date] = None
    actual_delivery_datetime: Optional[datetime] = None
    service_code: Optional[str] = None
    service_group: Optional[str] = None
    package_type: Optional[str] = None
    service_or_charge_type: str = ""
    origin_zip: Optional[str] = None
    destination_zip: Optional[str] = None
    zone: Optional[int] = None
    actual_weight_lbs: Optional[float] = None
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    rated_weight_lbs: Optional[float] = None
    rate_per_lb: Optional[float] = None
    published_charge: Optional[float] = None
    transport_charge: Optional[float] = None
    earned_discount_applied: Optional[float] = None
    incentive_credit: Optional[float] = None
    net_transport_charge: Optional[float] = None
    fuel_surcharge_billed: Optional[float] = None
    residential_surcharge_billed: Optional[float] = None
    das_billed: Optional[float] = None
    ahs_billed: Optional[float] = None
    large_package_billed: Optional[float] = None
    address_correction_billed: Optional[float] = None
    saturday_delivery_billed: Optional[float] = None
    declared_value_billed: Optional[float] = None
    total_billed: float = 0.0
    is_residential: Optional[bool] = None
    carrier_exception_code: Optional[str] = None
    base_amount: Optional[float] = None
    billed_amount: float = 0.0
    applied_discount_pct: Optional[float] = None
    source_page: Optional[int] = None
    source_text: Optional[str] = None
    raw_line_text: Optional[str] = None


class DiscrepancyType(str, Enum):
    OVERCHARGE = "overcharge"
    UNDERCHARGE = "undercharge"
    UNSUPPORTED_FEE = "unsupported_fee"
    MISSING_DISCOUNT = "missing_discount"
    AMBIGUOUS = "ambiguous_needs_review"


class AuditDiscrepancy(BaseModel):
    """A single invoice discrepancy against an approved agreement."""
    line_id: Optional[str] = None
    tracking_number: Optional[str] = None
    company_name: str = ""
    invoice_id: Optional[str] = None
    transaction_id: Optional[str] = None
    ship_date: Optional[date] = None
    service_or_charge_type: str = ""
    discrepancy_type: DiscrepancyType
    field: Optional[str] = None
    billed_amount: float = 0.0
    expected_amount: Optional[float] = None
    dollar_discrepancy: Optional[float] = None
    expected_value: Optional[float] = None
    billed_value: Optional[float] = None
    dollar_impact: float = 0.0
    why_discrepancy: str = ""
    explanation: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    invoice_source_reference: Optional[str] = None
    agreement_source_reference: Optional[str] = None


class InvoiceAuditReport(BaseModel):
    """Aggregate report for one invoice audit run."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    company_name: str
    agreement_id: str
    carrier: Optional[str] = None
    invoice_period_start: Optional[date] = None
    invoice_period_end: Optional[date] = None
    invoice_files: List[str] = Field(default_factory=list)
    discrepancies: List[AuditDiscrepancy] = Field(default_factory=list)
    total_recovery_potential: float = 0.0
    lines_audited: int = 0
    lines_with_discrepancies: int = 0


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
