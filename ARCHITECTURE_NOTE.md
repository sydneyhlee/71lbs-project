# Agreement + Invoice Audit Architecture Note

## What changed

This implementation introduces a strict multi-stage flow:

1. **Stage 1 parser** (`extraction/extractor.py`) keeps deterministic extraction output.
2. **Stage 2 LLM verifier** (`app/pipeline/llm_verifier.py`) reviews parser output and applies only targeted corrections with:
   - `was_llm_corrected`
   - `original_parser_value`
   - `llm_corrected_value`
   - `correction_reason`
   - `confidence_rationale`
3. **Human approval gate** remains mandatory for invoice audit. The UI only audits against records in `approved` status.
4. **Invoice audit engine** (`app/invoice/audit.py`) parses invoice lines, compares to approved agreement discounts, classifies discrepancies, and exports:
   - JSON artifact
   - TXT report
   - UI report table
5. **Reference-data operations layer** (`scripts/*.py`, `app/reference/*`) adds:
   - Carrier feed ingestion scaffolds for fuel, DAS ZIPs, zone/transit maps, and service guides
   - Timestamped version snapshots in `data/reference/**/versions/`
   - Drift validation guardrails (`>5%` change protection)
6. **API-first invoice ingestion** (`app/invoice/carrier_api.py`, `app/invoice/ingest.py`) attempts FedEx/UPS billing API invoice pulls first and falls back to file parsing.
7. **Hard validation gate for invoice lines** (`validate_invoice_items`) blocks audit execution when required fields are missing (`ship_date`, `service_code`, `rated_weight_lbs`), forcing human review.
8. **Observability + freshness warnings**:
   - Persistent per-run audit telemetry in `data/audit_runs/`
   - UI freshness checks for stale/missing fuel and DAS references

## Why this design

- Keeps deterministic extraction backward compatible while adding correction quality.
- Preserves explainability and auditability via provenance + correction metadata.
- Enforces human-in-the-loop control before financial comparison logic runs.
- Uses deterministic discrepancy classification for audit outcomes; LLM assists extraction/normalization, not final billing math decisions.
- Introduces operational guardrails (freshness, drift checks, run logs) so downstream teams can trust outcomes and maintain the system post-handoff.

