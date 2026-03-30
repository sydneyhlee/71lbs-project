"""
Example: build and query a ShippingContract.

Scenario: a negotiated UPS contract with:
  - GROUND service, 10% discount, $8.00 minimum
  - Residential delivery discounted 20%
  - Fuel surcharge fully waived on GROUND
  - DAS applies at published rate (no modification → not listed)
"""

from datetime import date
from decimal import Decimal

from models import (
    AccessorialCharge,
    BillingWeightRounding,
    Carrier,
    ChargeFormat,
    ContractStatus,
    ModificationType,
    ServiceType,
    ShipmentType,
    ShippingContract,
)
from models.contract import ContractMetadata
from models.pricing import ServiceTerm, WeightTier, ZoneRate
from models.surcharges import SurchargeCondition


# ------------------------------------------------------------------
# 1. Build the rate table for GROUND service
# ------------------------------------------------------------------

ground_zone2 = ZoneRate(
    zone="2",
    tiers=[
        WeightTier(min_weight=Decimal("0"), max_weight=Decimal("1"), base_rate=Decimal("9.42")),
        WeightTier(min_weight=Decimal("1"), max_weight=Decimal("2"), base_rate=Decimal("10.18")),
        WeightTier(min_weight=Decimal("2"), max_weight=Decimal("5"), base_rate=Decimal("11.65")),
        WeightTier(min_weight=Decimal("5"), max_weight=None,         base_rate=Decimal("14.20")),
    ],
)

ground_zone5 = ZoneRate(
    zone="5",
    tiers=[
        WeightTier(min_weight=Decimal("0"), max_weight=Decimal("1"), base_rate=Decimal("12.10")),
        WeightTier(min_weight=Decimal("1"), max_weight=Decimal("2"), base_rate=Decimal("13.55")),
        WeightTier(min_weight=Decimal("2"), max_weight=Decimal("5"), base_rate=Decimal("15.80")),
        WeightTier(min_weight=Decimal("5"), max_weight=None,         base_rate=Decimal("19.40")),
    ],
)

ground_term = ServiceTerm(
    service_type=ServiceType.GROUND,
    discount_percentage=Decimal("10"),   # 10% off published rates
    minimum_charge=Decimal("8.00"),
    billing_weight_rounding=BillingWeightRounding.NEXT_WHOLE_POUND,
    dim_divisor=Decimal("139"),
    zone_rates=[ground_zone2, ground_zone5],
)

# ------------------------------------------------------------------
# 2. Surcharges
# ------------------------------------------------------------------

residential_discount = AccessorialCharge(
    charge_code="RES",
    charge_name="Residential Delivery Surcharge",
    charge_format=ChargeFormat.PERCENTAGE,
    value=Decimal("20"),                   # 20% discount off published RES rate
    modification_type=ModificationType.DISCOUNT,
    condition=SurchargeCondition(
        shipment_type=ShipmentType.RESIDENTIAL,
        applicable_services=[ServiceType.GROUND],
    ),
)

fuel_waiver = AccessorialCharge(
    charge_code="FSC",
    charge_name="Fuel Surcharge",
    charge_format=ChargeFormat.WAIVED,
    value=Decimal("0"),
    modification_type=ModificationType.WAIVER,
    condition=SurchargeCondition(
        applicable_services=[ServiceType.GROUND],
    ),
)

# ------------------------------------------------------------------
# 3. Assemble the contract
# ------------------------------------------------------------------

contract = ShippingContract(
    metadata=ContractMetadata(
        agreement_number="UPS-2024-00123",
        carrier=Carrier.UPS,
        shipper_account_number="1Z999AA10123456784",
        shipper_name="Acme Corp",
        effective_date=date(2024, 1, 1),
        expiration_date=date(2025, 12, 31),
        auto_renews=True,
        cancellation_notice_days=30,
        status=ContractStatus.ACTIVE,
    ),
    service_terms=[ground_term],
    surcharges=[residential_discount, fuel_waiver],
)

# ------------------------------------------------------------------
# 4. Pricing queries
# ------------------------------------------------------------------

# Net rate for a 3-lb GROUND package to zone 5
net = contract.service_term(ServiceType.GROUND).net_rate(
    zone="5",
    weight=Decimal("3"),
)
print(f"Net rate (GROUND, zone 5, 3 lb): ${net:.4f}")
# base = $15.80, after 10% discount = $14.22 → above $8.00 minimum

# Which surcharges apply to a residential GROUND package to zone 5?
applicable = contract.applicable_surcharges(
    service_type=ServiceType.GROUND,
    zone="5",
    weight=Decimal("3"),
    shipment_type=ShipmentType.RESIDENTIAL,
)
for s in applicable:
    print(f"  Surcharge: {s.charge_name} ({s.modification_type}) — {s.charge_format} {s.value}")
