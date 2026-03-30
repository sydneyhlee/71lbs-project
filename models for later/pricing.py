"""
Core pricing models.

Hierarchy:
    ServiceTerm
    └── ZoneRate (one per zone)
        └── WeightTier (one per weight bracket within that zone)

A ServiceTerm captures all negotiated pricing for one service (e.g., GROUND)
within a contract, including the discount applied on top of published rates,
the minimum charge floor, and the full zone/weight rate table.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator


class WeightTier(BaseModel):
    """
    A single row in a rate table: the base rate for shipments that fall
    within [min_weight, max_weight] pounds for a given zone.

    Weight thresholds are in pounds. max_weight=None means "and above."
    """

    min_weight: Annotated[Decimal, Field(ge=0, description="Lower bound (lbs), inclusive")]
    max_weight: Annotated[Decimal | None, Field(
        default=None,
        description="Upper bound (lbs), inclusive. None = no upper limit.",
    )]
    base_rate: Annotated[Decimal, Field(ge=0, description="Published base rate in USD for this tier")]

    @model_validator(mode="after")
    def max_exceeds_min(self) -> WeightTier:
        if self.max_weight is not None and self.max_weight <= self.min_weight:
            raise ValueError(
                f"max_weight ({self.max_weight}) must be greater than "
                f"min_weight ({self.min_weight})"
            )
        return self


class ZoneRate(BaseModel):
    """
    Published rates for one carrier zone within a service.

    zone: carrier-assigned zone identifier (e.g., "2", "8", "902" for ground;
          "A", "B" for some air services).
    tiers: weight brackets, ordered by min_weight ascending, must be non-overlapping
           and together cover all expected shipment weights without gaps.
    """

    zone: Annotated[str, Field(min_length=1, description="Carrier zone identifier")]
    tiers: Annotated[
        list[WeightTier],
        Field(min_length=1, description="Weight tiers sorted by min_weight ascending"),
    ]

    @field_validator("tiers")
    @classmethod
    def tiers_non_overlapping_and_sorted(cls, tiers: list[WeightTier]) -> list[WeightTier]:
        sorted_tiers = sorted(tiers, key=lambda t: t.min_weight)

        for i in range(len(sorted_tiers) - 1):
            current = sorted_tiers[i]
            nxt = sorted_tiers[i + 1]

            if current.max_weight is None:
                raise ValueError(
                    f"Tier with min_weight={current.min_weight} has no max_weight "
                    f"but is not the last tier."
                )
            # Adjacent tiers must be contiguous: current.max_weight + smallest unit = next.min_weight
            # We enforce that next tier starts where current ends (no gap, no overlap).
            if nxt.min_weight != current.max_weight:
                raise ValueError(
                    f"Gap or overlap between tiers: tier ending at {current.max_weight} "
                    f"followed by tier starting at {nxt.min_weight}."
                )

        return sorted_tiers

    def rate_for_weight(self, weight: Decimal) -> Decimal:
        """Return the base rate for a given shipment weight in this zone."""
        for tier in self.tiers:
            if tier.min_weight <= weight and (
                tier.max_weight is None or weight <= tier.max_weight
            ):
                return tier.base_rate
        raise ValueError(f"No tier found for weight={weight} in zone={self.zone}")


class ServiceTerm(BaseModel):
    """
    Negotiated pricing terms for one service type within a contract.

    The effective rate for a shipment is calculated as:
        net_rate = max(base_rate × (1 - discount_percentage/100), minimum_charge)

    where base_rate comes from the zone_rates table lookup.
    """

    service_type: Annotated[str, Field(description="ServiceType enum value (e.g., 'GROUND')")]

    # --- Discount ---
    discount_percentage: Annotated[
        Decimal,
        Field(
            ge=0,
            le=100,
            description="Percentage discount off the published base rate (0–100).",
        ),
    ]

    # --- Floor ---
    minimum_charge: Annotated[
        Decimal,
        Field(ge=0, description="Minimum net charge in USD, applied after discount."),
    ]

    # --- Weight handling ---
    billing_weight_rounding: Annotated[
        str,
        Field(
            default="NEXT_WHOLE_POUND",
            description="BillingWeightRounding enum: how fractional weights are rounded.",
        ),
    ]

    dim_divisor: Annotated[
        Decimal | None,
        Field(
            default=None,
            ge=1,
            description=(
                "DIM weight divisor (cubic inches / divisor = DIM weight in lbs). "
                "Commonly 139 (UPS/FedEx domestic) or 166 (international). "
                "None means DIM weight is not applied for this service."
            ),
        ),
    ]

    # --- Rate table ---
    zone_rates: Annotated[
        list[ZoneRate],
        Field(min_length=1, description="Rate table: one ZoneRate entry per carrier zone."),
    ]

    @field_validator("zone_rates")
    @classmethod
    def unique_zones(cls, zone_rates: list[ZoneRate]) -> list[ZoneRate]:
        seen: set[str] = set()
        for zr in zone_rates:
            if zr.zone in seen:
                raise ValueError(f"Duplicate zone '{zr.zone}' in zone_rates.")
            seen.add(zr.zone)
        return zone_rates

    def net_rate(self, zone: str, weight: Decimal) -> Decimal:
        """
        Calculate the negotiated net rate for a shipment.

        1. Look up the published base rate from the zone/weight table.
        2. Apply the contracted discount.
        3. Apply the minimum charge floor.
        """
        zone_map = {zr.zone: zr for zr in self.zone_rates}
        if zone not in zone_map:
            raise ValueError(f"Zone '{zone}' not found in service term for {self.service_type}.")

        base = zone_map[zone].rate_for_weight(weight)
        discounted = base * (1 - self.discount_percentage / Decimal("100"))
        return max(discounted, self.minimum_charge)
