# 71lbs Contract Extraction Pipeline

Extracts structured pricing data from FedEx and UPS shipping contract PDFs.

## How It Works (The Short Version)

The pipeline takes a contract PDF and turns it into clean, structured JSON data. Here's the flow:

```
  PDF file
    │
    ▼
┌──────────────┐
│  1. PARSE    │  pdfplumber reads the PDF → text + tables per page
│  (pdf_parser)│  Falls back to OCR (pytesseract) for scanned PDFs
└──────┬───────┘
       │  ParsedDocument (pages with text + table data)
       ▼
┌──────────────┐
│  2. EXTRACT  │  Deterministic regex/table logic pulls out:
│  (extractor) │   • Service terms (zones, weight tiers, discounts)
│              │   • Surcharge modifications (e.g., "- 50%")
│              │   • DIM divisor rules (e.g., 194, 225)
│              │   • Earned discount programs (grace periods, tiers)
│              │   • Special terms (Money-Back Guarantee waivers)
│              │   • Contract metadata (customer, account, carrier)
│              │  LLM (OpenAI) only used as fallback for ambiguous text
└──────┬───────┘
       │  ContractExtraction (structured Pydantic model)
       ▼
┌──────────────┐
│  3. SCORE    │  Checks each field's confidence (0.0–1.0)
│  (confidence)│  Flags anything below threshold for human review
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  4. RESOLVE  │  If the doc is an amendment, applies changes
│  (resolver)  │  to create an active_terms_snapshot
└──────┬───────┘
       │
       ▼
   JSON output
```

Every extracted field is wrapped in an `ExtractedValue` that tracks:
- `value` — the actual data
- `confidence` — how sure we are (0.0 to 1.0)
- `source_page` — which PDF page it came from
- `source_text` — the raw text snippet for provenance

## Project Structure

```
71lbs-project/
├── app/                          # Base system (shared across teams)
│   ├── models/schema.py          # Canonical Pydantic schema
│   ├── pipeline/
│   │   ├── pdf_parser.py         # PDF → text + tables (Parsing Team)
│   │   ├── chunker.py            # Splits docs for LLM processing
│   │   ├── extractor.py          # Original LLM-only extractor
│   │   ├── confidence.py         # Confidence scoring (Validation Team)
│   │   ├── resolver.py           # Amendment resolution
│   │   └── ingestion.py          # Full pipeline orchestrator
│   ├── api/routes.py             # REST API endpoints
│   ├── storage/store.py          # JSON file persistence
│   └── review/ui.py              # Streamlit review UI
│
├── extraction_v2/                # Refined extraction (Aidan & Aria)
│   ├── table_parser.py           # Deterministic table parsing
│   ├── metadata_extractor.py     # Regex-based metadata extraction
│   ├── extractor.py              # Main extraction engine (v2)
│   └── run_pipeline.py           # Test runner
│
├── data/samples/                 # Example JSON outputs
├── requirements.txt
└── .env.example
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run extraction on a PDF
python -m extraction_v2.run_pipeline path/to/contract.pdf

# 3. Output is saved to extraction_v2/test_outputs/
```

No OpenAI API key needed — the pipeline uses deterministic logic first. Set `OPENAI_API_KEY` in a `.env` file only if you want LLM fallback for documents the regex can't handle.

## What Gets Extracted

| Category | Examples |
|----------|----------|
| **Metadata** | Customer name, account number, agreement number, carrier, effective date |
| **Service Terms** | FedEx Priority Overnight: Zone 2 = 57% discount, 1-10 lbs |
| **Surcharges** | Residential Delivery Surcharge: -50% modification |
| **DIM Rules** | Dimensional Weight Divisor: 250 for Domestic Express |
| **Earned Discounts** | Grace Discount: 10%, $1.83M-$3M threshold = 7% |
| **Special Terms** | Money-Back Guarantee: Waived |
| **Amendments** | Agreement 895468978-102-07, effective Dec 8, 2025 |

## How FedEx vs UPS Differ

**FedEx contracts** use `Zones => All Zones` table headers with weight tiers below:
```
FedEx Priority Overnight Envelope
Zones => All Zones
Envelope  57%
```

**UPS contracts** use `Weight (lbs) / Zones` tables with multi-line cells and text-based incentives:
```
UPS Ground - Commercial Package - Incentives Off Effective Rates
Weight   Zones  2     3     4     ...
1-5            34%   34%   34%   ...
```

The pipeline handles both formats automatically.

## Running the API + UI (Optional)

```bash
# API server (FastAPI)
python run_api.py
# → http://localhost:8000/docs

# Review UI (Streamlit)
python run_ui.py
# → http://localhost:8501
```

## Configuration

Copy `.env.example` to `.env` and edit as needed:

| Variable | Default | What it does |
|----------|---------|--------------|
| `OPENAI_API_KEY` | (blank) | Set for LLM fallback. Blank = deterministic only |
| `OPENAI_MODEL` | `gpt-4o` | Which model to use |
| `CONFIDENCE_THRESHOLD` | `0.7` | Below this → flagged for review |
