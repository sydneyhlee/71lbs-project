-- =============================================================================
-- Shipping Contract Pricing Schema
-- =============================================================================
-- Hierarchy:
--   contracts
--   └── service_terms          (one per service type per contract)
--       └── zone_rates         (one per carrier zone per service term)
--           └── weight_tiers   (one per weight bracket per zone rate)
--   └── surcharges             (all accessorial charges for the contract)
--       └── surcharge_conditions (applicability constraints per surcharge)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- ENUMS
-- ---------------------------------------------------------------------------

CREATE TYPE carrier AS ENUM (
    'UPS', 'FEDEX', 'USPS', 'DHL', 'ONTRAC', 'LSO'
);

CREATE TYPE contract_status AS ENUM (
    'PENDING', 'ACTIVE', 'EXPIRED', 'TERMINATED'
);

CREATE TYPE service_type AS ENUM (
    'GROUND', 'HOME_DELIVERY', 'SMART_POST', 'SURE_POST',
    '2DAY', '2DAY_AM', 'EXPRESS_SAVER',
    'OVERNIGHT', 'PRIORITY_OVERNIGHT', 'STANDARD_OVERNIGHT', 'FIRST_OVERNIGHT',
    'INTERNATIONAL_ECONOMY', 'INTERNATIONAL_PRIORITY'
);

CREATE TYPE billing_weight_rounding AS ENUM (
    'NEXT_WHOLE_POUND', 'NEAREST_POUND', 'NEXT_HALF_POUND', 'ACTUAL'
);

CREATE TYPE charge_format AS ENUM (
    'PERCENTAGE',
    'FLAT_AMOUNT',
    'DIVISOR',
    'PER_POUND',
    'PER_PACKAGE',
    'PERCENTAGE_OF_CHARGE',
    'WAIVED'
);

CREATE TYPE modification_type AS ENUM (
    'DISCOUNT', 'WAIVER', 'MARKUP', 'OVERRIDE'
);

CREATE TYPE shipment_type AS ENUM (
    'RESIDENTIAL', 'COMMERCIAL', 'ALL'
);

-- ---------------------------------------------------------------------------
-- TABLE: contracts
-- ---------------------------------------------------------------------------
-- One row per negotiated carrier agreement.
-- ---------------------------------------------------------------------------

CREATE TABLE contracts (
    id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity
    agreement_number         TEXT        NOT NULL,
    carrier                  carrier     NOT NULL,
    shipper_account_number   TEXT        NOT NULL,
    shipper_name             TEXT,

    -- Term dates
    effective_date           DATE        NOT NULL,
    expiration_date          DATE,               -- NULL = evergreen

    -- Auto-renewal
    auto_renews              BOOLEAN     NOT NULL DEFAULT FALSE,
    cancellation_notice_days INTEGER     CHECK (cancellation_notice_days >= 0),

    -- Status
    status                   contract_status NOT NULL DEFAULT 'PENDING',

    -- Audit
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT uq_contract_agreement UNIQUE (carrier, agreement_number, shipper_account_number),
    CONSTRAINT chk_expiration_after_effective
        CHECK (expiration_date IS NULL OR expiration_date > effective_date),
    CONSTRAINT chk_notice_requires_auto_renew
        CHECK (cancellation_notice_days IS NULL OR auto_renews = TRUE)
);

-- ---------------------------------------------------------------------------
-- TABLE: service_terms
-- ---------------------------------------------------------------------------
-- One row per service type within a contract.
-- Stores discount and minimum charge; rate table lives in zone_rates/weight_tiers.
-- ---------------------------------------------------------------------------

CREATE TABLE service_terms (
    id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id              UUID        NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,

    service_type             service_type NOT NULL,

    -- Discount applied on top of published rates
    discount_percentage      NUMERIC(6,4) NOT NULL
                                 CHECK (discount_percentage >= 0 AND discount_percentage <= 100),

    -- Minimum net charge floor (USD), applied after discount
    minimum_charge           NUMERIC(10,4) NOT NULL
                                 CHECK (minimum_charge >= 0),

    -- Weight handling
    billing_weight_rounding  billing_weight_rounding NOT NULL DEFAULT 'NEXT_WHOLE_POUND',
    dim_divisor              NUMERIC(6,2)  CHECK (dim_divisor IS NULL OR dim_divisor >= 1),

    -- Audit
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_service_per_contract UNIQUE (contract_id, service_type)
);

-- ---------------------------------------------------------------------------
-- TABLE: zone_rates
-- ---------------------------------------------------------------------------
-- One row per carrier zone within a service term.
-- ---------------------------------------------------------------------------

CREATE TABLE zone_rates (
    id               UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    service_term_id  UUID    NOT NULL REFERENCES service_terms(id) ON DELETE CASCADE,

    -- Zone identifier as the carrier defines it (e.g., '2', '8', 'A', '902')
    zone             TEXT    NOT NULL CHECK (length(zone) >= 1),

    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_zone_per_service_term UNIQUE (service_term_id, zone)
);

-- ---------------------------------------------------------------------------
-- TABLE: weight_tiers
-- ---------------------------------------------------------------------------
-- One row per weight bracket within a zone rate.
-- Together, all tiers for a zone_rate must be non-overlapping and contiguous.
-- ---------------------------------------------------------------------------

CREATE TABLE weight_tiers (
    id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_rate_id    UUID          NOT NULL REFERENCES zone_rates(id) ON DELETE CASCADE,

    -- Weight bounds in pounds (inclusive on both ends; max_weight NULL = no upper limit)
    min_weight      NUMERIC(8,2)  NOT NULL CHECK (min_weight >= 0),
    max_weight      NUMERIC(8,2)            CHECK (max_weight IS NULL OR max_weight > min_weight),

    -- Published base rate in USD for this zone/weight combination
    base_rate       NUMERIC(10,4) NOT NULL  CHECK (base_rate >= 0),

    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_weight_tier UNIQUE (zone_rate_id, min_weight)
);

-- Prevent overlapping tiers within the same zone_rate (check via trigger or app layer)
-- The UNIQUE on (zone_rate_id, min_weight) catches exact duplicates;
-- gap/overlap detection is enforced in the application model (ZoneRate.tiers_non_overlapping_and_sorted).

-- ---------------------------------------------------------------------------
-- TABLE: surcharges
-- ---------------------------------------------------------------------------
-- One row per negotiated accessorial charge in a contract.
-- A single charge code (e.g., 'RES') can appear multiple times if different
-- terms apply per service or per zone.
-- ---------------------------------------------------------------------------

CREATE TABLE surcharges (
    id                UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id       UUID              NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,

    -- Identity
    charge_code       TEXT              NOT NULL CHECK (length(charge_code) >= 1),
    charge_name       TEXT              NOT NULL CHECK (length(charge_name) >= 1),

    -- Value
    charge_format     charge_format     NOT NULL,
    value             NUMERIC(12,6)     NOT NULL CHECK (value >= 0),

    -- Modification
    modification_type modification_type NOT NULL,

    -- Free-text notes from the contract
    notes             TEXT,

    -- Audit
    created_at        TIMESTAMPTZ       NOT NULL DEFAULT NOW(),

    -- Cross-field constraints
    CONSTRAINT chk_waived_value_is_zero
        CHECK (charge_format <> 'WAIVED' OR value = 0),
    CONSTRAINT chk_percentage_max_100
        CHECK (charge_format NOT IN ('PERCENTAGE', 'PERCENTAGE_OF_CHARGE') OR value <= 100)
);

-- ---------------------------------------------------------------------------
-- TABLE: surcharge_conditions
-- ---------------------------------------------------------------------------
-- Applicability constraints for a surcharge.
-- One-to-one with surcharges (each surcharge has exactly one condition record).
-- Stored separately to keep surcharges table narrow.
-- ---------------------------------------------------------------------------

CREATE TABLE surcharge_conditions (
    id               UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    surcharge_id     UUID          NOT NULL UNIQUE REFERENCES surcharges(id) ON DELETE CASCADE,

    -- Shipment type restriction
    shipment_type    shipment_type,  -- NULL = applies to all shipment types

    -- Weight range restriction (NULL = no restriction on that bound)
    min_weight       NUMERIC(8,2)  CHECK (min_weight IS NULL OR min_weight >= 0),
    max_weight       NUMERIC(8,2)  CHECK (max_weight IS NULL OR max_weight >= 0),

    -- Declared value restriction (e.g., insurance thresholds)
    min_declared_value NUMERIC(10,4) CHECK (min_declared_value IS NULL OR min_declared_value >= 0),

    -- Free-form catch-all for conditions not covered by structured fields
    custom_conditions  JSONB,

    CONSTRAINT chk_weight_range
        CHECK (min_weight IS NULL OR max_weight IS NULL OR max_weight > min_weight)
);

-- ---------------------------------------------------------------------------
-- TABLE: surcharge_service_scope
-- ---------------------------------------------------------------------------
-- Junction table: which service types a surcharge applies to.
-- No rows for a surcharge = applies to ALL services.
-- ---------------------------------------------------------------------------

CREATE TABLE surcharge_service_scope (
    surcharge_id  UUID         NOT NULL REFERENCES surcharges(id) ON DELETE CASCADE,
    service_type  service_type NOT NULL,
    PRIMARY KEY (surcharge_id, service_type)
);

-- ---------------------------------------------------------------------------
-- TABLE: surcharge_zone_scope
-- ---------------------------------------------------------------------------
-- Junction table: which carrier zones a surcharge applies to.
-- No rows for a surcharge = applies to ALL zones.
-- ---------------------------------------------------------------------------

CREATE TABLE surcharge_zone_scope (
    surcharge_id  UUID  NOT NULL REFERENCES surcharges(id) ON DELETE CASCADE,
    zone          TEXT  NOT NULL CHECK (length(zone) >= 1),
    PRIMARY KEY (surcharge_id, zone)
);

-- ---------------------------------------------------------------------------
-- INDEXES
-- ---------------------------------------------------------------------------

-- Quickly find all contracts for a carrier/shipper account
CREATE INDEX idx_contracts_carrier_account
    ON contracts (carrier, shipper_account_number);

-- Filter contracts by effective date range (for "what contract was active on date X")
CREATE INDEX idx_contracts_dates
    ON contracts (effective_date, expiration_date);

-- Service term lookups by contract
CREATE INDEX idx_service_terms_contract
    ON service_terms (contract_id);

-- Zone rate lookups by service term + zone
CREATE INDEX idx_zone_rates_service_zone
    ON zone_rates (service_term_id, zone);

-- Weight tier lookups by zone + weight
CREATE INDEX idx_weight_tiers_zone_weight
    ON weight_tiers (zone_rate_id, min_weight);

-- Surcharge lookups by contract and charge code
CREATE INDEX idx_surcharges_contract_code
    ON surcharges (contract_id, charge_code);
