"""Persistent audit-run telemetry and trail logging."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import AUDIT_LOG_DIR
from app.models.schema import InvoiceAuditReport
from app.reference.health import summarize_health


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_audit_run_log(
    report: InvoiceAuditReport,
    *,
    checks_evaluated: int,
    checks_without_result: int,
) -> Path:
    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "audit_run_id": report.id,
        "created_at_utc": _utc_stamp(),
        "company_name": report.company_name,
        "agreement_id": report.agreement_id,
        "invoice_files": report.invoice_files,
        "lines_audited": report.lines_audited,
        "lines_with_discrepancies": report.lines_with_discrepancies,
        "discrepancy_count": len(report.discrepancies),
        "checks_evaluated": checks_evaluated,
        "checks_without_result": checks_without_result,
        "total_recovery_potential": report.total_recovery_potential,
        "reference_health": summarize_health(),
    }
    out_path = AUDIT_LOG_DIR / f"audit_run_{report.id}_{_utc_stamp()}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path

