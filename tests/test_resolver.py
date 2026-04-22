import unittest

from app.pipeline.resolver import resolve_active_terms
from app.models.schema import ContractExtraction


class TestResolver(unittest.TestCase):
    def test_amendment_overwrites_base_field(self):
        base = ContractExtraction(
            document_type="base_agreement",
            effective_date="2025-01-01",
            fuel_surcharge={"discount_pct": 5.0},
        )
        base.metadata.customer_name.value = "ACME"
        amd = ContractExtraction(
            document_type="amendment",
            effective_date="2025-02-01",
            fuel_surcharge={"discount_pct": 10.0},
        )
        resolved = resolve_active_terms([base, amd])
        self.assertEqual(resolved.fuel_surcharge["discount_pct"], 10.0)

    def test_same_effective_date_uses_amendment_priority(self):
        addendum = ContractExtraction(
            document_type="addendum",
            effective_date="2025-02-01",
            fuel_surcharge={"discount_pct": 7.0},
        )
        amendment = ContractExtraction(
            document_type="amendment",
            effective_date="2025-02-01",
            fuel_surcharge={"discount_pct": 9.0},
        )
        resolved = resolve_active_terms([addendum, amendment])
        self.assertEqual(resolved.fuel_surcharge["discount_pct"], 9.0)

    def test_expired_fuel_discount_defaults_zero(self):
        base = ContractExtraction(
            document_type="base_agreement",
            effective_date="2025-01-01",
            fuel_surcharge={"discount_pct": 8.0, "expiration_date": "2025-01-31"},
        )
        resolved = resolve_active_terms([base])
        self.assertEqual(resolved.fuel_surcharge["discount_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()

