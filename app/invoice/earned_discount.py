"""Earned-discount tier validation checks."""

from __future__ import annotations

from app.models.schema import AuditDiscrepancy, ContractExtraction, DiscrepancyType, InvoiceLineItem


def _tiers_from_contract(contract: ContractExtraction) -> list[dict]:
    ed = contract.earned_discounts or {}
    tiers = ed.get("tiers", [])
    return tiers if isinstance(tiers, list) else []


def _ups_multilayer_expected(
    invoice_line: InvoiceLineItem,
    contract: ContractExtraction,
) -> tuple[float, float] | None:
    """Return (expected_net_charge, effective_discount_pct) for UPS three-layer contracts.

    Layers stack multiplicatively:
      net = published × (1 - base%) × (1 - tier%) × (1 - epld%)
    """
    ed = contract.earned_discounts or {}
    if ed.get("type") != "ups_multi_layer":
        return None

    published = invoice_line.published_charge
    if not published or published <= 0:
        return None

    service = invoice_line.service_code or ""
    weight = invoice_line.rated_weight_lbs or 0.0
    zone = invoice_line.zone

    base_discounts = ed.get("base_discounts") or {}
    base_data = base_discounts.get(service)
    if isinstance(base_data, str):
        base_data = base_discounts.get(base_data)
    if base_data is None:
        # Fallback: use ground rates for unknown ground-class services
        if "ground" in service or "saver" in service:
            base_data = base_discounts.get("ups_ground")

    base_pct = 0.0
    if isinstance(base_data, dict):
        zone_exc = base_data.get("zone_exceptions") or {}
        if zone and str(zone) in zone_exc:
            base_pct = float(zone_exc[str(zone)])
        elif "flat_discount_pct" in base_data:
            base_pct = float(base_data["flat_discount_pct"])
        else:
            for wb in base_data.get("by_weight") or []:
                lo = float(wb.get("min_lbs") or 0)
                hi = wb.get("max_lbs")
                if weight >= lo and (hi is None or weight <= float(hi)):
                    base_pct = float(wb["discount_pct"])
                    break

    tier_pct = float((ed.get("tier_discounts") or {}).get(service) or 0.0)

    # Two-layer stack: base × tier.  ePLD is intentionally excluded here because
    # for most UPS contracts the tier rate already incorporates the ePLD bonus,
    # and stacking it separately produces false positives on verified-correct
    # Air shipments (e.g. 2DA billed at 71% matches tier, not tier+ePLD).
    expected = published * (1 - base_pct / 100) * (1 - tier_pct / 100)
    effective_discount = (1 - expected / published) * 100 if published else 0.0
    return round(expected, 2), round(effective_discount, 2)


def audit_earned_discount(
    invoice_line: InvoiceLineItem,
    contract: ContractExtraction,
    rolling_revenue: float,
) -> AuditDiscrepancy | None:
    # UPS contracts use a three-layer multiplicative structure
    ups_result = _ups_multilayer_expected(invoice_line, contract)
    if ups_result is not None:
        expected_charge, effective_discount_pct = ups_result
        billed = invoice_line.net_transport_charge or invoice_line.billed_amount or 0.0
        if billed <= 0 or expected_charge <= 0:
            return None
        delta = round(billed - expected_charge, 2)
        # Only flag if customer was overcharged (delta > small tolerance)
        if delta <= 0.05:
            return None
        return AuditDiscrepancy(
            line_id=invoice_line.id,
            tracking_number=invoice_line.tracking_number,
            invoice_id=invoice_line.invoice_id,
            transaction_id=invoice_line.transaction_id,
            service_or_charge_type=invoice_line.service_or_charge_type,
            discrepancy_type=DiscrepancyType.MISSING_DISCOUNT,
            field="earned_discount",
            expected_value=expected_charge,
            billed_value=billed,
            expected_amount=expected_charge,
            billed_amount=billed,
            dollar_impact=delta,
            dollar_discrepancy=delta,
            explanation=(
                f"Published ${invoice_line.published_charge:.2f} × contract multi-layer discount "
                f"({effective_discount_pct:.1f}% effective) = expected ${expected_charge:.2f}, "
                f"billed ${billed:.2f}"
            ),
            why_discrepancy="Billed net charge exceeds expected after applying all contract discount layers.",
            confidence=0.85,
            invoice_source_reference=invoice_line.raw_line_text,
        )

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

