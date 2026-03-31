"""
Surcharge and accessorial charge models.

Each AccessorialCharge record captures one negotiated surcharge entry from a
contract. The same carrier charge code can appear multiple times if the contract
specifies different terms per service or per zone (e.g., residential delivery
waived for GROUND but discounted 20% for 2DAY).

Charge calculation logic:
    PERCENTAGE   → charge = base_rate × (value / 100)
    FLAT_AMOUNT  → charge = value  (per package)
    PER_POUND    → charge = value × billable_weight
    DIVISOR      → not a charge; used as DIM divisor override on ServiceTerm
    WAIVED       → charge = 0
    PERCENTAGE_OF_CHARGE → charge = referenced_charge_amount × (value / 100)

Modification semantics (how this record relates to the published rate):
    DISCOUNT  → contract pays (published - discount_amount) or published × (1 - pct/100)
    WAIVER    → contract pays 0 regardless of published rate
    MARKUP    → contract pays more than published (rare)
    OVERRIDE  → contract pays exactly `value` regardless of published rate
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Well-known charge codes for the most common accessorial charges.
# These match carrier-published codes; unknown codes are stored as raw strings.
# ---------------------------------------------------------------------------

KNOWN_CHARGE_CODES: dict[str, str] = {
    # FedEx / UPS equivalents
    "RES": "Residential Delivery Surcharge",
    "FSC": "Fuel Surcharge",
    "DAS": "Delivery Area Surcharge",
    "EDAS": "Extended Delivery Area Surcharge",
    "RDAS": "Remote Delivery Area Surcharge",
    "AHS": "Additional Handling Surcharge",
    "OSP1": "Oversize Package (Tier 1)",
    "OSP2": "Oversize Package (Tier 2)",
    "SIGSVC": "Signature Required Service",
    "ADSIG": "Adult Signature Required",
    "SAT": "Saturday Delivery",
    "SUN": "Sunday / Holiday Delivery",
    "RET": "Return Shipment",
    "COD": "Collect on Delivery",
    "INSURE": "Declared Value / Insurance",
    "ADDR": "Address Correction",
    "HB": "Hundredweight / Multi-piece Discount",
    "PEAK": "Peak / Demand Surcharge",
}


class SurchargeCondition(BaseModel):
    """
    Structured conditions under which a surcharge applies.

    All fields are optional — only specify the ones that constrain applicability.
    Omitted fields mean "no restriction on this dimension."

    Examples:
        SurchargeCondition(shipment_type="RESIDENTIAL")
            → only on residential deliveries

        SurchargeCondition(applicable_services=["GROUND"], zones=["5","6","7","8"])
            → only on GROUND shipments to zones 5–8

        SurchargeCondition(min_weight=Decimal("151"))
            → only on shipments over 150 lbs (oversize threshold)
    """

    shipment_type: Annotated[
        str | None,
        Field(
            default=None,
            description="ShipmentType enum: 'RESIDENTIAL', 'COMMERCIAL', or 'ALL'.",
        ),
    ]

    applicable_services: Annotated[
        list[str] | None,
        Field(
            default=None,
            description=(
                "List of ServiceType values this surcharge applies to. "
                "None = applies to all services in the contract."
            ),
        ),
    ]

    applicable_zones: Annotated[
        list[str] | None,
        Field(
            default=None,
            description=(
                "Carrier zone identifiers this surcharge applies to. "
                "None = applies to all zones."
            ),
        ),
    ]

    min_weight: Annotated[
        Decimal | None,
        Field(default=None, ge=0, description="Minimum billable weight (lbs) for this charge to apply."),
    ]

    max_weight: Annotated[
        Decimal | None,
        Field(default=None, ge=0, description="Maximum billable weight (lbs) for this charge to apply."),
    ]

    min_declared_value: Annotated[
        Decimal | None,
        Field(default=None, ge=0, description="Minimum declared value (USD) for this charge to apply (e.g., insurance thresholds)."),
    ]

    custom_conditions: Annotated[
        dict[str, str] | None,
        Field(
            default=None,
            description=(
                "Catch-all for contract-specific conditions not captured by structured fields. "
                "Keys are condition names; values are free-text descriptions. "
                "Example: {'package_type': 'non-machinable', 'origin_state': 'AK'}."
            ),
        ),
    ]

    @model_validator(mode="after")
    def weight_range_valid(self) -> SurchargeCondition:
        if (
            self.min_weight is not None
            and self.max_weight is not None
            and self.max_weight <= self.min_weight
        ):
            raise ValueError(
                f"max_weight ({self.max_weight}) must be greater than min_weight ({self.min_weight})."
            )
        return self


class AccessorialCharge(BaseModel):
    """
    One negotiated accessorial / surcharge entry from a shipping contract.

    A contract may contain many AccessorialCharge records. They are aggregated
    on ShippingContract.surcharges.

    --- How to read a record ---

    charge_format + value define HOW to compute the dollar amount of this charge.
    modification_type defines HOW this record relates to the carrier's published rate.

    Example 1 — Residential delivery discounted 20%:
        charge_code      = "RES"
        charge_name      = "Residential Delivery Surcharge"
        charge_format    = PERCENTAGE          (the surcharge is expressed as % of base)
        value            = Decimal("20")       (20% discount off the published RES surcharge)
        modification_type = DISCOUNT

    Example 2 — Fuel surcharge fully waived for GROUND:
        charge_code      = "FSC"
        charge_name      = "Fuel Surcharge"
        charge_format    = WAIVED
        value            = Decimal("0")
        modification_type = WAIVER
        condition.applicable_services = ["GROUND"]

    Example 3 — Flat $4.50 residential fee (overriding published rate):
        charge_code      = "RES"
        charge_format    = FLAT_AMOUNT
        value            = Decimal("4.50")
        modification_type = OVERRIDE
    """

    # --- Identity ---
    charge_code: Annotated[
        str,
        Field(min_length=1, description="Carrier-assigned charge code (e.g., 'RES', 'FSC', 'DAS')."),
    ]
    charge_name: Annotated[
        str,
        Field(min_length=1, description="Human-readable name of the surcharge."),
    ]

    # --- Value ---
    charge_format: Annotated[
        str,
        Field(description="ChargeFormat enum: how `value` is interpreted."),
    ]
    value: Annotated[
        Decimal,
        Field(ge=0, description="Numeric value of the charge (meaning depends on charge_format)."),
    ]

    # --- Modification ---
    modification_type: Annotated[
        str,
        Field(
            description=(
                "ModificationType enum: whether this entry discounts, waives, "
                "marks up, or overrides the published surcharge."
            ),
        ),
    ]

    # --- Applicability ---
    condition: Annotated[
        SurchargeCondition,
        Field(
            default_factory=SurchargeCondition,
            description=(
                "Conditions that restrict when this surcharge applies. "
                "An empty SurchargeCondition() means the surcharge applies universally."
            ),
        ),
    ]

    # --- Notes ---
    notes: Annotated[
        str | None,
        Field(
            default=None,
            description="Free-text notes extracted from the contract (e.g., 'applies only to Alaska and Hawaii')."),
    ]

    @model_validator(mode="after")
    def waived_value_is_zero(self) -> AccessorialCharge:
        if self.charge_format == "WAIVED" and self.value != Decimal("0"):
            raise ValueError(
                "charge_format=WAIVED implies value must be 0 (or omitted). "
                f"Got value={self.value}."
            )
        return self

    @model_validator(mode="after")
    def percentage_value_in_range(self) -> AccessorialCharge:
        if self.charge_format in ("PERCENTAGE", "PERCENTAGE_OF_CHARGE"):
            if self.value > Decimal("100"):
                raise ValueError(
                    f"Percentage value {self.value} exceeds 100%. "
                    "Did you mean to use FLAT_AMOUNT or a different charge_format?"
                )
        return self
