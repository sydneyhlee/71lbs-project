from __future__ import annotations

import re
from typing import Any, Iterable

from ..models import (
    DiscountTier,
    ExtractedTable,
    Footnote,
    PricingRule,
    PricingRuleType,
    ServiceLevelTerm,
    Span,
    SurchargeRow,
    SurchargeTable,
)


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (h or "").strip().lower()).strip()


def _looks_like_surcharge_table(headers: list[str], text: str) -> bool:
    hs = " ".join(_norm_header(h) for h in headers)
    t = text.lower()
    return any(k in hs for k in ("surcharge", "fuel", "fee", "charge")) or "surcharge" in t or "fuel" in t


def _looks_like_discount_table(headers: list[str], text: str) -> bool:
    hs = " ".join(_norm_header(h) for h in headers)
    t = text.lower()
    return any(k in hs for k in ("discount", "incentive", "rebate", "tier")) or "discount" in t or "incentive" in t


def _looks_like_service_terms(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ("service level", "sla", "claims", "liability", "guarantee", "billing", "payment terms"))


def table_to_extracted(table: dict[str, Any]) -> ExtractedTable:
    rows = table.get("rows", []) or []
    headers: list[str] = []
    body = rows
    if rows and any(c for c in rows[0]):
        headers = [c.strip() for c in rows[0]]
        body = rows[1:]
    return ExtractedTable(
        id=table["id"],
        span=Span(page=int(table["page"]), bbox=None),
        headers=headers,
        rows=body,
        raw={"flavor": table.get("flavor"), **(table.get("raw") or {})},
    )


def extract_footnotes(raw_text: str, spans: list[Span]) -> list[Footnote]:
    # Simple pattern: lines starting with *, †, or numeric footnote markers.
    notes: list[Footnote] = []
    lines = [ln.rstrip() for ln in raw_text.splitlines()]
    buf: list[str] = []
    current_id: str | None = None
    for ln in lines:
        m = re.match(r"^\s*(\*+|†+|\d{1,2}[\)\.]|\([0-9]{1,2}\))\s+(.*)$", ln)
        if m:
            if current_id and buf:
                notes.append(Footnote(id=current_id, span=spans[-1] if spans else Span(page=1, bbox=None), text="\n".join(buf).strip()))
            marker = m.group(1)
            current_id = f"fn_{re.sub(r'[^0-9a-z]+','', marker.lower()) or 'x'}_{len(notes)+1:03d}"
            buf = [m.group(2)]
        elif current_id:
            if ln.strip():
                buf.append(ln.strip())
            else:
                notes.append(Footnote(id=current_id, span=spans[-1] if spans else Span(page=1, bbox=None), text="\n".join(buf).strip()))
                current_id = None
                buf = []
    if current_id and buf:
        notes.append(Footnote(id=current_id, span=spans[-1] if spans else Span(page=1, bbox=None), text="\n".join(buf).strip()))
    return notes


def derive_structured_from_section(
    *,
    section_id: str,
    section_text: str,
    section_spans: list[Span],
    tables: Iterable[ExtractedTable],
) -> tuple[list[PricingRule], list[SurchargeTable], list[DiscountTier], list[ServiceLevelTerm]]:
    pricing_rules: list[PricingRule] = []
    surcharge_tables: list[SurchargeTable] = []
    discount_tiers: list[DiscountTier] = []
    service_terms: list[ServiceLevelTerm] = []

    # Pricing-rule-ish clauses from text (baseline heuristics).
    for mi, m in enumerate(re.finditer(r"(?i)\b(fuel surcharge|residential surcharge|delivery area surcharge|das|peak surcharge|additional handling|dimensional weight|min(?:imum)? charge)\b.*", section_text)):
        clause = m.group(0).strip()
        rule_type = PricingRuleType.SURCHARGE if "surcharge" in clause.lower() or "das" in clause.lower() else PricingRuleType.GENERAL
        pricing_rules.append(
            PricingRule(
                id=f"{section_id}_rule_{mi+1:03d}",
                type=rule_type,
                title=None,
                text=clause,
                span=section_spans[0] if section_spans else None,
                confidence=0.55,
                sources=[],
            )
        )

    # Tables -> surcharge / discount structures.
    for t in tables:
        combined_text = " ".join([*t.headers, " ".join(" ".join(r) for r in t.rows[:5])]).strip()
        if _looks_like_surcharge_table(t.headers, combined_text):
            rows: list[SurchargeRow] = []
            # Map row cells to header keys when possible.
            for r in t.rows:
                fields: dict[str, Any] = {}
                for ci, cell in enumerate(r):
                    key = (t.headers[ci] if ci < len(t.headers) else f"col_{ci+1}").strip() or f"col_{ci+1}"
                    fields[key] = cell
                if any(v for v in fields.values()):
                    rows.append(SurchargeRow(fields=fields))
            surcharge_tables.append(
                SurchargeTable(
                    id=f"{section_id}_surch_{t.id}",
                    name=None,
                    surcharge_type=None,
                    rows=rows,
                    span=t.span,
                    source_table_id=t.id,
                    confidence=0.6,
                )
            )
            continue

        if _looks_like_discount_table(t.headers, combined_text):
            # Very baseline: emit tiers per row.
            for ri, r in enumerate(t.rows):
                row_text = " | ".join(c for c in r if c).strip()
                if not row_text:
                    continue
                discount_tiers.append(
                    DiscountTier(
                        id=f"{section_id}_disc_{t.id}_{ri+1:03d}",
                        scope={"table": t.id},
                        discount={"raw_row": row_text},
                        span=t.span,
                        sources=[t.id],
                        confidence=0.55,
                    )
                )

    # Service-level terms from text
    if _looks_like_service_terms(section_text):
        for ti, m in enumerate(
            re.finditer(
                r"(?is)\b(service level agreement|sla|claims?|liability|guarantee|billing|payment terms?)\b.{0,400}",
                section_text,
            )
        ):
            snippet = re.sub(r"\s+", " ", m.group(0)).strip()
            service_terms.append(
                ServiceLevelTerm(
                    id=f"{section_id}_term_{ti+1:03d}",
                    term_type=m.group(1).lower(),
                    text=snippet,
                    span=section_spans[0] if section_spans else None,
                    confidence=0.55,
                )
            )

    return pricing_rules, surcharge_tables, discount_tiers, service_terms

