from __future__ import annotations

from typing import Any

from contract_parser.types import Contract


def _validate_pricing(contract: Contract) -> list[str]:
    issues: list[str] = []
    for s in contract.services:
        for p in s.pricing:
            if p.discount is not None and not (0.0 <= p.discount <= 100.0):
                issues.append(f"invalid discount for {s.service_name}")
            if p.weight_range != "all":
                if p.weight_range.min > p.weight_range.max:
                    issues.append(f"invalid weight range for {s.service_name}")
            if p.zones != "all":
                if any(z < 1 or z > 8 for z in p.zones):
                    issues.append(f"invalid zones for {s.service_name}")
    return issues


def _required_field_issues(contract_dict: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    metadata = contract_dict.get("metadata", {})
    for key in ("carrier", "customer_name", "agreement_number", "effective_date"):
        if key not in metadata:
            issues.append(f"missing metadata.{key}")
    return issues


def validate(contract: Contract) -> dict[str, Any]:
    issues = []
    issues.extend(_validate_pricing(contract))
    issues.extend(_required_field_issues(contract.model_dump()))
    confidence = max(0.0, min(1.0, 1.0 - (0.07 * len(issues))))
    return {"confidence": confidence, "issues": issues}
