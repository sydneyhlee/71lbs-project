from __future__ import annotations

import re
from typing import Any


WEIGHT_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-to]+\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
WEIGHT_PLUS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\+\s*lb", re.IGNORECASE)
PERCENT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
ZONE_TOKEN_RE = re.compile(r"\b([1-8])\b")


def _parse_weight(value: str) -> dict[str, float] | str | None:
    v = value.lower()
    if "all applicable weights" in v or "all weights" in v:
        return "all"
    m = WEIGHT_RANGE_RE.search(v)
    if m:
        return {"min": float(m.group(1)), "max": float(m.group(2))}
    m = WEIGHT_PLUS_RE.search(v)
    if m:
        lo = float(m.group(1))
        return {"min": lo, "max": 9999.0}
    return None


def _parse_zones(header_cells: list[str], row_cells: list[str]) -> list[int] | str:
    header_text = " ".join(header_cells).lower()
    row_text = " ".join(row_cells).lower()
    text = f"{header_text} {row_text}"
    if "all zones" in text:
        return "all"
    zones = {int(z) for z in ZONE_TOKEN_RE.findall(header_text)}
    if not zones:
        zones = {int(z) for z in ZONE_TOKEN_RE.findall(row_text)}
    return sorted(zones) if zones else "all"


def _parse_discount(cell: str) -> float | None:
    m = PERCENT_RE.search(cell)
    if m:
        return float(m.group(1))
    return None


def _parse_money(cell: str) -> float | None:
    cleaned = cell.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_table(service_name: str, table: list[list[Any]]) -> list[dict[str, Any]]:
    if not table:
        return []
    header = [str(c or "").strip() for c in table[0]]
    rows: list[dict[str, Any]] = []

    for raw_row in table[1:]:
        row = [str(c or "").strip() for c in raw_row]
        row_text = " ".join(row)
        weight = _parse_weight(row_text)
        zones = _parse_zones(header, row)
        discount = None
        net_rate = None

        for c in row:
            if discount is None:
                discount = _parse_discount(c)
            if net_rate is None:
                net_rate = _parse_money(c)

        if weight is None:
            weight = _parse_weight(" ".join(row))
        if discount is None:
            discount = _parse_discount(" ".join(row))
        if weight is None and discount is None and net_rate is None:
            continue

        rows.append(
            {
                "service": service_name,
                "zones": zones,
                "weight_range": weight if weight is not None else "all",
                "discount": discount,
                "net_rate": net_rate,
            }
        )
    return rows


def extract_tables(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for section in sections:
        for t in section.get("tables", []):
            content = t.get("content") or []
            normalized_rows.extend(_normalize_table(section["service_name"], content))
    return normalized_rows
