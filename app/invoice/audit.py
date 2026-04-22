"""Invoice parsing + deterministic audit orchestration."""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.config import AUDIT_DIR, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from app.invoice.accessorials import (
    audit_address_correction,
    audit_ahs,
    audit_das,
    audit_duplicates,
    audit_large_package,
    audit_residential,
)
from app.invoice.dim import audit_dim
from app.invoice.earned_discount import audit_earned_discount
from app.invoice.fuel import audit_fuel
from app.invoice.gsr import audit_gsr
from app.invoice.ingest import (
    ingest_carrier_api_invoice,
    ingest_invoice,
    validate_invoice_items,
)
from app.invoice.mnc import audit_mnc
from app.invoice.observability import write_audit_run_log
from app.invoice.parse_prompt import INVOICE_PARSE_PROMPT
from app.models.schema import (
    AuditDiscrepancy,
    ContractExtraction,
    DiscrepancyType,
    InvoiceAuditReport,
    InvoiceLineItem,
)

logger = logging.getLogger(__name__)

_INVOICE_ID_PATTERNS = [
    re.compile(r"Invoice Number[:\s]+([A-Z0-9\-]+)", re.IGNORECASE),
    re.compile(r"Invoice #[:\s]+([A-Z0-9\-]+)", re.IGNORECASE),
]
_TRACKING_PATTERN = re.compile(r"\b(1Z[0-9A-Z]{16}|[0-9]{12,20})\b")
_AMOUNT_PATTERN = re.compile(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)")

def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    txt = str(val).replace(",", "").replace("$", "").strip()
    if not txt:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _norm_name(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", name.lower()).split())


def _extract_invoice_id(text: str) -> str | None:
    head = text[:3000]
    for pat in _INVOICE_ID_PATTERNS:
        m = pat.search(head)
        if m:
            return m.group(1)
    return None


def _parse_invoice_deterministic(file_name: str, text: str) -> tuple[str | None, list[InvoiceLineItem]]:
    """Fallback parser when LLM parsing is unavailable."""
    invoice_id = _extract_invoice_id(text)
    lines: list[InvoiceLineItem] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 6:
            continue
        amt_m = _AMOUNT_PATTERN.search(line)
        if not amt_m:
            continue
        amount = _to_float(amt_m.group(1))
        if amount is None:
            continue

        txn_m = _TRACKING_PATTERN.search(line)
        txn = txn_m.group(1) if txn_m else None
        service_guess = line[: max(8, min(64, amt_m.start()))].strip(" -:")
        if not service_guess:
            service_guess = "Unknown charge"

        lines.append(
            InvoiceLineItem(
                tracking_number=txn or "",
                transaction_id=txn,
                invoice_id=invoice_id,
                id=f"{file_name}:{len(lines)+1}",
                service_or_charge_type=service_guess,
                base_amount=None,
                billed_amount=amount,
                total_billed=amount,
                applied_discount_pct=None,
                source_page=1,
                source_text=line[:220],
                raw_line_text=line[:220],
            )
        )
        if len(lines) >= 250:
            break

    if not lines:
        logger.warning("No deterministic invoice lines parsed for %s", file_name)
    return invoice_id, lines


def _parse_invoice_with_llm(file_name: str, text: str) -> tuple[str | None, list[InvoiceLineItem]]:
    if not LLM_API_KEY:
        return _parse_invoice_deterministic(file_name, text)
    try:
        from openai import OpenAI

        client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
        response = client.chat.completions.create(
            model=LLM_MODEL,
            response_format={"type": "json_object"},
            temperature=0.0,
            messages=[
                {"role": "system", "content": _INVOICE_PARSE_PROMPT},
                {"role": "user", "content": text[:24000]},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        invoice_id = data.get("invoice_id") or _extract_invoice_id(text)

        items: list[InvoiceLineItem] = []
        for entry in data.get("line_items", []):
            if not isinstance(entry, dict):
                continue
            billed = _to_float(entry.get("billed_amount"))
            if billed is None:
                continue
            items.append(
                InvoiceLineItem(
                    id=str(entry.get("id") or f"{file_name}:{len(items)+1}"),
                    tracking_number=str(entry.get("tracking_number") or entry.get("transaction_id") or ""),
                    transaction_id=entry.get("transaction_id"),
                    invoice_id=invoice_id,
                    ship_date=entry.get("ship_date"),
                    actual_delivery_datetime=entry.get("actual_delivery_datetime"),
                    service_code=entry.get("service_code"),
                    service_group=entry.get("service_group"),
                    package_type=entry.get("package_type"),
                    service_or_charge_type=str(entry.get("service_or_charge_type") or "Unknown charge"),
                    origin_zip=entry.get("origin_zip"),
                    destination_zip=entry.get("destination_zip"),
                    zone=entry.get("zone"),
                    actual_weight_lbs=_to_float(entry.get("actual_weight_lbs")),
                    length=_to_float(entry.get("length")),
                    width=_to_float(entry.get("width")),
                    height=_to_float(entry.get("height")),
                    rated_weight_lbs=_to_float(entry.get("rated_weight_lbs")),
                    rate_per_lb=_to_float(entry.get("rate_per_lb")),
                    published_charge=_to_float(entry.get("published_charge")),
                    transport_charge=_to_float(entry.get("transport_charge")),
                    earned_discount_applied=_to_float(entry.get("earned_discount_applied")),
                    incentive_credit=_to_float(entry.get("incentive_credit")),
                    net_transport_charge=_to_float(entry.get("net_transport_charge")),
                    fuel_surcharge_billed=_to_float(entry.get("fuel_surcharge_billed")),
                    residential_surcharge_billed=_to_float(entry.get("residential_surcharge_billed")),
                    das_billed=_to_float(entry.get("das_billed")),
                    ahs_billed=_to_float(entry.get("ahs_billed")),
                    large_package_billed=_to_float(entry.get("large_package_billed")),
                    address_correction_billed=_to_float(entry.get("address_correction_billed")),
                    saturday_delivery_billed=_to_float(entry.get("saturday_delivery_billed")),
                    declared_value_billed=_to_float(entry.get("declared_value_billed")),
                    total_billed=_to_float(entry.get("total_billed")) or billed,
                    is_residential=entry.get("is_residential"),
                    carrier_exception_code=entry.get("carrier_exception_code"),
                    base_amount=_to_float(entry.get("base_amount")),
                    billed_amount=billed,
                    applied_discount_pct=_to_float(entry.get("applied_discount_pct")),
                    source_page=entry.get("source_page"),
                    source_text=(entry.get("source_text") or "")[:220] or None,
                    raw_line_text=(entry.get("raw_line_text") or entry.get("source_text") or "")[:220] or None,
                )
            )
        if not items:
            return _parse_invoice_deterministic(file_name, text)
        return invoice_id, items
    except Exception as exc:
        logger.error("Invoice LLM parsing failed for %s: %s", file_name, exc)
        return _parse_invoice_deterministic(file_name, text)


def render_discrepancy_text_report(report: InvoiceAuditReport) -> str:
    period = "N/A"
    if report.invoice_period_start and report.invoice_period_end:
        period = f"{report.invoice_period_start} to {report.invoice_period_end}"

    def _action_for(d: AuditDiscrepancy) -> str:
        field = (d.field or "").lower()
        kind = d.discrepancy_type.value
        if field == "service_refund":
            return "File GSR claim with carrier within allowed claim window."
        if field == "fuel_surcharge":
            return "Request fuel surcharge adjustment using weekly table and contract discount."
        if field == "rated_weight_lbs":
            return "Dispute billed rated weight with DIM calculation evidence."
        if kind == "missing_discount":
            return "Request rebill with contracted discount tier."
        if kind == "unsupported_fee":
            return "Dispute unsupported fee and request credit."
        return "Review invoice evidence and submit recovery request."

    generated = report.created_at if report.created_at.endswith("Z") else f"{report.created_at}Z"
    lines = [
        "71lbs Invoice Audit Report",
        "=" * 72,
        f"Company: {report.company_name}",
        f"Company:        {report.company_name}",
        f"Agreement ID:   {report.agreement_id}",
        f"Carrier:        {report.carrier or 'Unknown'}",
        f"Invoice Period: {period}",
        f"Audited Lines:  {report.lines_audited}",
        f"Lines Flagged:  {report.lines_with_discrepancies}",
        f"Total Recovery Potential: ${report.total_recovery_potential:.2f}",
        f"Generated:      {generated}",
        "=" * 72,
        "",
        "DISCREPANCIES FOUND",
        "-" * 72,
        "",
    ]

    summary_by_type: dict[str, dict[str, float]] = {}
    for idx, d in enumerate(report.discrepancies, 1):
        dtype = d.discrepancy_type.value.replace("_", " ").title()
        bucket = summary_by_type.setdefault(dtype, {"count": 0, "total": 0.0})
        bucket["count"] += 1
        bucket["total"] += float(d.dollar_impact or 0.0)
        lines.extend(
            [
                f"[{idx}] {dtype.upper()}",
                f"    Tracking:    {d.tracking_number or d.transaction_id or 'Unknown'}",
                f"    Transaction: {d.transaction_id or d.tracking_number or 'Unknown'}",
                f"    Ship Date:   {d.ship_date or 'Unknown'}",
                f"    Service:     {d.service_or_charge_type or 'Unknown'}",
                f"    Billed:      ${((d.billed_value if d.billed_value is not None else d.billed_amount) or 0.0):.2f}",
                f"    Expected:    ${((d.expected_value if d.expected_value is not None else d.expected_amount) or 0.0):.2f}",
                f"    Dollar Discrepancy: ${(d.dollar_impact or 0.0):.2f}",
                f"    Discrepancy: ${abs(d.dollar_impact or 0.0):.2f} {'overcharge' if (d.dollar_impact or 0.0) >= 0 else 'undercharge'}",
                f"    Why:         {d.explanation or d.why_discrepancy}",
                f"    Basis:       {d.explanation or d.why_discrepancy}",
                f"    Action:      {_action_for(d)}",
                "",
            ]
        )

    lines.extend(
        [
            "=" * 72,
            "SUMMARY BY DISCREPANCY TYPE",
            "-" * 72,
        ]
    )
    for dtype, rollup in sorted(summary_by_type.items()):
        lines.append(f"{dtype:<28}{int(rollup['count']):>3} shipments    ${rollup['total']:.2f}")
    lines.extend(
        [
            "-" * 72,
            f"TOTAL RECOVERY POTENTIAL                  ${report.total_recovery_potential:.2f}",
            "=" * 72,
        ]
    )
    return "\n".join(lines).strip() + "\n"


def save_audit_report(report: InvoiceAuditReport) -> tuple[Path, Path]:
    json_path = AUDIT_DIR / f"{report.id}.json"
    txt_path = AUDIT_DIR / f"{report.id}.txt"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    txt_path.write_text(render_discrepancy_text_report(report), encoding="utf-8")
    return json_path, txt_path


def run_invoice_audit(invoice_lines: list[InvoiceLineItem], contract: ContractExtraction) -> InvoiceAuditReport:
    rolling_revenue = _compute_rolling_revenue(invoice_lines, contract)
    all_discrepancies: list[AuditDiscrepancy] = []
    all_discrepancies.extend(audit_duplicates(invoice_lines))

    for line in invoice_lines:
        checks = [
            audit_gsr(line, contract),
            audit_earned_discount(line, contract, rolling_revenue),
            audit_dim(line, contract),
            audit_fuel(line, contract),
            audit_mnc(line, contract),
            audit_residential(line, contract),
            audit_ahs(line, contract),
            audit_large_package(line, contract),
            audit_address_correction(line, contract),
        ]
        checks.extend(audit_das(line, contract))
        for result in checks:
            if result is not None:
                if result.ship_date is None:
                    result.ship_date = line.ship_date
                all_discrepancies.append(result)

    total_recovery = sum(d.dollar_impact for d in all_discrepancies if d.dollar_impact > 0)
    line_ids = {d.line_id for d in all_discrepancies if d.line_id}
    company_name = (
        contract.client_id
        or str(contract.metadata.customer_name.effective() or "Unknown Company")
    )
    agreement_id = contract.contract_id or contract.id
    ship_dates = [line.ship_date for line in invoice_lines if line.ship_date is not None]
    return InvoiceAuditReport(
        agreement_id=agreement_id,
        company_name=company_name,
        carrier=str(contract.metadata.carrier.effective() or "Unknown"),
        invoice_period_start=min(ship_dates) if ship_dates else None,
        invoice_period_end=max(ship_dates) if ship_dates else None,
        discrepancies=all_discrepancies,
        total_recovery_potential=round(total_recovery, 2),
        lines_audited=len(invoice_lines),
        lines_with_discrepancies=len(line_ids),
    )


def _compute_rolling_revenue(invoice_lines: list[InvoiceLineItem], contract: ContractExtraction) -> float:
    carrier = str(contract.metadata.carrier.effective() or "").strip().lower()
    batch_sum = 0.0
    week_starts: set = set()
    for line in invoice_lines:
        if line.ship_date is not None:
            week_starts.add(line.ship_date - timedelta(days=line.ship_date.weekday()))
        if carrier == "ups":
            gross = line.published_charge or line.transport_charge or 0.0
            batch_sum += gross + (line.residential_surcharge_billed or 0.0) + (line.das_billed or 0.0)
        else:
            gross = line.transport_charge or line.published_charge or 0.0
            batch_sum += gross
    weeks_in_batch = max(len(week_starts), 1)
    return round((batch_sum / weeks_in_batch) * 52, 2)


def run_invoice_audit_from_files(
    approved_extraction: ContractExtraction,
    invoice_paths: list[Path],
    carrier_invoice_ids: list[str] | None = None,
) -> InvoiceAuditReport:
    if approved_extraction.status.value != "approved":
        raise ValueError("Invoice audit requires an approved agreement.")

    file_names: list[str] = []
    all_lines: list[InvoiceLineItem] = []
    validation_errors: list[str] = []
    carrier_hint = str(approved_extraction.metadata.carrier.effective() or "fedex").lower()

    # Primary path: direct electronic invoice API ingestion.
    for invoice_id in carrier_invoice_ids or []:
        try:
            api_lines = ingest_carrier_api_invoice(carrier_hint, invoice_id)
            all_lines.extend(api_lines)
            file_names.append(f"{carrier_hint.upper()} API invoice {invoice_id}")
            validation_errors.extend(validate_invoice_items(api_lines, f"API invoice {invoice_id}"))
        except Exception as exc:
            logger.warning("Carrier API ingestion failed for %s: %s", invoice_id, exc)

    # Fallback path: file ingestion (CSV/PDF with LLM + deterministic fallback).
    for path in invoice_paths:
        file_names.append(path.name)
        line_items = ingest_invoice(path, carrier_hint)
        validation_errors.extend(validate_invoice_items(line_items, path.name))
        all_lines.extend(line_items)

    if not all_lines:
        raise ValueError(
            "Invoice ingestion produced no auditable line items; missing critical field(s) requires human review before audit."
        )

    if validation_errors:
        # Hard-stop to avoid silent pass-through on incomplete invoice lines.
        raise ValueError(
            "Invoice ingestion validation failed; requires human review before audit:\n- "
            + "\n- ".join(validation_errors[:25])
        )

    report = run_invoice_audit(all_lines, approved_extraction)
    report.invoice_files = file_names
    checks_evaluated = len(all_lines) * 10
    checks_without_result = max(checks_evaluated - len(report.discrepancies), 0)
    write_audit_run_log(
        report,
        checks_evaluated=checks_evaluated,
        checks_without_result=checks_without_result,
    )
    return report

