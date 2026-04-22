"""Minimum Net Charge (MNC) checks."""

from __future__ import annotations

from app.models.schema import AuditDiscrepancy, ContractExtraction, DiscrepancyType, InvoiceLineItem

PUBLISHED_MNC_DEFAULTS = {
    "fedex": {"ground": 11.00, "home_delivery": 11.00, "express": 12.50, "ground_economy": 4.50},
    "ups": {"ground": 11.00, "ground_saver": 4.50, "express": 12.50},
}


def _carrier_slug(contract: ContractExtraction) -> str:
    raw = contract.metadata.carrier.effective() if hasattr(contract, "metadata") else None
    return str(raw or "").strip().lower()


def audit_mnc(invoice_line: InvoiceLineItem, contract: ContractExtraction) -> AuditDiscrepancy | None:
    service_group = invoice_line.service_group or "ground"
    contracted_mnc = None
    if contract.minimum_net_charge:
        contracted_mnc = contract.minimum_net_charge.get(service_group)

    carrier = _carrier_slug(contract)
    default_mnc = PUBLISHED_MNC_DEFAULTS.get(carrier, {}).get(service_group)
    effective_mnc = contracted_mnc if contracted_mnc is not None else default_mnc
    if effective_mnc is None:
        return None

    net = invoice_line.net_transport_charge or 0.0
    if contracted_mnc is not None and default_mnc is not None:
        if contracted_mnc < default_mnc and abs(net - default_mnc) < 0.05:
            delta = round(net - contracted_mnc, 2)
            return AuditDiscrepancy(
                line_id=invoice_line.id,
                tracking_number=invoice_line.tracking_number,
                invoice_id=invoice_line.invoice_id,
                transaction_id=invoice_line.transaction_id,
                service_or_charge_type=invoice_line.service_or_charge_type,
                discrepancy_type=DiscrepancyType.OVERCHARGE,
                field="minimum_net_charge",
                expected_value=contracted_mnc,
                billed_value=net,
                expected_amount=contracted_mnc,
                billed_amount=net,
                dollar_impact=delta,
                dollar_discrepancy=delta,
                explanation=f"Contract MNC ${contracted_mnc:.2f} but published default ${default_mnc:.2f} applied",
                why_discrepancy="Published MNC appears used instead of contracted MNC.",
                confidence=0.8,
                invoice_source_reference=invoice_line.raw_line_text,
            )
    return None

