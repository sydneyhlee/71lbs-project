"""
LLM-based extraction layer.

Sends document chunks to an LLM and parses structured contract fields.
Falls back to a mock extractor when no API key is configured, so the
app is fully functional for development and demos.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
from app.models.schema import (
    Amendment,
    ContractExtraction,
    ContractMetadata,
    DIMRule,
    ExtractedValue,
    ServiceTerm,
    SpecialTerm,
    Surcharge,
    ev,
)
from app.pipeline.chunker import DocumentChunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an expert at analyzing shipping carrier contracts.
Extract structured data from the contract text provided.

For EVERY field you extract, provide:
- "value": the extracted value
- "confidence": a float 0.0-1.0 indicating certainty
- "source_page": page number if identifiable (integer or null)
- "source_text": a short snippet of the source text (max 120 chars)

Return valid JSON with this structure:
{
  "metadata": {
    "customer_name": {"value": "...", "confidence": 0.95, "source_page": 1, "source_text": "..."},
    "account_number": {...},
    "agreement_number": {...},
    "version_number": {...},
    "effective_date": {...},
    "term_start": {...},
    "term_end": {...},
    "payment_terms": {...},
    "carrier": {...}
  },
  "service_terms": [
    {
      "service_type": {...},
      "applicable_zones": {"value": ["2","3","4"], ...},
      "discount_percentage": {"value": 50.0, ...},
      "base_rate_adjustment": {...},
      "conditions": {...},
      "effective_date": {...}
    }
  ],
  "surcharges": [
    {
      "surcharge_name": {...},
      "application": {...},
      "applicable_zones": {...},
      "modification": {...},
      "discount_percentage": {...},
      "effective_date": {...}
    }
  ],
  "dim_rules": [
    {
      "dim_divisor": {"value": 139.0, ...},
      "applicable_services": {"value": ["FedEx Ground", "FedEx Home Delivery"], ...},
      "conditions": {...}
    }
  ],
  "special_terms": [
    {
      "term_name": {"value": "Money-Back Guarantee Waiver", ...},
      "term_value": {"value": "Waived", ...},
      "conditions": {...}
    }
  ],
  "amendments": [
    {
      "amendment_number": {...},
      "effective_date": {...},
      "supersedes_version": {...},
      "description": {...},
      "modified_service_terms": [...],
      "modified_surcharges": [...],
      "modified_dim_rules": [...],
      "modified_special_terms": [...]
    }
  ]
}

Rules:
- Use null for fields you cannot find.
- Dates should be ISO format (YYYY-MM-DD) when possible.
- For discount_percentage, use the numeric value (e.g. 50.0 for 50%).
- Only include amendments if the document contains amendment language.
- Be thorough: extract ALL service terms, surcharges, and DIM rules found.
"""


def _raw_field_to_ev(raw: Any) -> ExtractedValue:
    """Convert a raw LLM JSON field dict to an ExtractedValue."""
    if raw is None:
        return ExtractedValue()
    if isinstance(raw, dict):
        return ExtractedValue(
            value=raw.get("value"),
            confidence=float(raw.get("confidence", 0.0)),
            source_page=raw.get("source_page"),
            source_text=raw.get("source_text"),
        )
    return ExtractedValue(value=raw, confidence=0.5)


def _parse_llm_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse the LLM JSON response into schema-compatible dicts."""
    result: Dict[str, Any] = {}

    # Metadata
    meta_raw = data.get("metadata", {})
    meta_fields = {}
    for key in [
        "customer_name", "account_number", "agreement_number",
        "version_number", "effective_date", "term_start", "term_end",
        "payment_terms", "carrier",
        "offer_expiration", "external_term_reference", "applicable_services",
    ]:
        meta_fields[key] = _raw_field_to_ev(meta_raw.get(key))
    result["metadata"] = ContractMetadata(**meta_fields)

    # Service terms
    result["service_terms"] = []
    for st in data.get("service_terms", []):
        result["service_terms"].append(ServiceTerm(
            service_type=_raw_field_to_ev(st.get("service_type")),
            applicable_zones=_raw_field_to_ev(st.get("applicable_zones")),
            discount_percentage=_raw_field_to_ev(st.get("discount_percentage")),
            base_rate_adjustment=_raw_field_to_ev(st.get("base_rate_adjustment")),
            conditions=_raw_field_to_ev(st.get("conditions")),
            effective_date=_raw_field_to_ev(st.get("effective_date")),
        ))

    # Surcharges
    result["surcharges"] = []
    for sc in data.get("surcharges", []):
        result["surcharges"].append(Surcharge(
            surcharge_name=_raw_field_to_ev(sc.get("surcharge_name")),
            application=_raw_field_to_ev(sc.get("application")),
            applicable_zones=_raw_field_to_ev(sc.get("applicable_zones")),
            modification=_raw_field_to_ev(sc.get("modification")),
            discount_percentage=_raw_field_to_ev(sc.get("discount_percentage")),
            effective_date=_raw_field_to_ev(sc.get("effective_date")),
        ))

    # DIM rules
    result["dim_rules"] = []
    for dr in data.get("dim_rules", []):
        result["dim_rules"].append(DIMRule(
            dim_divisor=_raw_field_to_ev(dr.get("dim_divisor")),
            applicable_services=_raw_field_to_ev(dr.get("applicable_services")),
            conditions=_raw_field_to_ev(dr.get("conditions")),
        ))

    # Special terms
    result["special_terms"] = []
    for sp in data.get("special_terms", []):
        result["special_terms"].append(SpecialTerm(
            term_name=_raw_field_to_ev(sp.get("term_name")),
            term_value=_raw_field_to_ev(sp.get("term_value")),
            conditions=_raw_field_to_ev(sp.get("conditions")),
        ))

    # Amendments
    result["amendments"] = []
    for am in data.get("amendments", []):
        amendment = Amendment(
            amendment_number=_raw_field_to_ev(am.get("amendment_number")),
            effective_date=_raw_field_to_ev(am.get("effective_date")),
            supersedes_version=_raw_field_to_ev(am.get("supersedes_version")),
            description=_raw_field_to_ev(am.get("description")),
        )
        for mst in am.get("modified_service_terms", []):
            amendment.modified_service_terms.append(ServiceTerm(
                service_type=_raw_field_to_ev(mst.get("service_type")),
                applicable_zones=_raw_field_to_ev(mst.get("applicable_zones")),
                discount_percentage=_raw_field_to_ev(mst.get("discount_percentage")),
                base_rate_adjustment=_raw_field_to_ev(mst.get("base_rate_adjustment")),
                conditions=_raw_field_to_ev(mst.get("conditions")),
                effective_date=_raw_field_to_ev(mst.get("effective_date")),
            ))
        for msc in am.get("modified_surcharges", []):
            amendment.modified_surcharges.append(Surcharge(
                surcharge_name=_raw_field_to_ev(msc.get("surcharge_name")),
                application=_raw_field_to_ev(msc.get("application")),
                applicable_zones=_raw_field_to_ev(msc.get("applicable_zones")),
                modification=_raw_field_to_ev(msc.get("modification")),
                discount_percentage=_raw_field_to_ev(msc.get("discount_percentage")),
                effective_date=_raw_field_to_ev(msc.get("effective_date")),
            ))
        for mdr in am.get("modified_dim_rules", []):
            amendment.modified_dim_rules.append(DIMRule(
                dim_divisor=_raw_field_to_ev(mdr.get("dim_divisor")),
                applicable_services=_raw_field_to_ev(mdr.get("applicable_services")),
                conditions=_raw_field_to_ev(mdr.get("conditions")),
            ))
        for msp in am.get("modified_special_terms", []):
            amendment.modified_special_terms.append(SpecialTerm(
                term_name=_raw_field_to_ev(msp.get("term_name")),
                term_value=_raw_field_to_ev(msp.get("term_value")),
                conditions=_raw_field_to_ev(msp.get("conditions")),
            ))
        result["amendments"].append(amendment)

    return result


# ---------------------------------------------------------------------------
# LLM extraction (OpenAI-compatible APIs)
# ---------------------------------------------------------------------------

def _call_llm(chunks: List[DocumentChunk]) -> Dict[str, Any]:
    """Send chunks to any OpenAI-compatible API and parse the JSON response.

    Works with Ollama, OpenAI, Groq, LM Studio, or any compatible provider.
    """
    from openai import OpenAI

    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    combined_text = "\n\n".join(c.text for c in chunks)

    response = client.chat.completions.create(
        model=LLM_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"CONTRACT TEXT:\n\n{combined_text}"},
        ],
        temperature=0.1,
    )
    raw = response.choices[0].message.content
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Mock extraction (no API key needed)
# ---------------------------------------------------------------------------

def _mock_extract(chunks: List[DocumentChunk]) -> Dict[str, Any]:
    """Return realistic mock data for development/demo without an API key."""
    logger.warning("Using MOCK extractor (no LLM_API_KEY configured)")

    page_nums = []
    for c in chunks:
        page_nums.extend(c.page_numbers)
    first_page = page_nums[0] if page_nums else 1

    return {
        "metadata": {
            "customer_name": {"value": "Acme Shipping Corp", "confidence": 0.92, "source_page": first_page, "source_text": "Customer: Acme Shipping Corp"},
            "account_number": {"value": "1234-5678-9", "confidence": 0.88, "source_page": first_page, "source_text": "Account Number: 1234-5678-9"},
            "agreement_number": {"value": "FX-2024-00456", "confidence": 0.95, "source_page": first_page, "source_text": "Agreement No. FX-2024-00456"},
            "version_number": {"value": "3", "confidence": 0.85, "source_page": first_page, "source_text": "Version 3"},
            "effective_date": {"value": "2024-01-15", "confidence": 0.93, "source_page": first_page, "source_text": "Effective Date: January 15, 2024"},
            "term_start": {"value": "2024-01-15", "confidence": 0.90, "source_page": first_page, "source_text": "Term: January 15, 2024 through January 14, 2026"},
            "term_end": {"value": "2026-01-14", "confidence": 0.90, "source_page": first_page, "source_text": "Term: January 15, 2024 through January 14, 2026"},
            "payment_terms": {"value": "Net 15", "confidence": 0.87, "source_page": first_page, "source_text": "Payment Terms: Net 15 days"},
            "carrier": {"value": "FedEx", "confidence": 0.99, "source_page": first_page, "source_text": "FedEx Corporation"},
        },
        "service_terms": [
            {
                "service_type": {"value": "FedEx Ground", "confidence": 0.94, "source_page": 2, "source_text": "FedEx Ground Services"},
                "applicable_zones": {"value": ["2", "3", "4", "5", "6", "7", "8"], "confidence": 0.85, "source_page": 2, "source_text": "Zones 2-8"},
                "discount_percentage": {"value": 50.0, "confidence": 0.91, "source_page": 2, "source_text": "50.00% discount off published rates"},
                "base_rate_adjustment": {"value": None, "confidence": 0.0, "source_page": None, "source_text": None},
                "conditions": {"value": "Based on published list rates", "confidence": 0.80, "source_page": 2, "source_text": "applicable to published list rates"},
                "effective_date": {"value": "2024-01-15", "confidence": 0.88, "source_page": 2, "source_text": "Effective January 15, 2024"},
            },
            {
                "service_type": {"value": "FedEx Express Saver", "confidence": 0.92, "source_page": 3, "source_text": "FedEx Express Saver"},
                "applicable_zones": {"value": ["2", "3", "4", "5"], "confidence": 0.83, "source_page": 3, "source_text": "Zones 2-5"},
                "discount_percentage": {"value": 45.0, "confidence": 0.89, "source_page": 3, "source_text": "45.00% discount"},
                "base_rate_adjustment": {"value": None, "confidence": 0.0, "source_page": None, "source_text": None},
                "conditions": {"value": "Packages up to 150 lbs", "confidence": 0.75, "source_page": 3, "source_text": "for packages not exceeding 150 lbs"},
                "effective_date": {"value": "2024-01-15", "confidence": 0.88, "source_page": 3, "source_text": "Effective January 15, 2024"},
            },
            {
                "service_type": {"value": "FedEx Home Delivery", "confidence": 0.93, "source_page": 3, "source_text": "FedEx Home Delivery"},
                "applicable_zones": {"value": ["2", "3", "4", "5", "6", "7", "8"], "confidence": 0.84, "source_page": 3, "source_text": "All zones"},
                "discount_percentage": {"value": 48.0, "confidence": 0.90, "source_page": 3, "source_text": "48.00% discount off list rates"},
                "base_rate_adjustment": {"value": None, "confidence": 0.0, "source_page": None, "source_text": None},
                "conditions": {"value": "Residential deliveries only", "confidence": 0.82, "source_page": 3, "source_text": "residential delivery addresses"},
                "effective_date": {"value": "2024-01-15", "confidence": 0.88, "source_page": 3, "source_text": "Effective January 15, 2024"},
            },
        ],
        "surcharges": [
            {
                "surcharge_name": {"value": "Residential Delivery Surcharge", "confidence": 0.93, "source_page": 4, "source_text": "Residential Delivery Surcharge"},
                "application": {"value": "Per package", "confidence": 0.88, "source_page": 4, "source_text": "applied per package"},
                "applicable_zones": {"value": None, "confidence": 0.0, "source_page": None, "source_text": None},
                "modification": {"value": "Discount", "confidence": 0.85, "source_page": 4, "source_text": "discount applied"},
                "discount_percentage": {"value": 40.0, "confidence": 0.87, "source_page": 4, "source_text": "40.00% discount on surcharge"},
                "effective_date": {"value": "2024-01-15", "confidence": 0.85, "source_page": 4, "source_text": "effective with agreement"},
            },
            {
                "surcharge_name": {"value": "Fuel Surcharge", "confidence": 0.96, "source_page": 4, "source_text": "Fuel Surcharge"},
                "application": {"value": "Per shipment", "confidence": 0.84, "source_page": 4, "source_text": "applied per shipment"},
                "applicable_zones": {"value": None, "confidence": 0.0, "source_page": None, "source_text": None},
                "modification": {"value": "Standard published rates apply", "confidence": 0.78, "source_page": 4, "source_text": "standard published fuel surcharge rates"},
                "discount_percentage": {"value": None, "confidence": 0.0, "source_page": None, "source_text": None},
                "effective_date": {"value": "2024-01-15", "confidence": 0.85, "source_page": 4, "source_text": "effective with agreement"},
            },
            {
                "surcharge_name": {"value": "Additional Handling Surcharge", "confidence": 0.91, "source_page": 5, "source_text": "Additional Handling Surcharge"},
                "application": {"value": "Per package", "confidence": 0.86, "source_page": 5, "source_text": "per package basis"},
                "applicable_zones": {"value": None, "confidence": 0.0, "source_page": None, "source_text": None},
                "modification": {"value": "Discount", "confidence": 0.82, "source_page": 5, "source_text": "discount on surcharge"},
                "discount_percentage": {"value": 25.0, "confidence": 0.84, "source_page": 5, "source_text": "25.00% discount"},
                "effective_date": {"value": "2024-01-15", "confidence": 0.85, "source_page": 5, "source_text": "effective with agreement"},
            },
        ],
        "dim_rules": [
            {
                "dim_divisor": {"value": 139.0, "confidence": 0.94, "source_page": 5, "source_text": "DIM divisor of 139"},
                "applicable_services": {"value": ["FedEx Ground", "FedEx Home Delivery"], "confidence": 0.90, "source_page": 5, "source_text": "applicable to Ground and Home Delivery"},
                "conditions": {"value": "Packages over 3 cubic feet", "confidence": 0.78, "source_page": 5, "source_text": "packages exceeding 3 cubic feet"},
            },
            {
                "dim_divisor": {"value": 166.0, "confidence": 0.92, "source_page": 5, "source_text": "DIM divisor of 166"},
                "applicable_services": {"value": ["FedEx Express Saver", "FedEx 2Day", "FedEx Priority Overnight"], "confidence": 0.88, "source_page": 5, "source_text": "Express services"},
                "conditions": {"value": None, "confidence": 0.0, "source_page": None, "source_text": None},
            },
        ],
        "special_terms": [
            {
                "term_name": {"value": "Money-Back Guarantee", "confidence": 0.95, "source_page": 6, "source_text": "Money-Back Guarantee"},
                "term_value": {"value": "Waived", "confidence": 0.93, "source_page": 6, "source_text": "Customer agrees to waive the FedEx Money-Back Guarantee"},
                "conditions": {"value": "Applies to all services under this agreement", "confidence": 0.80, "source_page": 6, "source_text": "for all services"},
            },
            {
                "term_name": {"value": "Earned Discount Program", "confidence": 0.82, "source_page": 6, "source_text": "Earned Discount Program"},
                "term_value": {"value": "Eligible - Tier 2", "confidence": 0.75, "source_page": 6, "source_text": "eligible for Tier 2 earned discounts"},
                "conditions": {"value": "Based on weekly revenue threshold of $5,000", "confidence": 0.72, "source_page": 6, "source_text": "weekly revenue of $5,000 or more"},
            },
        ],
        "amendments": [
            {
                "amendment_number": {"value": "AMD-001", "confidence": 0.90, "source_page": 8, "source_text": "Amendment No. AMD-001"},
                "effective_date": {"value": "2024-07-01", "confidence": 0.92, "source_page": 8, "source_text": "Effective July 1, 2024"},
                "supersedes_version": {"value": "3", "confidence": 0.85, "source_page": 8, "source_text": "supersedes Version 3 terms"},
                "description": {"value": "Updated Ground discount and DIM divisor", "confidence": 0.80, "source_page": 8, "source_text": "modifies Ground pricing and dimensional weight"},
                "modified_service_terms": [
                    {
                        "service_type": {"value": "FedEx Ground", "confidence": 0.93, "source_page": 8, "source_text": "FedEx Ground"},
                        "applicable_zones": {"value": ["2", "3", "4", "5", "6", "7", "8"], "confidence": 0.85, "source_page": 8, "source_text": "Zones 2-8"},
                        "discount_percentage": {"value": 52.0, "confidence": 0.91, "source_page": 8, "source_text": "52.00% discount (increased from 50.00%)"},
                        "base_rate_adjustment": {"value": None, "confidence": 0.0, "source_page": None, "source_text": None},
                        "conditions": {"value": "Replaces prior Ground discount", "confidence": 0.78, "source_page": 8, "source_text": "replaces prior discount"},
                        "effective_date": {"value": "2024-07-01", "confidence": 0.92, "source_page": 8, "source_text": "effective July 1, 2024"},
                    }
                ],
                "modified_surcharges": [],
                "modified_dim_rules": [
                    {
                        "dim_divisor": {"value": 166.0, "confidence": 0.90, "source_page": 9, "source_text": "DIM divisor changed to 166"},
                        "applicable_services": {"value": ["FedEx Ground", "FedEx Home Delivery"], "confidence": 0.88, "source_page": 9, "source_text": "Ground and Home Delivery"},
                        "conditions": {"value": "Replaces prior DIM divisor of 139", "confidence": 0.82, "source_page": 9, "source_text": "replaces divisor of 139"},
                    }
                ],
                "modified_special_terms": [],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def extract_contract(
    chunks: List[DocumentChunk],
    file_name: str = "",
    file_path: str = "",
) -> ContractExtraction:
    """
    Extract structured contract data from document chunks.

    Uses configured LLM provider when available, otherwise falls back to mock data.
    """
    if not LLM_API_KEY:
        raw_data = _mock_extract(chunks)
    else:
        logger.info("Extracting with LLM (base_url=%s, model=%s)", LLM_BASE_URL, LLM_MODEL)
        try:
            raw_data = _call_llm(chunks)
        except Exception as exc:
            logger.error("LLM extraction failed: %s — falling back to mock", exc)
            raw_data = _mock_extract(chunks)

    parsed = _parse_llm_response(raw_data)

    extraction = ContractExtraction(
        file_name=file_name,
        file_path=file_path,
        **parsed,
    )

    return extraction
