from __future__ import annotations

from statistics import mean
from typing import Iterable

from app.models.schema import ContractExtraction, ExtractedValue
from .models import ConfidenceBreakdown, Issue, IssueSeverity


def _collect_confidences(extraction: ContractExtraction) -> list[float]:
    """Collect all non-zero confidence scores from extracted values."""
    scores: list[float] = []

    for field_name in ["customer_name", "account_number", "agreement_number",
                       "effective_date", "carrier"]:
        fld = getattr(extraction.metadata, field_name)
        if fld.confidence > 0:
            scores.append(fld.confidence)

    for st in extraction.service_terms:
        if st.service_type.confidence > 0:
            scores.append(st.service_type.confidence)
        if st.discount_percentage.confidence > 0:
            scores.append(st.discount_percentage.confidence)

    for sc in extraction.surcharges:
        if sc.surcharge_name.confidence > 0:
            scores.append(sc.surcharge_name.confidence)

    for dr in extraction.dim_rules:
        if dr.dim_divisor.confidence > 0:
            scores.append(dr.dim_divisor.confidence)

    return scores


def _extraction_confidence(extraction: ContractExtraction) -> float:
    """Average confidence of all extracted entities."""
    s = _collect_confidences(extraction)
    if not s:
        return 0.4
    return round(mean(s), 4)


def _normalization_confidence(extraction: ContractExtraction) -> float:
    """How complete and structured the extraction is."""
    num = 0
    denom = 0

    meta = extraction.metadata
    for field_name in ["customer_name", "account_number", "agreement_number",
                       "effective_date", "carrier"]:
        denom += 1
        fld = getattr(meta, field_name)
        if fld.value is not None:
            num += 1

    for st in extraction.service_terms:
        denom += 1
        if st.service_type.value and st.discount_percentage.value is not None:
            num += 1
        elif st.service_type.value:
            num += 0.5

    for sc in extraction.surcharges:
        denom += 1
        if sc.surcharge_name.value and sc.modification.value:
            num += 1
        elif sc.surcharge_name.value:
            num += 0.4

    if denom == 0:
        return 0.5
    return round(min(1.0, num / denom), 4)


def _penalty_from_issues(issues: Iterable[Issue]) -> float:
    p = 0.0
    for i in issues:
        if i.severity == IssueSeverity.ERROR:
            p += 0.12
        elif i.severity == IssueSeverity.WARNING:
            p += 0.05
        else:
            p += 0.015
    return min(1.0, p)


def compute_confidence(extraction: ContractExtraction, issues: list[Issue]) -> ConfidenceBreakdown:
    ext = _extraction_confidence(extraction)
    norm = _normalization_confidence(extraction)
    penalty = _penalty_from_issues(issues)
    aggregate = max(0.0, min(1.0, 0.45 * ext + 0.35 * norm + 0.2 * (1.0 - penalty)))
    return ConfidenceBreakdown(
        extraction=ext,
        normalization=norm,
        validation_penalty=round(penalty, 4),
        aggregate=round(aggregate, 4),
    )
