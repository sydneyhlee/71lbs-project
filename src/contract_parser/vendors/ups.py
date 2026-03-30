from __future__ import annotations

import re

from .base import VendorAdapter, VendorDetection
from ..models import VendorType


class UPSAdapter(VendorAdapter):
    vendor_type = VendorType.UPS

    def detect(self, text: str) -> VendorDetection:
        t = text.lower()
        signals: list[str] = []
        score = 0.0
        if "ups" in t or "united parcel service" in t:
            score += 0.6
            signals.append("keyword:ups")
        if re.search(r"\bups\s+(ground|air|freight)\b", t):
            score += 0.25
            signals.append("keyword:ups_service")
        if "ups tariff" in t or "tariff" in t and "ups" in t:
            score += 0.15
            signals.append("keyword:tariff")
        return VendorDetection(vendor_type=self.vendor_type, vendor_name="UPS", confidence=min(score, 1.0), signals=signals)

