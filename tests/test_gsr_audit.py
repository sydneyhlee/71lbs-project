import unittest
from datetime import date, datetime

import app.invoice.gsr as gsr_mod
from app.models.schema import ContractExtraction, InvoiceLineItem


class TestGsAudit(unittest.TestCase):
    def setUp(self):
        self.orig_windows = gsr_mod._load_suspension_windows
        gsr_mod._load_suspension_windows = lambda: []

    def tearDown(self):
        gsr_mod._load_suspension_windows = self.orig_windows

    def _base_contract(self):
        c = ContractExtraction()
        c.metadata.carrier.value = "FedEx"
        c.gsr_status = {"express": "active"}
        return c

    def test_late_express_delivery_flagged(self):
        c = self._base_contract()
        line = InvoiceLineItem(
            tracking_number="t1",
            service_code="fedex_priority_overnight",
            service_group="express",
            ship_date=date(2026, 1, 5),
            actual_delivery_datetime=datetime(2026, 1, 6, 12, 0, 0),
            total_billed=34.0,
        )
        d = gsr_mod.audit_gsr(line, c)
        self.assertIsNotNone(d)

    def test_on_time_not_flagged(self):
        c = self._base_contract()
        line = InvoiceLineItem(
            tracking_number="t1",
            service_code="fedex_priority_overnight",
            service_group="express",
            ship_date=date(2026, 1, 5),
            actual_delivery_datetime=datetime(2026, 1, 6, 10, 0, 0),
            total_billed=34.0,
        )
        self.assertIsNone(gsr_mod.audit_gsr(line, c))

    def test_waived_contract_skips(self):
        c = self._base_contract()
        c.gsr_status = {"express": "waived"}
        line = InvoiceLineItem(
            tracking_number="t1",
            service_code="fedex_priority_overnight",
            service_group="express",
            ship_date=date(2026, 1, 5),
            actual_delivery_datetime=datetime(2026, 1, 6, 12, 0, 0),
            total_billed=34.0,
        )
        self.assertIsNone(gsr_mod.audit_gsr(line, c))

    def test_weather_exception_skips(self):
        c = self._base_contract()
        line = InvoiceLineItem(
            tracking_number="t1",
            service_code="fedex_priority_overnight",
            service_group="express",
            ship_date=date(2026, 1, 5),
            actual_delivery_datetime=datetime(2026, 1, 6, 12, 0, 0),
            carrier_exception_code="weather",
            total_billed=34.0,
        )
        self.assertIsNone(gsr_mod.audit_gsr(line, c))

    def test_suspension_window_skips(self):
        gsr_mod._load_suspension_windows = lambda: [
            {"carrier": "fedex", "start": "2026-01-01", "end": "2026-01-10"}
        ]
        c = self._base_contract()
        line = InvoiceLineItem(
            tracking_number="t1",
            service_code="fedex_priority_overnight",
            service_group="express",
            ship_date=date(2026, 1, 5),
            actual_delivery_datetime=datetime(2026, 1, 6, 12, 0, 0),
            total_billed=34.0,
        )
        self.assertIsNone(gsr_mod.audit_gsr(line, c))


if __name__ == "__main__":
    unittest.main()

