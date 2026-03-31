from __future__ import annotations

import re
from typing import Iterable

from contract_parser.models import (
    DiscountTier,
    ExtractedTable,
    Footnote,
    PricingRule,
    PricingRuleType,
    ServiceLevelTerm,
    Span,
    SurchargeRow,
    SurchargeTable,
    VendorType,
)
from contract_parser.normalize.parsers import (
    derive_structured_from_section as _base_derive,
    extract_footnotes,
    table_to_extracted,
)

from .normalization import normalize_percent, normalize_service_name, normalize_weight_range

__all__ = [
    "derive_refined_from_section",
    "extract_footnotes",
    "table_to_extracted",
]


def _enrich_pricing_rule(rule: PricingRule, vendor: VendorType) -> PricingRule:
    text = rule.text or ""
    expr = dict(rule.expression)
    scope = dict(rule.scope)

    pct = normalize_percent(text)
    if pct.get("value") is not None:
        expr["percent_normalized"] = pct

    svc_m = re.search(
        r"(?i)\b(UPS|FedEx|Fed Ex|Ground|Express|Next Day|2nd Day|3 Day|SurePost|Freight)\b[^.\n]{0,80}",
        text,
    )
    if svc_m:
        canon, conf = normalize_service_name(svc_m.group(0), vendor)
        if canon:
            scope["service_canonical"] = canon
            scope["service_resolution_confidence"] = conf

    wr_m = re.search(r"(?i)\d+(?:\.\d+)?\s*(?:-|–|—|to)\s*\d+(?:\.\d+)?\s*(?:lb|lbs|kg)s?\b", text)
    if wr_m:
        wr = normalize_weight_range(wr_m.group(0))
        if wr.get("min") is not None:
            expr["weight_range_normalized"] = wr

    # Confidence: bump if we normalized something useful
    conf = rule.confidence
    pn = expr.get("percent_normalized") or {}
    if isinstance(pn, dict) and (pn.get("confidence") or 0) > 0.7:
        conf = min(1.0, conf + 0.1)
    if scope.get("service_canonical"):
        conf = min(1.0, conf + 0.05 * (scope.get("service_resolution_confidence") or 0))

    return rule.model_copy(update={"expression": expr, "scope": scope, "confidence": round(min(1.0, conf), 4)})


def _enrich_surcharge_table(table: SurchargeTable, vendor: VendorType) -> SurchargeTable:
    rows = []
    for r in table.rows:
        fields = dict(r.fields)
        for hk, val in list(fields.items()):
            if val and isinstance(val, str):
                if "%" in val or re.search(r"(?i)percent|pct", hk):
                    fields[f"{hk}__normalized_percent"] = normalize_percent(val)
        rows.append(SurchargeRow(fields=fields))
    # Infer surcharge_type from first row keys
    stype = table.surcharge_type
    if not stype and table.rows:
        blob = " ".join(str(v) for v in table.rows[0].fields.values()).lower()
        for kw in ("fuel", "residential", "delivery area", "das", "peak", "additional handling"):
            if kw in blob:
                stype = kw.replace(" ", "_")
                break
    conf = min(1.0, table.confidence + (0.05 if stype else 0))
    return table.model_copy(update={"rows": rows, "surcharge_type": stype, "confidence": round(conf, 4)})


def _enrich_discount_tier(tier: DiscountTier, vendor: VendorType) -> DiscountTier:
    scope = dict(tier.scope)
    disc = dict(tier.discount)
    raw_row = disc.get("raw_row")
    if isinstance(raw_row, str):
        pct = normalize_percent(raw_row)
        if pct.get("value") is not None:
            disc["percent_normalized"] = pct
            disc["type"] = "percent"
            disc["value"] = pct.get("value")
        wr = normalize_weight_range(raw_row)
        if wr.get("min") is not None and wr.get("confidence", 0) > 0.5:
            scope["weight_range_normalized"] = wr
        svc_guess = re.findall(r"(?i)(fedex|ups)\s+[a-z\s]+", raw_row)
        if svc_guess:
            c, cf = normalize_service_name(svc_guess[0], vendor)
            if c:
                scope["service_canonical"] = c
                scope["service_resolution_confidence"] = cf
    conf = min(1.0, tier.confidence + (0.1 if disc.get("percent_normalized") else 0))
    return tier.model_copy(update={"scope": scope, "discount": disc, "confidence": round(conf, 4)})


def _enrich_service_term(term: ServiceLevelTerm) -> ServiceLevelTerm:
    # Slight bump if text is substantial
    conf = term.confidence
    if len(term.text) > 120:
        conf = min(1.0, conf + 0.05)
    return term.model_copy(update={"confidence": round(conf, 4)})


def derive_refined_from_section(
    *,
    section_id: str,
    section_text: str,
    section_spans: list[Span],
    tables: Iterable[ExtractedTable],
    vendor: VendorType,
) -> tuple[list[PricingRule], list[SurchargeTable], list[DiscountTier], list[ServiceLevelTerm]]:
    pr, st, dt, terms = _base_derive(
        section_id=section_id,
        section_text=section_text,
        section_spans=section_spans,
        tables=tables,
    )
    pr = [_enrich_pricing_rule(r, vendor) for r in pr]
    st = [_enrich_surcharge_table(t, vendor) for t in st]
    dt = [_enrich_discount_tier(t, vendor) for t in dt]
    terms = [_enrich_service_term(t) for t in terms]
    return pr, st, dt, terms
