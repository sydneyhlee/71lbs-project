from __future__ import annotations

from statistics import mean
from typing import Iterable

from contract_parser.models import ContractDocument

from .models import ConfidenceBreakdown, Issue, IssueSeverity


def _entity_scores(doc: ContractDocument) -> list[float]:
    scores: list[float] = []
    for sec in doc.sections:
        for r in sec.extracted_pricing_rules:
            scores.append(r.confidence)
        for t in sec.extracted_surcharge_tables:
            scores.append(t.confidence)
        for d in sec.extracted_discount_tiers:
            scores.append(d.confidence)
        for te in sec.extracted_service_terms:
            scores.append(te.confidence)
    return scores


def _extraction_confidence(doc: ContractDocument) -> float:
    """Heuristic: average confidence of extracted entities, or neutral if none."""
    s = _entity_scores(doc)
    if not s:
        return 0.4
    return round(mean(s), 4)


def _normalization_confidence(doc: ContractDocument) -> float:
    """How often normalization produced usable structured fields."""
    num = 0
    denom = 0
    for sec in doc.sections:
        for r in sec.extracted_pricing_rules:
            denom += 1
            ex = r.expression or {}
            if (ex.get("percent_normalized") or {}).get("value") is not None:
                num += 1
            elif (r.scope or {}).get("service_canonical"):
                num += 0.5
        for t in sec.extracted_surcharge_tables:
            denom += 1
            if t.surcharge_type:
                num += 1
            elif t.rows:
                num += 0.4
        for d in sec.extracted_discount_tiers:
            denom += 1
            disc = d.discount or {}
            if disc.get("percent_normalized") is not None or disc.get("value") is not None:
                num += 1
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


def compute_confidence(document: ContractDocument, issues: list[Issue]) -> ConfidenceBreakdown:
    ext = _extraction_confidence(document)
    norm = _normalization_confidence(document)
    penalty = _penalty_from_issues(issues)
    aggregate = max(0.0, min(1.0, 0.45 * ext + 0.35 * norm + 0.2 * (1.0 - penalty)))
    return ConfidenceBreakdown(
        extraction=ext,
        normalization=norm,
        validation_penalty=round(penalty, 4),
        aggregate=round(aggregate, 4),
    )
