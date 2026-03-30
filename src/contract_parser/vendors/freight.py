from __future__ import annotations

import re

from .base import VendorAdapter, VendorDetection
from ..models import VendorType


class FreightAdapter(VendorAdapter):
    vendor_type = VendorType.FREIGHT

    def detect(self, text: str) -> VendorDetection:
        t = text.lower()
        signals: list[str] = []
        score = 0.0
        if any(k in t for k in ("ltl", "less-than-truckload", "nmfc", "class 50", "class 55", "class 60", "class 65", "class 70", "class 77.5", "class 85", "class 92.5", "class 100")):
            score += 0.55
            signals.append("keyword:ltl_nmfc_class")
        if re.search(r"\b(fuel\s+surcharge|accessorial|rebill|reweigh|reclass)\b", t):
            score += 0.25
            signals.append("keyword:freight_accessorial")
        if "bill of lading" in t or "bol" in t:
            score += 0.1
            signals.append("keyword:bol")
        return VendorDetection(vendor_type=self.vendor_type, vendor_name=None, confidence=min(score, 1.0), signals=signals)

