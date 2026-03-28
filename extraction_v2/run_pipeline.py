"""
Test runner for the refined extraction pipeline (v2).

Tests on both FedEx and UPS contracts to validate:
- Metadata extraction
- Service term / zone / weight tier extraction
- Surcharge modification parsing
- DIM divisor detection
- Earned discount program extraction
- Schema conformance
- Integration with Parsing Team's ParsedDocument interface

Usage:
    python -m extraction_v2.run_pipeline <path_to_pdf>
    python -m extraction_v2.run_pipeline --test-all
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline.pdf_parser import parse_pdf
from app.pipeline.confidence import score_extraction
from app.pipeline.resolver import resolve_active_terms
from extraction_v2.extractor import extract_contract_v2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("extraction_v2.test")


def run_extraction(pdf_path: str) -> dict:
    """
    Run the full extraction pipeline on a single PDF.

    Steps match the main pipeline:
    1. Parse PDF (Parsing Team interface)
    2. Extract structured data (our v2 extractor)
    3. Score confidence (Validation Team interface)
    4. Resolve amendments
    """
    path = Path(pdf_path)
    if not path.exists():
        logger.error("File not found: %s", pdf_path)
        return {"error": f"File not found: {pdf_path}"}

    logger.info("=" * 70)
    logger.info("PROCESSING: %s", path.name)
    logger.info("=" * 70)

    # Step 1: Parse (Parsing Team's interface)
    logger.info("Step 1/4: Parsing PDF")
    doc = parse_pdf(path)
    logger.info("  Parsed %d pages (OCR=%s)", doc.total_pages, doc.used_ocr)
    if doc.errors:
        logger.warning("  Parse errors: %s", doc.errors)

    # Step 2: Extract (our v2 pipeline)
    logger.info("Step 2/4: Extracting with v2 pipeline")
    extraction = extract_contract_v2(
        doc=doc,
        file_name=path.name,
        file_path=str(path),
    )

    # Step 3: Score confidence (Validation Team's interface)
    logger.info("Step 3/4: Scoring confidence")
    extraction = score_extraction(extraction)

    # Step 4: Resolve amendments
    logger.info("Step 4/4: Resolving amendments")
    extraction = resolve_active_terms(extraction)

    result = extraction.model_dump()

    logger.info("")
    logger.info("=" * 70)
    logger.info("RESULTS SUMMARY: %s", path.name)
    logger.info("=" * 70)

    meta = extraction.metadata
    logger.info("Metadata:")
    logger.info("  Customer:     %s (conf=%.2f)",
                meta.customer_name.effective(), meta.customer_name.confidence)
    logger.info("  Account:      %s (conf=%.2f)",
                meta.account_number.effective(), meta.account_number.confidence)
    logger.info("  Agreement:    %s (conf=%.2f)",
                meta.agreement_number.effective(), meta.agreement_number.confidence)
    logger.info("  Carrier:      %s (conf=%.2f)",
                meta.carrier.effective(), meta.carrier.confidence)
    logger.info("  Effective:    %s", meta.effective_date.effective())
    logger.info("  Term:         %s → %s",
                meta.term_start.effective(), meta.term_end.effective())

    logger.info("")
    logger.info("Service Terms: %d extracted", len(extraction.service_terms))
    for i, st in enumerate(extraction.service_terms[:10]):
        logger.info("  [%d] %s | zones=%s | discount=%s%% | weight=%s",
                     i + 1,
                     st.service_type.effective(),
                     st.applicable_zones.effective(),
                     st.discount_percentage.effective(),
                     st.conditions.effective())
    if len(extraction.service_terms) > 10:
        logger.info("  ... and %d more", len(extraction.service_terms) - 10)

    logger.info("")
    logger.info("Surcharges: %d extracted", len(extraction.surcharges))
    for i, sc in enumerate(extraction.surcharges[:10]):
        logger.info("  [%d] %s | app=%s | mod=%s",
                     i + 1,
                     sc.surcharge_name.effective(),
                     sc.application.effective(),
                     sc.modification.effective())

    logger.info("")
    logger.info("DIM Rules: %d extracted", len(extraction.dim_rules))
    for dr in extraction.dim_rules:
        logger.info("  Divisor=%s | services=%s",
                     dr.dim_divisor.effective(),
                     dr.applicable_services.effective())

    logger.info("")
    logger.info("Special Terms: %d extracted", len(extraction.special_terms))
    for sp in extraction.special_terms[:5]:
        logger.info("  %s = %s",
                     sp.term_name.effective(),
                     str(sp.term_value.effective())[:100])

    logger.info("")
    logger.info("Amendments: %d detected", len(extraction.amendments))
    for am in extraction.amendments[:5]:
        logger.info("  #%s (effective=%s, supersedes=%s)",
                     am.amendment_number.effective(),
                     am.effective_date.effective(),
                     am.supersedes_version.effective())

    logger.info("")
    logger.info("Overall Confidence: %.2f", extraction.overall_confidence)
    logger.info("Total Fields Extracted: %d", extraction.total_fields_extracted)
    logger.info("Fields Needing Review: %d", extraction.fields_needing_review)
    logger.info("=" * 70)

    return result


def save_output(result: dict, output_path: str):
    """Save extraction result as JSON."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Output saved to: %s", output_path)


def main():
    parser = argparse.ArgumentParser(
        description="Run extraction v2 pipeline on contract PDFs"
    )
    parser.add_argument("pdf_path", nargs="?", help="Path to a PDF file")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument(
        "--test-all", action="store_true",
        help="Run on both sample FedEx and UPS contracts",
    )
    args = parser.parse_args()

    if args.test_all:
        pdfs_dir = Path(
            r"C:\Users\Ajone\AppData\Roaming\Cursor\User\workspaceStorage"
            r"\05995baafc1dbd017cbf76d33cf9941e\pdfs"
        )
        test_files = {
            "fedex_contract": pdfs_dir / "52943c12-126d-4107-9743-0260d33e39f8"
                              / "Armoire FedEx Pricing Agreement 12-8-2025.pdf",
            "ups_contract": pdfs_dir / "470c9c41-5ea6-408e-aa26-2e6616bd3bc4"
                            / "G-Global UPS final 2025.03.21.pdf",
        }

        output_dir = Path(__file__).parent / "test_outputs"
        output_dir.mkdir(exist_ok=True)

        for name, pdf_path in test_files.items():
            if pdf_path.exists():
                result = run_extraction(str(pdf_path))
                out_file = output_dir / f"{name}_extraction.json"
                save_output(result, str(out_file))
            else:
                logger.warning("Test file not found: %s", pdf_path)

    elif args.pdf_path:
        result = run_extraction(args.pdf_path)
        if args.output:
            save_output(result, args.output)
        else:
            out_path = Path(args.pdf_path).stem + "_extraction.json"
            out_dir = Path(__file__).parent / "test_outputs"
            out_dir.mkdir(exist_ok=True)
            save_output(result, str(out_dir / out_path))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
