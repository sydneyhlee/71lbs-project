import unittest

from app.invoice.dim import audit_dim, calculate_dim_weight
from app.models.schema import ContractExtraction, InvoiceLineItem


class TestDimAudit(unittest.TestCase):
    def test_rounding_rules_post_aug_2025(self):
        self.assertEqual(calculate_dim_weight(11.1, 8.1, 6.1, 139), 6)

    def test_fedex_40lb_minimum_triggers(self):
        c = ContractExtraction()
        c.metadata.carrier.value = "FedEx"
        line = InvoiceLineItem(
            tracking_number="123",
            service_or_charge_type="FedEx Ground",
            length=49.1,
            width=10.0,
            height=10.0,
            actual_weight_lbs=5.0,
            rated_weight_lbs=20.0,
            rate_per_lb=1.0,
        )
        d = audit_dim(line, c)
        self.assertIsNotNone(d)
        self.assertEqual(d.expected_value, 40.0)

    def test_ups_does_not_trigger_fedex_minimum(self):
        c = ContractExtraction()
        c.metadata.carrier.value = "UPS"
        line = InvoiceLineItem(
            tracking_number="123",
            service_or_charge_type="UPS Ground",
            length=49.1,
            width=10.0,
            height=10.0,
            actual_weight_lbs=5.0,
            rated_weight_lbs=40.0,
            rate_per_lb=1.0,
        )
        d = audit_dim(line, c)
        self.assertIsNotNone(d)
        self.assertNotEqual(d.expected_value, 40.0)


if __name__ == "__main__":
    unittest.main()

