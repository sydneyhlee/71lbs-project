"""
Extraction layer: delegates to `contract_parser.extract.pdfplumber_extractor`
so the refined pipeline stays aligned with the base implementation.
"""

from contract_parser.extract.pdfplumber_extractor import ExtractedPDF, PageTextBlock, extract_pdf

__all__ = ["extract_pdf", "ExtractedPDF", "PageTextBlock"]
