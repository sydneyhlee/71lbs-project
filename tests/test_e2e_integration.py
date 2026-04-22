import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.invoice.audit import render_discrepancy_text_report, run_invoice_audit_from_files
from app.pipeline.ingestion import ingest_pdf
from app.storage.store import approve_extraction, load_extraction


def _sample_contract_path() -> Path:
    repo_sample = Path("data/samples/sample_contract.pdf")
    if repo_sample.exists():
        return repo_sample
    cached = Path(
        r"C:\Users\Ajone\AppData\Roaming\Cursor\User\workspaceStorage"
        r"\2f999365a696416d970536ef6caa8e5b\pdfs"
        r"\26aed5b2-83b4-4360-8b59-c821867b60d8"
        r"\Armoire FDX Dom FXE, FXG and Ground Economy pricing agreement 895468978-102-05-01e-sign.pdf"
    )
    if cached.exists():
        return cached
    raise FileNotFoundError("Sample contract PDF not found")


class TestE2EIntegration(unittest.TestCase):
    def test_full_pipeline_catches_known_discrepancies(self):
        with patch("app.pipeline.ingestion.verify_extraction_with_llm", side_effect=lambda extraction, doc: extraction):
            extraction = ingest_pdf(_sample_contract_path())
        approved = approve_extraction(extraction.id) or load_extraction(extraction.id)
        self.assertIsNotNone(approved)

        # Configure deterministic contract hooks for known-expected checks.
        approved.fuel_surcharge = {"discount_pct": 13.3}
        approved.gsr_status = {"express": "active"}
        for rule in approved.dim_rules:
            rule.dim_divisor.value = 139

        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", newline="", encoding="utf-8") as tmp:
            writer = csv.DictWriter(
                tmp,
                fieldnames=[
                    "Tracking ID",
                    "Ship Date",
                    "Delivery Date",
                    "Service Type",
                    "Recipient ZIP",
                    "Zone",
                    "Billed Weight",
                    "Transportation Charge",
                    "Net Charge",
                    "Fuel Surcharge",
                    "actual_weight_lbs",
                    "length",
                    "width",
                    "height",
                    "rate_per_lb",
                    "total_billed",
                    "raw_line_text",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "Tracking ID": "TST0001",
                    "Ship Date": "2025-03-03",
                    "Delivery Date": "2025-03-04",
                    "Service Type": "FedEx Ground",
                    "Recipient ZIP": "94105",
                    "Zone": 8,
                    "Billed Weight": 80,
                    "actual_weight_lbs": 10,
                    "length": 20,
                    "width": 20,
                    "height": 20,
                    "rate_per_lb": 0.5,
                    "Transportation Charge": 40,
                    "Net Charge": 40,
                    "Fuel Surcharge": "",
                    "total_billed": 40,
                    "raw_line_text": "DIM mismatch synthetic line",
                }
            )
            writer.writerow(
                {
                    "Tracking ID": "TST0002",
                    "Ship Date": "2025-03-05",
                    "Delivery Date": "2025-03-06",
                    "Service Type": "FedEx Ground",
                    "Recipient ZIP": "10001",
                    "Zone": 5,
                    "Billed Weight": 7,
                    "actual_weight_lbs": 7,
                    "length": "",
                    "width": "",
                    "height": "",
                    "rate_per_lb": 0.4,
                    "Transportation Charge": 100,
                    "Net Charge": 100,
                    "Fuel Surcharge": 14.5,
                    "total_billed": 114.5,
                    "raw_line_text": "Fuel mismatch synthetic line",
                }
            )
            writer.writerow(
                {
                    "Tracking ID": "TST0003",
                    "Ship Date": "2025-03-03",
                    "Delivery Date": "2025-03-05",
                    "Service Type": "FedEx Priority Overnight",
                    "Recipient ZIP": "30301",
                    "Zone": 2,
                    "Billed Weight": 5,
                    "actual_weight_lbs": 5,
                    "length": "",
                    "width": "",
                    "height": "",
                    "rate_per_lb": 1.0,
                    "Transportation Charge": 28.5,
                    "Net Charge": 28.5,
                    "Fuel Surcharge": "",
                    "total_billed": 28.5,
                    "raw_line_text": "Late delivery synthetic line",
                }
            )
            writer.writerow(
                {
                    "Tracking ID": "TST0004",
                    "Ship Date": "2025-03-04",
                    "Delivery Date": "2025-03-05",
                    "Service Type": "FedEx Ground",
                    "Recipient ZIP": "98104",
                    "Zone": 4,
                    "Billed Weight": 8,
                    "actual_weight_lbs": 5,
                    "length": "",
                    "width": "",
                    "height": "",
                    "rate_per_lb": 0.4,
                    "Transportation Charge": 12,
                    "Net Charge": 12,
                    "Fuel Surcharge": "",
                    "total_billed": 12,
                    "raw_line_text": "Clean synthetic line",
                }
            )
            csv_path = Path(tmp.name)

        report = run_invoice_audit_from_files(approved, [csv_path])
        discrepant_tracks = {d.tracking_number for d in report.discrepancies}

        self.assertEqual(len(report.discrepancies), 3)
        self.assertNotIn("TST0004", discrepant_tracks)
        dim = next(d for d in report.discrepancies if d.tracking_number == "TST0001")
        fuel = next(d for d in report.discrepancies if d.tracking_number == "TST0002")
        gsr = next(d for d in report.discrepancies if d.tracking_number == "TST0003")
        self.assertGreater(dim.dollar_impact, 0)
        self.assertIn("Published rate", fuel.explanation)
        self.assertIn("contracted discount", fuel.explanation)
        self.assertEqual(gsr.dollar_impact, 28.5)

        txt = render_discrepancy_text_report(report)
        self.assertIn(str(report.company_name), txt)
        self.assertIn("TST0001", txt)
        self.assertIn("TST0002", txt)
        self.assertIn("TST0003", txt)
        self.assertGreater(report.total_recovery_potential, 0)

        csv_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

