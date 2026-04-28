"""Invoice ingestion pipeline: file -> normalized InvoiceLineItem rows."""

from __future__ import annotations

import csv
import logging
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from app.invoice.carrier_api import fetch_fedex_invoice, fetch_ups_invoice
from app.invoice.parse_prompt import build_invoice_parse_prompt
from app.models.schema import InvoiceLineItem
from app.pipeline.pdf_parser import parse_pdf

logger = logging.getLogger(__name__)


def _extract_text(file_path: Path) -> str:
    if file_path.suffix.lower() == ".csv":
        return file_path.read_text(encoding="utf-8", errors="ignore")
    doc = parse_pdf(file_path)
    return doc.full_text


_INVOICE_ID_PATTERNS = [
    re.compile(r"Invoice Number[:\s]+([A-Z0-9\-]+)", re.IGNORECASE),
    re.compile(r"Invoice #[:\s]+([A-Z0-9\-]+)", re.IGNORECASE),
    re.compile(r"Invoice[:\s]+([0-9]{4,}[A-Z0-9\-]+)", re.IGNORECASE),
]
_INVOICE_DATE_PATTERNS = [
    re.compile(r"Invoice Date[:\s]+([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})", re.IGNORECASE),
    re.compile(r"Invoice Date[:\s]+([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})", re.IGNORECASE),
]
_TRACKING_PATTERN = re.compile(r"\b(1Z[0-9A-Z]{16}|[0-9]{12,20})\b")
_AMOUNT_PATTERN = re.compile(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)")
_WEIGHT_PATTERN = re.compile(r"(?:Rated Weight|Billed Weight|Weight)\s*[: ]+\s*([0-9]+(?:\.[0-9]+)?)\s*(?:lb|lbs)?", re.IGNORECASE)
_SHIP_DATE_LINE_PATTERN = re.compile(r"Ship Date[:\s]+([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})", re.IGNORECASE)

# UPS multi-line invoice format patterns
_UPS_1Z_RE = re.compile(r"^(1Z[0-9A-Z]{16})\s+(.*)", re.IGNORECASE)
_UPS_SECTION_DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s*$")
_UPS_DECIMAL_RE = re.compile(r"-?\d{1,3}(?:,\d{3})*\.\d{2}")
_UPS_ZIP_ZONE_WEIGHT_RE = re.compile(r"\b(\d{5})\s+(\d{1,3})\s+([\d.]+)(?:\s|$)")
_UPS_PAGE_RE = re.compile(r"---\s*Page\s+(\d+)\s*---", re.IGNORECASE)

_UPS_SURCHARGE_MAP: dict[str, str] = {
    "fuel surcharge": "fuel_surcharge_billed",
    "residential delivery": "residential_surcharge_billed",
    "delivery area surcharge": "das_billed",
    "extended delivery area": "das_billed",
    "remote area surcharge": "das_billed",
    "additional handling": "ahs_billed",
    "large package": "large_package_billed",
    "address correction": "address_correction_billed",
    "saturday delivery": "saturday_delivery_billed",
    "declared value": "declared_value_billed",
}

_UPS_ADJUSTMENT_KEYWORDS = (
    "residential/commercial adjustments",
    "shipping charge corrections",
    "billing adjustments",
    "shipper number transfer",
    "c.o.d. amounts billed",
    "return services charges",
)

_UPS_META_PREFIXES = (
    "1st ref",
    "2nd ref",
    "sender",
    "receiver",
    "message codes",
    "userid",
    "customer entered",
)

_SERVICE_MAPPINGS: dict[str, tuple[str, str]] = {
    "fedex ground": ("fedex_ground", "ground"),
    "fxg": ("fedex_ground", "ground"),
    "fedex gnd": ("fedex_ground", "ground"),
    "fedex home delivery": ("fedex_home_delivery", "home_delivery"),
    "fedex hd": ("fedex_home_delivery", "home_delivery"),
    "home delivery": ("fedex_home_delivery", "home_delivery"),
    "fedex priority overnight": ("fedex_priority_overnight", "express"),
    "fpo": ("fedex_priority_overnight", "express"),
    "priority overnight": ("fedex_priority_overnight", "express"),
    "fedex first overnight": ("fedex_first_overnight", "express"),
    "ffo": ("fedex_first_overnight", "express"),
    "fedex standard overnight": ("fedex_standard_overnight", "express"),
    "fso": ("fedex_standard_overnight", "express"),
    "standard overnight": ("fedex_standard_overnight", "express"),
    "fedex 2day": ("fedex_2day", "express"),
    "f2d": ("fedex_2day", "express"),
    "fedex 2-day": ("fedex_2day", "express"),
    "fedex 2day am": ("fedex_2day_am", "express"),
    "f2a": ("fedex_2day_am", "express"),
    "fedex express saver": ("fedex_express_saver", "express"),
    "fes": ("fedex_express_saver", "express"),
    "express saver": ("fedex_express_saver", "express"),
    "fedex ground economy": ("fedex_ground_economy", "ground_economy"),
    "fedex smartpost": ("fedex_ground_economy", "ground_economy"),
    "ground economy": ("fedex_ground_economy", "ground_economy"),
    "fedex international priority": ("fedex_international_priority", "international"),
    "fip": ("fedex_international_priority", "international"),
    "fedex international economy": ("fedex_international_economy", "international"),
    "fie": ("fedex_international_economy", "international"),
    "ups ground": ("ups_ground", "ground"),
    "ups gnd": ("ups_ground", "ground"),
    "ground": ("ups_ground", "ground"),
    "ups next day air": ("ups_next_day_air", "express"),
    "nda": ("ups_next_day_air", "express"),
    "next day air": ("ups_next_day_air", "express"),
    "ups next day air early": ("ups_next_day_air_early", "express"),
    "nda early": ("ups_next_day_air_early", "express"),
    "next day air early a.m.": ("ups_next_day_air_early", "express"),
    "ups next day air saver": ("ups_next_day_air_saver", "express"),
    "nda saver": ("ups_next_day_air_saver", "express"),
    "ups 2nd day air": ("ups_2nd_day_air", "express"),
    "2da": ("ups_2nd_day_air", "express"),
    "2nd day air": ("ups_2nd_day_air", "express"),
    "ups 2nd day air a.m.": ("ups_2nd_day_air_am", "express"),
    "2da am": ("ups_2nd_day_air_am", "express"),
    "ups 3 day select": ("ups_3_day_select", "ground"),
    "3ds": ("ups_3_day_select", "ground"),
    "ups surepost": ("ups_ground_saver", "ground_saver"),
    "ups ground saver": ("ups_ground_saver", "ground_saver"),
    "surepost": ("ups_ground_saver", "ground_saver"),
}

_FEDX_COLS = {
    "tracking": ["tracking id", "tracking number"],
    "ship_date": ["ship date"],
    "delivery_date": ["delivery date"],
    "service": ["service type", "service"],
    "destination_zip": ["recipient zip", "ship to zip"],
    "zone": ["zone"],
    "rated_weight": ["billed weight", "rated weight"],
    "transport_charge": ["transportation charge"],
    "earned_discount": ["earned discount"],
    "net_charge": ["net charge", "billed charge", "total charge"],
    "fuel": ["fuel surcharge"],
    "residential": ["residential surcharge"],
}

_UPS_COLS = {
    "tracking": ["tracking number", "tracking id"],
    "ship_date": ["ship date"],
    "delivery_date": ["delivery date"],
    "service": ["service", "service type"],
    "destination_zip": ["ship to zip", "recipient zip"],
    "zone": ["zone"],
    "published_charge": ["published charge"],
    "incentive": ["incentive", "earned discount"],
    "billed_charge": ["billed charge", "net charge", "total charge"],
    "fuel": ["fuel surcharge"],
}


def _to_float(val: str) -> float | None:
    txt = str(val).replace(",", "").replace("$", "").strip()
    if not txt:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    txt = str(value or "").strip()
    if not txt:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_service_code(raw: str | None, carrier_hint: str) -> tuple[str | None, str | None]:
    text = str(raw or "").strip().lower()
    if not text:
        return None, None
    for variant, normalized in _SERVICE_MAPPINGS.items():
        if variant in text:
            return normalized
    if carrier_hint == "ups":
        return "ups_ground", "ground"
    if carrier_hint == "fedex":
        return "fedex_ground", "ground"
    return None, None


def _extract_invoice_context(raw_text: str, carrier_hint: str) -> dict[str, Any]:
    invoice_date = None
    header = raw_text[:5000]
    for pat in _INVOICE_DATE_PATTERNS:
        m = pat.search(header)
        if m:
            invoice_date = _parse_date(m.group(1))
            if invoice_date:
                break
    default_service, default_group = _normalize_service_code(header, carrier_hint)
    return {
        "invoice_date": invoice_date,
        "default_service_code": default_service,
        "default_service_group": default_group,
    }


def _extract_invoice_id(text: str) -> str | None:
    head = text[:3000]
    for pat in _INVOICE_ID_PATTERNS:
        m = pat.search(head)
        if m:
            return m.group(1)
    return None


def _parse_ups_detail_lines(
    file_path: Path,
    raw_text: str,
    invoice_id: str | None,
    fallback_date: date | None,
) -> list[InvoiceLineItem]:
    """Stateful parser for UPS multi-line invoice format.

    Each shipment opens with a 1Z tracking line (service, ZIP, zone, weight,
    published, credit, billed) and is followed by child lines for surcharges
    (Fuel Surcharge, Residential Delivery, DAS, etc.) and metadata to skip.
    Stops processing when it hits adjustment-section headers.
    """
    items: list[InvoiceLineItem] = []
    cur: dict[str, Any] = {}
    section_date = fallback_date
    in_adjustments = False
    current_page = 1

    def _flush() -> None:
        if not cur or not cur.get("tracking_number"):
            cur.clear()
            return
        tb = cur.get("total_billed")
        if tb is None:
            tb = round(
                (cur.get("net_transport_charge") or 0.0)
                + (cur.get("fuel_surcharge_billed") or 0.0)
                + (cur.get("residential_surcharge_billed") or 0.0)
                + (cur.get("das_billed") or 0.0)
                + (cur.get("ahs_billed") or 0.0)
                + (cur.get("large_package_billed") or 0.0)
                + (cur.get("address_correction_billed") or 0.0)
                + (cur.get("saturday_delivery_billed") or 0.0)
                + (cur.get("declared_value_billed") or 0.0),
                2,
            )
        svc = cur.get("service_or_charge_type") or "Unknown"
        svc_code, svc_group = _normalize_service_code(svc, "ups")
        items.append(
            InvoiceLineItem(
                id=f"{file_path.name}:{len(items) + 1}",
                invoice_id=invoice_id,
                tracking_number=cur["tracking_number"],
                transaction_id=cur["tracking_number"],
                ship_date=cur.get("ship_date") or section_date,
                service_code=svc_code,
                service_group=svc_group,
                service_or_charge_type=svc,
                destination_zip=cur.get("destination_zip"),
                zone=cur.get("zone"),
                rated_weight_lbs=cur.get("rated_weight_lbs") or cur.get("actual_weight_lbs"),
                actual_weight_lbs=cur.get("actual_weight_lbs"),
                published_charge=cur.get("published_charge"),
                incentive_credit=cur.get("incentive_credit"),
                net_transport_charge=cur.get("net_transport_charge"),
                transport_charge=cur.get("published_charge"),
                fuel_surcharge_billed=cur.get("fuel_surcharge_billed"),
                residential_surcharge_billed=cur.get("residential_surcharge_billed"),
                das_billed=cur.get("das_billed"),
                ahs_billed=cur.get("ahs_billed"),
                large_package_billed=cur.get("large_package_billed"),
                address_correction_billed=cur.get("address_correction_billed"),
                saturday_delivery_billed=cur.get("saturday_delivery_billed"),
                declared_value_billed=cur.get("declared_value_billed"),
                billed_amount=float(tb),
                total_billed=float(tb),
                source_page=current_page,
                raw_line_text=(cur.get("raw_line_text") or "")[:220],
            )
        )
        cur.clear()

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        page_m = _UPS_PAGE_RE.match(line)
        if page_m:
            current_page = int(page_m.group(1))
            continue

        line_lower = line.lower()

        if any(kw in line_lower for kw in _UPS_ADJUSTMENT_KEYWORDS):
            _flush()
            in_adjustments = True
            continue
        if in_adjustments:
            continue

        date_m = _UPS_SECTION_DATE_RE.match(line)
        if date_m:
            d = _parse_date(date_m.group(1))
            if d:
                section_date = d
            continue

        trk_m = _UPS_1Z_RE.match(line)
        if trk_m:
            _flush()
            tracking = trk_m.group(1).upper()
            rest = trk_m.group(2).strip()

            zzw_m = _UPS_ZIP_ZONE_WEIGHT_RE.search(rest)
            dest_zip = zone_int = weight = None
            svc_name = rest
            if zzw_m:
                dest_zip = zzw_m.group(1)
                zone_int = int(zzw_m.group(2))
                weight = _to_float(zzw_m.group(3))
                svc_name = rest[: zzw_m.start()].strip() or "Unknown"

            # Last 3 decimal values in rest = published, credit (neg), billed
            decimals = _UPS_DECIMAL_RE.findall(rest)
            published = credit = billed_t = None
            if len(decimals) >= 3:
                published = _to_float(decimals[-3])
                credit = _to_float(decimals[-2])
                billed_t = _to_float(decimals[-1])
            elif len(decimals) == 2:
                published = _to_float(decimals[-2])
                billed_t = _to_float(decimals[-1])
            elif decimals:
                billed_t = _to_float(decimals[-1])

            cur.update({
                "tracking_number": tracking,
                "service_or_charge_type": svc_name,
                "destination_zip": dest_zip,
                "zone": zone_int,
                "rated_weight_lbs": weight,
                "actual_weight_lbs": weight,
                "published_charge": published,
                "incentive_credit": credit,
                "net_transport_charge": billed_t,
                "ship_date": section_date,
                "raw_line_text": line[:220],
            })
            continue

        if not cur:
            continue

        if any(line_lower.startswith(p) for p in _UPS_META_PREFIXES):
            continue

        # Total line: grand total for this shipment
        if re.match(r"total\b", line_lower) and "total billed" not in line_lower:
            nums = _UPS_DECIMAL_RE.findall(line)
            if nums:
                cur["total_billed"] = _to_float(nums[-1])
            continue

        # Customer Weight line
        if "customer weight" in line_lower:
            m = re.search(r"([\d.]+)", line)
            if m:
                w = _to_float(m.group(1))
                cur["actual_weight_lbs"] = w
                if not cur.get("rated_weight_lbs"):
                    cur["rated_weight_lbs"] = w
            continue

        # Surcharge child lines
        for keyword, field in _UPS_SURCHARGE_MAP.items():
            if keyword in line_lower:
                nums = _UPS_DECIMAL_RE.findall(line)
                if nums:
                    amt = _to_float(nums[-1]) or 0.0
                    cur[field] = round((cur.get(field) or 0.0) + amt, 2)
                break

    _flush()
    return items


def _parse_deterministic_text(file_path: Path, raw_text: str) -> list[InvoiceLineItem]:
    """Deterministic parser for PDF invoice details (line-block based)."""
    invoice_id = _extract_invoice_id(raw_text)
    carrier_hint = "ups" if "ups" in raw_text[:5000].lower() else "fedex"
    context = _extract_invoice_context(raw_text, carrier_hint)
    items: list[InvoiceLineItem] = []
    current: dict[str, Any] = {}
    current_service_name: str | None = None

    def flush_current() -> None:
        if not current:
            return
        txn = str(current.get("tracking_number") or "")
        if not txn and current.get("total_billed") is None:
            current.clear()
            return
        service_name = current.get("service_or_charge_type") or current_service_name or "Unknown charge"
        service_code, service_group = _normalize_service_code(service_name, carrier_hint)
        items.append(
            InvoiceLineItem(
                id=f"{file_path.name}:{len(items)+1}",
                invoice_id=invoice_id,
                tracking_number=txn,
                transaction_id=txn or None,
                ship_date=current.get("ship_date") or context.get("invoice_date"),
                service_code=service_code or context.get("default_service_code"),
                service_group=service_group or context.get("default_service_group"),
                service_or_charge_type=str(service_name),
                destination_zip=current.get("destination_zip"),
                zone=current.get("zone"),
                rated_weight_lbs=current.get("rated_weight_lbs"),
                transport_charge=current.get("transport_charge"),
                net_transport_charge=current.get("transport_charge"),
                fuel_surcharge_billed=current.get("fuel_surcharge_billed"),
                billed_amount=float(current.get("total_billed") or current.get("transport_charge") or 0.0),
                total_billed=float(current.get("total_billed") or current.get("transport_charge") or 0.0),
                source_page=1,
                source_text=str(current.get("raw_line_text") or "")[:220],
                raw_line_text=str(current.get("raw_line_text") or "")[:220],
            )
        )
        current.clear()

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if any(
            token in line.lower()
            for token in (
                "fedex ground prepaid detail",
                "fedex home delivery",
                "priority overnight",
                "ups ground",
                "next day air",
                "2nd day air",
                "3 day select",
            )
        ):
            current_service_name = line

        ship_m = _SHIP_DATE_LINE_PATTERN.search(line)
        if ship_m:
            flush_current()
            current["ship_date"] = _parse_date(ship_m.group(1))
            current["raw_line_text"] = line
            continue

        trk_m = re.search(r"Tracking (?:ID|Number)\s+([A-Z0-9]{12,20}|1Z[0-9A-Z]{16})", line, re.IGNORECASE)
        if trk_m:
            current["tracking_number"] = trk_m.group(1)
            current["transaction_id"] = trk_m.group(1)
            current["raw_line_text"] = f"{current.get('raw_line_text', '')} {line}".strip()
            continue

        zone_m = re.search(r"\bZone\s+([0-9]{1,2})\b", line, re.IGNORECASE)
        if zone_m:
            current["zone"] = int(zone_m.group(1))

        zip_m = re.search(r"\b([0-9]{5})(?:-[0-9]{4})?\b", line)
        if zip_m and "destination_zip" not in current:
            current["destination_zip"] = zip_m.group(1)

        transport_m = re.search(r"Transportation Charge\s+\$?\s*([0-9]+(?:\.[0-9]{2})?)", line, re.IGNORECASE)
        if transport_m:
            current["transport_charge"] = _to_float(transport_m.group(1))
            current["raw_line_text"] = f"{current.get('raw_line_text', '')} {line}".strip()

        fuel_m = re.search(r"Fuel Surcharge\s+\$?\s*([0-9]+(?:\.[0-9]{2})?)", line, re.IGNORECASE)
        if fuel_m:
            current["fuel_surcharge_billed"] = _to_float(fuel_m.group(1))
            current["raw_line_text"] = f"{current.get('raw_line_text', '')} {line}".strip()

        weight_m = _WEIGHT_PATTERN.search(line)
        if weight_m:
            current["rated_weight_lbs"] = _to_float(weight_m.group(1))
            current["raw_line_text"] = f"{current.get('raw_line_text', '')} {line}".strip()
            transport = float(current.get("transport_charge") or 0.0)
            fuel = float(current.get("fuel_surcharge_billed") or 0.0)
            current["total_billed"] = round(transport + fuel, 2)
            flush_current()
            if len(items) >= 10000:
                break

    flush_current()
    return items


def _normalize_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(header).strip().lower()).strip()


def _first_value(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in row and str(row[key]).strip():
            return row[key]
    return None


def _carrier_from_headers(headers: set[str], carrier_hint: str) -> str:
    fedex_markers = {"tracking id", "service type", "transportation charge", "earned discount"}
    ups_markers = {"tracking number", "published charge", "incentive", "billed charge"}
    if len(headers & fedex_markers) >= 2:
        return "fedex"
    if len(headers & ups_markers) >= 2:
        return "ups"
    return carrier_hint


def _csv_to_items(file_path: Path, carrier_hint: str) -> list[InvoiceLineItem]:
    items: list[InvoiceLineItem] = []
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = {_normalize_header(h) for h in (reader.fieldnames or []) if h}
        if ({"service code", "ship date"} <= headers) or ({"service_code", "ship_date"} <= headers):
            for i, row in enumerate(reader, 1):
                n = {_normalize_header(k): v for k, v in row.items() if k}
                service_raw = n.get("service_code") or n.get("service code")
                service_code, service_group = _normalize_service_code(service_raw, carrier_hint)
                ship_date = _parse_date(n.get("ship_date") or n.get("ship date"))
                billed = _to_float(n.get("billed_amount") or n.get("billed amount")) or _to_float(n.get("total_billed") or n.get("total billed")) or 0.0
                tracking = str(n.get("tracking_number") or n.get("tracking number") or n.get("transaction_id") or n.get("transaction id") or "")
                items.append(
                    InvoiceLineItem(
                        id=str(n.get("id") or f"{file_path.name}:{i}"),
                        invoice_id=n.get("invoice_id") or n.get("invoice id"),
                        tracking_number=tracking,
                        transaction_id=n.get("transaction_id") or n.get("transaction id") or tracking or None,
                        ship_date=ship_date,
                        service_code=service_code or service_raw,
                        service_group=n.get("service_group") or n.get("service group") or service_group,
                        service_or_charge_type=str(n.get("service_or_charge_type") or n.get("service or charge type") or "Unknown charge"),
                        rated_weight_lbs=_to_float(n.get("rated_weight_lbs") or n.get("rated weight lbs")),
                        actual_weight_lbs=_to_float(n.get("actual_weight_lbs") or n.get("actual weight lbs")),
                        net_transport_charge=_to_float(n.get("net_transport_charge") or n.get("net transport charge")),
                        transport_charge=_to_float(n.get("transport_charge") or n.get("transport charge")),
                        published_charge=_to_float(n.get("published_charge") or n.get("published charge")),
                        fuel_surcharge_billed=_to_float(n.get("fuel_surcharge_billed") or n.get("fuel surcharge billed")),
                        billed_amount=billed,
                        total_billed=_to_float(n.get("total_billed") or n.get("total billed")) or billed,
                        raw_line_text=json.dumps(row, default=str)[:220],
                    )
                )
            return items

        csv_carrier = _carrier_from_headers(headers, carrier_hint)
        cols = _UPS_COLS if csv_carrier == "ups" else _FEDX_COLS
        for i, row in enumerate(reader, 1):
            normalized_row = {_normalize_header(k): v for k, v in row.items() if k}
            service_text = str(_first_value(normalized_row, cols.get("service", [])) or "Unknown charge")
            service_code, service_group = _normalize_service_code(service_text, csv_carrier)
            ship_date = _parse_date(_first_value(normalized_row, cols.get("ship_date", [])))
            delivery_date = _parse_date(_first_value(normalized_row, cols.get("delivery_date", [])))
            delivery_dt = datetime.combine(delivery_date, datetime.min.time()) if delivery_date else None
            rated_weight = _to_float(_first_value(normalized_row, cols.get("rated_weight", [])))
            rated_weight = rated_weight if rated_weight is not None else _to_float(normalized_row.get("rated_weight_lbs"))
            actual_weight = _to_float(
                normalized_row.get("actual_weight_lbs")
                or normalized_row.get("actual weight lbs")
                or normalized_row.get("actual weight")
            )
            length = _to_float(normalized_row.get("length"))
            width = _to_float(normalized_row.get("width"))
            height = _to_float(normalized_row.get("height"))
            rate_per_lb = _to_float(normalized_row.get("rate_per_lb") or normalized_row.get("rate per lb"))
            transport = _to_float(_first_value(normalized_row, cols.get("transport_charge", [])))
            published = _to_float(_first_value(normalized_row, cols.get("published_charge", [])))
            fuel = _to_float(_first_value(normalized_row, cols.get("fuel", [])))
            residential = _to_float(_first_value(normalized_row, cols.get("residential", [])))
            discount = _to_float(_first_value(normalized_row, cols.get("earned_discount", [])))
            incentive = _to_float(_first_value(normalized_row, cols.get("incentive", [])))
            net_charge = _to_float(_first_value(normalized_row, cols.get("net_charge", [])))
            billed = _to_float(_first_value(normalized_row, cols.get("billed_charge", [])))
            total = net_charge if net_charge is not None else billed
            if total is None:
                total = (transport or published or 0.0) + (fuel or 0.0) + (residential or 0.0)
            total = _to_float(normalized_row.get("total_billed")) if normalized_row.get("total_billed") not in (None, "") else total
            tracking = str(_first_value(normalized_row, cols.get("tracking", [])) or "")
            destination_zip_raw = _first_value(normalized_row, cols.get("destination_zip", []))
            destination_zip = str(destination_zip_raw).strip()[:5] if destination_zip_raw else None
            zone_value = _first_value(normalized_row, cols.get("zone", []))
            zone = int(float(str(zone_value))) if zone_value not in (None, "") else None

            items.append(
                InvoiceLineItem(
                    id=f"{file_path.name}:{i}",
                    tracking_number=tracking,
                    transaction_id=tracking or None,
                    ship_date=ship_date,
                    actual_delivery_datetime=delivery_dt,
                    service_code=service_code,
                    service_group=service_group,
                    service_or_charge_type=service_text,
                    destination_zip=destination_zip,
                    zone=zone,
                    actual_weight_lbs=actual_weight,
                    length=length,
                    width=width,
                    height=height,
                    rated_weight_lbs=rated_weight,
                    rate_per_lb=rate_per_lb,
                    transport_charge=transport,
                    published_charge=published,
                    earned_discount_applied=discount,
                    incentive_credit=incentive,
                    net_transport_charge=net_charge,
                    fuel_surcharge_billed=fuel,
                    residential_surcharge_billed=residential,
                    billed_amount=float(total or 0.0),
                    total_billed=float(total or 0.0),
                    raw_line_text=json.dumps(row, default=str)[:220],
                )
            )
    return items


def _line_from_dict(row: dict[str, Any], line_id: str) -> InvoiceLineItem:
    payload = dict(row)
    payload.setdefault("id", line_id)
    payload.setdefault("tracking_number", payload.get("transaction_id") or "")
    payload.setdefault("service_or_charge_type", payload.get("service_or_charge_type") or "Unknown")
    return InvoiceLineItem(**payload)


def ingest_carrier_api_invoice(carrier: str, invoice_id: str) -> list[InvoiceLineItem]:
    """
    Primary ingestion path for electronic carrier invoices.

    Expected JSON shape:
      { "line_items": [ {InvoiceLineItem-compatible fields...}, ... ] }
    """
    slug = (carrier or "").strip().lower()
    if slug == "fedex":
        payload = fetch_fedex_invoice(invoice_id)
    elif slug == "ups":
        payload = fetch_ups_invoice(invoice_id)
    else:
        raise ValueError(f"Unsupported carrier for API ingestion: {carrier}")

    rows = payload.get("line_items", [])
    if not isinstance(rows, list):
        raise RuntimeError("Carrier API payload missing list field `line_items`.")
    out: list[InvoiceLineItem] = []
    for idx, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        out.append(_line_from_dict(row, f"{invoice_id}:{idx}"))
    return out


def _call_llm(prompt: str) -> dict:
    from openai import OpenAI

    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    response = client.chat.completions.create(
        model=LLM_MODEL,
        response_format={"type": "json_object"},
        temperature=0.0,
        messages=[
            {"role": "system", "content": "Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
    )
    raw = response.choices[0].message.content or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw or "")
        return json.loads(m.group(0)) if m else {}


def _recover_line_item(
    item: InvoiceLineItem,
    context: dict[str, Any],
    carrier_hint: str,
) -> tuple[InvoiceLineItem | None, str | None]:
    if item.ship_date is None:
        item.ship_date = context.get("invoice_date")

    service_code, service_group = _normalize_service_code(
        item.service_code or item.service_or_charge_type or context.get("default_service_code"),
        carrier_hint,
    )
    if not item.service_code:
        item.service_code = service_code or context.get("default_service_code")
    if not item.service_group:
        item.service_group = service_group or context.get("default_service_group")

    if item.rated_weight_lbs is None:
        weight_match = _WEIGHT_PATTERN.search(item.raw_line_text or "")
        if weight_match:
            item.rated_weight_lbs = _to_float(weight_match.group(1))
    if item.rated_weight_lbs is None and item.actual_weight_lbs is not None:
        item.rated_weight_lbs = item.actual_weight_lbs
    if item.total_billed <= 0:
        inferred_total = (
            (item.net_transport_charge or 0.0)
            or (item.transport_charge or 0.0)
            or (item.published_charge or 0.0)
            or (item.billed_amount or 0.0)
        )
        inferred_total += item.fuel_surcharge_billed or 0.0
        inferred_total += item.residential_surcharge_billed or 0.0
        inferred_total += item.das_billed or 0.0
        item.total_billed = round(float(inferred_total), 2)
    if item.billed_amount <= 0:
        item.billed_amount = float(item.total_billed or 0.0)

    missing = []
    if item.ship_date is None:
        missing.append("ship_date")
    if not item.service_code:
        missing.append("service_code")
    if item.rated_weight_lbs is None:
        missing.append("rated_weight_lbs")
    if missing:
        reason = f"missing critical fields after recovery: {', '.join(missing)}"
        return None, reason
    return item, None


def _recover_and_filter_items(
    items: list[InvoiceLineItem],
    raw_text: str,
    carrier_hint: str,
    source_name: str,
) -> list[InvoiceLineItem]:
    context = _extract_invoice_context(raw_text, carrier_hint)
    kept: list[InvoiceLineItem] = []
    for item in items:
        recovered, drop_reason = _recover_line_item(item, context, carrier_hint)
        if recovered is not None:
            kept.append(recovered)
            continue
        logger.warning(
            "Dropped invoice line %s from %s (%s). raw_line=%s",
            item.id,
            source_name,
            drop_reason,
            (item.raw_line_text or item.source_text or "")[:180],
        )
    return kept


def validate_invoice_items(items: list[InvoiceLineItem], context: str) -> list[str]:
    """
    Post-parse required-field validation.

    Missing critical fields produce hard errors to force human review.
    """
    errors: list[str] = []
    for item in items:
        missing: list[str] = []
        if item.ship_date is None:
            missing.append("ship_date")
        if not item.service_code:
            missing.append("service_code")
        if item.rated_weight_lbs is None:
            missing.append("rated_weight_lbs")
        if missing:
            errors.append(
                f"{context} line `{item.id}` missing critical field(s): {', '.join(missing)}"
            )
    return errors


def ingest_invoice(file_path: Path, carrier: str) -> list[InvoiceLineItem]:
    """
    Parse invoice file into normalized line items.

    CSV files can be mapped directly when column names match schema fields.
    PDFs are converted to text and then parsed with LLM prompt extraction.
    """
    carrier_hint = (carrier or "fedex").strip().lower()
    if file_path.suffix.lower() == ".csv":
        csv_items = _csv_to_items(file_path, carrier_hint)
        raw_text = _extract_text(file_path)
        return _recover_and_filter_items(csv_items, raw_text, carrier_hint, file_path.name)

    raw_text = _extract_text(file_path)
    llm_items: list[InvoiceLineItem] = []
    if LLM_API_KEY:
        try:
            prompt = build_invoice_parse_prompt(raw_text, carrier_hint)
            parsed = _call_llm(prompt)
            rows = parsed.get("line_items", [])
            for idx, row in enumerate(rows, 1):
                if not isinstance(row, dict):
                    continue
                row.setdefault("id", f"{file_path.name}:{idx}")
                row.setdefault("tracking_number", row.get("transaction_id") or "")
                row.setdefault("service_or_charge_type", row.get("service_or_charge_type") or "Unknown")
                try:
                    llm_items.append(InvoiceLineItem(**row))
                except Exception as exc:
                    logger.warning("Skipping malformed LLM invoice row %s in %s: %s", idx, file_path.name, exc)
        except Exception as exc:
            logger.warning("LLM invoice parse failed for %s, falling back to deterministic parse: %s", file_path.name, exc)

    recovered_llm_items = _recover_and_filter_items(llm_items, raw_text, carrier_hint, file_path.name)
    if recovered_llm_items:
        return recovered_llm_items

    # UPS stateful multi-line parser (handles 1Z tracking + child surcharge lines)
    if carrier_hint == "ups" or "1z" in raw_text[:3000].lower():
        invoice_id = _extract_invoice_id(raw_text)
        fallback_date = _extract_invoice_context(raw_text, carrier_hint).get("invoice_date")
        ups_items = _parse_ups_detail_lines(file_path, raw_text, invoice_id, fallback_date)
        if ups_items:
            recovered_ups = _recover_and_filter_items(ups_items, raw_text, carrier_hint, file_path.name)
            if recovered_ups:
                return recovered_ups

    deterministic_items = _parse_deterministic_text(file_path, raw_text)
    return _recover_and_filter_items(deterministic_items, raw_text, carrier_hint, file_path.name)

