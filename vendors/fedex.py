from __future__ import annotations

import re

from .base import VendorAdapter, VendorDetection, VendorType


class FedExAdapter(VendorAdapter):
    vendor_type = VendorType.FEDEX

    def detect(self, text: str) -> VendorDetection:
        t = text.lower()
        signals: list[str] = []
        score = 0.0
        if "fedex" in t or "federal express" in t:
            score += 0.6
            signals.append("keyword:fedex")
        if re.search(r"\bfedex\s+(express|ground|freight)\b", t):
            score += 0.25
            signals.append("keyword:fedex_service")
        if "service guide" in t and "fedex" in t:
            score += 0.15
            signals.append("keyword:service_guide")
        return VendorDetection(vendor_type=self.vendor_type, vendor_name="FedEx", confidence=min(score, 1.0), signals=signals)
