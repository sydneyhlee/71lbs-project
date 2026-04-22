import unittest

from extraction.metadata_extractor import extract_metadata


class TestMetadataExtractorQuality(unittest.TestCase):
    def test_rejects_invoice_boilerplate_as_customer_name(self):
        text = """
        Delivery Service Invoice
        Shipper: Do not pay. The above charges were submitted to
        Invoice Number: 12345
        Invoice Date: 03/01/2026
        """
        meta = extract_metadata(text)
        self.assertIsNone(meta.customer_name.value)

    def test_extracts_company_from_submitted_to_line(self):
        text = """
        Delivery Service Invoice
        Submitted to: G-FULFILLMENT LLC
        Invoice Number: 12345
        Invoice Date: 03/01/2026
        """
        meta = extract_metadata(text)
        self.assertEqual(meta.customer_name.value, "G-FULFILLMENT LLC")

    def test_rejects_non_numeric_account_value(self):
        text = """
        Carrier Agreement
        Account Number: Invoice
        Effective Date: 03/01/2026
        """
        meta = extract_metadata(text)
        self.assertIsNone(meta.account_number.value)


if __name__ == "__main__":
    unittest.main()

