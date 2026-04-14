"""
Unified contract extraction pipeline.

Runs the full pipeline: PDF -> Parse -> Extract -> Validate -> Output JSON

Usage:
    python run_pipeline.py <path_to_pdf>
    python run_pipeline.py <path_to_pdf> --output result.json
    python run_pipeline.py a.pdf b.pdf c.pdf --output batch.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from app.pipeline.pdf_parser import parse_pdf
from app.pipeline.confidence import score_extraction
from app.pipeline.resolver import resolve_active_terms
from extraction.extractor import extract_contract_v2
from validation.validators import validate_extraction, summarize_issues
from validation.confidence import compute_confidence
from vendors.registry import detect_vendor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline")


def run_extraction(pdf_path: str) -> dict:
    """
    Run the full extraction pipeline on a single PDF.

    Pipeline stages:
    1. Parse PDF (text extraction + OCR fallback)
    2. Detect carrier vendor
    3. Extract structured data (deterministic + LLM fallback)
    4. Validate extraction and flag issues
    5. Score confidence
    6. Resolve amendments
    """
    path = Path(pdf_path)
    if not path.exists():
        logger.error("File not found: %s", pdf_path)
        return {"error": f"File not found: {pdf_path}"}

    logger.info("=" * 70)
    logger.info("PROCESSING: %s", path.name)
    logger.info("=" * 70)

    # Step 1: Parse PDF
    logger.info("Step 1/6: Parsing PDF")
    doc = parse_pdf(path)
    logger.info("  Parsed %d pages (OCR=%s)", doc.total_pages, doc.used_ocr)
    if doc.errors:
        logger.warning("  Parse errors: %s", doc.errors)

    # Step 2: Detect vendor
    logger.info("Step 2/6: Detecting vendor")
    vendor = detect_vendor(doc.full_text)
    logger.info("  Vendor: %s (confidence=%.2f)", vendor.vendor_name or vendor.vendor_type, vendor.confidence)

    # Step 3: Extract
    logger.info("Step 3/6: Extracting with v2 pipeline")
    extraction = extract_contract_v2(
        doc=doc,
        file_name=path.name,
        file_path=str(path),
    )

    # Step 4: Validate
    logger.info("Step 4/6: Validating extraction")
    issues = validate_extraction(extraction)
    summary = summarize_issues(issues)
    conf_breakdown = compute_confidence(extraction, issues)
    logger.info(
        "  Validation: %d issues (%d errors, %d warnings), confidence=%.2f",
        summary.total_issues, summary.errors, summary.warnings, conf_breakdown.aggregate,
    )

    # Step 5: Score confidence (field-level)
    logger.info("Step 5/6: Scoring field-level confidence")
    extraction = score_extraction(extraction)

    # Step 6: Resolve amendments
    logger.info("Step 6/6: Resolving amendments")
    extraction = resolve_active_terms(extraction)

    result = extraction.model_dump()
    result["_validation"] = {
        "issues": [i.model_dump() for i in issues],
        "summary": summary.model_dump(),
        "confidence_breakdown": conf_breakdown.model_dump(),
        "vendor_detection": {
            "vendor_type": vendor.vendor_type.value,
            "vendor_name": vendor.vendor_name,
            "confidence": vendor.confidence,
            "signals": vendor.signals,
        },
    }

    # Print summary
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
    logger.info("  Carrier:      %s (conf=%.2f)",
                meta.carrier.effective(), meta.carrier.confidence)

    logger.info("Service Terms: %d extracted", len(extraction.service_terms))
    for i, st in enumerate(extraction.service_terms[:10]):
        logger.info("  [%d] %s | zones=%s | discount=%s%%",
                     i + 1,
                     st.service_type.effective(),
                     st.applicable_zones.effective(),
                     st.discount_percentage.effective())
    if len(extraction.service_terms) > 10:
        logger.info("  ... and %d more", len(extraction.service_terms) - 10)

    logger.info("Surcharges: %d extracted", len(extraction.surcharges))
    logger.info("DIM Rules: %d extracted", len(extraction.dim_rules))
    logger.info("Special Terms: %d extracted", len(extraction.special_terms))
    logger.info("Amendments: %d detected", len(extraction.amendments))
    logger.info("Overall Confidence: %.2f", extraction.overall_confidence)
    logger.info("Validation Issues: %d (%d errors, %d warnings)",
                summary.total_issues, summary.errors, summary.warnings)
    logger.info("=" * 70)

    return result


def save_output(result: dict, output_path: str):
    """Save extraction result as JSON."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Output saved to: %s", output_path)


def _combine_batch_results(
    successes: list[dict], failures: list[dict]
) -> dict:
    """Wrap multiple per-file results in one JSON object."""
    return {
        "batch_version": 1,
        "document_count": len(successes),
        "documents": successes,
        "failed": failures,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run unified contract extraction pipeline on one or more PDFs"
    )
    parser.add_argument(
        "pdf_paths",
        nargs="+",
        help="Path(s) to one or more PDF files",
    )
    parser.add_argument("--output", "-o", help="Output JSON file path")
    args = parser.parse_args()

    paths = args.pdf_paths
    successes: list[dict] = []
    failures: list[dict] = []

    for pdf_path in paths:
        result = run_extraction(pdf_path)
        if result.get("error"):
            failures.append({"path": pdf_path, "error": result["error"]})
        else:
            successes.append(result)

    if len(paths) == 1:
        result = successes[0] if successes else {"error": failures[0]["error"]}
    else:
        result = _combine_batch_results(successes, failures)

    if args.output:
        save_output(result, args.output)
    else:
        out_dir = Path("extraction/test_outputs")
        out_dir.mkdir(exist_ok=True)
        if len(paths) == 1:
            stem = Path(paths[0]).stem
            out_path = out_dir / f"{stem}_extraction.json"
        else:
            out_path = out_dir / "batch_extraction.json"
        save_output(result, str(out_path))


if __name__ == "__main__":
    main()
