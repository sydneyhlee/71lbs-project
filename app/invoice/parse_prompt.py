"""Prompt template for invoice line-item extraction."""

INVOICE_PARSE_PROMPT = """You extract structured invoice line items for carrier audit.

CRITICAL REQUIRED FIELDS PER LINE ITEM:
- ship_date
- service_code
- rated_weight_lbs

You must NEVER return a line item with ship_date=null, service_code=null, or rated_weight_lbs=null.
If a required field is not explicit on the line, do best-effort inference:
- ship_date: use shipment date; if missing, use invoice date from header.
- service_code: map service names/abbreviations to normalized snake_case code using mapping table below.
- rated_weight_lbs: use billed/rated weight if shown; else use actual weight; else infer from dimensional/charge context.
When inferred, still provide the value and keep raw_line_text with the source snippet used.

Return strict JSON only:
{
  "invoice_id": "string or null",
  "line_items": [
    {
      "id": "stable id if present, else null",
      "tracking_number": "string or empty",
      "transaction_id": "string or null",
      "ship_date": "YYYY-MM-DD",
      "actual_delivery_datetime": "YYYY-MM-DDTHH:MM:SS or null",
      "service_code": "normalized snake_case code",
      "service_group": "express|ground|home_delivery|international|null",
      "package_type": "string or null",
      "service_or_charge_type": "string",
      "origin_zip": "5-digit zip or null",
      "destination_zip": "5-digit zip or null",
      "zone": 2,
      "actual_weight_lbs": 3.5,
      "length": 11.1,
      "width": 8.1,
      "height": 6.1,
      "rated_weight_lbs": 6.0,
      "rate_per_lb": 1.23,
      "published_charge": 25.0,
      "transport_charge": 25.0,
      "earned_discount_applied": -8.0,
      "incentive_credit": -8.0,
      "net_transport_charge": 17.0,
      "fuel_surcharge_billed": 2.1,
      "residential_surcharge_billed": 5.95,
      "das_billed": 4.2,
      "ahs_billed": 0.0,
      "large_package_billed": 0.0,
      "address_correction_billed": 0.0,
      "saturday_delivery_billed": 0.0,
      "declared_value_billed": 0.0,
      "total_billed": 29.25,
      "is_residential": true,
      "carrier_exception_code": "weather|address_error|business_closed|recipient_unavailable|customs_delay|null",
      "raw_line_text": "raw invoice line snippet"
    }
  ]
}

Service name normalization (always output these normalized codes):

FedEx mappings:
- "FedEx Ground" / "FXG" / "FedEx Gnd" -> fedex_ground
- "FedEx Home Delivery" / "FedEx HD" / "Home Delivery" -> fedex_home_delivery
- "FedEx Priority Overnight" / "FPO" / "Priority Overnight" -> fedex_priority_overnight
- "FedEx First Overnight" / "FFO" -> fedex_first_overnight
- "FedEx Standard Overnight" / "FSO" / "Standard Overnight" -> fedex_standard_overnight
- "FedEx 2Day" / "F2D" / "FedEx 2-Day" -> fedex_2day
- "FedEx 2Day AM" / "F2A" -> fedex_2day_am
- "FedEx Express Saver" / "FES" / "Express Saver" -> fedex_express_saver
- "FedEx Ground Economy" / "FedEx SmartPost" / "Ground Economy" -> fedex_ground_economy
- "FedEx International Priority" / "FIP" -> fedex_international_priority
- "FedEx International Economy" / "FIE" -> fedex_international_economy

UPS mappings:
- "UPS Ground" / "UPS Gnd" / "Ground" -> ups_ground
- "UPS Next Day Air" / "NDA" / "Next Day Air" -> ups_next_day_air
- "UPS Next Day Air Early" / "NDA Early" / "Next Day Air Early A.M." -> ups_next_day_air_early
- "UPS Next Day Air Saver" / "NDA Saver" -> ups_next_day_air_saver
- "UPS 2nd Day Air" / "2DA" / "2nd Day Air" -> ups_2nd_day_air
- "UPS 2nd Day Air A.M." / "2DA AM" -> ups_2nd_day_air_am
- "UPS 3 Day Select" / "3DS" -> ups_3_day_select
- "UPS SurePost" / "UPS Ground Saver" / "SurePost" -> ups_ground_saver

Additional rules:
- Keep numeric fields numeric.
- Keep discount/credit lines negative when shown as credits.
- For FedEx, Transportation Charge is gross before discounts.
- For UPS, Published Charge is gross before discounts.
- Return only JSON, no markdown.
"""


def build_invoice_parse_prompt(raw_text: str, carrier: str) -> str:
    """Build carrier-aware invoice parsing prompt payload."""
    return (
        f"{INVOICE_PARSE_PROMPT}\n\n"
        f"Carrier hint: {carrier}\n\n"
        f"INVOICE TEXT:\n{raw_text[:24000]}"
    )

