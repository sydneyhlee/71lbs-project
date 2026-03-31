# 71lbs Contract Extraction Pipeline

Unified contract extraction and invoice auditing system for 71lbs by VCG.

Converts FedEx and UPS contract PDFs into structured JSON for pricing analysis and auditing.

## Architecture

The pipeline has three integrated stages:

### 1. Parsing (ingestion/)
- PDF text extraction via pdfplumber with OCR fallback (pytesseract + pdf2image)
- Layout-aware header/table/paragraph detection with font analysis
- Section classification (PRICING, SURCHARGE, TERMS, BOILERPLATE)

### 2. Extraction (extraction/)
- Deterministic table parsing for zone/weight/discount tables
- FedEx and UPS format support
- Metadata extraction (customer, account, dates, carrier)
- Surcharge modification parsing
- DIM divisor and earned discount detection
- LLM fallback only for ambiguous text (Ollama/OpenAI/Groq compatible)

### 3. Validation (validation/)
- Schema consistency checks
- Missing field detection
- Confidence scoring (extraction quality + normalization completeness)
- Issue tracking with severity levels (error/warning/info)
- Service name and percent normalization

### Supporting Modules
- **vendors/** — Carrier detection (FedEx, UPS, 3PL, Freight)
- **domain_models/** — Future DB-ready domain models (ShippingContract, pricing, surcharges)
- **app/** — FastAPI REST API + Streamlit review UI

## Quick Start

### Install Dependencies

```bash
pip install -r requirements.txt
```

### For LLM fallback (optional)

```bash
ollama pull llama3.2
cp .env.example .env
```

### Run Extraction on a PDF

```bash
python run_pipeline.py "path/to/contract.pdf"
python run_pipeline.py "path/to/contract.pdf" --output result.json
```

### Run Parse-Only (no extraction)

```bash
python run_ingestion.py "path/to/contract.pdf"
```

### Start the API

```bash
python run_api.py
```

API docs: http://localhost:8000/docs

### Start the Review UI

```bash
python run_ui.py
```

Streamlit UI: http://localhost:8501

## What It Extracts

- **Metadata**: customer name, account number, agreement number, dates, carrier
- **Service Terms**: service type, zones, discount percentages, weight conditions
- **Surcharges**: surcharge name, application, modification details
- **DIM Rules**: dimensional weight divisors and applicable services
- **Special Terms**: money-back guarantee waivers, payment terms, earned discounts
- **Amendments**: amendment detection, effective dates, superseded versions

## Output

The pipeline produces a `ContractExtraction` JSON with:
- Every field wrapped in `ExtractedValue` carrying confidence, source page, and source text
- Validation issues with severity codes
- Confidence breakdown (extraction, normalization, validation penalty)
- Amendment-resolved active terms snapshot

## Project Structure

```
├── run_pipeline.py          # Full pipeline CLI
├── run_ingestion.py         # Parse-only CLI
├── run_api.py               # FastAPI server
├── run_ui.py                # Streamlit UI
│
├── ingestion/               # PDF parsing (Parsing Team)
│   ├── pdf_reader.py        # Raw page extraction + OCR
│   ├── layout_parser.py     # Header/table/paragraph detection
│   ├── section_classifier.py # Section type classification
│   └── document.py          # Data models
│
├── extraction/              # Data extraction (Extraction Team)
│   ├── extractor.py         # Main extraction engine
│   ├── table_parser.py      # Deterministic table parsing
│   └── metadata_extractor.py # Metadata regex extraction
│
├── validation/              # Validation (Validation Team)
│   ├── validators.py        # Issue detection
│   ├── confidence.py        # Confidence scoring
│   ├── normalization.py     # Service name/percent/weight normalization
│   ├── models.py            # Issue and summary models
│   └── issues.py            # Issue code constants
│
├── vendors/                 # Carrier detection
├── domain_models/           # Future domain models
├── app/                     # FastAPI + Streamlit
│   ├── api/routes.py        # REST endpoints
│   ├── models/schema.py     # Extraction schema
│   ├── pipeline/            # Pipeline utilities
│   ├── review/ui.py         # Streamlit review UI
│   └── storage/store.py     # JSON file storage
│
├── data/samples/            # Sample extraction outputs
└── tests/
```
