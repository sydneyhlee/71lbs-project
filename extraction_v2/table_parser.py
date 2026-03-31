"""
Deterministic table parser for FedEx and UPS contract pricing tables.

Handles:
- pdfplumber-extracted table structures (headers + rows)
- Text-based service pricing blocks
- Multi-column zone discount tables (e.g., "Zones => 2 3 4 5 6 7-8 9-10")
- Weight tier breakdowns (e.g., "1.0 - 10.0 lb(s) 57%")
- "All Zones" and "All Applicable Weights" shorthand
- Surcharge modification tables
- Earned discount tier tables (including multi-line cells from pdfplumber)
- DIM divisor specifications
- Money-Back Guarantee and other special provisions
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ZoneDiscount:
    """A discount for a specific zone or zone range."""
    zone: str
    discount_pct: float


@dataclass
class WeightTierDiscount:
    """Discount applied to a specific weight range with per-zone discounts."""
    weight_range: str
    zone_discounts: List[ZoneDiscount]


@dataclass
class ServicePricing:
    """Parsed pricing for a single service type."""
    service_name: str
    zones: List[str]
    weight_tiers: List[WeightTierDiscount]
    is_all_zones: bool = False
    source_page: Optional[int] = None


@dataclass
class SurchargeModification:
    """A surcharge with its modification percentage."""
    name: str
    application: str
    applicable_zones: str
    modification: str
    source_page: Optional[int] = None


@dataclass
class EarnedDiscountTier:
    """An earned discount tier with revenue threshold."""
    services: List[str]
    grace_discount_pct: Optional[float]
    tiers: List[Dict[str, Any]]
    program_number: Optional[int] = None
    grace_period_weeks: Optional[int] = None


@dataclass
class DIMSpec:
    """Dimensional weight divisor specification."""
    name: str
    divisor: float
    application: str
    source_page: Optional[int] = None


@dataclass
class SpecialProvision:
    """Money-Back Guarantee, volume terms, etc."""
    name: str
    value: str
    source_page: Optional[int] = None


# ---------------------------------------------------------------------------
# pdfplumber table-based extraction (primary approach)
# ---------------------------------------------------------------------------

_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _is_zone_table(headers: List[str]) -> bool:
    """Check if table headers indicate a Zones => pricing table (FedEx style)."""
    return len(headers) >= 2 and headers[0].strip().lower().startswith("zones")


def _is_ups_weight_zones_table(headers: List[str]) -> bool:
    """Check if headers match UPS Weight/Zones table format."""
    if len(headers) < 2:
        return False
    h0 = headers[0].replace("\n", " ").strip().lower()
    h1 = headers[1].replace("\n", " ").strip().lower()
    return ("weight" in h0 and ("zones" in h1 or h1 == ""))


def _is_surcharge_table(headers: List[str]) -> bool:
    """Check if headers match surcharge modification layout."""
    h = " ".join(h.lower() for h in headers)
    return "name of surcharge" in h or ("surcharge" in h and "modification" in h)


def _is_earned_discount_table(headers: List[str]) -> bool:
    """Check if headers match earned discount layout."""
    h = " ".join(h.lower() for h in headers)
    return "grace discount" in h or ("annualized" in h and "earned" in h)


def extract_pricing_from_tables(
    tables: list,
    page_text: str,
    page_number: int,
) -> Tuple[
    List[ServicePricing],
    List[SurchargeModification],
    List[EarnedDiscountTier],
    List[DIMSpec],
    List[SpecialProvision],
]:
    """
    Extract structured pricing data from pdfplumber table objects.

    This is the primary extraction path: pdfplumber gives us clean
    table structures with headers and rows that we can parse deterministically.
    """
    service_pricings: List[ServicePricing] = []
    surcharges: List[SurchargeModification] = []
    earned_discounts: List[EarnedDiscountTier] = []
    dim_specs: List[DIMSpec] = []
    special_provisions: List[SpecialProvision] = []

    service_context = _find_service_names_in_text(page_text)

    for table in tables:
        headers = table.headers
        rows = table.rows

        if _is_surcharge_table(headers):
            surcharges.extend(
                _parse_surcharge_table(headers, rows, page_number)
            )
        elif _is_earned_discount_table(headers):
            earned_discounts.extend(
                _parse_earned_discount_table(headers, rows, page_number)
            )
        elif _is_zone_table(headers):
            sp = _parse_zone_pricing_table(
                headers, rows, page_number, service_context, page_text
            )
            if sp:
                service_pricings.append(sp)
        elif _is_ups_weight_zones_table(headers):
            sp_list = _parse_ups_weight_zones_table(
                headers, rows, page_number, service_context, page_text
            )
            service_pricings.extend(sp_list)

    special_provisions.extend(_extract_special_provisions(page_text, page_number))

    return service_pricings, surcharges, earned_discounts, dim_specs, special_provisions


def _find_service_names_in_text(text: str) -> List[Tuple[int, str]]:
    """
    Scan text for FedEx/UPS service names to provide context for zone tables.
    Returns list of (position, service_name).
    """
    results = []

    service_patterns = [
        re.compile(
            r"^(FedEx\s+(?:Priority|Standard|First)\s+Overnight(?:\s+(?:Envelope|Pak))?)\s*$",
            re.MULTILINE,
        ),
        re.compile(
            r"^(FedEx\s+2Day(?:\s+A\.M\.)?(?:\s+(?:Envelope|Pak))?)\s*$",
            re.MULTILINE,
        ),
        re.compile(
            r"^(FedEx\s+Express\s+Saver(?:\s+(?:Envelope|Pak))?)\s*$",
            re.MULTILINE,
        ),
        re.compile(
            r"^(FedEx\s+\dDay\s+Freight)\s*$",
            re.MULTILINE,
        ),
        re.compile(
            r"^(Ground\s+Domestic\s+(?:Single\s+Piece|MWT)\s*(?:\([^)]+\))?)\s*$",
            re.MULTILINE,
        ),
        re.compile(
            r"^(Home\s+Delivery\s+Domestic\s+(?:Single\s+Piece|MWT)\s*(?:\([^)]+\))?)\s*$",
            re.MULTILINE,
        ),
        re.compile(
            r"^(FedEx\s+Ground\s+Economy(?:\s+(?:by\s+(?:Ounce|Pound)|Bound\s+Printed\s+Matter))?"
            r"\s*(?:\([^)]+\))?)\s*$",
            re.MULTILINE,
        ),
        re.compile(
            r"^(UPS\s+(?:Ground|Next\s+Day\s+Air|2nd\s+Day\s+Air|3\s+Day\s+Select)"
            r"(?:\s+(?:Saver|A\.M\.)?)?(?:\s+(?:Letter|Package))?)\s*$",
            re.MULTILINE,
        ),
    ]

    for pat in service_patterns:
        for m in pat.finditer(text):
            results.append((m.start(), m.group(1).strip()))

    results.sort(key=lambda x: x[0])
    return results


def _parse_zone_pricing_table(
    headers: List[str],
    rows: List[List[str]],
    page_number: int,
    service_context: List[Tuple[int, str]],
    page_text: str,
) -> Optional[ServicePricing]:
    """Parse a Zones => pricing table into a ServicePricing object."""
    zones = [h.strip() for h in headers[1:] if h.strip()]
    is_all_zones = len(zones) == 1 and "all" in zones[0].lower()

    weight_tiers: List[WeightTierDiscount] = []

    for row in rows:
        if len(row) < 2:
            continue
        weight_label = row[0].strip() if row[0] else ""
        if not weight_label:
            continue

        zone_discounts: List[ZoneDiscount] = []
        for i, cell in enumerate(row[1:]):
            cell = (cell or "").strip()
            pct_match = _PCT_RE.search(cell)
            if pct_match:
                zone_name = zones[i] if i < len(zones) else f"zone_{i}"
                zone_discounts.append(ZoneDiscount(
                    zone=zone_name,
                    discount_pct=float(pct_match.group(1)),
                ))

        if zone_discounts:
            weight_tiers.append(WeightTierDiscount(
                weight_range=weight_label,
                zone_discounts=zone_discounts,
            ))

    if not weight_tiers:
        return None

    service_name = _infer_service_name(page_text, headers, service_context)

    return ServicePricing(
        service_name=service_name,
        zones=zones,
        weight_tiers=weight_tiers,
        is_all_zones=is_all_zones,
        source_page=page_number,
    )


def _infer_service_name(
    page_text: str,
    table_headers: List[str],
    service_context: List[Tuple[int, str]],
) -> str:
    """
    Infer which FedEx/UPS service a zone table belongs to by looking at
    the text immediately preceding the table's zone header.
    """
    zone_header_str = " ".join(table_headers)
    pos = page_text.find(zone_header_str)
    if pos < 0:
        zones_text = "Zones =>"
        for h in table_headers[1:]:
            zones_text += f" {h.strip()}"
        pos = page_text.find(zones_text)

    if pos >= 0:
        preceding = page_text[:pos].rstrip()
        lines = preceding.split("\n")
        for line in reversed(lines[-10:]):
            stripped = line.strip()
            if not stripped:
                continue
            if any(kw in stripped.lower() for kw in [
                "term ", "agreement", "version", "proposal",
                "pricing", "supersedes", "discounts and",
            ]):
                continue
            if re.match(r"^\d+$", stripped):
                continue
            if len(stripped) > 5:
                return stripped

    if service_context:
        return service_context[-1][1]

    return "Unknown Service"


def _parse_surcharge_table(
    headers: List[str],
    rows: List[List[str]],
    page_number: int,
) -> List[SurchargeModification]:
    """Parse a surcharge modifications table."""
    results = []

    for row in rows:
        if len(row) < 4:
            continue

        name = (row[0] or "").strip().replace("\n", " ")
        application = (row[1] or "").strip().replace("\n", " ")
        zones = (row[2] or "").strip().replace("\n", " ")
        modification = (row[3] or "").strip().replace("\n", " ")

        if not name or name.lower().startswith("name of"):
            continue

        if name.lower().startswith("dim"):
            continue

        results.append(SurchargeModification(
            name=name,
            application=application,
            applicable_zones=zones if zones else "All Zones",
            modification=modification,
            source_page=page_number,
        ))

    return results


def _extract_dim_from_all_tables(
    tables: list,
    page_number: int,
) -> List[DIMSpec]:
    """Check all surcharge tables for DIM rows."""
    dims = []
    for table in tables:
        if _is_surcharge_table(table.headers):
            for row in table.rows:
                if len(row) < 4:
                    continue
                name = (row[0] or "").strip().replace("\n", " ")
                if name.lower().startswith("dim"):
                    application = (row[1] or "").strip()
                    mod = (row[3] or "").strip()
                    try:
                        divisor = float(re.sub(r"[^\d.]", "", mod))
                        dims.append(DIMSpec(
                            name=name,
                            divisor=divisor,
                            application=application,
                            source_page=page_number,
                        ))
                    except (ValueError, TypeError):
                        pass
    return dims


def _parse_earned_discount_table(
    headers: List[str],
    rows: List[List[str]],
    page_number: int,
) -> List[EarnedDiscountTier]:
    """Parse earned discount tables, handling multi-line pdfplumber cells."""
    results = []

    grace_match = _PCT_RE.search(headers[0]) if headers else None
    grace_pct = float(grace_match.group(1)) if grace_match else None

    for row in rows:
        if len(row) < 3:
            continue
        services_cell = (row[0] or "").strip()
        thresholds_cell = (row[1] or "").strip()
        discounts_cell = (row[2] or "").strip()

        if services_cell.lower().startswith("service"):
            continue
        if services_cell.lower().startswith("grace discount"):
            gm = _PCT_RE.search(services_cell)
            if gm:
                grace_pct = float(gm.group(1))
            continue

        services = [s.strip() for s in services_cell.split("\n") if s.strip()]
        threshold_lines = [t.strip() for t in thresholds_cell.split("\n") if t.strip()]
        discount_lines = [d.strip() for d in discounts_cell.split("\n") if d.strip()]

        tiers = []
        for i, thresh in enumerate(threshold_lines):
            disc = discount_lines[i] if i < len(discount_lines) else None
            disc_val = None
            if disc:
                dm = _PCT_RE.search(disc)
                if dm:
                    disc_val = float(dm.group(1))
            tiers.append({
                "threshold": thresh,
                "discount_pct": disc_val,
            })

        if services or tiers:
            results.append(EarnedDiscountTier(
                services=services,
                grace_discount_pct=grace_pct,
                tiers=tiers,
            ))

    return results


# ---------------------------------------------------------------------------
# UPS Weight/Zones table parsing
# ---------------------------------------------------------------------------

def _parse_ups_weight_zones_table(
    headers: List[str],
    rows: List[List[str]],
    page_number: int,
    service_context: List[Tuple[int, str]],
    page_text: str,
) -> List[ServicePricing]:
    """
    Parse UPS-style tables where cells can contain multi-line data like:
    headers: ['Weight\n(lbs)', 'Zones', '', '', ...]
    row[0]:  ['', '2', '3', '4', '5', ...]  (zone numbers)
    row[1]:  ['1-5\n6-10\n11-20', '34.00%\n36.00%\n38.00%', ...]
    """
    results = []

    zone_row = None
    data_rows = []
    for row in rows:
        first_cell = (row[0] or "").strip()
        if not first_cell and len(row) > 1:
            candidate_zones = [(r or "").strip() for r in row[1:]]
            if all(re.match(r"^\d+$", z) for z in candidate_zones if z):
                zone_row = candidate_zones
                continue
        data_rows.append(row)

    if not zone_row:
        zone_row = [h.strip() for h in headers[1:] if h.strip()]

    zones = [z for z in zone_row if z]

    service_name = _infer_ups_service_name(page_text, headers, service_context)

    for row in data_rows:
        first_cell = (row[0] or "").strip()
        if not first_cell:
            continue

        weight_lines = first_cell.split("\n")
        pct_columns = []
        for cell in row[1:]:
            cell_text = (cell or "").strip()
            pct_columns.append(cell_text.split("\n"))

        for wi, weight_range in enumerate(weight_lines):
            weight_range = weight_range.strip()
            if not weight_range:
                continue

            zone_discounts = []
            for zi, zone in enumerate(zones):
                if zi < len(pct_columns):
                    col_lines = pct_columns[zi]
                    pct_text = col_lines[wi].strip() if wi < len(col_lines) else ""
                    pct_match = _PCT_RE.search(pct_text)
                    if pct_match:
                        zone_discounts.append(ZoneDiscount(
                            zone=zone,
                            discount_pct=float(pct_match.group(1)),
                        ))

            if zone_discounts:
                wt = WeightTierDiscount(
                    weight_range=weight_range,
                    zone_discounts=zone_discounts,
                )

                found = False
                for sp in results:
                    if sp.service_name == service_name:
                        sp.weight_tiers.append(wt)
                        found = True
                        break
                if not found:
                    results.append(ServicePricing(
                        service_name=service_name,
                        zones=zones,
                        weight_tiers=[wt],
                        is_all_zones=False,
                        source_page=page_number,
                    ))

    return results


def _infer_ups_service_name(
    page_text: str,
    table_headers: List[str],
    service_context: List[Tuple[int, str]],
) -> str:
    """Infer UPS service name from context near the table."""
    ups_service_pattern = re.compile(
        r"(UPS[^\n]*?(?:Commercial|Residential)\s*Package[^\n]*?)"
        r"(?:Incentives|Rates)",
        re.IGNORECASE,
    )
    m = ups_service_pattern.search(page_text)
    if m:
        name = m.group(1).strip()
        name = re.sub(r"\s*-\s*Prepaid.*$", "", name).strip()
        return name

    ups_line_pattern = re.compile(
        r"(UPS\s*(?:®|™)?\s*(?:Ground|SurePost)[^\n]*?)"
        r"(?:-\s*(?:Commercial|Residential)|Incentives|Rates)",
        re.IGNORECASE,
    )
    m = ups_line_pattern.search(page_text)
    if m:
        return m.group(1).strip()

    return "UPS Service"


# ---------------------------------------------------------------------------
# UPS text-based incentive parsing
# ---------------------------------------------------------------------------

_UPS_INCENTIVE_PATTERN = re.compile(
    r"(UPS[^\n]*?)-\s*Incentives?\s*Off\s*Effective\s*Rates\s*-?\s*(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)

_UPS_DIM_PATTERN = re.compile(
    r"Custom\s*Dimensional\s*Weight\s*Divisor\s*[:\s]*(\d+)",
    re.IGNORECASE,
)

_UPS_CUBIC_THRESHOLD_PATTERN = re.compile(
    r"Custom\s*Cubic\s*Inch\s*Threshold\s*[:\s]*(\d+)",
    re.IGNORECASE,
)


def extract_ups_text_incentives(
    text: str,
    page_number: int,
) -> Tuple[List[SurchargeModification], List[DIMSpec]]:
    """
    Extract UPS text-based incentives like:
    'UPS Next Day Air™ Early - Fuel Surcharge - Incentives Off Effective Rates - 20.00%'
    and DIM divisors like 'Custom Dimensional Weight Divisor: 194'
    """
    surcharges = []
    dims = []

    for m in _UPS_INCENTIVE_PATTERN.finditer(text):
        full_name = m.group(1).strip()
        pct = float(m.group(2))

        parts = full_name.split("-")
        service = parts[0].strip() if parts else full_name
        surcharge_type = parts[-1].strip() if len(parts) > 1 else "General Incentive"

        service = re.sub(r"[™®]", "", service).strip()
        surcharge_type = re.sub(r"[™®]", "", surcharge_type).strip()

        surcharges.append(SurchargeModification(
            name=f"{service} - {surcharge_type}",
            application=service,
            applicable_zones="All Zones",
            modification=f"- {pct}%",
            source_page=page_number,
        ))

    for m in _UPS_DIM_PATTERN.finditer(text):
        divisor = float(m.group(1))
        context_start = max(0, m.start() - 300)
        context = text[context_start:m.start()].strip()

        service = "UPS Service"
        ups_dim_svc = re.findall(
            r"(UPS[^\n]*?-\s*DimensionalWeight)",
            context, re.IGNORECASE,
        )
        if ups_dim_svc:
            raw = ups_dim_svc[-1]
            raw = re.sub(r"[™®\u2122\u00ae]", "", raw).strip()
            raw = re.sub(r"\s*-?\s*DimensionalWeight\s*$", "", raw, flags=re.IGNORECASE).strip()
            service = raw if raw else "UPS Service"
        else:
            ups_svc = re.findall(r"(UPS\s*[^\n]{3,40}?)(?:\n|$)", context)
            if ups_svc:
                raw = re.sub(r"[™®\u2122\u00ae]", "", ups_svc[-1]).strip()
                service = raw[:60] if raw else "UPS Service"

        dims.append(DIMSpec(
            name=f"DIM Divisor ({service})",
            divisor=divisor,
            application=service,
            source_page=page_number,
        ))

    for m in _UPS_CUBIC_THRESHOLD_PATTERN.finditer(text):
        threshold = float(m.group(1))
        context_start = max(0, m.start() - 200)
        context = text[context_start:m.start()].strip()

        service = "UPS Service"
        ups_svc = re.findall(r"(UPS[^\n]*?)(?:\n|$)", context)
        if ups_svc:
            service = re.sub(r"[™®]", "", ups_svc[-1]).strip()

        dims.append(DIMSpec(
            name=f"Cubic Inch Threshold ({service})",
            divisor=threshold,
            application=service,
            source_page=page_number,
        ))

    return surcharges, dims


# ---------------------------------------------------------------------------
# Text-based extraction (fallback for text without tables)
# ---------------------------------------------------------------------------

_ZONE_HEADER_PATTERN = re.compile(r"Zones?\s*=>\s*(.*)", re.IGNORECASE)
_ALL_ZONES_PATTERN = re.compile(r"All\s+Zones", re.IGNORECASE)

_WEIGHT_PATTERN = re.compile(
    r"((?:[\d.]+\s*-\s*[\d.]+\s*(?:lb|oz)\(?s?\)?)"
    r"|All\s+Applicable\s+Weights"
    r"|Envelope"
    r"|(?:[\d.]+\s*\+\s*(?:lb|oz)\(?s?\)?))",
    re.IGNORECASE,
)


def extract_service_pricing_from_text(
    text: str,
    page_number: Optional[int] = None,
) -> List[ServicePricing]:
    """
    Fallback: extract pricing from raw text when pdfplumber tables
    aren't available (e.g., OCR output).
    """
    results = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        service_name = None
        if re.match(r"^(FedEx|Ground Domestic|Home Delivery|UPS)\s+", line, re.IGNORECASE):
            if not any(skip in line.lower() for skip in [
                "the following", "pricing", "supersedes", "accounts",
                "discounts and", "for services", "shipments",
                "fedex and", "fedex freight", "fedex corporation",
                "fedex transportation", "fedex credit",
                "fedex money", "fedex service guide",
            ]):
                service_name = line

        if not service_name:
            i += 1
            continue

        i += 1
        zones = []
        is_all_zones = False
        weight_tiers = []

        while i < len(lines):
            next_line = lines[i].strip()
            if not next_line:
                i += 1
                continue

            zone_match = _ZONE_HEADER_PATTERN.search(next_line)
            if zone_match:
                zone_text = zone_match.group(1).strip()
                if _ALL_ZONES_PATTERN.search(zone_text):
                    zones = ["All Zones"]
                    is_all_zones = True
                else:
                    zones = re.split(r"\s+", zone_text)
                i += 1
                continue

            weight_match = _WEIGHT_PATTERN.match(next_line)
            if weight_match:
                weight_range = weight_match.group(0).strip()
                remainder = next_line[weight_match.end():].strip()
                pcts = _PCT_RE.findall(remainder)
                if not pcts:
                    pcts = _PCT_RE.findall(next_line)

                if pcts:
                    zone_discounts = []
                    for j, pct in enumerate(pcts):
                        zone_name = zones[j] if j < len(zones) else ("All Zones" if is_all_zones else f"zone_{j}")
                        zone_discounts.append(ZoneDiscount(
                            zone=zone_name,
                            discount_pct=float(pct),
                        ))
                    weight_tiers.append(WeightTierDiscount(
                        weight_range=weight_range,
                        zone_discounts=zone_discounts,
                    ))
                i += 1
                continue

            if re.match(r"^(FedEx|Ground Domestic|Home Delivery|UPS)\s+", next_line, re.IGNORECASE):
                break
            if any(kw in next_line.lower() for kw in [
                "earned discount", "term ", "united states",
                "pricing provisions", "name of surcharge",
                "express returns", "proposal", "money back",
            ]):
                break

            i += 1
            continue

        if weight_tiers:
            results.append(ServicePricing(
                service_name=service_name,
                zones=zones,
                weight_tiers=weight_tiers,
                is_all_zones=is_all_zones,
                source_page=page_number,
            ))

    return results


# ---------------------------------------------------------------------------
# Special provisions parsing
# ---------------------------------------------------------------------------

def _extract_special_provisions(text: str, page_number: int) -> List[SpecialProvision]:
    """Extract Money-Back Guarantee waivers, volume provisions, etc."""
    provisions = []

    mbg = re.search(
        r"Money\s*[-\s]?Back\s+Guarantee\.\s*(.+?)(?:\n[A-Z]|\n\n)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if mbg:
        waived = "waive" in mbg.group(1).lower()
        provisions.append(SpecialProvision(
            name="Money-Back Guarantee",
            value="Waived" if waived else mbg.group(1).strip()[:200],
            source_page=page_number,
        ))

    uiv = re.search(
        r"Unexpected\s+International\s+Volume\.\s*(.+?)(?:\n[A-Z][a-z]|\n\n)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if uiv:
        provisions.append(SpecialProvision(
            name="Unexpected International Volume",
            value=uiv.group(1).strip()[:200],
            source_page=page_number,
        ))

    payment_match = re.search(
        r"Payment\s+Terms?\.\s*Payment\s+is\s+due\s+within\s+(?:the\s+following\s+number\s+of\s+days"
        r".*?|(\d+)\s+days)",
        text, re.IGNORECASE,
    )
    if payment_match:
        days_match = re.search(r":\s*(\d+)", text[payment_match.start():payment_match.end() + 50])
        if days_match:
            provisions.append(SpecialProvision(
                name="Payment Terms",
                value=f"Net {days_match.group(1)} days",
                source_page=page_number,
            ))

    return provisions
