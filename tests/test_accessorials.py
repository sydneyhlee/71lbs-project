import unittest
from datetime import date

import app.invoice.accessorials as acc_mod
from app.models.schema import ContractExtraction, InvoiceLineItem


class TestAccessorialChecks(unittest.TestCase):
    def setUp(self):
        self.orig_loader = acc_mod._load_das_zips
        acc_mod._load_das_zips = lambda carrier: {"10001": "das"}

    def tearDown(self):
        acc_mod._load_das_zips = self.orig_loader

    def _contract(self):
        c = ContractExtraction()
        c.metadata.carrier.value = "FedEx"
        return c

    def test_das_on_non_das_zip_flags(self):
        c = self._contract()
        line = InvoiceLineItem(
            tracking_number="t1",
            destination_zip="99999",
            das_billed=5.0,
            total_billed=5.0,
        )
        out = acc_mod.audit_das(line, c)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].discrepancy_type.value, "unsupported_fee")

    def test_residential_on_commercial_flags(self):
        c = self._contract()
        line = InvoiceLineItem(
            tracking_number="t1",
            is_residential=False,
            residential_surcharge_billed=4.0,
            total_billed=4.0,
        )
        d = acc_mod.audit_residential(line, c)
        self.assertIsNotNone(d)
        self.assertEqual(d.discrepancy_type.value, "unsupported_fee")

    def test_duplicate_tracking_flags_overcharge(self):
        lines = [
            InvoiceLineItem(tracking_number="t1", ship_date=date(2026, 1, 1), total_billed=10.0),
            InvoiceLineItem(tracking_number="t1", ship_date=date(2026, 1, 1), total_billed=10.0),
        ]
        out = acc_mod.audit_duplicates(lines)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].discrepancy_type.value, "overcharge")


if __name__ == "__main__":
    unittest.main()

