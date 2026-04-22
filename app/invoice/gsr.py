"""Late-delivery / GSR eligibility checks."""

from __future__ import annotations

import json
from datetime import date, time, timedelta
from pathlib import Path
from typing import Optional

from app.models.schema import AuditDiscrepancy, ContractExtraction, DiscrepancyType, InvoiceLineItem

try:
    import holidays

    US_HOLIDAYS = holidays.US()
except Exception:  # pragma: no cover
    US_HOLIDAYS = {}

SERVICE_COMMITMENTS: dict[str, tuple[int, Optional[time]]] = {
    "fedex_first_overnight": (1, time(8, 0)),
    "fedex_priority_overnight": (1, time(10, 30)),
    "fedex_standard_overnight": (1, time(16, 30)),
    "fedex_2day_am": (2, time(10, 30)),
    "fedex_2day": (2, time(16, 30)),
    "fedex_express_saver": (3, time(16, 30)),
    "ups_next_day_air_early": (1, time(8, 0)),
    "ups_next_day_air": (1, time(10, 30)),
    "ups_next_day_air_saver": (1, time(15, 0)),
    "ups_2nd_day_air_am": (2, time(10, 30)),
    "ups_2nd_day_air": (2, None),
    "ups_3_day_select": (3, None),
}

GSR_EXEMPT_EXCEPTION_CODES = {
    "weather",
    "address_error",
    "business_closed",
    "recipient_unavailable",
    "customs_delay",
}

SUSPENSION_WINDOWS_PATH = Path("data/reference/gsr_suspension_windows.json")


def _load_suspension_windows() -> list[dict]:
    if SUSPENSION_WINDOWS_PATH.exists():
        return json.loads(SUSPENSION_WINDOWS_PATH.read_text(encoding="utf-8"))
    return []


def _carrier_slug(contract: ContractExtraction) -> str:
    raw = contract.metadata.carrier.effective() if hasattr(contract, "metadata") else None
    return str(raw or "").strip().lower()


def _is_in_suspension_window(ship_date: date, carrier: str) -> bool:
    for window in _load_suspension_windows():
        if window.get("carrier") != carrier:
            continue
        start = date.fromisoformat(window["start"])
        end = date.fromisoformat(window["end"])
        if start <= ship_date <= end:
            return True
    return False


def _add_business_days(start: date, n: int) -> date:
    d = start
    added = 0
    while added < n:
        d = d + timedelta(days=1)
        if d.weekday() < 5 and d not in US_HOLIDAYS:
            added += 1
    return d


def _gsr_is_active(contract: ContractExtraction, service_group: str) -> bool:
    status = contract.gsr_status or {}
    raw = status.get(service_group, "active")
    return str(raw).lower() == "active"


def audit_gsr(invoice_line: InvoiceLineItem, contract: ContractExtraction) -> AuditDiscrepancy | None:
    service_code = invoice_line.service_code
    if not service_code or service_code not in SERVICE_COMMITMENTS:
        return None

    service_group = invoice_line.service_group or "express"
    if not _gsr_is_active(contract, service_group):
        return None
    if not invoice_line.actual_delivery_datetime or not invoice_line.ship_date:
        return None

    ex_code = (invoice_line.carrier_exception_code or "").lower()
    if ex_code in GSR_EXEMPT_EXCEPTION_CODES:
        return None

    carrier = _carrier_slug(contract)
    if _is_in_suspension_window(invoice_line.ship_date, carrier):
        return None

    days, commit_time = SERVICE_COMMITMENTS[service_code]
    promised_date = _add_business_days(invoice_line.ship_date, days)
    actual_dt = invoice_line.actual_delivery_datetime

    is_late = False
    if actual_dt.date() > promised_date:
        is_late = True
    elif actual_dt.date() == promised_date and commit_time and actual_dt.time() > commit_time:
        is_late = True
    if not is_late:
        return None

    refund_amount = invoice_line.total_billed
    return AuditDiscrepancy(
        line_id=invoice_line.id,
        tracking_number=invoice_line.tracking_number,
        invoice_id=invoice_line.invoice_id,
        transaction_id=invoice_line.transaction_id,
        service_or_charge_type=invoice_line.service_or_charge_type,
        discrepancy_type=DiscrepancyType.OVERCHARGE,
        field="gsr_late_delivery",
        expected_value=0.0,
        billed_value=invoice_line.total_billed,
        expected_amount=0.0,
        billed_amount=invoice_line.total_billed,
        dollar_impact=refund_amount,
        dollar_discrepancy=refund_amount,
        explanation=(
            f"GSR eligible: promised {promised_date} by {commit_time or 'EOD'}, "
            f"delivered {actual_dt}. Full refund of ${refund_amount:.2f} eligible."
        ),
        why_discrepancy="Late delivery qualifies for money-back guarantee refund.",
        confidence=0.9,
        invoice_source_reference=invoice_line.raw_line_text,
    )

