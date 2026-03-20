# 71lbs-project
Contract extraction and invoice auditing for 71lbs by VCG.

## Carrier Contract Parsing Pipeline

Production-grade modular parser for FedEx and UPS agreements:

- `pdf_ingestion/`: `pdfplumber` text extraction with OCR fallback (`pytesseract` + `pdf2image`) and OCR cache
- `layout_parser/`: header/table/footnote-aware page layout segmentation
- `section_classifier/`: section typing (`service_pricing`, `surcharge`, `earned_discount`, `metadata`)
- `table_extractor/`: deterministic zone/weight/discount normalization from tables
- `llm_extractor/`: optional LLM-only pass for messy clauses and earned discount interpretation
- `post_processor/`: canonicalization, service merge, surcharge + earned discount shaping
- `validator/`: schema and quality checks with confidence score + issue list

### Run

```bash
python3 -m pip install -e ".[dev]"
python3 -m contract_parser.main /path/to/contract.pdf
```

### Final Output Shape

```json
{
  "contract": {},
  "confidence": 0.0,
  "raw_sections": []
}
```
