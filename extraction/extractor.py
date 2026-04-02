"""
Refined extraction engine (v2) — Aidan & Aria Extraction Team.

Strategy:
1. Deterministic extraction for tabular pricing data using pdfplumber tables
   (zones, weight tiers, discounts, surcharges, DIM divisors, earned discounts).
2. Deterministic metadata extraction (customer, account, dates, carrier).
3. Text-based fallback for pages without structured tables.
4. LLM fallback only for messy/ambiguous text that resists pattern matching.

Accepts ParsedDocument from the Parsing Team and produces a
ContractExtraction matching the canonical schema for the Validation Team.
"""

from __future__ import annotations

import json
import logging
import re
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
from app.pipeline.pdf_parser import ParsedDocument
from app.pipeline.chunker import chunk_document

from extraction.table_parser import (
    extract_pricing_from_tables,
    extract_service_pricing_from_text,
    extract_ups_text_incentives,
    _extract_dim_from_all_tables,
    _extract_special_provisions,
    ServicePricing,
    SurchargeModification,
    EarnedDiscountTier,
    DIMSpec,
    SpecialProvision,
)
from extraction.metadata_extractor import extract_metadata

logger = logging.getLogger(__name__)

_INVOICE_SERVICE_TOTAL_PATTERN = re.compile(
    r"([A-Za-z][A-Za-z &/\-]{3,80}?)\s+Total Charges\s+USD\s+\$?([\d,]+(?:\.\d{2})?)",
    re.IGNORECASE,
)
_TOTAL_INVOICE_PATTERN = re.compile(
    r"TOTAL\s+THIS\s+INVOICE\s+USD\s+\$?([\d,]+(?:\.\d{2})?)",
    re.IGNORECASE,
)
_FUEL_SURCHARGE_PATTERN = re.compile(
    r"Fuel Surcharge\s+([\d,]+(?:\.\d{2})?)",
    re.IGNORECASE,
)
_UPS_TRANSPORT_CHARGE_PATTERN = re.compile(
    r"Transportation Charges\s+([\d,]+(?:\.\d{2})?)",
    re.IGNORECASE,
)
_INVOICE_NUMBER_PATTERN = re.compile(
    r"Invoice Number\s+([A-Z0-9\-]+)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Deterministic → Schema conversion
# ---------------------------------------------------------------------------

def _service_pricing_to_terms(sp: ServicePricing) -> List[ServiceTerm]:
    """Convert a deterministically parsed ServicePricing to ServiceTerm objects."""
    terms = []

    for wt in sp.weight_tiers:
        for zd in wt.zone_discounts:
            terms.append(ServiceTerm(
                service_type=ev(
                    value=sp.service_name,
                    confidence=0.90,
                    source_page=sp.source_page,
                    source_text=sp.service_name,
                ),
                applicable_zones=ev(
                    value=[zd.zone] if not sp.is_all_zones else ["All Zones"],
                    confidence=0.90,
                    source_page=sp.source_page,
                    source_text=zd.zone,
                ),
                discount_percentage=ev(
                    value=zd.discount_pct,
                    confidence=0.92,
                    source_page=sp.source_page,
                    source_text=f"{zd.discount_pct}%",
                ),
                conditions=ev(
                    value=f"Weight: {wt.weight_range}",
                    confidence=0.85,
                    source_page=sp.source_page,
                    source_text=wt.weight_range,
                ),
            ))

    return terms


def _surcharge_mod_to_schema(sm: SurchargeModification) -> Surcharge:
    """Convert a parsed SurchargeModification to the canonical Surcharge model."""
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", sm.modification)
    pct_value = float(pct_match.group(1)) if pct_match else None

    return Surcharge(
        surcharge_name=ev(
            value=sm.name, confidence=0.90,
            source_page=sm.source_page, source_text=sm.name,
        ),
        application=ev(
            value=sm.application, confidence=0.85,
            source_page=sm.source_page, source_text=sm.application,
        ),
        applicable_zones=ev(
            value=sm.applicable_zones, confidence=0.85,
            source_page=sm.source_page, source_text=sm.applicable_zones,
        ),
        modification=ev(
            value=sm.modification, confidence=0.90,
            source_page=sm.source_page, source_text=sm.modification,
        ),
        discount_percentage=ev(
            value=pct_value, confidence=0.85 if pct_value else 0.0,
            source_page=sm.source_page,
            source_text=sm.modification if pct_value else None,
        ),
    )


def _dim_spec_to_rule(ds: DIMSpec) -> DIMRule:
    """Convert a parsed DIMSpec to a DIMRule schema object."""
    condition_text = ds.name if ds.name and ds.name.lower() != "dim" else ""
    return DIMRule(
        dim_divisor=ev(
            value=ds.divisor, confidence=0.90,
            source_page=ds.source_page, source_text=ds.name,
        ),
        applicable_services=ev(
            value=ds.application, confidence=0.85,
            source_page=ds.source_page, source_text=ds.application,
        ),
        conditions=ev(
            value=condition_text or "Standard",
            confidence=0.85,
            source_page=ds.source_page,
            source_text=ds.name,
        ),
    )


def _earned_discount_to_special_terms(ed: EarnedDiscountTier) -> List[SpecialTerm]:
    """Convert earned discount tier info to SpecialTerm entries."""
    parts = []
    if ed.grace_discount_pct is not None:
        parts.append(f"Grace Discount: {ed.grace_discount_pct}%")
    if ed.grace_period_weeks is not None:
        parts.append(f"Grace Period: {ed.grace_period_weeks} weeks")
    if ed.program_number is not None:
        parts.append(f"Program #: {ed.program_number}")

    for tier in ed.tiers:
        tier_str = tier["threshold"]
        if tier.get("discount_pct") is not None:
            tier_str += f" → {tier['discount_pct']}%"
        parts.append(tier_str)

    return [SpecialTerm(
        term_name=ev(
            value="Earned Discount Program", confidence=0.85,
            source_text="Earned Discount",
        ),
        term_value=ev(
            value="; ".join(parts) if parts else "See contract",
            confidence=0.75,
            source_text="; ".join(ed.services)[:120] if ed.services else "",
        ),
        conditions=ev(
            value=f"Applicable to: {', '.join(ed.services)}" if ed.services else None,
            confidence=0.70 if ed.services else 0.0,
            source_text=", ".join(ed.services)[:120] if ed.services else None,
        ),
    )]


def _special_provision_to_schema(sp: SpecialProvision) -> SpecialTerm:
    """Convert a SpecialProvision to schema SpecialTerm."""
    return SpecialTerm(
        term_name=ev(
            value=sp.name, confidence=0.90,
            source_page=sp.source_page, source_text=sp.name,
        ),
        term_value=ev(
            value=sp.value, confidence=0.85,
            source_page=sp.source_page, source_text=sp.value[:120],
        ),
    )


def _is_likely_invoice(full_text: str) -> bool:
    """Heuristic detector for invoice-style documents."""
    head = full_text[:4000]
    return (
        ("Invoice Number" in head and "Invoice Date" in head)
        or ("Delivery Service Invoice" in head)
    )


def _extract_invoice_signals(
    full_text: str,
) -> tuple[list[ServiceTerm], list[Surcharge], list[SpecialTerm]]:
    """
    Deterministic extraction for invoice-style files.

    These docs are not pricing contracts, so this extracts stable invoice
    signals (summary charges / totals / surcharge presence) to avoid
    unnecessary LLM fallback.
    """
    service_terms: list[ServiceTerm] = []
    surcharges: list[Surcharge] = []
    special_terms: list[SpecialTerm] = []
    special_terms.append(
        SpecialTerm(
            term_name=ev(
                value="Document Type",
                confidence=0.95,
                source_page=1,
                source_text="Invoice",
            ),
            term_value=ev(
                value="Invoice",
                confidence=0.95,
                source_page=1,
                source_text="Invoice Number",
            ),
            conditions=ev(
                value="Classified by deterministic invoice markers",
                confidence=0.75,
                source_page=1,
                source_text="Invoice Number / Invoice Date",
            ),
        )
    )
    invoice_number_match = _INVOICE_NUMBER_PATTERN.search(full_text)
    if invoice_number_match:
        special_terms.append(
            SpecialTerm(
                term_name=ev(
                    value="Invoice Number",
                    confidence=0.90,
                    source_page=1,
                    source_text="Invoice Number",
                ),
                term_value=ev(
                    value=invoice_number_match.group(1),
                    confidence=0.90,
                    source_page=1,
                    source_text=invoice_number_match.group(0)[:120],
                ),
                conditions=ev(
                    value="Derived from invoice header",
                    confidence=0.70,
                    source_page=1,
                    source_text="Invoice header",
                ),
            )
        )

    seen_services = set()
    for m in _INVOICE_SERVICE_TOTAL_PATTERN.finditer(full_text):
        service_name = " ".join(m.group(1).split())
        amount = m.group(2)
        key = service_name.lower()
        if key in seen_services:
            continue
        seen_services.add(key)

        service_terms.append(
            ServiceTerm(
                service_type=ev(
                    value=service_name,
                    confidence=0.80,
                    source_page=1,
                    source_text=service_name,
                ),
                applicable_zones=ev(
                    value=["Invoice Summary"],
                    confidence=0.70,
                    source_page=1,
                    source_text="Invoice Summary",
                ),
                base_rate_adjustment=ev(
                    value=f"Total Charges USD {amount}",
                    confidence=0.80,
                    source_page=1,
                    source_text=m.group(0)[:120],
                ),
                conditions=ev(
                    value="Derived from invoice summary charge line",
                    confidence=0.70,
                    source_page=1,
                    source_text="Invoice Summary",
                ),
            )
        )
        if len(service_terms) >= 5:
            break

    total_m = _TOTAL_INVOICE_PATTERN.search(full_text)
    if total_m:
        amount = total_m.group(1)
        special_terms.append(
            SpecialTerm(
                term_name=ev(
                    value="Invoice Total",
                    confidence=0.90,
                    source_page=1,
                    source_text="TOTAL THIS INVOICE",
                ),
                term_value=ev(
                    value=f"USD {amount}",
                    confidence=0.90,
                    source_page=1,
                    source_text=total_m.group(0)[:120],
                ),
                conditions=ev(
                    value="Captured from invoice summary",
                    confidence=0.70,
                    source_page=1,
                    source_text="Invoice Summary",
                ),
            )
        )

    fuel_m = _FUEL_SURCHARGE_PATTERN.search(full_text)
    if fuel_m:
        surcharges.append(
            Surcharge(
                surcharge_name=ev(
                    value="Fuel Surcharge",
                    confidence=0.80,
                    source_page=1,
                    source_text="Fuel Surcharge",
                ),
                application=ev(
                    value="Invoice line item",
                    confidence=0.70,
                    source_page=1,
                    source_text=fuel_m.group(0)[:120],
                ),
                modification=ev(
                    value=f"Observed amount {fuel_m.group(1)}",
                    confidence=0.70,
                    source_page=1,
                    source_text=fuel_m.group(0)[:120],
                ),
            )
        )

    # UPS invoices often expose transportation charge lines rather than service
    # summary blocks; include one deterministic signal for those documents.
    if not service_terms:
        transport_m = _UPS_TRANSPORT_CHARGE_PATTERN.search(full_text)
        if transport_m:
            amount = transport_m.group(1)
            service_terms.append(
                ServiceTerm(
                    service_type=ev(
                        value="UPS Transportation Charges",
                        confidence=0.75,
                        source_page=1,
                        source_text="Transportation Charges",
                    ),
                    applicable_zones=ev(
                        value=["Invoice"],
                        confidence=0.60,
                        source_page=1,
                        source_text="Delivery Service Invoice",
                    ),
                    base_rate_adjustment=ev(
                        value=f"Transportation Charges {amount}",
                        confidence=0.75,
                        source_page=1,
                        source_text=transport_m.group(0)[:120],
                    ),
                    conditions=ev(
                        value="Derived from UPS invoice line item",
                        confidence=0.65,
                        source_page=1,
                        source_text="Transportation Charges",
                    ),
                )
            )

    return service_terms, surcharges, special_terms


# ---------------------------------------------------------------------------
# LLM fallback for ambiguous text
# ---------------------------------------------------------------------------

_LLM_FALLBACK_PROMPT = """You are an expert at analyzing shipping carrier contracts.
The following text could not be fully parsed by deterministic rules.
Extract any additional structured data you can find.

Focus on:
- Service terms with discount percentages
- Surcharge modifications
- DIM divisor rules
- Special terms (e.g., money-back guarantee waivers)
- Amendment details

For EVERY field, provide: "value", "confidence" (0.0-1.0), "source_page" (int or null), "source_text" (short snippet).

Return valid JSON with:
{
  "service_terms": [...],
  "surcharges": [...],
  "dim_rules": [...],
  "special_terms": [...],
  "amendments": [...]
}

Use null for fields you cannot find. Dates in ISO format. Discount as float (50.0 for 50%).
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


def _llm_fallback(text: str) -> Dict[str, Any]:
    """Call LLM for text that couldn't be parsed deterministically.

    Works with any OpenAI-compatible API: Ollama, OpenAI, Groq, LM Studio, etc.
    """
    if not LLM_API_KEY:
        logger.info("No LLM_API_KEY set — skipping LLM fallback")
        return {}

    try:
        from openai import OpenAI
        client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)

        response = client.chat.completions.create(
            model=LLM_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _LLM_FALLBACK_PROMPT},
                {"role": "user", "content": f"CONTRACT TEXT:\n\n{text[:8000]}"},
            ],
            temperature=0.1,
        )
        raw = response.choices[0].message.content
        return json.loads(raw)
    except Exception as exc:
        logger.error("LLM fallback failed: %s", exc)
        return {}


def _merge_llm_results(
    extraction: ContractExtraction,
    llm_data: Dict[str, Any],
) -> ContractExtraction:
    """Merge LLM-extracted data into existing extraction, avoiding duplicates."""
    existing_services = {
        st.service_type.value for st in extraction.service_terms if st.service_type.value
    }

    for st_raw in llm_data.get("service_terms", []):
        svc = _raw_field_to_ev(st_raw.get("service_type"))
        if svc.value and svc.value not in existing_services:
            extraction.service_terms.append(ServiceTerm(
                service_type=svc,
                applicable_zones=_raw_field_to_ev(st_raw.get("applicable_zones")),
                discount_percentage=_raw_field_to_ev(st_raw.get("discount_percentage")),
                base_rate_adjustment=_raw_field_to_ev(st_raw.get("base_rate_adjustment")),
                conditions=_raw_field_to_ev(st_raw.get("conditions")),
                effective_date=_raw_field_to_ev(st_raw.get("effective_date")),
            ))

    existing_surcharges = {
        s.surcharge_name.value for s in extraction.surcharges if s.surcharge_name.value
    }
    for sc_raw in llm_data.get("surcharges", []):
        name = _raw_field_to_ev(sc_raw.get("surcharge_name"))
        if name.value and name.value not in existing_surcharges:
            extraction.surcharges.append(Surcharge(
                surcharge_name=name,
                application=_raw_field_to_ev(sc_raw.get("application")),
                applicable_zones=_raw_field_to_ev(sc_raw.get("applicable_zones")),
                modification=_raw_field_to_ev(sc_raw.get("modification")),
                discount_percentage=_raw_field_to_ev(sc_raw.get("discount_percentage")),
                effective_date=_raw_field_to_ev(sc_raw.get("effective_date")),
            ))

    for dr_raw in llm_data.get("dim_rules", []):
        extraction.dim_rules.append(DIMRule(
            dim_divisor=_raw_field_to_ev(dr_raw.get("dim_divisor")),
            applicable_services=_raw_field_to_ev(dr_raw.get("applicable_services")),
            conditions=_raw_field_to_ev(dr_raw.get("conditions")),
        ))

    for sp_raw in llm_data.get("special_terms", []):
        extraction.special_terms.append(SpecialTerm(
            term_name=_raw_field_to_ev(sp_raw.get("term_name")),
            term_value=_raw_field_to_ev(sp_raw.get("term_value")),
            conditions=_raw_field_to_ev(sp_raw.get("conditions")),
        ))

    return extraction


# ---------------------------------------------------------------------------
# Amendment detection (restrictive to avoid false positives)
# ---------------------------------------------------------------------------

_AMENDMENT_DOC_PATTERN = re.compile(
    r"(?:FedEx|UPS)?\s*(?:Transportation\s+Services\s+)?Agreement\s+Amendment",
    re.IGNORECASE,
)

_SUPERSEDES_PATTERN = re.compile(
    r"(?:supersedes|replaces)\s+(?:Pricing\s+Proposal\s+)?(?:Version\s+)?(\d+)",
    re.IGNORECASE,
)


def _detect_amendment_info(full_text: str) -> Optional[Amendment]:
    """
    Detect if this document IS an amendment (not just mentions one).
    Only triggers on explicit "Agreement Amendment" title text.
    """
    m = _AMENDMENT_DOC_PATTERN.search(full_text[:2000])
    if not m:
        return None

    agreement_nums = re.findall(
        r"Agreement\s*Number\(?s?\)?\s*[:\-]?\s*([\d\-]+)",
        full_text[:2000], re.IGNORECASE,
    )

    supersedes_m = _SUPERSEDES_PATTERN.search(full_text)
    supersedes = supersedes_m.group(1) if supersedes_m else None

    from extraction.metadata_extractor import _EFFECTIVE_DATE_PATTERNS
    eff_date = None
    for dp in _EFFECTIVE_DATE_PATTERNS:
        dm = dp.search(full_text[:2000])
        if dm:
            eff_date = dm.group(1) if dm.lastindex else dm.group(0)
            break

    amend_num = agreement_nums[0] if agreement_nums else "Unknown"

    return Amendment(
        amendment_number=ev(
            value=amend_num, confidence=0.85,
            source_text=f"Agreement Amendment {amend_num}",
        ),
        effective_date=ev(
            value=eff_date, confidence=0.80 if eff_date else 0.0,
            source_text=eff_date if eff_date else None,
        ),
        supersedes_version=ev(
            value=supersedes, confidence=0.75 if supersedes else 0.0,
            source_text=f"supersedes {supersedes}" if supersedes else None,
        ),
        description=ev(
            value="FedEx Transportation Services Agreement Amendment",
            confidence=0.85,
            source_text=m.group(0)[:120],
        ),
    )


# ---------------------------------------------------------------------------
# Public interface — matches ingestion pipeline's expectations
# ---------------------------------------------------------------------------

def extract_contract_v2(
    doc: ParsedDocument,
    file_name: str = "",
    file_path: str = "",
) -> ContractExtraction:
    """
    Extract structured contract data from a ParsedDocument.

    Uses deterministic parsing first, then LLM fallback for any
    remaining ambiguous content.

    Interface:
        Input:  ParsedDocument (from Parsing Team)
        Output: ContractExtraction (for Validation Team)
    """
    full_text = doc.full_text
    page_texts = {p.page_number: p.text for p in doc.pages}

    # --- Phase 1: Deterministic metadata extraction ---
    logger.info("Phase 1: Extracting metadata deterministically")
    metadata = extract_metadata(full_text, page_texts)

    # --- Phase 2: Deterministic table extraction ---
    logger.info("Phase 2: Extracting from pdfplumber tables + text")
    all_service_terms: List[ServiceTerm] = []
    all_surcharges: List[Surcharge] = []
    all_dim_rules: List[DIMRule] = []
    all_special_terms: List[SpecialTerm] = []
    deterministic_hits = 0

    for page in doc.pages:
        if page.tables:
            sp_list, sm_list, ed_list, dim_list, prov_list = extract_pricing_from_tables(
                tables=page.tables,
                page_text=page.text,
                page_number=page.page_number,
            )

            for sp in sp_list:
                all_service_terms.extend(_service_pricing_to_terms(sp))
                deterministic_hits += 1

            for sm in sm_list:
                all_surcharges.append(_surcharge_mod_to_schema(sm))
                deterministic_hits += 1

            for ed in ed_list:
                all_special_terms.extend(_earned_discount_to_special_terms(ed))
                deterministic_hits += 1

            for ds in dim_list:
                all_dim_rules.append(_dim_spec_to_rule(ds))
                deterministic_hits += 1

            for prov in prov_list:
                all_special_terms.append(_special_provision_to_schema(prov))
                deterministic_hits += 1

            dim_from_tables = _extract_dim_from_all_tables(page.tables, page.page_number)
            for ds in dim_from_tables:
                all_dim_rules.append(_dim_spec_to_rule(ds))
                deterministic_hits += 1

        text_sp = extract_service_pricing_from_text(page.text, page.page_number)
        existing_services = {st.service_type.value for st in all_service_terms}
        for sp in text_sp:
            if sp.service_name not in existing_services:
                all_service_terms.extend(_service_pricing_to_terms(sp))
                deterministic_hits += 1

        ups_surcharges, ups_dims = extract_ups_text_incentives(
            page.text, page.page_number
        )
        for us in ups_surcharges:
            all_surcharges.append(_surcharge_mod_to_schema(us))
            deterministic_hits += 1
        for ud in ups_dims:
            all_dim_rules.append(_dim_spec_to_rule(ud))
            deterministic_hits += 1

        provisions = _extract_special_provisions(page.text, page.page_number)
        for prov in provisions:
            all_special_terms.append(_special_provision_to_schema(prov))
            deterministic_hits += 1

    # --- Phase 2b: Deterministic invoice-mode extraction for non-contract docs ---
    if deterministic_hits < 3 and _is_likely_invoice(full_text):
        logger.info("Phase 2b: Low coverage invoice detected — extracting invoice signals")
        inv_terms, inv_surcharges, inv_special_terms = _extract_invoice_signals(full_text)

        existing_service_names = {
            (st.service_type.value or "").strip().lower() for st in all_service_terms
        }
        for st in inv_terms:
            name = (st.service_type.value or "").strip().lower()
            if name and name not in existing_service_names:
                all_service_terms.append(st)
                deterministic_hits += 1

        existing_surcharge_names = {
            (sc.surcharge_name.value or "").strip().lower() for sc in all_surcharges
        }
        for sc in inv_surcharges:
            name = (sc.surcharge_name.value or "").strip().lower()
            if name and name not in existing_surcharge_names:
                all_surcharges.append(sc)
                deterministic_hits += 1

        existing_special_names = {
            (sp.term_name.value or "").strip().lower() for sp in all_special_terms
        }
        for sp in inv_special_terms:
            name = (sp.term_name.value or "").strip().lower()
            if name and name not in existing_special_names:
                all_special_terms.append(sp)
                deterministic_hits += 1

    # --- Phase 3: Amendment detection ---
    logger.info("Phase 3: Detecting amendments")
    amendments = []
    amendment_info = _detect_amendment_info(full_text)
    if amendment_info:
        amendment_info.modified_service_terms = list(all_service_terms[:])
        amendment_info.modified_surcharges = list(all_surcharges[:])
        amendment_info.modified_dim_rules = list(all_dim_rules[:])
        amendments.append(amendment_info)

    # --- Phase 4: Assemble initial extraction ---
    extraction = ContractExtraction(
        file_name=file_name,
        file_path=file_path,
        metadata=metadata,
        service_terms=all_service_terms,
        surcharges=all_surcharges,
        dim_rules=all_dim_rules,
        special_terms=all_special_terms,
        amendments=amendments,
    )

    # --- Phase 5: LLM fallback for low-coverage documents ---
    if deterministic_hits < 3 and not _is_likely_invoice(full_text):
        logger.info(
            "Phase 5: Low deterministic coverage (%d hits) — trying LLM fallback "
            "(provider: %s, model: %s)",
            deterministic_hits, LLM_BASE_URL, LLM_MODEL,
        )
        chunks = chunk_document(doc)
        combined = "\n\n".join(c.text for c in chunks)
        llm_data = _llm_fallback(combined)
        if llm_data:
            extraction = _merge_llm_results(extraction, llm_data)
    elif deterministic_hits < 3 and _is_likely_invoice(full_text):
        logger.info(
            "Phase 5: Low deterministic coverage (%d hits) but invoice-mode "
            "document detected — skipping LLM fallback",
            deterministic_hits,
        )
    else:
        logger.info(
            "Phase 5: Good deterministic coverage (%d hits) — skipping LLM",
            deterministic_hits,
        )

    # --- Phase 6: Compute stats ---
    total_fields = 0
    review_count = 0

    for field_name in [
        "customer_name", "account_number", "agreement_number",
        "version_number", "effective_date", "term_start",
        "term_end", "payment_terms", "carrier",
    ]:
        fld = getattr(extraction.metadata, field_name)
        if fld.value is not None:
            total_fields += 1
        if fld.needs_review:
            review_count += 1

    total_fields += len(extraction.service_terms)
    total_fields += len(extraction.surcharges)
    total_fields += len(extraction.dim_rules)
    total_fields += len(extraction.special_terms)

    extraction.total_fields_extracted = total_fields
    extraction.fields_needing_review = review_count

    confidences = []
    for field_name in [
        "customer_name", "account_number", "agreement_number",
        "effective_date", "carrier",
    ]:
        fld = getattr(extraction.metadata, field_name)
        if fld.confidence > 0:
            confidences.append(fld.confidence)
    for st in extraction.service_terms:
        if st.discount_percentage.confidence > 0:
            confidences.append(st.discount_percentage.confidence)
    for sc in extraction.surcharges:
        if sc.surcharge_name.confidence > 0:
            confidences.append(sc.surcharge_name.confidence)

    extraction.overall_confidence = (
        sum(confidences) / len(confidences) if confidences else 0.0
    )

    logger.info(
        "Extraction complete: %d service terms, %d surcharges, %d DIM rules, "
        "%d special terms, %d amendments (confidence=%.2f)",
        len(extraction.service_terms), len(extraction.surcharges),
        len(extraction.dim_rules), len(extraction.special_terms),
        len(extraction.amendments), extraction.overall_confidence,
    )

    return extraction
