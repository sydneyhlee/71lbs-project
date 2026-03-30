from __future__ import annotations

from .base import VendorAdapter, VendorDetection
from .fedex import FedExAdapter
from .freight import FreightAdapter
from .three_pl import ThreePLAdapter
from .ups import UPSAdapter
from ..models import VendorType


ALL_ADAPTERS: list[VendorAdapter] = [
    FedExAdapter(),
    UPSAdapter(),
    ThreePLAdapter(),
    FreightAdapter(),
]


def detect_vendor(document_text: str) -> VendorDetection:
    best = VendorDetection(vendor_type=VendorType.UNKNOWN, vendor_name=None, confidence=0.0, signals=[])
    for adapter in ALL_ADAPTERS:
        det = adapter.detect(document_text)
        if det.confidence > best.confidence:
            best = det
    return best

