"""
Quick test runner for the PDF ingestion pipeline.

Usage:
    python3 run_ingestion.py path/to/invoice.pdf
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ingestion import ingest_pdf, SectionType
from ingestion.document import TableBlock, TextBlock, BlockType


def main(pdf_path: str) -> None:
    print(f"\nIngesting: {pdf_path}")
    print("=" * 60)

    doc = ingest_pdf(pdf_path)

    print(f"Pages:      {doc.page_count}")
    print(f"Extraction: {doc.extraction_method.value}")
    if doc.pages_ocr:
        print(f"OCR pages:  {doc.pages_ocr}")
    print(f"Sections:   {len(doc.sections)}")
    print()

    for i, section in enumerate(doc.sections, 1):
        title = section.title or "(no title)"
        tables = len(section.tables)
        text_blocks = len(section.text_blocks)
        print(f"[{i:02d}] {section.section_type.value:<12}  conf={section.confidence:.2f}  "
              f"p{section.page_start}–{section.page_end}  "
              f"{tables} table(s)  {text_blocks} text block(s)  |  {title[:60]}")

    # Show table contents for pricing and surcharge sections
    for section_type in (SectionType.PRICING, SectionType.SURCHARGE):
        relevant = doc.sections_of_type(section_type)
        if not relevant:
            continue
        print(f"\n{'─'*60}")
        print(f"{section_type.value} SECTIONS — table previews")
        print(f"{'─'*60}")
        for section in relevant:
            print(f"\n  >> {section.title or '(untitled)'}  (p{section.page_start})")
            for table in section.tables:
                rows = table.to_dicts()
                if not rows:
                    continue
                # Print up to 5 rows
                headers = list(rows[0].keys())
                col_w = max(14, max(len(h) for h in headers))
                header_line = "  ".join(h[:col_w].ljust(col_w) for h in headers)
                print(f"    {header_line}")
                print(f"    {'  '.join(['-'*col_w]*len(headers))}")
                for row in rows[:5]:
                    row_line = "  ".join(str(v or "")[:col_w].ljust(col_w) for v in row.values())
                    print(f"    {row_line}")
                if len(rows) > 5:
                    print(f"    ... ({len(rows) - 5} more rows)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 run_ingestion.py path/to/invoice.pdf")
        sys.exit(1)
    main(sys.argv[1])
