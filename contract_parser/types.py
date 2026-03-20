from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


Carrier = Literal["fedex", "ups", "other"]
ServiceType = Literal["express", "ground", "freight", "international"]


class Metadata(BaseModel):
    carrier: Carrier = "other"
    customer_name: str = ""
    agreement_number: str = ""
    effective_date: str = ""


class WeightRange(BaseModel):
    min: float
    max: float

    @model_validator(mode="after")
    def validate_range(self) -> "WeightRange":
        if self.min > self.max:
            raise ValueError("weight min must be <= max")
        return self


class PricingRule(BaseModel):
    zones: list[int] | Literal["all"] = "all"
    weight_range: WeightRange | Literal["all"] = "all"
    discount: float | None = None
    net_rate: float | None = None


class Tier(BaseModel):
    spend_range: tuple[float, float]
    discount: float


class EarnedDiscount(BaseModel):
    services: list[str] = Field(default_factory=list)
    tiers: list[Tier] = Field(default_factory=list)
    grace_discount: float | None = None


class Surcharge(BaseModel):
    type: str
    discount: float | None = None
    amount: float | None = None


class Commitments(BaseModel):
    revenue_commitments: list[dict[str, Any]] = Field(default_factory=list)
    volume_commitments: list[dict[str, Any]] = Field(default_factory=list)


class Service(BaseModel):
    service_name: str
    service_type: ServiceType = "ground"
    pricing: list[PricingRule] = Field(default_factory=list)
    minimums: list[dict[str, Any]] = Field(default_factory=list)
    surcharges: list[Surcharge] = Field(default_factory=list)


class Contract(BaseModel):
    metadata: Metadata
    services: list[Service] = Field(default_factory=list)
    earned_discounts: list[EarnedDiscount] = Field(default_factory=list)
    surcharges: list[Surcharge] = Field(default_factory=list)
    commitments: Commitments = Field(default_factory=Commitments)


class PipelineOutput(BaseModel):
    contract: Contract
    confidence: float
    raw_sections: list[dict[str, Any]]
