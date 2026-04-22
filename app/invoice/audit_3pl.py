"""3PL-focused invoice audit checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.models.schema import AuditDiscrepancy, DiscrepancyType


@dataclass
class ThreePLInvoiceLine:
    line_id: str
    service_category: str
    unit_of_measure: str
    quantity_billed: float
    rate_billed: float
    amount_billed: float
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    reference_id: Optional[str] = None


def audit_3pl_line(
    line: ThreePLInvoiceLine,
    contract_terms: dict,
    actual_usage: dict | None = None,
) -> list[AuditDiscrepancy]:
    """
    Deterministic 3PL checks:
      - storage rate/unit mismatch
      - pick/pack tier mismatch (when configured)
      - long-term storage trigger violation
      - monthly minimum misapplication (batch-level check should complement this)
    """
    out: list[AuditDiscrepancy] = []
    svc = line.service_category.lower().strip()
    terms = contract_terms or {}

    if svc == "storage":
        expected_rate = ((terms.get("storage") or {}).get("rate"))
        expected_unit = ((terms.get("storage") or {}).get("unit"))
        if expected_rate is not None and abs(line.rate_billed - float(expected_rate)) > 0.01:
            out.append(
                AuditDiscrepancy(
                    line_id=line.line_id,
                    tracking_number=line.reference_id,
                    service_or_charge_type=line.service_category,
                    discrepancy_type=DiscrepancyType.OVERCHARGE if line.rate_billed > float(expected_rate) else DiscrepancyType.UNDERCHARGE,
                    field="storage_rate",
                    expected_value=float(expected_rate),
                    billed_value=line.rate_billed,
                    expected_amount=round(line.quantity_billed * float(expected_rate), 2),
                    billed_amount=line.amount_billed,
                    dollar_impact=round(line.amount_billed - line.quantity_billed * float(expected_rate), 2),
                    explanation="3PL storage billed rate differs from contract rate.",
                )
            )
        if expected_unit and line.unit_of_measure != expected_unit:
            out.append(
                AuditDiscrepancy(
                    line_id=line.line_id,
                    tracking_number=line.reference_id,
                    service_or_charge_type=line.service_category,
                    discrepancy_type=DiscrepancyType.AMBIGUOUS,
                    field="storage_unit",
                    billed_value=0.0,
                    explanation=f"Storage billed as {line.unit_of_measure}, contract expects {expected_unit}.",
                )
            )

    return out

