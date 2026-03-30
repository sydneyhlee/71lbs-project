from __future__ import annotations

from dataclasses import dataclass

from ..models import VendorType


@dataclass(frozen=True)
class VendorDetection:
    vendor_type: VendorType
    vendor_name: str | None
    confidence: float
    signals: list[str]


class VendorAdapter:
    vendor_type: VendorType = VendorType.UNKNOWN

    def detect(self, text: str) -> VendorDetection:
        raise NotImplementedError

