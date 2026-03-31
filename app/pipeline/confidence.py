"""
Confidence scoring and review-flagging logic.

Combines LLM-reported confidence with heuristic checks to produce
a final confidence score per field. Flags fields below the configured
threshold for human review.
"""

from __future__ import annotations

import re
import logging
from typing import List, Tuple

from app.config import CONFIDENCE_THRESHOLD
from app.models.schema import (
    ContractExtraction,
    ExtractedValue,
    ServiceTerm,
    Surcharge,
    DIMRule,
    SpecialTerm,
    Amendment,
)

logger = logging.getLogger(__name__)

# Heuristic patterns for validation
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUMBER_PATTERN = re.compile(r"^-?\d+\.?\d*$")
_ACCOUNT_PATTERN = re.compile(r"[\dA-Z]{4,}")


def _boost_if_pattern_matches(ev: ExtractedValue, pattern: re.Pattern, boost: float = 0.1) -> float:
    """Add a confidence boost if the value matches an expected pattern."""
    if ev.value and isinstance(ev.value, str) and pattern.search(ev.value):
        return min(ev.confidence + boost, 1.0)
    return ev.confidence


def _penalize_if_missing(ev: ExtractedValue, penalty: float = 0.3) -> float:
    """Penalize confidence if value is None or empty."""
    if ev.value is None or ev.value == "" or ev.value == []:
        return 0.0
    return ev.confidence


def _score_extracted_value(ev: ExtractedValue, field_name: str) -> float:
    """Compute a refined confidence score for a single extracted value."""
    if ev.value is None:
        return 0.0

    score = ev.confidence

    # Apply pattern-based boosts for known field types
    if "date" in field_name:
        score = _boost_if_pattern_matches(ev, _DATE_PATTERN, 0.05)
    elif "account" in field_name:
        score = _boost_if_pattern_matches(ev, _ACCOUNT_PATTERN, 0.05)
    elif "percentage" in field_name or "divisor" in field_name:
        if isinstance(ev.value, (int, float)):
            score = min(score + 0.05, 1.0)

    # Boost if provenance is present
    if ev.source_page is not None and ev.source_text:
        score = min(score + 0.03, 1.0)

    return round(score, 3)


def _walk_extracted_values(obj, prefix: str = "") -> List[Tuple[str, ExtractedValue]]:
    """Recursively find all ExtractedValue fields in a Pydantic model."""
    results = []
    if isinstance(obj, ExtractedValue):
        results.append((prefix, obj))
    elif hasattr(obj, "model_fields"):
        for field_name in obj.model_fields:
            val = getattr(obj, field_name, None)
            path = f"{prefix}.{field_name}" if prefix else field_name
            if isinstance(val, ExtractedValue):
                results.append((path, val))
            elif isinstance(val, list):
                for i, item in enumerate(val):
                    results.extend(_walk_extracted_values(item, f"{path}[{i}]"))
            elif hasattr(val, "model_fields"):
                results.extend(_walk_extracted_values(val, path))
    return results


def score_extraction(extraction: ContractExtraction) -> ContractExtraction:
    """
    Refine confidence scores and flag fields needing review.

    Mutates the extraction in place and returns it.
    """
    all_fields = _walk_extracted_values(extraction)
    total = 0
    review_count = 0
    score_sum = 0.0
    non_null_count = 0

    for path, ev in all_fields:
        field_name = path.split(".")[-1].split("[")[0]
        refined = _score_extracted_value(ev, field_name)
        ev.confidence = refined
        total += 1

        if ev.value is not None:
            non_null_count += 1
            score_sum += refined
            if refined < CONFIDENCE_THRESHOLD:
                ev.needs_review = True
                review_count += 1
            else:
                ev.needs_review = False

    extraction.overall_confidence = round(
        score_sum / max(non_null_count, 1), 3
    )
    extraction.fields_needing_review = review_count
    extraction.total_fields_extracted = non_null_count

    logger.info(
        "Scored %d fields: overall=%.2f, needing_review=%d",
        total, extraction.overall_confidence, review_count,
    )
    return extraction
