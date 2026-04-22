"""DIM weight discrepancy checks."""

from __future__ import annotations

import math

from app.models.schema import AuditDiscrepancy, ContractExtraction, DiscrepancyType, InvoiceLineItem


def calculate_dim_weight(length: float, width: float, height: float, divisor: int) -> int:
    return math.ceil(math.ceil(length) * math.ceil(width) * math.ceil(height) / divisor)


def rated_weight(actual_lbs: float, dim_lbs: int) -> float:
    return max(actual_lbs, float(dim_lbs))


def _carrier_slug(contract: ContractExtraction) -> str:
    raw = contract.metadata.carrier.effective() if hasattr(contract, "metadata") else None
    return str(raw or "").strip().lower()


def _contract_dim_divisor(contract: ContractExtraction) -> int:
    # Prefer negotiated DIM rules when present, otherwise negotiated-account default.
    for dr in contract.dim_rules:
        val = dr.dim_divisor.effective()
        if isinstance(val, (int, float)) and val > 0:
            return int(val)
    return 139


def audit_dim(invoice_line: InvoiceLineItem, contract: ContractExtraction) -> AuditDiscrepancy | None:
    if not all([
        invoice_line.length is not None,
        invoice_line.width is not None,
        invoice_line.height is not None,
        invoice_line.actual_weight_lbs is not None,
    ]):
        return None

    divisor = _contract_dim_divisor(contract)
    expected_dim = calculate_dim_weight(
        invoice_line.length,
        invoice_line.width,
        invoice_line.height,
        divisor,
    )
    expected_rated = rated_weight(invoice_line.actual_weight_lbs, expected_dim)

    # FedEx-only 40-lb minimum when longest side > 48"
    if _carrier_slug(contract) == "fedex":
        longest = max(
            math.ceil(invoice_line.length),
            math.ceil(invoice_line.width),
            math.ceil(invoice_line.height),
        )
        if longest > 48:
            expected_rated = max(expected_rated, 40.0)

    billed_rated = (
        invoice_line.rated_weight_lbs
        if invoice_line.rated_weight_lbs is not None
        else invoice_line.actual_weight_lbs
    )
    if billed_rated is None:
        return None

    if abs(billed_rated - expected_rated) < 0.5:
        return None

    delta_lbs = billed_rated - expected_rated
    rate = invoice_line.rate_per_lb or 0.0
    return AuditDiscrepancy(
        line_id=invoice_line.id,
        tracking_number=invoice_line.tracking_number,
        invoice_id=invoice_line.invoice_id,
        transaction_id=invoice_line.transaction_id,
        service_or_charge_type=invoice_line.service_or_charge_type,
        discrepancy_type=DiscrepancyType.OVERCHARGE if delta_lbs > 0 else DiscrepancyType.UNDERCHARGE,
        field="rated_weight_lbs",
        expected_value=expected_rated,
        billed_value=billed_rated,
        expected_amount=expected_rated,
        billed_amount=billed_rated,
        dollar_impact=round(delta_lbs * rate, 2),
        dollar_discrepancy=round(delta_lbs * rate, 2),
        explanation=(
            f"DIM divisor {divisor}: ceil({invoice_line.length})×ceil({invoice_line.width})×"
            f"ceil({invoice_line.height})/{divisor} = {expected_dim} lb DIM, "
            f"rated {expected_rated} lb, billed {billed_rated} lb"
        ),
        why_discrepancy="Rated weight differs from contract-based DIM expectation.",
        confidence=0.9,
        invoice_source_reference=invoice_line.raw_line_text,
    )

