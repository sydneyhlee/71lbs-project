from __future__ import annotations

import csv
from typing import Optional

from pydantic import BaseModel


class ParallelStudyRecord(BaseModel):
    shipment_id: str
    tracking_number: str
    ai_found_discrepancy: bool
    ai_discrepancy_type: Optional[str] = None
    ai_dollar_impact: Optional[float] = None
    human_found_discrepancy: bool
    human_discrepancy_type: Optional[str] = None
    human_dollar_impact: Optional[float] = None
    outcome: str = ""

    def model_post_init(self, __context):
        if self.ai_found_discrepancy and self.human_found_discrepancy:
            self.outcome = "TP"
        elif self.ai_found_discrepancy and not self.human_found_discrepancy:
            self.outcome = "FP"
        elif not self.ai_found_discrepancy and self.human_found_discrepancy:
            self.outcome = "FN"
        else:
            self.outcome = "TN"


def compute_metrics(records: list[ParallelStudyRecord]) -> dict:
    TP = sum(1 for r in records if r.outcome == "TP")
    FP = sum(1 for r in records if r.outcome == "FP")
    FN = sum(1 for r in records if r.outcome == "FN")
    TN = sum(1 for r in records if r.outcome == "TN")
    precision = TP / (TP + FP) if (TP + FP) > 0 else 0.0
    recall = TP / (TP + FN) if (TP + FN) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    ai_only_recovery = sum(r.ai_dollar_impact or 0 for r in records if r.outcome == "FP")
    return {
        "TP": TP,
        "FP": FP,
        "FN": FN,
        "TN": TN,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "total_records": len(records),
        "total_ai_recovery_potential": sum(r.ai_dollar_impact or 0 for r in records if r.ai_found_discrepancy),
        "total_human_recovery": sum(r.human_dollar_impact or 0 for r in records if r.human_found_discrepancy),
        "ai_only_additional_recovery": ai_only_recovery,
        "sow_recall_target_met": recall >= 0.90,
        "sow_additional_finds_target_met": ai_only_recovery > 0,
    }


def _parse_bool(raw: str) -> bool:
    return str(raw).strip().lower() in {"1", "true", "t", "yes", "y"}


def load_parallel_study_csv(path: str) -> list[ParallelStudyRecord]:
    """Load human-vs-AI comparison records from a CSV export."""
    records: list[ParallelStudyRecord] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(
                ParallelStudyRecord(
                    shipment_id=row.get("shipment_id", ""),
                    tracking_number=row.get("tracking_number", ""),
                    ai_found_discrepancy=_parse_bool(row.get("ai_found_discrepancy", "")),
                    ai_discrepancy_type=row.get("ai_discrepancy_type") or None,
                    ai_dollar_impact=float(row["ai_dollar_impact"]) if row.get("ai_dollar_impact") else None,
                    human_found_discrepancy=_parse_bool(row.get("human_found_discrepancy", "")),
                    human_discrepancy_type=row.get("human_discrepancy_type") or None,
                    human_dollar_impact=float(row["human_dollar_impact"]) if row.get("human_dollar_impact") else None,
                )
            )
    return records

