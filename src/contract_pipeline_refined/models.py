from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from contract_parser.models import ContractDocument


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Issue(BaseModel):
    """Single validation or quality finding for downstream auditing."""

    code: str
    severity: IssueSeverity
    message: str
    entity_kind: Optional[str] = None  # pricing_rule, surcharge_table, discount_tier, section, document
    entity_id: Optional[str] = None
    section_id: Optional[str] = None
    field: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationSummary(BaseModel):
    total_issues: int = 0
    errors: int = 0
    warnings: int = 0
    infos: int = 0
    codes: dict[str, int] = Field(default_factory=dict)


class ConfidenceBreakdown(BaseModel):
    """Explainable scores for aggregate confidence."""

    extraction: float = Field(ge=0.0, le=1.0)
    normalization: float = Field(ge=0.0, le=1.0)
    validation_penalty: float = Field(ge=0.0, le=1.0, description="Amount subtracted from score due to issues")
    aggregate: float = Field(ge=0.0, le=1.0)


class RefinedContractDocument(BaseModel):
    """
    Canonical v2 envelope: same contract payload as v1 plus validation and confidence metadata.
    """

    schema_version: Literal["2.0"] = "2.0"
    document: ContractDocument
    issues: list[Issue] = Field(default_factory=list)
    validation_summary: ValidationSummary = Field(default_factory=ValidationSummary)
    confidence: ConfidenceBreakdown = Field(default_factory=ConfidenceBreakdown)
    normalized_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Document-level normalized fields (e.g. inferred currency)",
    )
