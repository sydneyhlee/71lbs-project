"""Download/build zone-map and transit-day reference files.

If live tool scraping is unavailable, generates representative 3-digit prefix
lookups and transit tables for deterministic audit coverage.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.reference.ingest_common import utc_stamp


def _ensure(path: Path, header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(header + "\n", encoding="utf-8")
        print(f"Created template: {path}")
    else:
        print(f"Exists: {path}")


def _seed_zone_rows() -> list[str]:
    origins = ["070", "100", "303", "606", "750", "770", "850", "900", "941", "981"]
    destinations = ["005", "021", "070", "100", "191", "303", "331", "482", "606", "733", "770", "850", "900", "941", "981", "995"]
    rows = ["origin_prefix,destination_prefix,zone"]
    for o in origins:
        for d in destinations:
            distance = abs(int(o) - int(d))
            zone = 2 + min(distance // 120, 7)
            rows.append(f"{o},{d},{zone}")
    return rows


def _seed_transit_rows() -> list[str]:
    rows = ["zone,business_days"]
    for zone in range(2, 9):
        days = 1 if zone <= 3 else 2 if zone <= 5 else 3 if zone <= 6 else 4
        rows.append(f"{zone},{days}")
    return rows


def main() -> None:
    zone_paths = [
        Path("data/reference/zone_maps/fedex_zones.csv"),
        Path("data/reference/zone_maps/ups_zones.csv"),
    ]
    transit_paths = [
        Path("data/reference/transit_days/fedex_ground_transit.csv"),
        Path("data/reference/transit_days/ups_ground_transit.csv"),
    ]
    for p in zone_paths:
        _ensure(p, "origin_prefix,destination_prefix,zone")
        row_count = max(len(p.read_text(encoding="utf-8").splitlines()) - 1, 0)
        if row_count < 50:
            p.write_text("\n".join(_seed_zone_rows()) + "\n", encoding="utf-8")
            print(f"[warn] Wrote representative fallback zone rows: {p}")
    for p in transit_paths:
        _ensure(p, "zone,business_days")
        row_count = max(len(p.read_text(encoding="utf-8").splitlines()) - 1, 0)
        if row_count < 7:
            p.write_text("\n".join(_seed_transit_rows()) + "\n", encoding="utf-8")
            print(f"[warn] Wrote representative fallback transit rows: {p}")

    for p in zone_paths + transit_paths:
        if p.exists() and p.stat().st_size > 0:
            versions = p.parent / "versions"
            versions.mkdir(parents=True, exist_ok=True)
            latest = sorted(versions.glob(f"{p.stem}_*.csv"))
            if latest:
                prev_lines = latest[-1].read_text(encoding="utf-8").splitlines()
                curr_lines = p.read_text(encoding="utf-8").splitlines()
                if prev_lines:
                    drift = abs(len(curr_lines) - len(prev_lines)) / max(len(prev_lines), 1)
                    if drift > 0.05:
                        print(
                            f"[error] {p.name} row drift {drift:.2%} exceeds 5%; "
                            "review export before publishing."
                        )
                        continue
            snap = versions / f"{p.stem}_{utc_stamp()}{p.suffix}"
            shutil.copy2(p, snap)
            print(f"Versioned snapshot: {snap}")

    print("Populate from carrier zone locator and transit exports.")


if __name__ == "__main__":
    main()

