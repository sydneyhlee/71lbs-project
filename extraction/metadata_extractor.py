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
    # UPS: 'between G-FULFILLMENT LLC ("Customer")' (handles merged words)
    re.compile(r'(?:between)\s*(.+?)\s*\(\s*"?\s*Customer\s*"?\s*\)', re.IGNORECASE),
    re.compile(r'(?:made\s*and\s*entered\s*into\s*by\s*and\s*between)\s*(.+?)\s*(?:\(|")', re.IGNORECASE),
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
    # UPS: "voidifnotacceptedbyApril20,2025" (handles merged-word PDFs)
    re.compile(
        r"void\s*if\s*not\s*accepted\s*by\s*"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s*\d{1,2},?\s*\d{4})",
        re.IGNORECASE,
    ),
    # UPS: "Date Signed: <date>"
    re.compile(
        r"Date\s*Signed\s*:\s*"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
        re.IGNORECASE,
    ),
]

_TERM_RANGE_PATTERNS = [
    # Explicit date range: "Term: January 1, 2025 through December 31, 2025"
    re.compile(
        r"Term\s*[:\-]?\s*"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4})"
        r"\s+through\s+"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4})",
        re.IGNORECASE,
    ),
    # Numeric date range: "01/01/2025 through 12/31/2025"
    re.compile(
        r"(\d{1,2}/\d{1,2}/\d{4})\s*(?:through|to|-)\s*(\d{1,2}/\d{1,2}/\d{4})",
        re.IGNORECASE,
    ),
    # FedEx table format: "1 Effective Date Does Not Expire ..."
    re.compile(
        r"(?:^|\n)\s*1\s+(Effective\s+Date)\s+(Does\s+Not\s+Expire)",
        re.IGNORECASE,
    ),
    # FedEx table: "1 Effective Date 24 Month(s) ..."
    re.compile(
        r"(?:^|\n)\s*1\s+(Effective\s+Date)\s+(\d+\s+Month\(?s?\)?)",
        re.IGNORECASE,
    ),
    # FedEx table: "1 <date> Does Not Expire ..."
    re.compile(
        r"(?:^|\n)\s*1\s+"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4})"
        r"\s+(Does\s+Not\s+Expire)",
        re.IGNORECASE,
    ),
    # FedEx table: "1 <date> <date>" (written-out months)
    re.compile(
        r"(?:^|\n)\s*1\s+"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4})"
        r"\s+"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4})",
        re.IGNORECASE,
    ),
    # FedEx table: "1 MM/DD/YYYY MM/DD/YYYY ..." (numeric dates)
    re.compile(
        r"(?:^|\n)\s*1\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}/\d{1,2}/\d{4})",
        re.IGNORECASE,
    ),
    # FedEx table: "1 MM/DD/YYYY Does Not Expire ..."
    re.compile(
        r"(?:^|\n)\s*1\s+(\d{1,2}/\d{1,2}/\d{4})\s+(Does\s+Not\s+Expire)",
        re.IGNORECASE,
    ),
    # FedEx table: "1 MM/DD/YYYY 24 Month(s) ..."
    re.compile(
        r"(?:^|\n)\s*1\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d+\s+Month\(?s?\)?)",
        re.IGNORECASE,
    ),
]

# UPS-style term duration: "remain in effect for 156 weeks" (handles merged words)
_TERM_DURATION_PATTERN = re.compile(
    r"remain\s*in\s*effect\s*for\s*(\d+)\s*(weeks?|months?|years?)",
    re.IGNORECASE,
)

_PAYMENT_DAYS_PATTERNS = [
    # "Payment is due within the following number of days ... Attachment: 15"
    re.compile(
        r"Payment\s+is\s+due\s+within\s+the\s+following\s+number\s+of\s+days"
        r"[\s\S]{0,500}?(?:Attachment|Credit\s+Term)\s*[:\s]\s*(\d+)",
        re.IGNORECASE,
    ),
    # "Payment is due within ... : 30 days" (limited to 200 chars to avoid backtracking)
    re.compile(
        r"Payment\s+is\s+due\s+within[^\n]{0,200}?(\d+)\s*(?:days?|calendar)",
        re.IGNORECASE,
    ),
    # UPS Addendum A: "PaymentTerms(Days)" header, then account lines ending with days
    re.compile(
        r"Payment\s*Terms?\s*\(\s*Days\s*\)[^\n]*\n(?:[^\n]*\n){0,5}?[^\n]*[\dA-Z]{8,}\s+\S+[^\n]*\s(\d{1,3})\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    # "Payment Terms: Net 30" or "Payment Terms: 30 days"
    re.compile(r"Payment\s+Terms?\s*[:\-]\s*(?:Net\s+)?(\d+)\s*(?:days?)?", re.IGNORECASE),
    # Standalone "Net 30 days"
    re.compile(r"Net\s+(\d+)\s+days?", re.IGNORECASE),
]

_PAYMENT_PATTERNS = [
    re.compile(r"Payment\s+Terms?\s*[:\-]\s*(.+?)(?:\n|$)", re.IGNORECASE),
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


def _clean_company_name(name: str) -> str:
    """Insert missing spaces before common suffixes in merged PDF text."""
    name = re.sub(r"(?<=[a-zA-Z])(LLC|INC|CORP|LTD|CO|LP)\b", r" \1", name)
    name = re.sub(r"(?<=[a-zA-Z])(Inc|Corp|Ltd)\.", r" \1.", name)
    return name.strip()


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


def _extract_payment_terms(text: str, page_hint: Optional[int] = None) -> Optional[ExtractedValue]:
    """Extract payment terms, preferring the numeric 'Net N days' form."""
    for pat in _PAYMENT_DAYS_PATTERNS:
        m = pat.search(text)
        if m:
            days = m.group(1).strip()
            snippet = text[max(0, m.start() - 20):m.end() + 20].strip()
            return ev(
                value=f"Net {days} days",
                confidence=0.90,
                source_page=page_hint,
                source_text=snippet[:120],
            )
    return _find_first(text, _PAYMENT_PATTERNS, page_hint)


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

    if customer:
        customer = ev(
            value=_clean_company_name(customer.value),
            confidence=customer.confidence,
            source_page=customer.source_page,
            source_text=customer.source_text,
            needs_review=customer.needs_review,
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
            raw_start = m.group(1).strip()
            raw_end = m.group(2).strip()

            if raw_start.lower() == "effective date" and eff_date:
                raw_start = eff_date.value

            term_start = ev(value=raw_start, confidence=0.85,
                            source_page=page_hint, source_text=snippet[:120])
            term_end = ev(value=raw_end, confidence=0.85,
                          source_page=page_hint, source_text=snippet[:120])
            break

    if not term_end.value:
        dur = _TERM_DURATION_PATTERN.search(full_text)
        if dur:
            duration_str = f"{dur.group(1)} {dur.group(2)}"
            snippet = full_text[max(0, dur.start() - 20):dur.end() + 20].strip()
            term_end = ev(value=duration_str, confidence=0.80,
                          source_page=page_hint, source_text=snippet[:120])
            if eff_date and not term_start.value:
                term_start = ev(value=eff_date.value, confidence=0.80,
                                source_page=page_hint, source_text="Derived from effective date")

    payment = _extract_payment_terms(full_text, page_hint)

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
