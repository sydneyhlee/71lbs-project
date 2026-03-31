"""
Amendment resolver: merges amendments into a resolved "active terms" snapshot.

When a contract has amendments, later amendments (by effective date) override
earlier terms. This module builds a flattened view of what terms are currently
active, preserving the full amendment history for audit.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from app.models.schema import (
    Amendment,
    ContractExtraction,
    DIMRule,
    ServiceTerm,
    SpecialTerm,
    Surcharge,
)

logger = logging.getLogger(__name__)


def _parse_date_safe(date_str: Optional[str]) -> Optional[date]:
    """Parse an ISO date string, returning None on failure."""
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def _sort_amendments(amendments: List[Amendment]) -> List[Amendment]:
    """Sort amendments by effective date (earliest first)."""
    def sort_key(a: Amendment) -> str:
        d = a.effective_date.effective()
        return d if d else "0000-00-00"
    return sorted(amendments, key=sort_key)


def _term_key(term: ServiceTerm) -> str:
    """Generate a dedup key for a service term based on service type."""
    svc = term.service_type.effective() or "unknown"
    return svc.lower().strip()


def _surcharge_key(s: Surcharge) -> str:
    name = s.surcharge_name.effective() or "unknown"
    return name.lower().strip()


def _dim_key(d: DIMRule) -> str:
    services = d.applicable_services.effective() or []
    if isinstance(services, list):
        return "|".join(sorted(s.lower().strip() for s in services))
    return str(services).lower().strip()


def _special_key(s: SpecialTerm) -> str:
    name = s.term_name.effective() or "unknown"
    return name.lower().strip()


def resolve_active_terms(extraction: ContractExtraction) -> ContractExtraction:
    """
    Build an active_terms_snapshot by layering amendments on top of base terms.

    Amendments are applied in effective-date order. When an amendment modifies
    a term that matches an existing one (by service type / surcharge name),
    it replaces the prior version. New terms are added.

    The original extraction data is preserved unchanged; only the
    active_terms_snapshot field is populated.
    """
    # Start with base terms
    active_service: Dict[str, dict] = {}
    for st in extraction.service_terms:
        key = _term_key(st)
        active_service[key] = st.model_dump()

    active_surcharges: Dict[str, dict] = {}
    for sc in extraction.surcharges:
        key = _surcharge_key(sc)
        active_surcharges[key] = sc.model_dump()

    active_dim: Dict[str, dict] = {}
    for dr in extraction.dim_rules:
        key = _dim_key(dr)
        active_dim[key] = dr.model_dump()

    active_special: Dict[str, dict] = {}
    for sp in extraction.special_terms:
        key = _special_key(sp)
        active_special[key] = sp.model_dump()

    # Layer amendments
    sorted_amendments = _sort_amendments(extraction.amendments)
    for amendment in sorted_amendments:
        amd_date = amendment.effective_date.effective()
        amd_num = amendment.amendment_number.effective() or "?"
        logger.info("Applying amendment %s (effective %s)", amd_num, amd_date)

        for st in amendment.modified_service_terms:
            key = _term_key(st)
            active_service[key] = st.model_dump()

        for sc in amendment.modified_surcharges:
            key = _surcharge_key(sc)
            active_surcharges[key] = sc.model_dump()

        for dr in amendment.modified_dim_rules:
            key = _dim_key(dr)
            active_dim[key] = dr.model_dump()

        for sp in amendment.modified_special_terms:
            key = _special_key(sp)
            active_special[key] = sp.model_dump()

    extraction.active_terms_snapshot = {
        "resolved_at": date.today().isoformat(),
        "amendments_applied": [
            {
                "number": a.amendment_number.effective(),
                "effective_date": a.effective_date.effective(),
            }
            for a in sorted_amendments
        ],
        "service_terms": list(active_service.values()),
        "surcharges": list(active_surcharges.values()),
        "dim_rules": list(active_dim.values()),
        "special_terms": list(active_special.values()),
    }

    logger.info(
        "Resolved active terms: %d service, %d surcharges, %d DIM, %d special",
        len(active_service), len(active_surcharges),
        len(active_dim), len(active_special),
    )
    return extraction
