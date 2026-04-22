import unittest

from app.models.schema import ContractExtraction
from app.pipeline.llm_verifier import _apply_single_correction


class TestLlmVerifier(unittest.TestCase):
    def test_apply_single_correction_tracks_parser_and_reason(self):
        extraction = ContractExtraction()
        extraction.metadata.customer_name.value = "Armoire LLC"
        extraction.metadata.customer_name.confidence = 0.61

        corr = {
            "field_path": "metadata.customer_name",
            "corrected_value": "ARMOIRE",
            "confidence": 0.95,
            "source_page": 1,
            "source_text": "Customer Name: ARMOIRE",
            "correction_reason": "Normalize legal name casing.",
            "confidence_rationale": "Exact match in title block.",
        }
        _apply_single_correction(extraction, corr)

        ev = extraction.metadata.customer_name
        self.assertEqual(ev.original_parser_value, "Armoire LLC")
        self.assertEqual(ev.llm_corrected_value, "ARMOIRE")
        self.assertEqual(ev.value, "ARMOIRE")
        self.assertTrue(ev.was_llm_corrected)
        self.assertEqual(ev.correction_reason, "Normalize legal name casing.")
        self.assertEqual(ev.confidence_rationale, "Exact match in title block.")
        self.assertEqual(ev.source_page, 1)
        self.assertEqual(ev.source_text, "Customer Name: ARMOIRE")


if __name__ == "__main__":
    unittest.main()

