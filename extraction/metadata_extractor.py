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

from dateutil import parser as date_parser

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
    re.compile(
        r"Account\s*(?:Number|#|No\.?)\s*[:\-]?\s*([A-Z0-9\-]{6,20})",
        re.IGNORECASE,
    ),
    re.compile(
        r"Acct\s*(?:No\.?|#)\s*[:\-]?\s*([A-Z0-9\-]{6,20})",
        re.IGNORECASE,
    ),
    # UPS Addendum row often starts with account id, then company/address text
    re.compile(
        r"(?:^|\n)\s*([A-Z0-9]{6,12})\s+[A-Z0-9&.,'\- ]{3,}\n",
        re.IGNORECASE,
    ),
    # FedEx-ish numeric formats
    re.compile(r"(\d{9,12})\s*-\s*\d{2,3}", re.IGNORECASE),
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
    # UPS: "Date Signed: <date>"
    re.compile(
        r"Date\s*Signed\s*:\s*"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
        re.IGNORECASE,
    ),
    # Label on signature / cover page (must be followed by a parseable date on same line)
    re.compile(
        r"Effective\s+Date\s*:\s*"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
        re.IGNORECASE,
    ),
]

# How far to scan for calendar effective dates (signature blocks often land after page 1).
_EFFECTIVE_DATE_SEARCH_WINDOW = 32_000

# Offer acceptance / void-if-not-accepted — never treat as contract effective date.
_OFFER_EXPIRATION_PATTERNS = [
    re.compile(
        r"(?:offer\s+is\s+)?void\s*if\s*not\s*accepted\s*by\s*"
        r"((?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})",
        re.IGNORECASE,
    ),
]

_EXTERNAL_TERM_SIGNAL_PATTERNS = [
    re.compile(r"\b(?:Addendum|Exhibit|Schedule)\s+[A-Z]\b", re.IGNORECASE),
    re.compile(r"\bMaster\s+Agreement\b", re.IGNORECASE),
    re.compile(r"49\s*U\.?\s*S\.?\s*C\.?\s*§?\s*13102", re.IGNORECASE),
    re.compile(r"\bas\s+the\s+term\s+is\s+defined\b", re.IGNORECASE),
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

# UPS Carrier Agreement — standard opening sentence (not the whole narrative block).
_UPS_CARRIER_PAYMENT_OPENING = re.compile(
    r"(Customer agrees to pay the total invoice amount in full within the time period required by UPS\.)",
    re.IGNORECASE,
)

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


_BAD_COMPANY_SNIPPETS = (
    "do not pay",
    "charges were submitted",
    "your charges have been submitted",
    "your bank account will be",
    "invoice summary",
    "delivery service invoice",
    "have you seen the new bill payment platform",
    "bill payment experience easier",
    "total amount outstanding",
    "invoice number",
)


def _clean_company_name(name: str) -> str:
    """Insert missing spaces before common suffixes in merged PDF text."""
    name = re.sub(r"^UPSHC[-_]", "", name, flags=re.IGNORECASE)
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    name = re.sub(r"(?<=[a-zA-Z])(LLC|INC|CORP|LTD|CO|LP)\b", r" \1", name)
    name = re.sub(r"(?<=[a-zA-Z])(Inc|Corp|Ltd)\.", r" \1.", name)
    name = re.sub(r"\s{2,}", " ", name)
    return name.strip()


def _is_valid_company_candidate(raw: str | None) -> bool:
    if not raw:
        return False
    txt = " ".join(str(raw).split()).strip()
    low = txt.lower()
    words = txt.split()
    if len(txt) < 3:
        return False
    if any(bad in low for bad in _BAD_COMPANY_SNIPPETS):
        return False
    # Reject obvious sentence-like captures.
    if low.endswith(" to") or low.startswith("the ") or low.startswith("your "):
        return False
    if len(words) > 8:
        return False

    company_markers = ("llc", "inc", "corp", "ltd", "co", "company", "international", "holdings")
    if any(marker in low for marker in company_markers):
        return True

    # Otherwise only allow concise proper-name style strings.
    if len(words) <= 5 and all(re.match(r"^[A-Za-z0-9&.'-]+$", w) for w in words):
        return True
    return False


def _extract_invoice_bill_to_name(
    text: str, page_hint: Optional[int] = None
) -> Optional[ExtractedValue]:
    """
    Invoice-safe fallback to capture billed customer names without taking
    boilerplate lines like "Do not pay ... submitted to".
    """
    patterns = [
        re.compile(r"(?:Bill(?:ed)?\s+To|Submitted\s+to)\s*[:\-][ \t]*([A-Z][A-Z0-9&.,' \-]{2,120})", re.IGNORECASE),
        re.compile(r"(?:Submitted\s+to)\s+([A-Z][A-Z0-9&.,' \-]{2,120}\b(?:LLC|Inc\.?|Corp\.?|Ltd\.?|Company))", re.IGNORECASE),
        re.compile(r"(?:Customer\s+Name)\s*[:\-][ \t]*([A-Z][A-Z0-9&.,' \-]{2,120})", re.IGNORECASE),
    ]
    for pat in patterns:
        m = pat.search(text)
        if not m:
            continue
        cand = _clean_company_name(m.group(1).strip())
        if not _is_valid_company_candidate(cand):
            continue
        snippet = text[max(0, m.start() - 20):m.end() + 20].strip()
        return ev(
            value=cand,
            confidence=0.72,
            source_page=page_hint,
            source_text=snippet[:120],
            needs_review=True,
        )
    return None


def _looks_like_account_number(raw: str | None) -> bool:
    if not raw:
        return False
    txt = str(raw).strip()
    if len(txt) < 6:
        return False
    # Require at least one digit to avoid values like "Invoice".
    if not re.search(r"\d", txt):
        return False
    return True


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


def _extract_ups_procedural_effective_date(
    text: str, page_hint: Optional[int] = None
) -> Optional[ExtractedValue]:
    """
    UPS Carrier Agreement often defines effect as Monday-after-signing vs Effective Date
    with no OCR-parseable calendar date (DocuSign merge fields). Surface a concise value
    for reviewers instead of leaving the field empty.
    """
    m = re.search(
        r"This\s+Agreement\s+shall\s+take\s+effect\s+on\s+the\s+Monday\s+following\s+the\s+signing"
        r"\s+of\s+this\s+Agreement\s+or\s+the\s+Effective\s+Date,\s+whichever\s+is\s+later",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None
    snippet = text[max(0, m.start() - 40) : m.end() + 40].strip()
    return ev(
        value="Monday after signing or Effective Date on signature page, whichever is later",
        confidence=0.72,
        source_page=page_hint,
        source_text=snippet[:200],
        needs_review=True,
    )


def _extract_payment_terms(text: str, page_hint: Optional[int] = None) -> Optional[ExtractedValue]:
    """Extract payment terms, preferring the numeric 'Net N days' form."""
    m_open = _UPS_CARRIER_PAYMENT_OPENING.search(text)
    if m_open:
        snippet = text[max(0, m_open.start() - 40) : m_open.end() + 30].strip()
        return ev(
            value=m_open.group(1).strip(),
            confidence=0.88,
            source_page=page_hint,
            source_text=snippet[:200],
        )
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


def _extract_ups_addendum_account(
    text: str, page_hint: Optional[int] = None
) -> Optional[ExtractedValue]:
    """
    Fallback for UPS Addendum A tables where OCR/text extraction breaks
    headers/cells and normal account regexes miss.
    """
    m = re.search(
        r"List\s+of\s+Account\s+Numbers[\s\S]{0,2500}?(?:^|\n)\s*([A-Z0-9]{6,12})\s+[A-Z0-9&.,'\- ]{3,}",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if not m:
        return None

    snippet = text[max(0, m.start() - 20) : m.end() + 20].strip()
    return ev(
        value=m.group(1).strip(),
        confidence=0.82,
        source_page=page_hint,
        source_text=snippet[:120],
    )


def _extract_offer_expiration(
    text: str, page_hint: Optional[int] = None
) -> Optional[ExtractedValue]:
    return _find_first(text, _OFFER_EXPIRATION_PATTERNS, page_hint)


def extract_payment_terms_block(
    text: str, page_hint: Optional[int] = None
) -> Optional[ExtractedValue]:
    """
    Heuristic: capture narrative under a 'Payment Terms' heading until the next
    known section heading (multiline-safe).
    """
    m = re.search(r"(?is)\bPayment\s+Terms\.?\s*", text)
    if not m:
        return None
    rest = text[m.end() :]
    stop = re.search(
        r"(?im)(?:^|\n)[ \t]*(?:Applicable\s+Services|Special\s+Provisions|Effective\s+Date|"
        r"Definitions|Waiver|Surcharges|Service\.|Confidentiality\.|"
        r"Offer\s+Expiration|Term\.|All\s+Services\s+provided)\b",
        rest,
    )
    raw_body = rest[: stop.start()] if stop else rest
    body = re.sub(r"\s+", " ", raw_body).strip()
    if len(body) < 40:
        return None

    clipped = body[:4000]
    hit_max = len(body) > 4000
    snippet = clipped[:500] + ("…" if len(clipped) > 500 else "")
    return ev(
        value=clipped + ("…" if hit_max else ""),
        confidence=0.78,
        source_page=page_hint,
        source_text=snippet,
        needs_review=True,
    )


def _extract_applicable_services_block(
    text: str, page_hint: Optional[int] = None
) -> Optional[ExtractedValue]:
    """Document-level applicable services section (narrative or list)."""
    head = text[:25000]
    m = re.search(
        r"(?is)\bApplicable\s+Services\s*[:\.]?\s*(.*?)(?=\n[ \t]*(?:Payment\s+Terms|Special\s+Provisions|"
        r"Effective\s+Date|Surcharges|Definitions|Master\s+Agreement)\b|\Z)",
        head,
    )
    if not m:
        # Fallback: common introductory clause
        m2 = re.search(
            r"(?is)\b(?:the\s+following\s+services?|services?\s+covered)\b[\s:,-]+(.{40,3500}?)"
            r"(?=\n[ \t]*(?:Payment\s+Terms|Special\s+Provisions|Effective\s+Date)\b|\Z)",
            head,
        )
        if not m2:
            return None
        body = re.sub(r"\s+", " ", m2.group(1)).strip()
    else:
        body = re.sub(r"\s+", " ", m.group(1)).strip()

    if len(body) < 25:
        return None
    clipped = body[:4000]
    hit_max = len(body) > 4000
    snippet = clipped[:500] + ("…" if len(clipped) > 500 else "")
    return ev(
        value=clipped + ("…" if hit_max else ""),
        confidence=0.74,
        source_page=page_hint,
        source_text=snippet,
        needs_review=True,
    )


def _detect_external_term_reference(
    text: str, page_hint: Optional[int] = None
) -> Optional[ExtractedValue]:
    """True when the agreement points to another document for term dates/duration."""
    for pat in _EXTERNAL_TERM_SIGNAL_PATTERNS:
        m = pat.search(text)
        if m:
            snippet = text[max(0, m.start() - 60) : m.end() + 80].strip()
            return ev(
                value=True,
                confidence=0.78,
                source_page=page_hint,
                source_text=snippet[:220],
                needs_review=True,
            )
    return None


def _effective_date_parseable(eff: Optional[ExtractedValue]) -> bool:
    if not eff or not eff.value:
        return False
    val = str(eff.value).strip()
    # Require an explicit calendar token; fuzzy=True alone would treat "Monday …" as a date.
    if not re.search(
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}",
        val,
        re.IGNORECASE,
    ):
        return False
    try:
        date_parser.parse(val, fuzzy=True)
        return True
    except (ValueError, TypeError, OverflowError):
        return False


def extract_metadata(full_text: str, page_texts: Optional[dict] = None) -> ContractMetadata:
    """
    Extract contract metadata from full document text.

    Args:
        full_text: Complete document text
        page_texts: Optional dict mapping page_number -> page_text
                    for better source_page attribution.
    """
    first_pages = full_text[:5000]
    eff_date_window = full_text[:_EFFECTIVE_DATE_SEARCH_WINDOW]
    page_hint = 1

    customer = _find_first(first_pages, _CUSTOMER_PATTERNS, page_hint)

    if customer:
        cleaned_customer = _clean_company_name(customer.value)
        if _is_valid_company_candidate(cleaned_customer):
            customer = ev(
                value=cleaned_customer,
                confidence=customer.confidence,
                source_page=customer.source_page,
                source_text=customer.source_text,
                needs_review=customer.needs_review,
            )
        else:
            customer = None

    if not customer:
        customer = _extract_invoice_bill_to_name(first_pages, page_hint)

    account = _find_first(full_text, _ACCOUNT_PATTERNS, page_hint)

    if not account:
        account = _extract_ups_addendum_account(full_text, page_hint)

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
    if account and not _looks_like_account_number(account.value):
        account = None

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
    if not eff_date:
        eff_date = _find_first(eff_date_window, _EFFECTIVE_DATE_PATTERNS, page_hint)
    offer_expiration = _extract_offer_expiration(full_text, page_hint)
    external_term_reference = _detect_external_term_reference(full_text, page_hint)
    carrier = _detect_carrier(first_pages, page_hint)
    if (not eff_date or not eff_date.value) and carrier.value == "UPS":
        proc_eff = _extract_ups_procedural_effective_date(full_text, page_hint)
        if proc_eff:
            eff_date = proc_eff

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
            if eff_date and not term_start.value and _effective_date_parseable(eff_date):
                term_start = ev(value=eff_date.value, confidence=0.80,
                                source_page=page_hint, source_text="Derived from effective date")

    # Policy: when the agreement defers term dates to another instrument, we do not
    # invent term_end. Optionally seed term_start from a parseable Effective Date
    # only as a provisional placeholder for reviewers.
    if (
        external_term_reference
        and external_term_reference.value
        and not term_start.value
        and eff_date
        and eff_date.value
        and _effective_date_parseable(eff_date)
    ):
        term_start = ev(
            value=eff_date.value,
            confidence=0.62,
            source_page=page_hint,
            source_text=(
                "Provisional term_start: same as Effective Date because the text references "
                "an external document for the full term; term_end intentionally left unset. "
                "Review required."
            ),
            needs_review=True,
        )

    payment = _extract_payment_terms(full_text, page_hint)
    if payment is None or not payment.value:
        block_pt = extract_payment_terms_block(full_text, page_hint)
        if block_pt:
            payment = block_pt

    applicable_services = _extract_applicable_services_block(full_text, page_hint)

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
        offer_expiration=offer_expiration or ExtractedValue(),
        external_term_reference=external_term_reference or ExtractedValue(),
        applicable_services=applicable_services or ExtractedValue(),
    )
