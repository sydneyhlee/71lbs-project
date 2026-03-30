# 71lbs-project
Contract extraction and invoice auditing for 71lbs by VCG.

## Contract PDF parser (canonical JSON)

This repo includes a baseline PDF contract parser that extracts:
- structured **pricing rules**
- **surcharge tables**
- **discount tiers**
- **service-level terms**
- plus the underlying segmented **sections**, **tables**, and **footnotes**

### Install

```bash
python3 -m pip install -e .
```

### Parse a PDF

```bash
contract-parse parse "/path/to/contract.pdf" --out contract.json
```

### Output shape

The parser emits a machine-readable JSON document (`schema_version: "1.0"`) with:
- `metadata.vendor_type`: `fedex | ups | 3pl | freight | unknown`
- `sections[]`: each section includes `raw_text`, `tables[]`, `footnotes[]` and extracted:
  - `extracted_pricing_rules[]`
  - `extracted_surcharge_tables[]`
  - `extracted_discount_tiers[]`
  - `extracted_service_terms[]`
