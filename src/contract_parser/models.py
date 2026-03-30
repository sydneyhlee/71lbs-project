from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Tuple

from pydantic import BaseModel, Field


class VendorType(str, Enum):
    FEDEX = "fedex"
    UPS = "ups"
    THREE_PL = "3pl"
    FREIGHT = "freight"
    UNKNOWN = "unknown"


class Span(BaseModel):
    page: int = Field(ge=1)
    bbox: Optional[Tuple[float, float, float, float]] = None  # (x0, top, x1, bottom)


class ExtractedTable(BaseModel):
    id: str
    span: Span
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class Footnote(BaseModel):
    id: str
    span: Span
    text: str


class PricingRuleType(str, Enum):
    BASE_RATE = "base_rate"
    DISCOUNT = "discount"
    SURCHARGE = "surcharge"
    MINIMUM = "minimum"
    DIMENSIONAL = "dimensional"
    ACCESSORIAL = "accessorial"
    GENERAL = "general"


class PricingRule(BaseModel):
    id: str
    type: PricingRuleType = PricingRuleType.GENERAL
    title: Optional[str] = None
    scope: dict[str, Any] = Field(default_factory=dict)  # e.g., service, zone, weight_break, package_type
    expression: dict[str, Any] = Field(default_factory=dict)  # canonicalized math/logic (rate, percent, min/max)
    text: Optional[str] = None  # raw clause text
    span: Optional[Span] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    sources: list[str] = Field(default_factory=list)  # ids of tables/clauses/footnotes


class SurchargeRow(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)


class SurchargeTable(BaseModel):
    id: str
    name: Optional[str] = None
    surcharge_type: Optional[str] = None  # e.g. fuel, residential, DAS, peak
    effective_dates: dict[str, str] = Field(default_factory=dict)
    rows: list[SurchargeRow] = Field(default_factory=list)
    span: Optional[Span] = None
    source_table_id: Optional[str] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class DiscountTier(BaseModel):
    id: str
    scope: dict[str, Any] = Field(default_factory=dict)  # e.g. service, lane, zone, weight range
    discount: dict[str, Any] = Field(default_factory=dict)  # e.g. {"type":"percent","value":23.5}
    minimums: dict[str, Any] = Field(default_factory=dict)
    span: Optional[Span] = None
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ServiceLevelTerm(BaseModel):
    id: str
    term_type: str  # e.g. "guarantee", "claims", "billing", "invoicing", "transit_time", "exceptions"
    text: str
    scope: dict[str, Any] = Field(default_factory=dict)
    span: Optional[Span] = None
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class SectionType(str, Enum):
    PRICING_RULES = "pricing_rules"
    SURCHARGES = "surcharges"
    DISCOUNTS = "discounts"
    SERVICE_TERMS = "service_terms"
    DEFINITIONS = "definitions"
    GENERAL = "general"
    UNKNOWN = "unknown"


class ContractSection(BaseModel):
    id: str
    title: Optional[str] = None
    type: SectionType = SectionType.UNKNOWN
    spans: list[Span] = Field(default_factory=list)
    raw_text: str = ""
    tables: list[ExtractedTable] = Field(default_factory=list)
    footnotes: list[Footnote] = Field(default_factory=list)
    extracted_pricing_rules: list[PricingRule] = Field(default_factory=list)
    extracted_surcharge_tables: list[SurchargeTable] = Field(default_factory=list)
    extracted_discount_tiers: list[DiscountTier] = Field(default_factory=list)
    extracted_service_terms: list[ServiceLevelTerm] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class ContractMetadata(BaseModel):
    vendor_name: Optional[str] = None
    vendor_type: VendorType = VendorType.UNKNOWN
    contract_id: Optional[str] = None
    effective_date: Optional[str] = None
    expiration_date: Optional[str] = None
    currency: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ContractDocument(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    source_path: Optional[str] = None
    metadata: ContractMetadata = Field(default_factory=ContractMetadata)
    sections: list[ContractSection] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

