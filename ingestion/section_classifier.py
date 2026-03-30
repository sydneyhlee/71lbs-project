"""
Section Classifier — groups blocks into sections and assigns a SectionType.

Approach:
  1. Walk all blocks across all pages in order.
  2. A HEADER block starts a new section.
  3. All subsequent non-header blocks belong to that section until the next header.
  4. Once a section's blocks are collected, classify it by scoring keyword hits
     against its title and full text content.
  5. Sections with no clear signal default to UNKNOWN.

Classification is intentionally conservative: a section needs a minimum keyword
score to be classified; otherwise it stays UNKNOWN. This prevents mislabeling
legal/boilerplate text as pricing content.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .document import Block, BlockType, Section, SectionType, TableBlock, TextBlock

# ---------------------------------------------------------------------------
# Keyword dictionaries
# Each entry: keyword_pattern → weight
# Weights are additive; highest total wins.
# ---------------------------------------------------------------------------

_PRICING_KEYWORDS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\brate\s*(table|schedule|card)?\b", re.I), 1.5),
    (re.compile(r"\bzone\s*\d*\b", re.I), 1.2),
    (re.compile(r"\bdiscount\b", re.I), 1.0),
    (re.compile(r"\bbase\s*rate\b", re.I), 1.5),
    (re.compile(r"\bnet\s*(charge|rate)\b", re.I), 1.0),
    (re.compile(r"\bminimum\s*charge\b", re.I), 1.0),
    (re.compile(r"\bweight\s*(tier|break|range|limit)\b", re.I), 1.2),
    (re.compile(r"\bper\s+pound\b", re.I), 1.0),
    (re.compile(r"\bdim(ensional)?\s*(weight|divisor|factor)\b", re.I), 1.2),
    (re.compile(r"\bground\b", re.I), 0.5),
    (re.compile(r"\bovernight\b", re.I), 0.5),
    (re.compile(r"\b2[\s-]?day\b", re.I), 0.5),
    (re.compile(r"\bpriority\s*overnight\b", re.I), 0.8),
    (re.compile(r"\bexpress\b", re.I), 0.5),
    (re.compile(r"\bpublished\s*(rate|tariff)\b", re.I), 1.0),
    (re.compile(r"\$\s*\d+\.\d{2}\b"), 0.8),                  # dollar amounts in text
    (re.compile(r"\b\d+\s*%\s*(discount|off)\b", re.I), 1.2),
]

_SURCHARGE_KEYWORDS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\bsurcharge\b", re.I), 2.0),
    (re.compile(r"\baccessorial\b", re.I), 2.0),
    (re.compile(r"\bfuel\s*(surcharge|adjustment|index)?\b", re.I), 1.5),
    (re.compile(r"\bresidential\s*(delivery|surcharge|fee)?\b", re.I), 1.5),
    (re.compile(r"\bdelivery\s*area\s*(surcharge|DAS)?\b", re.I), 1.5),
    (re.compile(r"\b(extended|remote)\s*delivery\s*area\b", re.I), 1.5),
    (re.compile(r"\badditional\s*handling\b", re.I), 1.2),
    (re.compile(r"\boversize\b", re.I), 1.0),
    (re.compile(r"\bsignature\s*(required|service)\b", re.I), 1.0),
    (re.compile(r"\baddress\s*correction\b", re.I), 1.0),
    (re.compile(r"\bsaturday\s*(delivery|pickup)\b", re.I), 1.0),
    (re.compile(r"\bpeak\s*(surcharge|season)?\b", re.I), 0.8),
    (re.compile(r"\bDAS\b"), 1.5),
    (re.compile(r"\bFSC\b"), 1.5),
    (re.compile(r"\bAHS\b"), 1.2),
    (re.compile(r"\bwaived?\b", re.I), 0.8),
    (re.compile(r"\bflat\s*(fee|rate|amount)\b", re.I), 0.8),
]

_TERMS_KEYWORDS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\bterm(s)?\s+(and\s+condition|of\s+agreement|of\s+service)\b", re.I), 2.0),
    (re.compile(r"\bgoverning\s+law\b", re.I), 2.0),
    (re.compile(r"\bindemnif(y|ication)\b", re.I), 2.0),
    (re.compile(r"\bliabilit(y|ies)\b", re.I), 1.2),
    (re.compile(r"\btermination\b", re.I), 1.0),
    (re.compile(r"\bconfidential(ity)?\b", re.I), 1.2),
    (re.compile(r"\barbitration\b", re.I), 1.5),
    (re.compile(r"\bforce\s+majeure\b", re.I), 1.5),
    (re.compile(r"\bwarrant(y|ies|ed)?\b", re.I), 0.8),
    (re.compile(r"\bintellectual\s+property\b", re.I), 1.0),
    (re.compile(r"\bnotice\s+period\b", re.I), 0.8),
    (re.compile(r"\bauto[\s-]?renew\b", re.I), 0.8),
]

_BOILERPLATE_KEYWORDS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\bdefinitions?\b", re.I), 1.5),
    (re.compile(r"\brecitals?\b", re.I), 1.5),
    (re.compile(r"\bwhereas\b", re.I), 2.0),
    (re.compile(r"\bin\s+witness\s+whereof\b", re.I), 2.0),
    (re.compile(r"\bpreamble\b", re.I), 1.5),
    (re.compile(r"\bhereinafter\b", re.I), 1.5),
    (re.compile(r"\bherein\b", re.I), 0.5),
    (re.compile(r"\bexhibit\s+[a-z]\b", re.I), 0.8),
    (re.compile(r"\bappendix\b", re.I), 0.8),
    (re.compile(r"\bschedule\s+\d+\b", re.I), 0.6),
    (re.compile(r"\bnotice\s+to\s+proceed\b", re.I), 0.8),
]

_KEYWORD_MAP: dict[SectionType, list[tuple[re.Pattern[str], float]]] = {
    SectionType.PRICING: _PRICING_KEYWORDS,
    SectionType.SURCHARGE: _SURCHARGE_KEYWORDS,
    SectionType.TERMS: _TERMS_KEYWORDS,
    SectionType.BOILERPLATE: _BOILERPLATE_KEYWORDS,
}

# Minimum total keyword score required to assign a non-UNKNOWN label.
MIN_CLASSIFICATION_SCORE = 2.0


def _score_text(text: str, keywords: list[tuple[re.Pattern[str], float]]) -> float:
    """Sum weights for all keyword patterns that match anywhere in text."""
    score = 0.0
    for pattern, weight in keywords:
        if pattern.search(text):
            score += weight
    return score


def _classify(title: str | None, content: str) -> tuple[SectionType, float]:
    """
    Score a section against all keyword dictionaries.

    Title matches are weighted 2× relative to body text matches, since
    section headers are strong signals.
    """
    scores: dict[SectionType, float] = defaultdict(float)
    combined = (title or "") + "\n" + content

    for section_type, keywords in _KEYWORD_MAP.items():
        # Body score
        scores[section_type] += _score_text(content, keywords)
        # Title bonus (2× weight)
        if title:
            scores[section_type] += _score_text(title, keywords) * 2.0

    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]

    if best_score < MIN_CLASSIFICATION_SCORE:
        return SectionType.UNKNOWN, 0.0

    # Normalize confidence: cap at 1.0 above a "strong" score of 10.
    confidence = min(best_score / 10.0, 1.0)
    return best_type, round(confidence, 3)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify_sections(
    pages_blocks: dict[int, list[Block]],
) -> list[Section]:
    """
    Walk all blocks in page order, split on headers, classify each section.

    Args:
        pages_blocks: Output of layout_parser.parse_layout() —
                      dict mapping page_number → list of Blocks.

    Returns:
        Ordered list of Section objects.
    """
    sections: list[Section] = []

    # Flatten to a single ordered sequence: (page_number, block)
    ordered: list[tuple[int, Block]] = []
    for page_num in sorted(pages_blocks.keys()):
        for block in pages_blocks[page_num]:
            ordered.append((page_num, block))

    if not ordered:
        return sections

    # Seed the first section (catches any content before the first header)
    current_title: str | None = None
    current_blocks: list[Block] = []
    current_page_start: int = ordered[0][0]
    current_page_end: int = ordered[0][0]

    def flush_section() -> None:
        nonlocal current_title, current_blocks, current_page_start, current_page_end
        if not current_blocks and current_title is None:
            return

        # Build full text for classification
        text_parts: list[str] = []
        for blk in current_blocks:
            if isinstance(blk, TextBlock):
                text_parts.append(blk.text)
            elif isinstance(blk, TableBlock):
                for row in blk.rows:
                    text_parts.append("  ".join(cell or "" for cell in row))

        content_text = "\n".join(text_parts)
        section_type, confidence = _classify(current_title, content_text)

        sections.append(Section(
            section_type=section_type,
            title=current_title,
            page_start=current_page_start,
            page_end=current_page_end,
            blocks=list(current_blocks),
            confidence=confidence,
        ))

        current_title = None
        current_blocks = []

    for page_num, block in ordered:
        current_page_end = page_num

        if isinstance(block, TextBlock) and block.block_type == BlockType.HEADER:
            flush_section()
            current_title = block.text
            current_page_start = page_num
        else:
            current_blocks.append(block)

    flush_section()
    return sections
