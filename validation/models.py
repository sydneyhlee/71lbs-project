from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Issue(BaseModel):
    """Single validation or quality finding for downstream auditing."""

    code: str
    severity: IssueSeverity
    message: str
    entity_kind: Optional[str] = None
    entity_id: Optional[str] = None
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


class ValidationResult(BaseModel):
    """Container for validation output attached to an extraction."""

    issues: list[Issue] = Field(default_factory=list)
    summary: ValidationSummary = Field(default_factory=ValidationSummary)
    confidence: ConfidenceBreakdown = Field(
        default_factory=lambda: ConfidenceBreakdown(
            extraction=0.5, normalization=0.5, validation_penalty=0.0, aggregate=0.5
        )
    )
