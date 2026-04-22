"""Reference-data freshness and audit metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ReferenceHealth:
    name: str
    exists: bool
    age_days: float | None
    stale: bool
    path: str


def _file_age_days(path: Path) -> float | None:
    if not path.exists():
        return None
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    return (now - modified).total_seconds() / 86400.0


def assess_reference_files() -> list[ReferenceHealth]:
    checks = [
        ("fuel_weekly_rates", Path("data/reference/fuel_surcharges/weekly_rates.json"), 10),
        ("fedex_das_zips", Path("data/reference/das_zips/fedex_das_zips.csv"), 90),
        ("ups_das_zips", Path("data/reference/das_zips/ups_das_zips.csv"), 90),
        ("fedex_zone_map", Path("data/reference/zone_maps/fedex_zones.csv"), 120),
        ("ups_zone_map", Path("data/reference/zone_maps/ups_zones.csv"), 120),
    ]

    out: list[ReferenceHealth] = []
    for name, path, stale_after_days in checks:
        age = _file_age_days(path)
        exists = path.exists()
        stale = (age is None) or (age > stale_after_days)
        out.append(
            ReferenceHealth(
                name=name,
                exists=exists,
                age_days=age,
                stale=stale,
                path=str(path),
            )
        )
    return out


def summarize_health() -> dict:
    entries = assess_reference_files()
    return {
        "total": len(entries),
        "stale_or_missing": sum(1 for e in entries if e.stale),
        "entries": [
            {
                "name": e.name,
                "exists": e.exists,
                "age_days": round(e.age_days, 2) if e.age_days is not None else None,
                "stale": e.stale,
                "path": e.path,
            }
            for e in entries
        ],
    }

