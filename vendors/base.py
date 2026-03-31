from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VendorType(str, Enum):
    FEDEX = "fedex"
    UPS = "ups"
    THREE_PL = "3pl"
    FREIGHT = "freight"
    UNKNOWN = "unknown"


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
