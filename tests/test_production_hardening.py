import csv
import tempfile
import unittest
from pathlib import Path

from app.config import AUDIT_LOG_DIR
from app.invoice.audit import run_invoice_audit_from_files
from app.models.schema import ContractExtraction, ExtractionStatus


class TestProductionHardening(unittest.TestCase):
    def _approved_contract(self) -> ContractExtraction:
        contract = ContractExtraction(status=ExtractionStatus.APPROVED)
        contract.metadata.customer_name.value = "ARMOIRE"
        contract.metadata.carrier.value = "FedEx"
        contract.client_id = "ARMOIRE"
        contract.contract_id = "AGR-001"
        contract.fuel_surcharge = {"discount_pct": 10}
        return contract

    def test_end_to_end_invoice_audit_with_observability_log(self):
        contract = self._approved_contract()
        with tempfile.NamedTemporaryFile("w", newline="", suffix=".csv", delete=False) as tmp:
            writer = csv.DictWriter(
                tmp,
                fieldnames=[
                    "id",
                    "invoice_id",
                    "tracking_number",
                    "transaction_id",
                    "ship_date",
                    "service_code",
                    "service_group",
                    "service_or_charge_type",
                    "rated_weight_lbs",
                    "billed_amount",
                    "total_billed",
                    "net_transport_charge",
                    "fuel_surcharge_billed",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "id": "line-1",
                    "invoice_id": "INV-1001",
                    "tracking_number": "123456789012",
                    "transaction_id": "123456789012",
                    "ship_date": "2025-01-13",
                    "service_code": "FXG",
                    "service_group": "ground",
                    "service_or_charge_type": "Fuel Surcharge",
                    "rated_weight_lbs": "10",
                    "billed_amount": "20.00",
                    "total_billed": "120.00",
                    "net_transport_charge": "100.00",
                    "fuel_surcharge_billed": "20.00",
                }
            )
            csv_path = Path(tmp.name)

        try:
            report = run_invoice_audit_from_files(contract, [csv_path])
            self.assertGreaterEqual(len(report.discrepancies), 1)
            fuel_discrepancies = [d for d in report.discrepancies if d.field == "fuel_surcharge"]
            self.assertTrue(fuel_discrepancies, "Expected at least one fuel discrepancy.")
            self.assertAlmostEqual(fuel_discrepancies[0].expected_value or 0.0, 11.25, places=2)
            self.assertAlmostEqual(fuel_discrepancies[0].dollar_impact, 8.75, places=2)

            logs = list(AUDIT_LOG_DIR.glob(f"audit_run_{report.id}_*.json"))
            self.assertTrue(logs, "Expected persistent audit run log file.")
        finally:
            csv_path.unlink(missing_ok=True)
            for p in AUDIT_LOG_DIR.glob("audit_run_*.json"):
                # Keep workspace clean for repeated local runs.
                p.unlink(missing_ok=True)

    def test_invoice_validation_hard_error_for_missing_critical_fields(self):
        contract = self._approved_contract()
        with tempfile.NamedTemporaryFile("w", newline="", suffix=".csv", delete=False) as tmp:
            writer = csv.DictWriter(
                tmp,
                fieldnames=["id", "invoice_id", "tracking_number", "billed_amount", "total_billed"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "id": "line-1",
                    "invoice_id": "INV-1002",
                    "tracking_number": "123456789012",
                    "billed_amount": "15.00",
                    "total_billed": "15.00",
                }
            )
            csv_path = Path(tmp.name)

        try:
            with self.assertRaises(ValueError) as ctx:
                run_invoice_audit_from_files(contract, [csv_path])
            self.assertIn("missing critical field(s)", str(ctx.exception))
        finally:
            csv_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

