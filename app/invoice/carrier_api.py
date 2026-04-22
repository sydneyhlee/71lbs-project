"""Carrier billing API ingestion (FedEx/UPS) with normalized output."""

from __future__ import annotations

from typing import Any

import requests

from app.config import (
    FEDEX_BILLING_API_BASE_URL,
    FEDEX_BILLING_API_KEY,
    UPS_BILLING_API_BASE_URL,
    UPS_BILLING_API_KEY,
)


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _fetch_json(base_url: str, api_key: str, invoice_id: str) -> dict[str, Any]:
    if not base_url or not api_key:
        raise RuntimeError("Carrier API credentials are not configured.")
    url = f"{base_url.rstrip('/')}/invoices/{invoice_id}"
    resp = requests.get(url, headers=_headers(api_key), timeout=45)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Carrier API response was not a JSON object.")
    return payload


def fetch_fedex_invoice(invoice_id: str) -> dict[str, Any]:
    return _fetch_json(FEDEX_BILLING_API_BASE_URL, FEDEX_BILLING_API_KEY, invoice_id)


def fetch_ups_invoice(invoice_id: str) -> dict[str, Any]:
    return _fetch_json(UPS_BILLING_API_BASE_URL, UPS_BILLING_API_KEY, invoice_id)

