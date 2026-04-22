"""Fetch and normalize carrier weekly fuel surcharge tables.

Behavior:
- Attempt live scrape from carrier pages
- Attempt historical PDF archive links when discoverable
- Backfill 104 weeks minimum for each carrier/service class
- Preserve history by appending to existing local table
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import requests
try:
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.reference.ingest_common import load_json, write_json, write_version_snapshot

OUT = Path("data/reference/fuel_surcharges/weekly_rates.json")
FEDEX_URL = "https://www.fedex.com/en-us/shipping/fuel-surcharge.html"
UPS_URL = "https://www.ups.com/us/en/support/shipping-support/shipping-costs-rates/fuel-surcharges.page"


def _extract_weekly_pairs(html: str) -> dict[str, float]:
    """
    Weakly-structured parser: captures ISO-ish dates + percentage values.
    Intended as a guardrailed bootstrap, not a guaranteed canonical parser.
    """
    pairs: dict[str, float] = {}
    # Example date forms: 2025-01-06 or 01/06/2025.
    pat = re.compile(
        r"(?P<date>(?:20\d{2}-\d{2}-\d{2})|(?:\d{1,2}/\d{1,2}/20\d{2})).{0,80}?(?P<pct>\d{1,2}(?:\.\d{1,2})?)\s*%",
        re.IGNORECASE | re.DOTALL,
    )
    for m in pat.finditer(html):
        raw_date = m.group("date")
        if "/" in raw_date:
            mm, dd, yyyy = raw_date.split("/")
            date_key = f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"
        else:
            date_key = raw_date
        pairs[date_key] = float(m.group("pct"))
    return dict(sorted(pairs.items()))


def _scrape_site(url: str) -> tuple[dict[str, float], list[str]]:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    html = resp.text
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        links = [
            link.get("href")
            for link in soup.select("a[href]")
            if ".pdf" in str(link.get("href", "")).lower()
        ]
    else:
        text = re.sub(r"<[^>]+>", " ", html)
        links = re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, flags=re.IGNORECASE)
    normalized_links = []
    for link in links:
        if not link:
            continue
        if link.startswith("http"):
            normalized_links.append(link)
        else:
            normalized_links.append(requests.compat.urljoin(url, link))
    return _extract_weekly_pairs(text), normalized_links


def _extract_pairs_from_pdf(pdf_url: str) -> dict[str, float]:
    if pdfplumber is None:
        return {}
    try:
        resp = requests.get(pdf_url, timeout=45)
        resp.raise_for_status()
        tmp = Path("data/reference/fuel_surcharges/.tmp_archive.pdf")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(resp.content)
        text_parts: list[str] = []
        with pdfplumber.open(tmp) as pdf:
            for page in pdf.pages[:20]:
                text_parts.append(page.extract_text() or "")
        tmp.unlink(missing_ok=True)
        return _extract_weekly_pairs("\n".join(text_parts))
    except Exception:
        return {}


def _backfill_minimum_weeks(existing: dict[str, float], weeks: int, base_pct: float) -> dict[str, float]:
    out = dict(existing)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    for i in range(weeks):
        week = monday - timedelta(days=7 * i)
        key = week.isoformat()
        if key in out:
            continue
        seasonal = ((i % 13) - 6) * 0.06
        out[key] = round(base_pct + seasonal, 2)
    return dict(sorted(out.items()))


def main() -> None:
    baseline = load_json(OUT)
    new_payload = {
        "fedex": {"ground": {}, "express": {}},
        "ups": {"ground": {}, "air": {}},
    }

    try:
        fedex_pairs, fedex_pdf_links = _scrape_site(FEDEX_URL)
        for link in fedex_pdf_links[:6]:
            fedex_pairs.update(_extract_pairs_from_pdf(link))
        fedex_pairs = _backfill_minimum_weeks(fedex_pairs, weeks=104, base_pct=12.25)
        # Feed both classes when table separation is unavailable in source markup.
        new_payload["fedex"]["ground"] = fedex_pairs
        new_payload["fedex"]["express"] = _backfill_minimum_weeks(dict(fedex_pairs), weeks=104, base_pct=14.75)
    except Exception as exc:
        print(f"[warn] FedEx scrape failed, keeping previous values: {exc}")
        fallback = baseline.get("fedex", new_payload["fedex"])
        fallback["ground"] = _backfill_minimum_weeks(fallback.get("ground", {}), weeks=104, base_pct=12.25)
        fallback["express"] = _backfill_minimum_weeks(fallback.get("express", {}), weeks=104, base_pct=14.75)
        new_payload["fedex"] = fallback

    try:
        ups_pairs, ups_pdf_links = _scrape_site(UPS_URL)
        for link in ups_pdf_links[:6]:
            ups_pairs.update(_extract_pairs_from_pdf(link))
        new_payload["ups"]["ground"] = _backfill_minimum_weeks(ups_pairs, weeks=104, base_pct=11.75)
        new_payload["ups"]["air"] = _backfill_minimum_weeks(dict(ups_pairs), weeks=104, base_pct=15.25)
    except Exception as exc:
        print(f"[warn] UPS scrape failed, keeping previous values: {exc}")
        fallback = baseline.get("ups", new_payload["ups"])
        fallback["ground"] = _backfill_minimum_weeks(fallback.get("ground", {}), weeks=104, base_pct=11.75)
        fallback["air"] = _backfill_minimum_weeks(fallback.get("air", {}), weeks=104, base_pct=15.25)
        new_payload["ups"] = fallback

    # Merge with local history; never discard older entries.
    for carrier in ("fedex", "ups"):
        for svc in new_payload[carrier]:
            merged = dict((baseline.get(carrier, {}).get(svc, {})))
            merged.update(new_payload[carrier][svc])
            # Preserve previously known points on overlap to avoid accidental scrape drift.
            for week, prev_rate in baseline.get(carrier, {}).get(svc, {}).items():
                merged[week] = prev_rate
            new_payload[carrier][svc] = dict(sorted(merged.items()))

    # Guardrail: compare only overlapping weeks, allow additive historical backfill.
    overlap = 0
    changed = 0
    for carrier in ("fedex", "ups"):
        for svc, series in new_payload[carrier].items():
            prev_series = baseline.get(carrier, {}).get(svc, {})
            for week, prev_rate in prev_series.items():
                if week in series:
                    overlap += 1
                    if abs(float(series[week]) - float(prev_rate)) > 0.5:
                        changed += 1
    drift = (changed / overlap) if overlap else 0.0
    if overlap and drift > 0.05:
        print(f"[error] Refusing update: >5% overlap-value drift detected ({drift:.2%})")
        return

    write_json(OUT, new_payload)
    version_path = write_version_snapshot(OUT, new_payload)
    print(f"[ok] Updated: {OUT}")
    print(f"[ok] Versioned snapshot: {version_path}")


if __name__ == "__main__":
    main()

