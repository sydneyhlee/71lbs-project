from __future__ import annotations

from typing import Any, Optional, Set, Tuple

from contract_parser.models import ContractDocument, SectionType

from ..models import Issue, IssueSeverity, ValidationSummary
from . import issues as C


def _issue(
    code: str,
    severity: IssueSeverity,
    message: str,
    *,
    entity_kind: Optional[str] = None,
    entity_id: Optional[str] = None,
    section_id: Optional[str] = None,
    field: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> Issue:
    return Issue(
        code=code,
        severity=severity,
        message=message,
        entity_kind=entity_kind,
        entity_id=entity_id,
        section_id=section_id,
        field=field,
        details=details or {},
    )


def validate_document(doc: ContractDocument) -> list[Issue]:
    out: list[Issue] = []

    if not doc.sections:
        out.append(
            _issue(
                C.EMPTY_DOCUMENT,
                IssueSeverity.ERROR,
                "No sections were produced; PDF may be empty or unreadable.",
                entity_kind="document",
            )
        )
        return out

    any_content = False
    for sec in doc.sections:
        if (sec.raw_text or "").strip() or sec.tables:
            any_content = True
            break
    if not any_content:
        out.append(
            _issue(
                C.SCANNED_PDF_SUSPECTED,
                IssueSeverity.WARNING,
                "No extractable text or tables; possible scanned/image-only PDF.",
                entity_kind="document",
            )
        )

    tier_keys: Set[Tuple[str, str, str]] = set()
    for sec in doc.sections:
        sid = sec.id
        if not (sec.title or "").strip() and sec.type == SectionType.UNKNOWN:
            out.append(
                _issue(
                    C.SECTION_MISSING_TITLE,
                    IssueSeverity.INFO,
                    "Section has no detected title.",
                    entity_kind="section",
                    entity_id=sid,
                    section_id=sid,
                )
            )
        if not (sec.raw_text or "").strip() and not sec.tables:
            out.append(
                _issue(
                    C.SECTION_EMPTY,
                    IssueSeverity.WARNING,
                    "Section has no text and no tables.",
                    entity_kind="section",
                    entity_id=sid,
                    section_id=sid,
                )
            )

        for rule in sec.extracted_pricing_rules:
            if not (rule.text or "").strip():
                out.append(
                    _issue(
                        C.PRICING_RULE_MISSING_TEXT,
                        IssueSeverity.WARNING,
                        "Pricing rule has no clause text.",
                        entity_kind="pricing_rule",
                        entity_id=rule.id,
                        section_id=sid,
                    )
                )
            if rule.confidence < 0.35:
                out.append(
                    _issue(
                        C.PRICING_RULE_LOW_CONFIDENCE,
                        IssueSeverity.WARNING,
                        f"Pricing rule confidence is low ({rule.confidence:.2f}).",
                        entity_kind="pricing_rule",
                        entity_id=rule.id,
                        section_id=sid,
                        field="confidence",
                        details={"value": rule.confidence},
                    )
                )
            pn = (rule.expression or {}).get("percent_normalized") or {}
            if isinstance(pn, dict) and pn.get("unit") == "unknown":
                out.append(
                    _issue(
                        C.PRICING_RULE_PERCENT_AMBIGUOUS,
                        IssueSeverity.INFO,
                        "Could not normalize a clear percent value from rule text.",
                        entity_kind="pricing_rule",
                        entity_id=rule.id,
                        section_id=sid,
                    )
                )

        for st in sec.extracted_surcharge_tables:
            if not st.rows:
                out.append(
                    _issue(
                        C.SURCHARGE_TABLE_NO_ROWS,
                        IssueSeverity.WARNING,
                        "Surcharge table has no data rows.",
                        entity_kind="surcharge_table",
                        entity_id=st.id,
                        section_id=sid,
                    )
                )
            if not (st.surcharge_type or "").strip():
                out.append(
                    _issue(
                        C.SURCHARGE_TABLE_MISSING_TYPE,
                        IssueSeverity.INFO,
                        "Surcharge category (fuel, residential, etc.) was not inferred.",
                        entity_kind="surcharge_table",
                        entity_id=st.id,
                        section_id=sid,
                    )
                )
            for i, row in enumerate(st.rows):
                if not any(str(v).strip() for v in row.fields.values()):
                    out.append(
                        _issue(
                            C.SURCHARGE_ROW_INCOMPLETE,
                            IssueSeverity.INFO,
                            f"Surcharge row {i+1} appears empty.",
                            entity_kind="surcharge_table",
                            entity_id=st.id,
                            section_id=sid,
                            field=f"row_{i+1}",
                        )
                    )

        for dt in sec.extracted_discount_tiers:
            disc = dt.discount or {}
            if disc.get("percent_normalized") is None and not disc.get("value"):
                out.append(
                    _issue(
                        C.DISCOUNT_TIER_MISSING_PERCENT,
                        IssueSeverity.WARNING,
                        "Discount tier has no normalized percent or numeric value.",
                        entity_kind="discount_tier",
                        entity_id=dt.id,
                        section_id=sid,
                    )
                )
            wr = (dt.scope or {}).get("weight_range_normalized") or {}
            if isinstance(wr, dict) and wr.get("min") is not None and wr.get("max") is not None:
                if float(wr["min"]) > float(wr["max"]):
                    out.append(
                        _issue(
                            C.DISCOUNT_WEIGHT_RANGE_INVALID,
                            IssueSeverity.ERROR,
                            "Weight range has min greater than max.",
                            entity_kind="discount_tier",
                            entity_id=dt.id,
                            section_id=sid,
                            field="weight_range_normalized",
                            details=wr,
                        )
                    )
            sk = (
                str(dt.scope.get("service_canonical", "")),
                str((disc.get("percent_normalized") or {}).get("value", "")),
                str((dt.scope.get("weight_range_normalized") or {}).get("raw", "")),
            )
            if sk[0] or sk[1] or sk[2]:
                if sk in tier_keys:
                    out.append(
                        _issue(
                            C.DISCOUNT_TIER_DUPLICATE_SCOPE,
                            IssueSeverity.INFO,
                            "Possible duplicate discount tier for same scope snapshot.",
                            entity_kind="discount_tier",
                            entity_id=dt.id,
                            section_id=sid,
                        )
                    )
                tier_keys.add(sk)

        for te in sec.extracted_service_terms:
            if len((te.text or "").strip()) < 40:
                out.append(
                    _issue(
                        C.SERVICE_TERM_SHORT_SNIPPET,
                        IssueSeverity.INFO,
                        "Service term snippet is very short; may be a partial extraction.",
                        entity_kind="service_term",
                        entity_id=te.id,
                        section_id=sid,
                    )
                )

    # Cross-check: absurd discount percents
    for sec in doc.sections:
        for dt in sec.extracted_discount_tiers:
            pn = (dt.discount or {}).get("percent_normalized") or {}
            if isinstance(pn, dict) and pn.get("value") is not None:
                v = float(pn["value"])
                if v < 0 or v > 100:
                    out.append(
                        _issue(
                            C.INCONSISTENT_PERCENT_RANGE,
                            IssueSeverity.ERROR,
                            f"Percent value {v} is outside 0–100.",
                            entity_kind="discount_tier",
                            entity_id=dt.id,
                            section_id=sec.id,
                            details={"value": v},
                        )
                    )

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
