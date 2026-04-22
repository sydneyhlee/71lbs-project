"""Accessorial discrepancy checks (DAS/residential/address correction/duplicates)."""

from __future__ import annotations

import csv
import math
from functools import lru_cache
from pathlib import Path

from app.models.schema import AuditDiscrepancy, ContractExtraction, DiscrepancyType, InvoiceLineItem

DAS_ZIP_DIR = Path("data/reference/das_zips")


def _carrier_slug(contract: ContractExtraction) -> str:
    raw = contract.metadata.carrier.effective() if hasattr(contract, "metadata") else None
    return str(raw or "").strip().lower()


@lru_cache(maxsize=4)
def _load_das_zips(carrier: str) -> dict[str, str]:
    path = DAS_ZIP_DIR / f"{carrier}_das_zips.csv"
    if not path.exists():
        return {}
    result = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[row["zip"].strip().zfill(5)] = row["tier"].strip()
    return result


def audit_das(invoice_line: InvoiceLineItem, contract: ContractExtraction) -> list[AuditDiscrepancy]:
    results: list[AuditDiscrepancy] = []
    carrier = _carrier_slug(contract)
    das_map = _load_das_zips(carrier)
    dest_zip = (invoice_line.destination_zip or "")[:5].zfill(5)
    actual_tier = das_map.get(dest_zip)
    das_billed = invoice_line.das_billed or 0.0

    if das_billed > 0 and actual_tier is None:
        results.append(
            AuditDiscrepancy(
                line_id=invoice_line.id,
                tracking_number=invoice_line.tracking_number,
                invoice_id=invoice_line.invoice_id,
                transaction_id=invoice_line.transaction_id,
                service_or_charge_type=invoice_line.service_or_charge_type,
                discrepancy_type=DiscrepancyType.UNSUPPORTED_FEE,
                field="das_surcharge",
                expected_value=0.0,
                billed_value=das_billed,
                expected_amount=0.0,
                billed_amount=das_billed,
                dollar_impact=das_billed,
                dollar_discrepancy=das_billed,
                explanation=f"ZIP {dest_zip} is not on {carrier.upper()} DAS list but DAS was charged",
                why_discrepancy="DAS billed on ZIP not present in carrier DAS mapping.",
                confidence=0.85,
                invoice_source_reference=invoice_line.raw_line_text,
            )
        )
    return results


def audit_residential(invoice_line: InvoiceLineItem, contract: ContractExtraction) -> AuditDiscrepancy | None:
    res_billed = invoice_line.residential_surcharge_billed or 0.0
    if res_billed <= 0:
        return None
    if invoice_line.is_residential is False:
        return AuditDiscrepancy(
            line_id=invoice_line.id,
            tracking_number=invoice_line.tracking_number,
            invoice_id=invoice_line.invoice_id,
            transaction_id=invoice_line.transaction_id,
            service_or_charge_type=invoice_line.service_or_charge_type,
            discrepancy_type=DiscrepancyType.UNSUPPORTED_FEE,
            field="residential_surcharge",
            expected_value=0.0,
            billed_value=res_billed,
            expected_amount=0.0,
            billed_amount=res_billed,
            dollar_impact=res_billed,
            dollar_discrepancy=res_billed,
            explanation="Residential surcharge applied to commercial address",
            why_discrepancy="Residential fee should not apply to commercial address.",
            confidence=0.8,
            invoice_source_reference=invoice_line.raw_line_text,
        )
    if res_billed > 0 and contract.accessorials:
        acc = (contract.accessorials or {}).get("residential_delivery", {})
        flat_override = acc.get("flat_fee_override")
        if flat_override is not None and abs(res_billed - float(flat_override)) > 0.02:
            delta = round(res_billed - float(flat_override), 2)
            return AuditDiscrepancy(
                line_id=invoice_line.id,
                tracking_number=invoice_line.tracking_number,
                invoice_id=invoice_line.invoice_id,
                transaction_id=invoice_line.transaction_id,
                service_or_charge_type=invoice_line.service_or_charge_type,
                discrepancy_type=DiscrepancyType.OVERCHARGE if delta > 0 else DiscrepancyType.UNDERCHARGE,
                field="residential_surcharge",
                expected_value=float(flat_override),
                billed_value=res_billed,
                expected_amount=float(flat_override),
                billed_amount=res_billed,
                dollar_impact=delta,
                dollar_discrepancy=delta,
                explanation=f"Contract specifies flat residential fee of ${float(flat_override):.2f}, billed ${res_billed:.2f}",
                why_discrepancy="Residential surcharge does not match flat override.",
                confidence=0.83,
                invoice_source_reference=invoice_line.raw_line_text,
            )
    return None


def audit_address_correction(invoice_line: InvoiceLineItem, contract: ContractExtraction) -> AuditDiscrepancy | None:
    ac_billed = invoice_line.address_correction_billed or 0.0
    if ac_billed <= 0:
        return None
    if contract.accessorials:
        acc = (contract.accessorials or {}).get("address_correction", {})
        flat_override = acc.get("flat_fee_override")
        if flat_override is not None and abs(ac_billed - float(flat_override)) > 0.02:
            delta = round(ac_billed - float(flat_override), 2)
            return AuditDiscrepancy(
                line_id=invoice_line.id,
                tracking_number=invoice_line.tracking_number,
                invoice_id=invoice_line.invoice_id,
                transaction_id=invoice_line.transaction_id,
                service_or_charge_type=invoice_line.service_or_charge_type,
                discrepancy_type=DiscrepancyType.OVERCHARGE if delta > 0 else DiscrepancyType.UNDERCHARGE,
                field="address_correction",
                expected_value=float(flat_override),
                billed_value=ac_billed,
                expected_amount=float(flat_override),
                billed_amount=ac_billed,
                dollar_impact=delta,
                dollar_discrepancy=delta,
                explanation=f"Contract address correction fee: ${float(flat_override):.2f}, billed: ${ac_billed:.2f}",
                why_discrepancy="Address correction fee does not match contract override.",
                confidence=0.83,
                invoice_source_reference=invoice_line.raw_line_text,
            )
    return None


def audit_ahs(invoice_line: InvoiceLineItem, contract: ContractExtraction) -> AuditDiscrepancy | None:
    ahs_billed = invoice_line.ahs_billed or 0.0
    if ahs_billed <= 0:
        return None
    if not all([invoice_line.length, invoice_line.width, invoice_line.height]):
        return None
    dims = sorted(
        [
            math.ceil(invoice_line.length),
            math.ceil(invoice_line.width),
            math.ceil(invoice_line.height),
        ],
        reverse=True,
    )
    longest, second, shortest = dims
    girth = 2 * (second + shortest)
    actual = invoice_line.actual_weight_lbs or 0
    carrier = _carrier_slug(contract)
    if carrier == "fedex":
        meets_criteria = longest > 48 or second > 30 or actual > 70
    else:
        meets_criteria = longest > 48 or actual > 70 or (longest + girth) > 105
    if meets_criteria:
        return None
    return AuditDiscrepancy(
        line_id=invoice_line.id,
        tracking_number=invoice_line.tracking_number,
        invoice_id=invoice_line.invoice_id,
        transaction_id=invoice_line.transaction_id,
        service_or_charge_type=invoice_line.service_or_charge_type,
        discrepancy_type=DiscrepancyType.UNSUPPORTED_FEE,
        field="ahs_surcharge",
        expected_value=0.0,
        billed_value=ahs_billed,
        expected_amount=0.0,
        billed_amount=ahs_billed,
        dollar_impact=ahs_billed,
        dollar_discrepancy=ahs_billed,
        explanation=(
            f"AHS charged but package dims {invoice_line.length}x{invoice_line.width}x{invoice_line.height} "
            f"and weight {actual} lbs do not meet {carrier.upper()} AHS criteria"
        ),
        why_discrepancy="AHS fee appears unsupported by package dimensions/weight.",
        confidence=0.83,
        invoice_source_reference=invoice_line.raw_line_text,
    )


def audit_large_package(invoice_line: InvoiceLineItem, contract: ContractExtraction) -> AuditDiscrepancy | None:
    lp_billed = invoice_line.large_package_billed or 0.0
    if lp_billed <= 0:
        return None
    if not all([invoice_line.length, invoice_line.width, invoice_line.height]):
        return None
    L = math.ceil(invoice_line.length)
    W = math.ceil(invoice_line.width)
    H = math.ceil(invoice_line.height)
    longest = max(L, W, H)
    second = sorted([L, W, H], reverse=True)[1]
    third = min(L, W, H)
    girth = 2 * (second + third)
    carrier = _carrier_slug(contract)
    if carrier == "fedex":
        meets_criteria = (longest + girth) > 165 or longest > 96
    else:
        meets_criteria = longest > 108 or (longest + girth) > 165
    if meets_criteria:
        return None
    return AuditDiscrepancy(
        line_id=invoice_line.id,
        tracking_number=invoice_line.tracking_number,
        invoice_id=invoice_line.invoice_id,
        transaction_id=invoice_line.transaction_id,
        service_or_charge_type=invoice_line.service_or_charge_type,
        discrepancy_type=DiscrepancyType.UNSUPPORTED_FEE,
        field="large_package_surcharge",
        expected_value=0.0,
        billed_value=lp_billed,
        expected_amount=0.0,
        billed_amount=lp_billed,
        dollar_impact=lp_billed,
        dollar_discrepancy=lp_billed,
        explanation=(
            f"Large Package Surcharge charged but dims {L}x{W}x{H} do not meet "
            f"{carrier.upper()} large package threshold"
        ),
        why_discrepancy="Large package fee appears unsupported by dimension thresholds.",
        confidence=0.84,
        invoice_source_reference=invoice_line.raw_line_text,
    )


def audit_duplicates(invoice_lines: list[InvoiceLineItem]) -> list[AuditDiscrepancy]:
    seen = {}
    results: list[AuditDiscrepancy] = []
    for line in invoice_lines:
        key = (line.tracking_number, line.ship_date)
        if key in seen and line.total_billed > 0:
            results.append(
                AuditDiscrepancy(
                    line_id=line.id,
                    tracking_number=line.tracking_number,
                    invoice_id=line.invoice_id,
                    transaction_id=line.transaction_id,
                    service_or_charge_type=line.service_or_charge_type,
                    discrepancy_type=DiscrepancyType.OVERCHARGE,
                    field="duplicate_charge",
                    expected_value=0.0,
                    billed_value=line.total_billed,
                    expected_amount=0.0,
                    billed_amount=line.total_billed,
                    dollar_impact=line.total_billed,
                    dollar_discrepancy=line.total_billed,
                    explanation=f"Tracking number {line.tracking_number} billed more than once on {line.ship_date}",
                    why_discrepancy="Potential duplicate invoice line.",
                    confidence=0.9,
                    invoice_source_reference=line.raw_line_text,
                )
            )
        else:
            seen[key] = line
    return results

