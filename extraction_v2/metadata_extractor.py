"""
Deterministic metadata extractor for contract PDFs.

Extracts customer name, account numbers, agreement numbers,
effective dates, term start/end, carrier info, and payment terms
using regex patterns rather than LLM calls.
"""

from __future__ import annotations

import re
import logging
from typing import Optional

from app.models.schema import ContractMetadata, ExtractedValue, ev

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for FedEx and UPS contract metadata
# ---------------------------------------------------------------------------

_CUSTOMER_PATTERNS = [
    re.compile(r"Customer\s*(?:Name)?\s*[:\-]\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"(?:Prepared\s+for|Shipper)\s*[:\-]\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"This\s+FedEx.*?agreement.*?between.*?(?:FedEx.*?and|and)\s+(.+?)(?:\(|,|\n)", re.IGNORECASE),
    re.compile(r'(?:made\s*and\s*entered\s*into\s*by\s*and\s*between)\s*(.+?)(?:\(|")', re.IGNORECASE),
    re.compile(r'(?:madeandentered\s*intobyandbetween)\s*(.+?)(?:\(|")', re.IGNORECASE),
    re.compile(r"This\s+UPS.*?agreement.*?between.*?(?:UPS.*?and|and)\s+(.+?)(?:\(|,|\n)", re.IGNORECASE),
    re.compile(r"^([A-Z][A-Za-z\s&.,\-]+(?:Inc|LLC|Corp|Ltd|Co|LP)\.?)\s*$", re.MULTILINE),
]

_ACCOUNT_PATTERNS = [
    re.compile(r"Account\s*(?:Number|#|No\.?)\s*[:\-]?\s*([\d\-]+)", re.IGNORECASE),
    re.compile(r"Acct\s*(?:No\.?|#)\s*[:\-]?\s*([\d\-]+)", re.IGNORECASE),
    re.compile(r"(\d{9,12})\s*-\s*\d{3}", re.IGNORECASE),
    re.compile(r"([\dA-Z]{10,})\s+[A-Z\-]+\s+\d+\s*\n\s*[\dA-Z]+", re.IGNORECASE),
]

_AGREEMENT_PATTERNS = [
    re.compile(r"Agreement\s*(?:Number|#|No\.?)\s*[:\-]?\s*([\w\-]+)", re.IGNORECASE),
    re.compile(r"Contract\s*(?:Number|#|No\.?)\s*[:\-]?\s*([\w\-]+)", re.IGNORECASE),
    re.compile(r"(\d{9,12}-\d{3}-\d{2}-\d{2})", re.IGNORECASE),
]

_VERSION_PATTERNS = [
    re.compile(r"Version\s*(?:Number|#|No\.?)?\s*[:\-]?\s*(\d+)", re.IGNORECASE),
    re.compile(r"(?:Pricing\s+Proposal)\s+(\d+)", re.IGNORECASE),
]

_EFFECTIVE_DATE_PATTERNS = [
    re.compile(
        r"Effective\s+(?:Date|from|as\s+of)\s*[:\-]?\s*"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"effective\s+(?:on\s+)?(\d{1,2}/\d{1,2}/\d{4})",
        re.IGNORECASE,
    ),
]

_TERM_RANGE_PATTERNS = [
    re.compile(
        r"Term\s*[:\-]?\s*"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4})"
        r"\s+through\s+"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(\d{1,2}/\d{1,2}/\d{4})\s*(?:through|to|-)\s*(\d{1,2}/\d{1,2}/\d{4})",
        re.IGNORECASE,
    ),
]

_PAYMENT_PATTERNS = [
    re.compile(r"Payment\s+Terms?\s*[:\-]?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"Net\s+\d+\s+(?:days?)?", re.IGNORECASE),
]

_CARRIER_INDICATORS = {
    "FedEx": [
        re.compile(r"FedEx", re.IGNORECASE),
        re.compile(r"Federal\s+Express", re.IGNORECASE),
    ],
    "UPS": [
        re.compile(r"\bUPS\b"),
        re.compile(r"United\s+Parcel\s+Service", re.IGNORECASE),
    ],
}


def _find_first(text: str, patterns: list, page_hint: Optional[int] = None) -> Optional[ExtractedValue]:
    """Try each pattern in order, return first match as ExtractedValue."""
    for pat in patterns:
        m = pat.search(text)
        if m:
            value = m.group(1).strip() if m.lastindex else m.group(0).strip()
            snippet = text[max(0, m.start() - 20):m.end() + 20].strip()
            return ev(
                value=value,
                confidence=0.85,
                source_page=page_hint,
                source_text=snippet[:120],
            )
    return None


def _detect_carrier(text: str, page_hint: Optional[int] = None) -> ExtractedValue:
    """Detect the carrier from text content."""
    for carrier_name, patterns in _CARRIER_INDICATORS.items():
        for pat in patterns:
            m = pat.search(text)
            if m:
                snippet = text[max(0, m.start() - 20):m.end() + 20].strip()
                return ev(
                    value=carrier_name,
                    confidence=0.95,
                    source_page=page_hint,
                    source_text=snippet[:120],
                )
    return ev(value="Unknown", confidence=0.3, needs_review=True)


def extract_metadata(full_text: str, page_texts: Optional[dict] = None) -> ContractMetadata:
    """
    Extract contract metadata from full document text.

    Args:
        full_text: Complete document text
        page_texts: Optional dict mapping page_number -> page_text
                    for better source_page attribution.
    """
    first_pages = full_text[:5000]
    page_hint = 1

    customer = _find_first(first_pages, _CUSTOMER_PATTERNS, page_hint)

    if not customer:
        ups_cust = re.search(
            r'(?:madeandentered\s*intobyandbetween|between)\s*'
            r'([A-Z][A-Z\-\s]+(?:LLC|INC|CORP|LTD|CO)\.?)\s*(?:\(|")',
            first_pages, re.IGNORECASE,
        )
        if ups_cust:
            customer = ev(
                value=ups_cust.group(1).strip(),
                confidence=0.82,
                source_page=page_hint,
                source_text=first_pages[max(0, ups_cust.start() - 20):ups_cust.end() + 20][:120],
            )

    account = _find_first(full_text, _ACCOUNT_PATTERNS, page_hint)

    if not account:
        ups_acct = re.search(r"([\dA-Z]{10,11})\s+[A-Z\-]", full_text[:8000])
        if ups_acct:
            account = ev(
                value=ups_acct.group(1).strip(),
                confidence=0.70,
                source_page=page_hint,
                source_text=full_text[max(0, ups_acct.start() - 10):ups_acct.end() + 20][:120],
                needs_review=True,
            )

    agreement = _find_first(full_text, _AGREEMENT_PATTERNS, page_hint)

    if not agreement:
        ups_agree = re.search(r"(P\d{9,12}-\d{2})", full_text)
        if ups_agree:
            agreement = ev(
                value=ups_agree.group(1).strip(),
                confidence=0.80,
                source_page=page_hint,
                source_text=full_text[max(0, ups_agree.start() - 10):ups_agree.end() + 20][:120],
            )
    version = _find_first(full_text, _VERSION_PATTERNS, page_hint)
    eff_date = _find_first(first_pages, _EFFECTIVE_DATE_PATTERNS, page_hint)
    carrier = _detect_carrier(first_pages, page_hint)

    term_start = ExtractedValue()
    term_end = ExtractedValue()
    for pat in _TERM_RANGE_PATTERNS:
        m = pat.search(full_text)
        if m:
            snippet = full_text[max(0, m.start() - 10):m.end() + 10].strip()
            term_start = ev(value=m.group(1).strip(), confidence=0.85,
                            source_page=page_hint, source_text=snippet[:120])
            term_end = ev(value=m.group(2).strip(), confidence=0.85,
                          source_page=page_hint, source_text=snippet[:120])
            break

    payment = _find_first(full_text, _PAYMENT_PATTERNS, page_hint)

    return ContractMetadata(
        customer_name=customer or ExtractedValue(needs_review=True),
        account_number=account or ExtractedValue(needs_review=True),
        agreement_number=agreement or ExtractedValue(needs_review=True),
        version_number=version or ExtractedValue(),
        effective_date=eff_date or ExtractedValue(needs_review=True),
        term_start=term_start,
        term_end=term_end,
        payment_terms=payment or ExtractedValue(),
        carrier=carrier,
    )
