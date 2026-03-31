from enum import Enum


class Carrier(str, Enum):
    UPS = "UPS"
    FEDEX = "FEDEX"
    USPS = "USPS"
    DHL = "DHL"
    ONTRAC = "ONTRAC"
    LSO = "LSO"


class ContractStatus(str, Enum):
    PENDING = "PENDING"       # Not yet in effect
    ACTIVE = "ACTIVE"         # Currently effective
    EXPIRED = "EXPIRED"       # Past expiration date
    TERMINATED = "TERMINATED" # Manually ended before expiration


class ServiceType(str, Enum):
    # Ground
    GROUND = "GROUND"
    HOME_DELIVERY = "HOME_DELIVERY"
    SMART_POST = "SMART_POST"
    SURE_POST = "SURE_POST"

    # Express / Air
    TWO_DAY = "2DAY"
    TWO_DAY_AM = "2DAY_AM"
    EXPRESS_SAVER = "EXPRESS_SAVER"
    OVERNIGHT = "OVERNIGHT"
    PRIORITY_OVERNIGHT = "PRIORITY_OVERNIGHT"
    STANDARD_OVERNIGHT = "STANDARD_OVERNIGHT"
    FIRST_OVERNIGHT = "FIRST_OVERNIGHT"

    # International
    INTERNATIONAL_ECONOMY = "INTERNATIONAL_ECONOMY"
    INTERNATIONAL_PRIORITY = "INTERNATIONAL_PRIORITY"


class BillingWeightRounding(str, Enum):
    NEXT_WHOLE_POUND = "NEXT_WHOLE_POUND"   # Most common: ceil to nearest lb
    NEAREST_POUND = "NEAREST_POUND"          # Round half-up
    NEXT_HALF_POUND = "NEXT_HALF_POUND"
    ACTUAL = "ACTUAL"                        # No rounding (use exact weight)


class ChargeFormat(str, Enum):
    """How the surcharge value is applied to calculate a charge amount."""
    PERCENTAGE = "PERCENTAGE"       # value = % of base rate (e.g., 14.5 → 14.5%)
    FLAT_AMOUNT = "FLAT_AMOUNT"     # value = fixed dollar amount per package
    DIVISOR = "DIVISOR"             # value = divisor for DIM weight (e.g., 139)
    PER_POUND = "PER_POUND"         # value = $ per lb (e.g., oversize weight)
    PER_PACKAGE = "PER_PACKAGE"     # alias for FLAT_AMOUNT (semantic clarity)
    PERCENTAGE_OF_CHARGE = "PERCENTAGE_OF_CHARGE"  # % of a specific charge (e.g., 5% of fuel)
    WAIVED = "WAIVED"               # charge is fully waived; value is ignored


class ModificationType(str, Enum):
    """Whether this surcharge entry reduces, removes, or increases the published rate."""
    DISCOUNT = "DISCOUNT"   # Reduces the published surcharge (e.g., 20% off residential)
    WAIVER = "WAIVER"       # Eliminates the surcharge entirely
    MARKUP = "MARKUP"       # Increases above published (rare in negotiated contracts)
    OVERRIDE = "OVERRIDE"   # Replaces published rate with a fixed custom amount


class ShipmentType(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    ALL = "ALL"
