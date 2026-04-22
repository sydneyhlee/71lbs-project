"""Earned-discount tier validation checks."""

from __future__ import annotations

from app.models.schema import AuditDiscrepancy, ContractExtraction, DiscrepancyType, InvoiceLineItem


def _tiers_from_contract(contract: ContractExtraction) -> list[dict]:
    ed = contract.earned_discounts or {}
    tiers = ed.get("tiers", [])
    return tiers if isinstance(tiers, list) else []


def audit_earned_discount(
    invoice_line: InvoiceLineItem,
    contract: ContractExtraction,
    rolling_revenue: float,
) -> AuditDiscrepancy | None:
    tiers = _tiers_from_contract(contract)
    if not tiers:
        return None

    correct_tier = None
    for tier in sorted(tiers, key=lambda t: t.get("threshold_min") or 0):
        lo = tier.get("threshold_min") or 0
        hi = tier.get("threshold_max")
        hi = float("inf") if hi is None else hi
        if lo <= rolling_revenue < hi:
            correct_tier = tier
            break
    if correct_tier is None:
        return None

    service = invoice_line.service_code or ""
    discounts = correct_tier.get("discounts", {})
    expected_discount_pct = float(discounts.get(service, 0.0) or 0.0)

    gross = invoice_line.transport_charge or invoice_line.published_charge or 0.0
    if gross == 0:
        return None

    applied_discount = invoice_line.earned_discount_applied or invoice_line.incentive_credit or 0.0
    applied_pct = abs(applied_discount) / gross * 100 if gross else 0.0
    delta_pct = expected_discount_pct - applied_pct
    if abs(delta_pct) < 0.1:
        return None

    expected_discount_amt = round(gross * expected_discount_pct / 100, 2)
    delta_dollars = round(expected_discount_amt - abs(applied_discount), 2)

    return AuditDiscrepancy(
        line_id=invoice_line.id,
        tracking_number=invoice_line.tracking_number,
        invoice_id=invoice_line.invoice_id,
        transaction_id=invoice_line.transaction_id,
        service_or_charge_type=invoice_line.service_or_charge_type,
        discrepancy_type=DiscrepancyType.MISSING_DISCOUNT if delta_dollars > 0 else DiscrepancyType.UNDERCHARGE,
        field="earned_discount",
        expected_value=expected_discount_amt,
        billed_value=abs(applied_discount),
        expected_amount=expected_discount_amt,
        billed_amount=abs(applied_discount),
        dollar_impact=delta_dollars,
        dollar_discrepancy=delta_dollars,
        explanation=(
            f"Rolling revenue ${rolling_revenue:,.0f} -> tier expects {expected_discount_pct:.1f}%, "
            f"applied {applied_pct:.1f}% (${abs(applied_discount):.2f} vs ${expected_discount_amt:.2f})"
        ),
        why_discrepancy="Applied earned discount does not match expected tier.",
        confidence=0.82,
        invoice_source_reference=invoice_line.raw_line_text,
    )

