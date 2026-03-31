from __future__ import annotations

from typing import Any, Optional, Set, Tuple

from app.models.schema import ContractExtraction, ExtractedValue
from .models import Issue, IssueSeverity, ValidationSummary
from . import issues as C


def _issue(
    code: str,
    severity: IssueSeverity,
    message: str,
    *,
    entity_kind: Optional[str] = None,
    entity_id: Optional[str] = None,
    field: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> Issue:
    return Issue(
        code=code,
        severity=severity,
        message=message,
        entity_kind=entity_kind,
        entity_id=entity_id,
        field=field,
        details=details or {},
    )


def _check_ev(ev: ExtractedValue, field_name: str, entity_kind: str) -> list[Issue]:
    """Check a single ExtractedValue for common problems."""
    issues = []
    if ev.value is None or ev.value == "" or ev.value == []:
        issues.append(_issue(
            f"{entity_kind.upper()}_MISSING_{field_name.upper()}",
            IssueSeverity.WARNING,
            f"{entity_kind} is missing {field_name}.",
            entity_kind=entity_kind,
            field=field_name,
        ))
    if ev.confidence > 0 and ev.confidence < 0.35:
        issues.append(_issue(
            f"{entity_kind.upper()}_LOW_CONFIDENCE",
            IssueSeverity.WARNING,
            f"{entity_kind} {field_name} has low confidence ({ev.confidence:.2f}).",
            entity_kind=entity_kind,
            field=field_name,
            details={"confidence": ev.confidence},
        ))
    return issues


def validate_extraction(extraction: ContractExtraction) -> list[Issue]:
    """Validate a ContractExtraction and return a list of issues found."""
    out: list[Issue] = []

    # Metadata checks
    meta = extraction.metadata
    if not meta.customer_name.value:
        out.append(_issue(C.METADATA_MISSING_CUSTOMER, IssueSeverity.WARNING,
                          "Customer name not extracted.", entity_kind="metadata", field="customer_name"))
    if not meta.account_number.value:
        out.append(_issue(C.METADATA_MISSING_ACCOUNT, IssueSeverity.WARNING,
                          "Account number not extracted.", entity_kind="metadata", field="account_number"))
    if not meta.carrier.value or meta.carrier.value == "Unknown":
        out.append(_issue(C.METADATA_MISSING_CARRIER, IssueSeverity.WARNING,
                          "Carrier not detected.", entity_kind="metadata", field="carrier"))

    for field_name in ["customer_name", "account_number", "agreement_number",
                       "effective_date", "carrier"]:
        fld = getattr(meta, field_name)
        if fld.value is not None and fld.confidence < 0.5:
            out.append(_issue(C.METADATA_LOW_CONFIDENCE, IssueSeverity.INFO,
                              f"Metadata field '{field_name}' has low confidence ({fld.confidence:.2f}).",
                              entity_kind="metadata", field=field_name,
                              details={"confidence": fld.confidence}))

    # Service terms checks
    if not extraction.service_terms:
        out.append(_issue(C.NO_SERVICE_TERMS, IssueSeverity.WARNING,
                          "No service terms extracted.", entity_kind="extraction"))

    seen_services: Set[str] = set()
    for i, st in enumerate(extraction.service_terms):
        svc_val = st.service_type.effective()
        if not svc_val:
            out.append(_issue(C.SERVICE_TERM_MISSING_TYPE, IssueSeverity.WARNING,
                              f"Service term #{i+1} has no service type.",
                              entity_kind="service_term", entity_id=str(i)))
        else:
            key = str(svc_val).lower().strip()
            if key in seen_services:
                out.append(_issue(C.DUPLICATE_SERVICE_TERM, IssueSeverity.INFO,
                                  f"Possible duplicate service term: {svc_val}",
                                  entity_kind="service_term", entity_id=str(i)))
            seen_services.add(key)

        if st.discount_percentage.value is None:
            out.append(_issue(C.SERVICE_TERM_MISSING_DISCOUNT, IssueSeverity.INFO,
                              f"Service term '{svc_val or i+1}' has no discount percentage.",
                              entity_kind="service_term", entity_id=str(i)))
        elif isinstance(st.discount_percentage.value, (int, float)):
            v = float(st.discount_percentage.value)
            if v < 0 or v > 100:
                out.append(_issue(C.INCONSISTENT_PERCENT_RANGE, IssueSeverity.ERROR,
                                  f"Discount {v}% is outside 0-100 range.",
                                  entity_kind="service_term", entity_id=str(i),
                                  details={"value": v}))

        if st.service_type.confidence > 0 and st.service_type.confidence < 0.5:
            out.append(_issue(C.SERVICE_TERM_LOW_CONFIDENCE, IssueSeverity.INFO,
                              f"Service term '{svc_val or i+1}' has low confidence.",
                              entity_kind="service_term", entity_id=str(i),
                              details={"confidence": st.service_type.confidence}))

    # Surcharge checks
    for i, sc in enumerate(extraction.surcharges):
        if not sc.surcharge_name.value:
            out.append(_issue(C.SURCHARGE_MISSING_NAME, IssueSeverity.WARNING,
                              f"Surcharge #{i+1} has no name.",
                              entity_kind="surcharge", entity_id=str(i)))
        if not sc.modification.value:
            out.append(_issue(C.SURCHARGE_MISSING_MODIFICATION, IssueSeverity.INFO,
                              f"Surcharge '{sc.surcharge_name.value or i+1}' has no modification value.",
                              entity_kind="surcharge", entity_id=str(i)))

    # DIM rule checks
    for i, dr in enumerate(extraction.dim_rules):
        if dr.dim_divisor.value is None:
            out.append(_issue(C.DIM_RULE_MISSING_DIVISOR, IssueSeverity.WARNING,
                              f"DIM rule #{i+1} has no divisor value.",
                              entity_kind="dim_rule", entity_id=str(i)))

    return out


def summarize_issues(issues: list[Issue]) -> ValidationSummary:
    s = ValidationSummary(total_issues=len(issues))
    for i in issues:
        s.codes[i.code] = s.codes.get(i.code, 0) + 1
        if i.severity == IssueSeverity.ERROR:
            s.errors += 1
        elif i.severity == IssueSeverity.WARNING:
            s.warnings += 1
        else:
            s.infos += 1
    return s
