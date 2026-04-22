#!/usr/bin/env bash
set -euo pipefail

python scripts/scrape_fuel_surcharges.py
python scripts/download_das_zips.py
python scripts/download_zone_maps.py
python scripts/download_service_guides.py

echo "Reference data refresh scaffold complete."

