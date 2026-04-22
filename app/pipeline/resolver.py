"""Amendment + multi-document supersession resolver."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.models.schema import (
    Amendment,
    ExtractedValue,
    ContractExtraction,
    DIMRule,
    ServiceTerm,
    SpecialTerm,
    Surcharge,
)

logger = logging.getLogger(__name__)

DOC_TYPE_PRIORITY = {
    "amendment": 3,
    "addendum": 2,
    "pricing_addendum": 2,
    "accessorial_addendum": 2,
    "base_agreement": 1,
}


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


def _effective_date_for_doc(doc: ContractExtraction) -> str:
    if doc.effective_date:
        return doc.effective_date
    md = doc.metadata.effective_date.effective()
    return str(md) if md else "1900-01-01"


def _doc_priority(doc: ContractExtraction) -> int:
    return DOC_TYPE_PRIORITY.get((doc.document_type or "base_agreement").lower(), 1)


def _overlay_extracted_value(base: ExtractedValue, overlay: ExtractedValue, overlay_doc: ContractExtraction) -> None:
    new_val = overlay.effective()
    if new_val in (None, "", []):
        return
    base.value = overlay.value
    base.confidence = overlay.confidence
    base.source_page = overlay.source_page
    base.source_text = overlay.source_text
    # Mark when an amendment controls the final value.
    if (overlay_doc.document_type or "").lower() == "amendment":
        note = f"Controlled by amendment {overlay_doc.file_name or overlay_doc.id}"
        if base.confidence_rationale:
            if note not in base.confidence_rationale:
                base.confidence_rationale = f"{base.confidence_rationale}; {note}"
        else:
            base.confidence_rationale = note


def _deep_overlay(base: Any, overlay: Any, overlay_doc: ContractExtraction) -> Any:
    if isinstance(base, ExtractedValue) and isinstance(overlay, ExtractedValue):
        _overlay_extracted_value(base, overlay, overlay_doc)
        return base

    if isinstance(base, BaseModel) and isinstance(overlay, BaseModel):
        for field_name in type(base).model_fields:
            if not hasattr(overlay, field_name):
                continue
            b_val = getattr(base, field_name)
            o_val = getattr(overlay, field_name)
            if isinstance(b_val, ExtractedValue) and isinstance(o_val, ExtractedValue):
                _overlay_extracted_value(b_val, o_val, overlay_doc)
            elif isinstance(b_val, BaseModel) and isinstance(o_val, BaseModel):
                _deep_overlay(b_val, o_val, overlay_doc)
            elif isinstance(b_val, dict) and isinstance(o_val, dict):
                merged = _merge_dicts(b_val, o_val)
                setattr(base, field_name, merged)
            elif isinstance(b_val, list) and isinstance(o_val, list):
                if o_val:
                    setattr(base, field_name, o_val)
            elif o_val not in (None, "", []):
                setattr(base, field_name, o_val)
        return base

    if isinstance(base, dict) and isinstance(overlay, dict):
        return _merge_dicts(base, overlay)

    return overlay if overlay not in (None, "", []) else base


def _merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if k not in out:
            out[k] = v
            continue
        b = out[k]
        if isinstance(b, dict) and isinstance(v, dict):
            out[k] = _merge_dicts(b, v)
        elif v not in (None, "", []):
            out[k] = v
    return out


def _apply_fuel_expiration(resolved: ContractExtraction) -> None:
    fs = resolved.fuel_surcharge
    if not isinstance(fs, dict):
        return
    exp = fs.get("expiration_date")
    if not exp:
        return
    exp_dt = _parse_date_safe(str(exp))
    if not exp_dt:
        return
    if date.today() > exp_dt:
        fs["discount_pct"] = 0.0
        fs["note"] = "Fuel surcharge discount expired; defaulted to 0%."
        resolved.fuel_surcharge = fs


def _resolve_single_extraction(extraction: ContractExtraction) -> ContractExtraction:
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
    _apply_fuel_expiration(extraction)
    return extraction


def resolve_active_terms(
    extraction_or_documents: ContractExtraction | List[ContractExtraction],
) -> ContractExtraction:
    """
    Resolve active terms from either:
      - a single extraction (base + amendments inside one doc), or
      - a list of extraction docs (base + addenda + amendments).
    """
    if isinstance(extraction_or_documents, ContractExtraction):
        return _resolve_single_extraction(extraction_or_documents)

    documents = extraction_or_documents
    if not documents:
        raise ValueError("No documents to resolve")
    if len(documents) == 1:
        return _resolve_single_extraction(documents[0])

    sorted_docs = sorted(
        documents,
        key=lambda d: (_effective_date_for_doc(d), _doc_priority(d)),
    )
    resolved = sorted_docs[0].model_copy(deep=True)
    for doc in sorted_docs[1:]:
        _deep_overlay(resolved, doc, doc)

    _apply_fuel_expiration(resolved)
    return _resolve_single_extraction(resolved)
