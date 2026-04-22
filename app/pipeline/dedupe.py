"""Deterministic de-duplication helpers for approved snapshots."""

from __future__ import annotations

from app.models.schema import ContractExtraction, ServiceTerm


def _norm(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return "|".join(str(x).strip().lower() for x in v)
    return str(v).strip().lower()


def dedupe_service_terms(extraction: ContractExtraction) -> ContractExtraction:
    """
    Remove duplicate service terms while keeping first-seen ordering.

    Uniqueness key:
      service_type + zones + discount + conditions + effective_date
    """
    seen: set[tuple[str, str, str, str, str]] = set()
    unique: list[ServiceTerm] = []
    for st in extraction.service_terms:
        key = (
            _norm(st.service_type.effective()),
            _norm(st.applicable_zones.effective()),
            _norm(st.discount_percentage.effective()),
            _norm(st.conditions.effective()),
            _norm(st.effective_date.effective()),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(st)
    extraction.service_terms = unique
    return extraction

