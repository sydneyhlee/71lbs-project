"""
Adapter: StructuredDocument → ParsedDocument

Bridges our layout-aware ingestion layer to the extraction_v2 pipeline,
which expects app.pipeline.pdf_parser.ParsedDocument as its input.

The adapter preserves the extra value our ingestion layer provides
(section classification, better table detection, repeated header suppression)
while conforming to the interface extraction_v2 expects.
"""

from __future__ import annotations

from collections import defaultdict

from app.pipeline.pdf_parser import PageContent, ParsedDocument, TableData

from .document import StructuredDocument, TableBlock, TextBlock


def to_parsed_document(doc: StructuredDocument) -> ParsedDocument:
    """
    Convert a StructuredDocument into a ParsedDocument.

    Per-page text is reconstructed by grouping TextBlocks by their
    page_number. Tables are converted from TableBlock → TableData format.
    Section-type context (PRICING / SURCHARGE / etc.) is embedded as a
    comment line at the top of each section's text so the extractor can
    use it as a signal without requiring interface changes.
    """
    page_texts: dict[int, list[str]] = defaultdict(list)
    page_tables: dict[int, list[TableData]] = defaultdict(list)

    for section in doc.sections:
        section_tag = f"[SECTION:{section.section_type.value}]"
        if section.title:
            section_tag += f" {section.title}"

        for block in section.blocks:
            if isinstance(block, TextBlock):
                # Prefix the first block of each section with the section type tag
                # so extraction_v2 regex patterns get extra context.
                text = block.text
                if block is section.blocks[0]:
                    text = f"{section_tag}\n{text}"
                page_texts[block.page_number].append(text)

            elif isinstance(block, TableBlock):
                headers = [str(h) if h is not None else "" for h in block.headers]
                rows = [
                    [str(cell) if cell is not None else "" for cell in row]
                    for row in block.data_rows
                ]
                if headers and rows:
                    page_tables[block.page_number].append(TableData(
                        page_number=block.page_number,
                        headers=headers,
                        rows=rows,
                    ))

    pages: list[PageContent] = []
    for page_num in range(1, doc.page_count + 1):
        text = "\n".join(page_texts.get(page_num, []))
        tables = page_tables.get(page_num, [])
        pages.append(PageContent(
            page_number=page_num,
            text=text,
            tables=tables,
            is_ocr=page_num in doc.pages_ocr,
        ))

    return ParsedDocument(
        file_path=doc.source_path,
        total_pages=doc.page_count,
        pages=pages,
        used_ocr=bool(doc.pages_ocr),
    )
