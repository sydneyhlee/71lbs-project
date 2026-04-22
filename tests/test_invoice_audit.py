import unittest

from app.invoice.audit import render_discrepancy_text_report
from app.models.schema import AuditDiscrepancy, DiscrepancyType, InvoiceAuditReport


class TestInvoiceAudit(unittest.TestCase):
    def test_txt_report_format_contains_required_fields(self):
        report = InvoiceAuditReport(
            company_name="ARMOIRE",
            agreement_id="agreement-1",
            invoice_files=["invoice.pdf"],
            discrepancies=[
                AuditDiscrepancy(
                    line_id="line-1",
                    tracking_number="123456789012",
                    transaction_id="123456789012",
                    invoice_id="INV-1001",
                    service_or_charge_type="FedEx Ground",
                    discrepancy_type=DiscrepancyType.MISSING_DISCOUNT,
                    expected_value=50.0,
                    billed_value=80.0,
                    dollar_impact=30.0,
                    explanation="Missing discount.",
                )
            ],
        )
        text = render_discrepancy_text_report(report)
        self.assertIn("Company: ARMOIRE", text)
        self.assertIn("Transaction: 123456789012", text)
        self.assertIn("Dollar Discrepancy", text)
        self.assertIn("Why:", text)


if __name__ == "__main__":
    unittest.main()

