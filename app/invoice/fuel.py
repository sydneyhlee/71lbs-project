"""Fuel surcharge discrepancy checks."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.models.schema import AuditDiscrepancy, ContractExtraction, DiscrepancyType, InvoiceLineItem

FUEL_TABLE_PATH = Path("data/reference/fuel_surcharges/weekly_rates.json")


@lru_cache(maxsize=1)
def _load_fuel_table() -> dict:
    if not FUEL_TABLE_PATH.exists():
        return {}
    return json.loads(FUEL_TABLE_PATH.read_text(encoding="utf-8"))


def _carrier_slug(contract: ContractExtraction) -> str:
    raw = contract.metadata.carrier.effective() if hasattr(contract, "metadata") else None
    return str(raw or "").strip().lower()


def get_weekly_rate(ship_date: date, carrier: str, service_class: str) -> float | None:
    table = _load_fuel_table()
    service_table = table.get(carrier, {}).get(service_class, {})
    if not service_table:
        return None
    dates = sorted(service_table.keys(), reverse=True)
    ship_str = str(ship_date)
    for d in dates:
        if d <= ship_str:
            return float(service_table[d])
    return None


def _contract_fuel_terms(contract: ContractExtraction) -> tuple[float, date | None]:
    terms = contract.fuel_surcharge or {}
    discount = float(terms.get("discount_pct") or 0.0)
    exp = terms.get("expiration_date")
    if isinstance(exp, str):
        try:
            return discount, date.fromisoformat(exp)
        except ValueError:
            return discount, None
    return discount, None


def audit_fuel(invoice_line: InvoiceLineItem, contract: ContractExtraction) -> AuditDiscrepancy | None:
    if invoice_line.fuel_surcharge_billed is None:
        return None
    if invoice_line.ship_date is None:
        return None

    # Skip if no contract fuel terms — can't validate without discount data
    fuel_terms = contract.fuel_surcharge or {}
    if not fuel_terms or fuel_terms.get("discount_pct") is None:
        return None

    carrier = _carrier_slug(contract)
    if carrier not in {"fedex", "ups"}:
        return None

    service_class = "ground" if invoice_line.service_group in ("ground", "home_delivery", "ground_saver") else "express"
    if carrier == "ups" and service_class == "express":
        service_class = "air"

    published_rate_pct = get_weekly_rate(invoice_line.ship_date, carrier, service_class)
    if published_rate_pct is None:
        return None

    discount_pct, expiration_date = _contract_fuel_terms(contract)
    if expiration_date and invoice_line.ship_date > expiration_date:
        discount_pct = 0.0
    effective_rate = published_rate_pct * (1 - discount_pct / 100.0)

    if carrier == "fedex":
        base = invoice_line.net_transport_charge or 0.0
    else:
        base = invoice_line.published_charge or 0.0

    expected_fuel = round(base * effective_rate / 100.0, 2)
    delta = round(invoice_line.fuel_surcharge_billed - expected_fuel, 2)
    # Only flag overcharges — if billed < expected the customer got a better deal, no action needed.
    if delta <= 0.02:
        return None

    return AuditDiscrepancy(
        line_id=invoice_line.id,
        tracking_number=invoice_line.tracking_number,
        invoice_id=invoice_line.invoice_id,
        transaction_id=invoice_line.transaction_id,
        service_or_charge_type=invoice_line.service_or_charge_type,
        discrepancy_type=DiscrepancyType.OVERCHARGE if delta > 0 else DiscrepancyType.UNDERCHARGE,
        field="fuel_surcharge",
        expected_value=expected_fuel,
        billed_value=invoice_line.fuel_surcharge_billed,
        expected_amount=expected_fuel,
        billed_amount=invoice_line.fuel_surcharge_billed,
        dollar_impact=delta,
        dollar_discrepancy=delta,
        explanation=(
            f"Published rate {published_rate_pct}% - {discount_pct}% contracted discount = "
            f"{effective_rate:.3f}% effective. Base: ${base:.2f}. "
            f"Expected: ${expected_fuel:.2f}, Billed: ${invoice_line.fuel_surcharge_billed:.2f}"
        ),
        why_discrepancy="Fuel surcharge does not match weekly table and contracted discount.",
        confidence=0.86,
        invoice_source_reference=invoice_line.raw_line_text,
    )

