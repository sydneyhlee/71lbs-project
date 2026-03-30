from __future__ import annotations

from .base import VendorAdapter, VendorDetection
from ..models import VendorType


class ThreePLAdapter(VendorAdapter):
    vendor_type = VendorType.THREE_PL

    def detect(self, text: str) -> VendorDetection:
        t = text.lower()
        signals: list[str] = []
        score = 0.0
        if any(k in t for k in ("warehouse", "pick and pack", "pick/pack", "kitting", "storage fee", "pallet in", "pallet out", "fulfillment", "receiving", "handling fee")):
            score += 0.65
            signals.append("keyword:3pl_ops")
        if any(k in t for k in ("sla", "service level agreement", "order cutoff", "same day shipping")):
            score += 0.2
            signals.append("keyword:sla")
        if "monthly minimum" in t or "minimum monthly" in t:
            score += 0.1
            signals.append("keyword:monthly_minimum")
        return VendorDetection(vendor_type=self.vendor_type, vendor_name=None, confidence=min(score, 1.0), signals=signals)

