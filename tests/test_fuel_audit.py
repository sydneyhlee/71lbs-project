import unittest
from datetime import date

import app.invoice.fuel as fuel_mod
from app.models.schema import ContractExtraction, InvoiceLineItem


class TestFuelAudit(unittest.TestCase):
    def setUp(self):
        self.orig_loader = fuel_mod._load_fuel_table
        fuel_mod._load_fuel_table = lambda: {
            "fedex": {"ground": {"2025-01-06": 12.25}, "express": {"2025-01-06": 14.75}},
            "ups": {"ground": {"2025-01-06": 11.75}, "air": {"2025-01-06": 15.25}},
        }

    def tearDown(self):
        fuel_mod._load_fuel_table = self.orig_loader

    def test_weekly_rate_lookup(self):
        rate = fuel_mod.get_weekly_rate(date(2025, 1, 10), "fedex", "ground")
        self.assertEqual(rate, 12.25)

    def test_fuel_discount_application(self):
        c = ContractExtraction()
        c.metadata.carrier.value = "FedEx"
        c.fuel_surcharge = {"discount_pct": 10.0}
        line = InvoiceLineItem(
            tracking_number="1",
            ship_date=date(2025, 1, 10),
            service_group="ground",
            net_transport_charge=100.0,
            fuel_surcharge_billed=20.0,
        )
        d = fuel_mod.audit_fuel(line, c)
        self.assertIsNotNone(d)
        self.assertAlmostEqual(d.expected_value, 11.03, places=2)

    def test_expired_discount_falls_back_to_zero(self):
        c = ContractExtraction()
        c.metadata.carrier.value = "FedEx"
        c.fuel_surcharge = {"discount_pct": 10.0, "expiration_date": "2024-12-31"}
        line = InvoiceLineItem(
            tracking_number="1",
            ship_date=date(2025, 1, 10),
            service_group="ground",
            net_transport_charge=100.0,
            fuel_surcharge_billed=20.0,
        )
        d = fuel_mod.audit_fuel(line, c)
        self.assertIsNotNone(d)
        self.assertAlmostEqual(d.expected_value, 12.25, places=2)

    def test_fedex_vs_ups_base_amount(self):
        c_fx = ContractExtraction()
        c_fx.metadata.carrier.value = "FedEx"
        c_ups = ContractExtraction()
        c_ups.metadata.carrier.value = "UPS"
        line = InvoiceLineItem(
            tracking_number="1",
            ship_date=date(2025, 1, 10),
            service_group="ground",
            net_transport_charge=100.0,
            published_charge=200.0,
            fuel_surcharge_billed=30.0,
        )
        d_fx = fuel_mod.audit_fuel(line, c_fx)
        d_ups = fuel_mod.audit_fuel(line, c_ups)
        self.assertIsNotNone(d_fx)
        self.assertIsNotNone(d_ups)
        self.assertNotEqual(d_fx.expected_value, d_ups.expected_value)


if __name__ == "__main__":
    unittest.main()

