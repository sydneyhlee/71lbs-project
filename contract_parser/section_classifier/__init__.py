from __future__ import annotations

from typing import Any


def _infer_section_type(text_blob: str) -> str:
    t = text_blob.lower()
    if "earned discount" in t or ("spend" in t and "discount" in t):
        return "earned_discount"
    if "surcharge" in t or "fuel" in t:
        return "surcharge"
    if "agreement" in t or "effective" in t or "account" in t:
        return "metadata"
    return "service_pricing"


def _infer_service_name(headers: list[str], text_blob: str) -> str:
    candidates = headers + text_blob.splitlines()
    for c in candidates:
        s = c.strip()
        lowered = s.lower()
        if "fedex" in lowered or "ups" in lowered:
            return s
    return "Unknown Service"


def classify_sections(layout: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for page in layout:
        text_blob = " ".join(b.get("content", "") for b in page.get("text_blocks", []))
        section_type = _infer_section_type(text_blob)
        service_name = _infer_service_name(page.get("headers", []), text_blob)
        sections.append(
            {
                "page": page["page"],
                "section_type": section_type,
                "service_name": service_name,
                "headers": page.get("headers", []),
                "tables": page.get("tables", []),
                "footnotes": page.get("footnotes", []),
                "text_blob": text_blob,
            }
        )
    return sections
