"""
Layout Parser — converts RawPage data into typed Block objects.

For digital pages (has char-level font data):
  - Groups characters into lines, then lines into blocks.
  - Detects headers using font size ratio AND/OR vertical gap signals.
    (Bold alone is NOT enough — column headers and form labels are bold
    at body font size, so they must not split sections.)
  - Extracts tables using pdfplumber's text-strategy table finder, which
    handles space-aligned columns (common in carrier invoices).
  - Everything else becomes a PARAGRAPH.

For OCR pages (flat text string, no font data):
  - Splits text into lines.
  - Uses heuristic text patterns to detect headers (short all-caps lines,
    lines ending with ":", lines that look like numbered headings).
  - No table detection (OCR table structure is unreliable without extra passes).
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from .document import BlockType, TableBlock, TextBlock
from .pdf_reader import RawChar, RawPage, RawTable

# How much larger than the median font size a line must be to trigger a header
# on size alone (regardless of bold).
HEADER_SIZE_RATIO = 1.15

# Minimum vertical gap (in points) between the previous line and the current
# line for a bold-only line (same body size) to be treated as a section header.
# Set high enough that column headers and form labels (tight spacing) don't qualify.
HEADER_GAP_THRESHOLD = 20.0


# ---------------------------------------------------------------------------
# Digital page processing
# ---------------------------------------------------------------------------

@dataclass
class _Line:
    """Characters grouped onto the same horizontal baseline."""
    chars: list[RawChar]

    @property
    def text(self) -> str:
        return "".join(ch.text for ch in self.chars).strip()

    @property
    def avg_font_size(self) -> float:
        sizes = [ch.font_size for ch in self.chars if ch.font_size > 0]
        return statistics.mean(sizes) if sizes else 0.0

    @property
    def is_bold(self) -> bool:
        bold_chars = sum(
            1 for ch in self.chars
            if "bold" in ch.font_name.lower() or "heavy" in ch.font_name.lower()
        )
        return bold_chars > len(self.chars) / 2


def _group_chars_into_lines(chars: list[RawChar], tolerance: float = 2.0) -> list[_Line]:
    """
    Group characters that share approximately the same y0 (baseline) into lines.
    Characters are sorted left-to-right within each line.
    """
    if not chars:
        return []

    # Sort by top-of-character (y0 descending in PDF coords = top-down visually)
    # pdfplumber uses bottom-left origin, so higher y0 = higher on page.
    sorted_chars = sorted(chars, key=lambda c: (-c.y0, c.x0))

    lines: list[_Line] = []
    current_baseline: float = sorted_chars[0].y0
    current_chars: list[RawChar] = []

    for ch in sorted_chars:
        if abs(ch.y0 - current_baseline) <= tolerance:
            current_chars.append(ch)
        else:
            if current_chars:
                lines.append(_Line(sorted(current_chars, key=lambda c: c.x0)))
            current_baseline = ch.y0
            current_chars = [ch]

    if current_chars:
        lines.append(_Line(sorted(current_chars, key=lambda c: c.x0)))

    return lines


def _median_font_size(lines: list[_Line]) -> float:
    sizes = [line.avg_font_size for line in lines if line.avg_font_size > 0]
    return statistics.median(sizes) if sizes else 12.0


def _is_header_line(line: _Line, median_size: float, gap_above: float) -> bool:
    """
    Return True if this line should open a new section.

    Rules (either is sufficient):
      1. Font size is meaningfully larger than the page median (size-ratio signal).
      2. Line is bold AND there is a significant vertical gap above it.
         This catches same-size bold section titles (e.g. "Other Charges Summary")
         while excluding column headers and form labels that are bold but tightly
         packed with surrounding content.

    Intentionally NOT used as a sole signal:
      - Bold alone: column headers and form field labels are bold at body size.
      - Short text alone: many values and labels are short.
    """
    if not line.text:
        return False

    size_ratio = line.avg_font_size / median_size if median_size > 0 else 1.0
    larger_font = size_ratio >= HEADER_SIZE_RATIO
    large_gap = gap_above >= HEADER_GAP_THRESHOLD

    # Require bold in all cases — carrier invoices use the same large font for
    # both page-header labels and true section headers; boldness is the only
    # reliable differentiator when combined with size or gap.
    return line.is_bold and (larger_font or large_gap)


def _parse_digital_page(raw: RawPage) -> list[TextBlock | TableBlock]:
    blocks: list[TextBlock | TableBlock] = []

    # --- Table extraction (text-strategy) ---
    # Uses pdfplumber's text-strategy to detect space-aligned columns, which
    # carrier invoices use instead of ruled lines.
    # Conservative settings prevent the entire page from being treated as one table:
    #   - min_words_vertical=4: at least 4 rows (header + 3 data rows)
    #   - min_words_horizontal=3: at least 3 distinct columns
    #   - snap_tolerance=5: allow small x-jitter in column alignment
    import pdfplumber
    with pdfplumber.open(raw._pdf_path) as pdf:  # type: ignore[attr-defined]
        pdf_page = pdf.pages[raw.page_number - 1]
        text_tables = pdf_page.find_tables({
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "snap_tolerance": 10,   # wider snap merges ligature-split chars into one column
            "join_tolerance": 10,
            "text_x_tolerance": 5,  # tolerance when grouping chars into words within cells
            "text_y_tolerance": 5,
            "min_words_vertical": 4,
            "min_words_horizontal": 3,
        })

    # Collect table bounding boxes (in page-top coordinate system) so we can
    # skip those y-ranges when building paragraph text blocks below.
    table_y_ranges: list[tuple[float, float]] = []
    for tbl_obj in text_tables:
        tbl = tbl_obj.extract()
        if not tbl or len(tbl) < 2:
            continue
        cleaned_rows = [
            [cell if cell is not None else "" for cell in row]
            for row in tbl
        ]
        # Filter out single-column "tables" — those are just aligned paragraphs
        max_cols = max(len(r) for r in cleaned_rows)
        if max_cols < 3:
            continue
        blocks.append(TableBlock(
            page_number=raw.page_number,
            rows=cleaned_rows,
            header_row=True,
        ))
        bbox = tbl_obj.bbox   # (x0, top, x1, bottom) in page-top coords
        table_y_ranges.append((bbox[1], bbox[3]))

    # --- Line grouping ---
    lines = _group_chars_into_lines(raw.chars)
    if not lines:
        return blocks

    median_size = _median_font_size(lines)

    # Merge consecutive non-header lines into paragraph blocks.
    # Track y0 of previous line to compute vertical gap.
    current_paragraph_lines: list[str] = []
    prev_y0: float | None = None

    def flush_paragraph() -> None:
        text = " ".join(current_paragraph_lines).strip()
        if text:
            blocks.append(TextBlock(
                block_type=BlockType.PARAGRAPH,
                text=text,
                page_number=raw.page_number,
                font_size=median_size,
                is_bold=False,
            ))
        current_paragraph_lines.clear()

    for line in lines:
        text = line.text
        if not text:
            continue

        # pdfplumber chars use bottom-left origin (y0), but table bboxes use
        # page-top origin. Convert: page_top = page_height - char_y0.
        char_top = raw.height - line.chars[0].y0
        if any(t_top <= char_top <= t_bot for t_top, t_bot in table_y_ranges):
            continue  # This line's content is already captured in a TableBlock

        # Vertical gap from the bottom of the previous line.
        # y0 decreases as we move down the page (bottom-left origin).
        gap_above = (prev_y0 - line.chars[0].y0) if prev_y0 is not None else HEADER_GAP_THRESHOLD + 1
        prev_y0 = line.chars[0].y0

        if _is_header_line(line, median_size, gap_above):
            flush_paragraph()
            blocks.append(TextBlock(
                block_type=BlockType.HEADER,
                text=text,
                page_number=raw.page_number,
                font_size=line.avg_font_size,
                is_bold=line.is_bold,
            ))
        else:
            current_paragraph_lines.append(text)

    flush_paragraph()
    return blocks


# ---------------------------------------------------------------------------
# OCR page processing
# ---------------------------------------------------------------------------

# Header heuristics for plain text (no font metadata)
_RE_NUMBERED_HEADING = re.compile(r"^\d+(\.\d+)*\s+[A-Z]")    # "1.2 SECTION NAME"
_RE_ALLCAPS_SHORT = re.compile(r"^[A-Z][A-Z0-9\s\-&/,\.]{2,60}$")  # "RATE SCHEDULE"
_RE_ENDS_WITH_COLON = re.compile(r".{5,}:$")                   # "Residential Surcharges:"
_RE_UNDERLINE_NEXT = re.compile(r"^[-=]{4,}$")                  # "----" separator lines


def _is_ocr_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) < 3:
        return False
    if _RE_NUMBERED_HEADING.match(stripped):
        return True
    if _RE_ALLCAPS_SHORT.match(stripped) and len(stripped) <= 80:
        return True
    if _RE_ENDS_WITH_COLON.match(stripped) and len(stripped) <= 80:
        return True
    return False


def _parse_ocr_page(raw: RawPage) -> list[TextBlock]:
    """Parse OCR text into header + paragraph blocks (no table detection)."""
    blocks: list[TextBlock] = []
    if not raw.ocr_text:
        return blocks

    lines = raw.ocr_text.splitlines()
    current_paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        text = " ".join(current_paragraph_lines).strip()
        if text:
            blocks.append(TextBlock(
                block_type=BlockType.PARAGRAPH,
                text=text,
                page_number=raw.page_number,
                font_size=None,
                is_bold=False,
            ))
        current_paragraph_lines.clear()

    for line in lines:
        stripped = line.strip()

        # Skip blank lines and separator lines
        if not stripped or _RE_UNDERLINE_NEXT.match(stripped):
            if current_paragraph_lines:
                flush_paragraph()
            continue

        if _is_ocr_header(stripped):
            flush_paragraph()
            blocks.append(TextBlock(
                block_type=BlockType.HEADER,
                text=stripped,
                page_number=raw.page_number,
                font_size=None,
                is_bold=False,
            ))
        else:
            current_paragraph_lines.append(stripped)

    flush_paragraph()
    return blocks


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_layout(pages: list[RawPage]) -> dict[int, list[TextBlock | TableBlock]]:
    """
    Parse layout for all pages.

    Returns a dict mapping page_number → list of Blocks in document order.

    Repeated page headers (e.g. "Invoice Number  Account Number  Page" that
    appears identically on every page) are downgraded from HEADER to PARAGRAPH
    so they don't create spurious section boundaries in the classifier.
    """
    result: dict[int, list[TextBlock | TableBlock]] = {}
    seen_headers: set[str] = set()

    for page in pages:
        if page.is_ocr:
            blocks = _parse_ocr_page(page)
        else:
            blocks = _parse_digital_page(page)

        # Downgrade repeated headers to paragraphs
        for block in blocks:
            if isinstance(block, TextBlock) and block.block_type == BlockType.HEADER:
                key = block.text.strip()
                if key in seen_headers:
                    block.block_type = BlockType.PARAGRAPH
                else:
                    seen_headers.add(key)

        result[page.page_number] = blocks

    return result
