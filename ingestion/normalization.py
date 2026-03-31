"""
Normalization utilities for extracted shipping contract values.

Three functions used by the normalization layer:
  - normalize_percent       raw string → typed percent value + confidence
  - normalize_weight_range  raw string → {min, max, unit} + confidence
  - normalize_service_name  free-text service label → canonical snake_case token
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional, Tuple


class VendorType(str, Enum):
    FEDEX = "FEDEX"
    UPS = "UPS"
    UNKNOWN = "UNKNOWN"


# Canonical service tokens used across carriers (auditing-friendly).
SERVICE_CANONICAL: dict[str, str] = {
    "fedex ground": "fedex_ground",
    "fedex express": "fedex_express",
    "fedex home delivery": "fedex_home_delivery",
    "fedex freight": "fedex_freight",
    "ground": "ground",
    "ups ground": "ups_ground",
    "ups next day air": "ups_next_day_air",
    "ups 2nd day air": "ups_2nd_day_air",
    "ups 3 day select": "ups_3_day_select",
    "ups surepost": "ups_surepost",
}

_VENDOR_PREFIX = {
    VendorType.FEDEX: "fedex",
    VendorType.UPS: "ups",
}


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def normalize_service_name(text: str, vendor: VendorType) -> Tuple[Optional[str], float]:
    """
    Map free-text service labels to canonical snake_case tokens.
    Returns (canonical_token or None, confidence 0..1).

    Example: "FedEx Ground Multiweight Shipments (Original)" → ("fedex_ground", 0.75)
    """
    raw = _collapse_ws(text)
    if not raw:
        return None, 0.0
    key = raw.lower()
    for alias, canon in SERVICE_CANONICAL.items():
        if key == alias:
            return canon, 0.95
        if alias in key and len(alias) >= 4:
            return canon, 0.88
    if vendor == VendorType.FEDEX and re.search(r"\bground\b", key):
        return "fedex_ground", 0.75
    if vendor == VendorType.UPS and re.search(r"\bground\b", key):
        return "ups_ground", 0.75
    prefix = _VENDOR_PREFIX.get(vendor)
    if prefix and len(key) <= 64:
        slug = re.sub(r"[^a-z0-9]+", "_", key).strip("_")
        if slug:
            return f"{prefix}_{slug}" if not slug.startswith(prefix) else slug, 0.45
    slug = re.sub(r"[^a-z0-9]+", "_", key).strip("_")
    return (slug if slug else None), 0.35


_PERCENT_RE = re.compile(
    r"(?P<val>\d+(?:\.\d+)?)\s*(?:%|percent|pct\.?)\b",
    re.IGNORECASE,
)
_FRACTION_RE = re.compile(r"\b(?P<num>\d+(?:\.\d+)?)\s*/\s*(?P<den>\d+(?:\.\d+)?)\b")


def normalize_percent(text: str) -> dict[str, Any]:
    """
    Normalize percentage-like strings to a consistent structure.
    Returns: {unit, value (0-100), raw, confidence}

    Confidence reflects how certain the interpretation is:
      0.90 — explicit % or 'percent' keyword
      0.65 — plain number assumed to be percent
      0.55 — fraction converted to percent
      0.20 — could not parse
    """
    s = _collapse_ws(text)
    if not s:
        return {"unit": "unknown", "value": None, "raw": text, "confidence": 0.0}

    m = _PERCENT_RE.search(s)
    if m:
        return {"unit": "percent", "value": float(m.group("val")), "raw": s, "confidence": 0.9}

    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        v = float(s)
        if 0 <= v <= 1:
            return {"unit": "fraction", "value": v * 100.0, "raw": s, "confidence": 0.5}
        if 0 < v <= 100:
            return {"unit": "percent", "value": v, "raw": s, "confidence": 0.65}

    fm = _FRACTION_RE.search(s)
    if fm:
        num, den = float(fm.group("num")), float(fm.group("den"))
        if den:
            return {"unit": "percent", "value": round(100.0 * num / den, 6), "raw": s, "confidence": 0.55}

    return {"unit": "unknown", "value": None, "raw": s, "confidence": 0.2}


_WEIGHT_RANGE_RE = re.compile(
    r"""
    (?P<lo>\d+(?:\.\d+)?)\s*
    (?:-|–|—|to|through)\s*
    (?P<hi>\d+(?:\.\d+)?)\s*
    (?P<unit>lbs?|pounds?|kgs?|kilograms?|oz|ounces?)?
    """,
    re.IGNORECASE | re.VERBOSE,
)
_SINGLE_WEIGHT_RE = re.compile(
    r"^(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>lbs?|pounds?|kgs?|kilograms?|oz)?$",
    re.IGNORECASE,
)


def _normalize_weight_unit(u: Optional[str]) -> str:
    if not u:
        return "lb"
    u = u.lower()
    if u in ("kg", "kgs", "kilogram", "kilograms"):
        return "kg"
    if u in ("oz", "ounce", "ounces"):
        return "oz"
    return "lb"


def normalize_weight_range(text: str) -> dict[str, Any]:
    """
    Parse weight range text into {min, max, unit, confidence}.

    Example: "166 lbs" → {"min": 166.0, "max": 166.0, "unit": "lb", "confidence": 0.6}
    Example: "1-5 lbs" → {"min": 1.0,   "max": 5.0,   "unit": "lb", "confidence": 0.85}
    """
    s = _collapse_ws(text)
    if not s:
        return {"min": None, "max": None, "unit": None, "raw": text, "confidence": 0.0}

    m = _WEIGHT_RANGE_RE.search(s)
    if m:
        lo, hi = float(m.group("lo")), float(m.group("hi"))
        unit = _normalize_weight_unit(m.group("unit"))
        return {"min": lo, "max": hi, "unit": unit, "raw": s, "confidence": 0.85 if lo <= hi else 0.3}

    sm = _SINGLE_WEIGHT_RE.match(s)
    if sm:
        v = float(sm.group("val"))
        return {"min": v, "max": v, "unit": _normalize_weight_unit(sm.group("unit")), "raw": s, "confidence": 0.6}

    return {"min": None, "max": None, "unit": None, "raw": s, "confidence": 0.25}
