"""
Top-level ShippingContract model.

Full hierarchy:

    ShippingContract          ← one row per negotiated carrier agreement
    ├── metadata              ← agreement number, carrier, shipper account, dates, status
    ├── service_terms[]       ← one ServiceTerm per service type in scope
    │   └── zone_rates[]      ← one ZoneRate per carrier zone
    │       └── tiers[]       ← weight brackets with base rates
    └── surcharges[]          ← all negotiated accessorial charges
        └── condition         ← applicability constraints per surcharge
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from .enums import Carrier, ContractStatus
from .pricing import ServiceTerm
from .surcharges import AccessorialCharge


class ContractMetadata(BaseModel):
    """
    Administrative details that identify and govern the contract.

    These fields come directly from the contract document header / cover page.
    """

    agreement_number: Annotated[
        str,
        Field(min_length=1, description="Carrier-assigned contract or agreement number."),
    ]
    carrier: Annotated[
        Carrier,
        Field(description="Carrier covered by this contract."),
    ]
    shipper_account_number: Annotated[
        str,
        Field(min_length=1, description="Shipper's carrier account number."),
    ]
    shipper_name: Annotated[
        str | None,
        Field(default=None, description="Legal name of the shipper / account holder."),
    ]

    # --- Term dates ---
    effective_date: Annotated[
        date,
        Field(description="Date on which the contract pricing takes effect."),
    ]
    expiration_date: Annotated[
        date | None,
        Field(
            default=None,
            description=(
                "Date on which the contract expires. None = evergreen / no stated end date."
            ),
        ),
    ]

    # --- Auto-renewal ---
    auto_renews: Annotated[
        bool,
        Field(
            default=False,
            description="Whether the contract auto-renews at expiration.",
        ),
    ]
    cancellation_notice_days: Annotated[
        int | None,
        Field(
            default=None,
            ge=0,
            description=(
                "Number of days' written notice required to cancel or opt out of auto-renewal. "
                "Typically 30, 60, or 90 days."
            ),
        ),
    ]

    # --- Status (computed or manually set) ---
    status: Annotated[
        ContractStatus,
        Field(
            default=ContractStatus.PENDING,
            description="Lifecycle status of this contract record.",
        ),
    ]

    @model_validator(mode="after")
    def expiration_after_effective(self) -> ContractMetadata:
        if (
            self.expiration_date is not None
            and self.expiration_date <= self.effective_date
        ):
            raise ValueError(
                f"expiration_date ({self.expiration_date}) must be after "
                f"effective_date ({self.effective_date})."
            )
        return self

    @model_validator(mode="after")
    def notice_requires_auto_renew(self) -> ContractMetadata:
        if self.cancellation_notice_days is not None and not self.auto_renews:
            raise ValueError(
                "cancellation_notice_days is set but auto_renews is False. "
                "Notice period only applies to auto-renewing contracts."
            )
        return self


class ShippingContract(BaseModel):
    """
    Complete, structured representation of one carrier shipping contract.

    This is the root model that downstream systems query for:
      - Invoice auditing: compare billed charges against net_rate() + surcharges
      - Contract comparison: diff two ShippingContract objects side-by-side
      - Rate shopping: select the cheapest service for a given shipment
    """

    metadata: ContractMetadata

    service_terms: Annotated[
        list[ServiceTerm],
        Field(
            min_length=1,
            description=(
                "Negotiated pricing terms, one per service type. "
                "Each entry contains the full zone/weight rate table and discount for that service."
            ),
        ),
    ]

    surcharges: Annotated[
        list[AccessorialCharge],
        Field(
            default_factory=list,
            description=(
                "All negotiated accessorial charges and fees. "
                "A contract with no surcharge modifications has an empty list — "
                "implying published rates apply unmodified."
            ),
        ),
    ]

    @model_validator(mode="after")
    def unique_service_types(self) -> ShippingContract:
        seen: set[str] = set()
        for term in self.service_terms:
            if term.service_type in seen:
                raise ValueError(
                    f"Duplicate service_type '{term.service_type}' in service_terms. "
                    "Each service type must appear at most once per contract."
                )
            seen.add(term.service_type)
        return self

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def service_term(self, service_type: str) -> ServiceTerm:
        """Return the ServiceTerm for a given service type, or raise KeyError."""
        for term in self.service_terms:
            if term.service_type == service_type:
                return term
        raise KeyError(f"Service type '{service_type}' not found in this contract.")

    def applicable_surcharges(
        self,
        service_type: str,
        zone: str,
        weight: Decimal,
        shipment_type: str = "COMMERCIAL",
    ) -> list[AccessorialCharge]:
        """
        Return all surcharge records that apply to a given shipment.

        Filters on:
          - condition.applicable_services (None = all)
          - condition.applicable_zones    (None = all)
          - condition.shipment_type       (None / 'ALL' = all)
          - condition.min_weight / max_weight
        """
        matches: list[AccessorialCharge] = []
        for surcharge in self.surcharges:
            c = surcharge.condition

            if c.applicable_services and service_type not in c.applicable_services:
                continue
            if c.applicable_zones and zone not in c.applicable_zones:
                continue
            if c.shipment_type and c.shipment_type != "ALL" and c.shipment_type != shipment_type:
                continue
            if c.min_weight is not None and weight < c.min_weight:
                continue
            if c.max_weight is not None and weight > c.max_weight:
                continue

            matches.append(surcharge)

        return matches
