from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ..models import SectionType, Span
from ..extract.pdfplumber_extractor import PageTextBlock


@dataclass(frozen=True)
class SectionCandidate:
    id: str
    title: str | None
    type: SectionType
    spans: list[Span]
    blocks: list[PageTextBlock]


_HEADING_RE = re.compile(
    r"^(?P<prefix>(section|sec\.|article)\s+\d+(\.\d+)*\s*[-:])?\s*(?P<title>[A-Z][A-Z0-9 /,&()'’\-]{4,})\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _guess_section_type(title: str) -> SectionType:
    t = title.lower()
    if any(k in t for k in ("surcharge", "fuel", "accessorial")):
        return SectionType.SURCHARGES
    if any(k in t for k in ("discount", "incentive", "tier", "rebate")):
        return SectionType.DISCOUNTS
    if any(k in t for k in ("service", "terms", "liability", "claims", "guarantee", "billing", "payment")):
        return SectionType.SERVICE_TERMS
    if any(k in t for k in ("rate", "pricing", "charges", "base")):
        return SectionType.PRICING_RULES
    if "definition" in t:
        return SectionType.DEFINITIONS
    return SectionType.GENERAL


def _pick_heading_lines(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    headings: list[str] = []
    for ln in lines:
        if not ln:
            continue
        if len(ln) > 120:
            continue
        if _HEADING_RE.match(ln) and sum(ch.isalpha() for ch in ln) >= 4:
            headings.append(ln)
    return headings


def sectionize(blocks: Iterable[PageTextBlock]) -> list[SectionCandidate]:
    """
    Heuristic sectionization:
    - detect likely headings within text blocks
    - split stream into sections at heading boundaries
    """
    blocks_list = list(blocks)
    # Build boundaries (block index -> heading)
    boundaries: list[tuple[int, str]] = []
    for idx, b in enumerate(blocks_list):
        if b.block_type != "text" or not b.text.strip():
            continue
        headings = _pick_heading_lines(b.text)
        if headings:
            # choose the first heading on that page block as boundary marker
            boundaries.append((idx, headings[0]))

    if not boundaries:
        # single section fallback
        spans = [Span(page=b.page, bbox=b.bbox) for b in blocks_list]
        return [
            SectionCandidate(
                id="sec_0001",
                title=None,
                type=SectionType.UNKNOWN,
                spans=spans,
                blocks=blocks_list,
            )
        ]

    # Ensure the first boundary starts at 0
    if boundaries[0][0] != 0:
        boundaries = [(0, "Document")] + boundaries

    sections: list[SectionCandidate] = []
    for si, (start_idx, heading) in enumerate(boundaries):
        end_idx = boundaries[si + 1][0] if si + 1 < len(boundaries) else len(blocks_list)
        sec_blocks = blocks_list[start_idx:end_idx]
        title = heading.strip()
        sec_type = _guess_section_type(title) if title and title != "Document" else SectionType.GENERAL
        spans = [Span(page=b.page, bbox=b.bbox) for b in sec_blocks]
        sections.append(
            SectionCandidate(
                id=f"sec_{si+1:04d}",
                title=None if title == "Document" else title,
                type=sec_type,
                spans=spans,
                blocks=sec_blocks,
            )
        )
    return sections

