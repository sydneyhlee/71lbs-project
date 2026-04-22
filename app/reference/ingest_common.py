"""Common helpers for reference-data ingestion/versioning."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def write_version_snapshot(target_path: Path, payload: dict[str, Any]) -> Path:
    """Write versioned snapshot under sibling `versions/` directory."""
    versions_dir = target_path.parent / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    version_file = versions_dir / f"{target_path.stem}_{utc_stamp()}{target_path.suffix}"
    version_file.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return version_file


def flatten_numeric_values(obj: Any, out: list[float] | None = None) -> list[float]:
    if out is None:
        out = []
    if isinstance(obj, dict):
        for v in obj.values():
            flatten_numeric_values(v, out)
    elif isinstance(obj, list):
        for v in obj:
            flatten_numeric_values(v, out)
    elif isinstance(obj, (int, float)):
        out.append(float(obj))
    return out


def percent_change_guard(previous: dict[str, Any], current: dict[str, Any], threshold: float = 0.05) -> tuple[bool, float]:
    """
    Heuristic guard against parser corruption.

    Returns (is_valid, ratio_changed). ratio_changed is value-count drift ratio.
    """
    prev_vals = flatten_numeric_values(previous)
    cur_vals = flatten_numeric_values(current)
    if not prev_vals:
        return True, 0.0
    if not cur_vals:
        return False, 1.0

    # Compare list lengths as a simple shape-stability signal.
    drift = abs(len(cur_vals) - len(prev_vals)) / max(len(prev_vals), 1)
    return drift <= threshold, drift

