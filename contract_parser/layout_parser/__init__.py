from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any


def _is_header(text: str, font_size: float | None, median_size: float) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.isupper() and len(stripped) > 4:
        return True
    if font_size is not None and font_size >= (median_size * 1.25):
        return True
    patterns = ("fedex", "ups", "ground", "2day", "next day", "surcharge", "earned discount")
    lowered = stripped.lower()
    return any(p in lowered for p in patterns)


def parse_layout(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    font_sizes: list[float] = []
    for page in pages:
        for b in page.get("blocks", []):
            if b.get("type") == "text" and b.get("font_size") is not None:
                font_sizes.append(float(b["font_size"]))
    med = median(font_sizes) if font_sizes else 10.0

    layout: list[dict[str, Any]] = []
    for page in pages:
        grouped = defaultdict(list)
        headers = []
        for b in page.get("blocks", []):
            if b.get("type") == "table":
                grouped["tables"].append(b)
                continue
            if b.get("type") != "text":
                continue
            txt = b.get("content", "")
            if _is_header(txt, b.get("font_size"), med):
                headers.append(txt)
            if txt.strip().startswith("*") or "note" in txt.lower():
                grouped["footnotes"].append(b)
            else:
                grouped["text"].append(b)

        layout.append(
            {
                "page": page["page"],
                "headers": headers,
                "tables": grouped["tables"],
                "footnotes": grouped["footnotes"],
                "text_blocks": grouped["text"],
            }
        )
    return layout
