from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from contract_parser.types import Contract, EarnedDiscount, Metadata, PricingRule, Service, Surcharge, Tier


SERVICE_MAP = {
    "fedex 2day": "FedEx 2Day",
    "fedex ground": "FedEx Ground",
    "ups ground": "UPS Ground",
    "ups next day air": "UPS Next Day Air",
}
SPEND_RANGE_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)\s*[-to]+\s*\$?\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)
PERCENT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")


def _canonical_service_name(name: str) -> str:
    key = name.strip().lower()
    for k, v in SERVICE_MAP.items():
        if k in key:
            return v
    return name.strip() or "Unknown Service"


def _service_type(name: str) -> str:
    n = name.lower()
    if "international" in n:
        return "international"
    if "freight" in n:
        return "freight"
    if "express" in n or "2day" in n or "next day" in n or "air" in n:
        return "express"
    return "ground"


def _merge_services(rows: list[dict[str, Any]]) -> list[Service]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_canonical_service_name(row["service"])].append(row)
    services: list[Service] = []
    for name, rules in grouped.items():
        pricing = [
            PricingRule(
                zones=r["zones"],
                weight_range=r["weight_range"],
                discount=r["discount"],
                net_rate=r["net_rate"],
            )
            for r in rules
        ]
        services.append(Service(service_name=name, service_type=_service_type(name), pricing=pricing))
    return services


def _parse_earned_discounts(sections: list[dict[str, Any]], llm_fragments: list[dict[str, Any]]) -> list[EarnedDiscount]:
    earned: list[EarnedDiscount] = []
    for s in sections:
        if s.get("section_type") != "earned_discount":
            continue
        text = s.get("text_blob", "")
        tiers: list[Tier] = []
        for m in SPEND_RANGE_RE.finditer(text):
            tail = text[m.end() : m.end() + 40]
            p = PERCENT_RE.search(tail)
            if p:
                lo = float(m.group(1).replace(",", ""))
                hi = float(m.group(2).replace(",", ""))
                tiers.append(Tier(spend_range=(lo, hi), discount=float(p.group(1))))
        if tiers:
            earned.append(EarnedDiscount(services=[_canonical_service_name(s.get("service_name", ""))], tiers=tiers))
    for frag in llm_fragments:
        for item in frag.get("earned_discounts", []):
            try:
                earned.append(EarnedDiscount(**item))
            except Exception:
                pass
    return earned


def _parse_surcharges(sections: list[dict[str, Any]], llm_fragments: list[dict[str, Any]]) -> list[Surcharge]:
    surcharges: list[Surcharge] = []
    for s in sections:
        if s.get("section_type") != "surcharge":
            continue
        text = s.get("text_blob", "")
        for seg in text.split("  "):
            if "surcharge" not in seg.lower() and "fuel" not in seg.lower():
                continue
            p = PERCENT_RE.search(seg)
            surcharges.append(Surcharge(type=seg.strip()[:80], discount=float(p.group(1)) if p else None))
    for frag in llm_fragments:
        for item in frag.get("surcharges", []):
            try:
                surcharges.append(Surcharge(**item))
            except Exception:
                pass
    return surcharges


def build_contract(
    metadata: dict[str, Any],
    sections: list[dict[str, Any]],
    table_rows: list[dict[str, Any]],
    llm_fragments: list[dict[str, Any]],
) -> Contract:
    services = _merge_services(table_rows)
    earned_discounts = _parse_earned_discounts(sections, llm_fragments)
    surcharges = _parse_surcharges(sections, llm_fragments)
    return Contract(
        metadata=Metadata(**metadata),
        services=services,
        earned_discounts=earned_discounts,
        surcharges=surcharges,
    )
