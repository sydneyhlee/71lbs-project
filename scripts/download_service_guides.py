"""Version annual carrier service-guide base-rate files (post-GRI refresh)."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.reference.ingest_common import load_json, percent_change_guard
from app.reference.ingest_common import utc_stamp


def _version_if_exists(path: Path) -> None:
    if not path.exists():
        print(f"[warn] Missing expected service guide file: {path}")
        return
    versions = path.parent / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    snap = versions / f"{path.stem}_{utc_stamp()}{path.suffix}"
    shutil.copy2(path, snap)
    print(f"[ok] Versioned service guide: {snap}")


def main() -> None:
    guides = [
        Path("data/reference/service_guides/fedex_2025_rates.json"),
        Path("data/reference/service_guides/ups_2025_rates.json"),
    ]
    for guide in guides:
        versions_dir = guide.parent / "versions"
        latest = sorted(versions_dir.glob(f"{guide.stem}_*.json")) if versions_dir.exists() else []
        if latest and guide.exists():
            prev_payload = load_json(latest[-1])
            curr_payload = load_json(guide)
            valid, drift = percent_change_guard(prev_payload, curr_payload, threshold=0.05)
            if not valid:
                print(
                    f"[error] {guide.name} numeric shape drift {drift:.2%} exceeds 5%; "
                    "review before versioning."
                )
                continue
        _version_if_exists(guide)
    print("Service guide refresh completed (annual cadence after GRI).")


if __name__ == "__main__":
    main()

