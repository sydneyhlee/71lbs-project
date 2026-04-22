"""Scheduled reference-data refresh runner.

Cadence targets:
- Fuel surcharge tables: weekly (Mon/Wed source updates)
- DAS ZIPs: quarterly
- Service guide rates: annual (January post-GRI)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime


def _run(script: str) -> int:
    cmd = [sys.executable, script]
    print(f"[run] {' '.join(cmd)}")
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["all", "fuel", "das", "zones", "service_guides"], default="all")
    args = parser.parse_args()

    now = datetime.utcnow()
    tasks = []
    if args.task == "all":
        tasks = [
            ("fuel", "scripts/scrape_fuel_surcharges.py"),
            ("das", "scripts/download_das_zips.py"),
            ("zones", "scripts/download_zone_maps.py"),
            ("service_guides", "scripts/download_service_guides.py"),
        ]
    else:
        mapping = {
            "fuel": "scripts/scrape_fuel_surcharges.py",
            "das": "scripts/download_das_zips.py",
            "zones": "scripts/download_zone_maps.py",
            "service_guides": "scripts/download_service_guides.py",
        }
        tasks = [(args.task, mapping[args.task])]

    print(f"[info] refresh start utc={now.isoformat()} task={args.task}")
    rc = 0
    for name, script in tasks:
        code = _run(script)
        if code != 0:
            print(f"[error] task `{name}` failed with exit code {code}")
            rc = code
    if rc != 0:
        raise SystemExit(rc)
    print("[ok] reference refresh run complete")


if __name__ == "__main__":
    main()

