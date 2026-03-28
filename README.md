# 71lbs Contract Extraction Pipeline — Phase 1 MVP

AI-powered extraction of structured pricing and audit rules from shipping carrier contract PDFs.

## What This Does

Phase 1 turns messy carrier contract PDFs into clean, reviewable structured data:

1. **Upload** a contract PDF (text-based or scanned)
2. **Parse** text, tables, clauses, and footnotes (OCR fallback for scans)
3. **Extract** structured fields via LLM (OpenAI GPT-4o)
4. **Score** confidence per field and flag low-confidence values
5. **Review** extractions in a simple web UI — edit, approve, or reject
6. **Export** approved data as canonical JSON for downstream use

Currently targets **FedEx** contracts. Designed to extend to UPS, DHL, 3PL, and freight.

## Project Structure

```
71lbs-project/
├── app/
│   ├── config.py                  # Environment-based configuration
│   ├── main.py                    # FastAPI application
│   ├── models/
│   │   └── schema.py              # Pydantic canonical schema
│   ├── pipeline/
│   │   ├── ingestion.py           # Orchestrates the full pipeline
│   │   ├── pdf_parser.py          # PDF text + OCR extraction
│   │   ├── chunker.py             # Document segmentation
│   │   ├── extractor.py           # LLM extraction (+ mock mode)
│   │   ├── confidence.py          # Confidence scoring & review flagging
│   │   └── resolver.py            # Amendment precedence resolution
│   ├── api/
│   │   └── routes.py              # REST API endpoints
│   ├── storage/
│   │   └── store.py               # JSON file-based persistence
│   └── review/
│       └── ui.py                  # Streamlit review interface
├── data/
│   ├── uploads/                   # Uploaded PDFs
│   ├── extracted/                 # Raw extraction results
│   ├── approved/                  # Human-approved outputs
│   └── samples/                   # Example JSON outputs
├── run_api.py                     # Start FastAPI server
├── run_ui.py                      # Start Streamlit UI
├── requirements.txt
├── .env.example
└── README.md
```

## Quick Start

### 1. Prerequisites

- Python 3.10+
- (Optional) Tesseract OCR — only needed for scanned PDFs
- (Optional) Poppler — required by `pdf2image` for OCR

### 2. Install Dependencies

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your OpenAI API key. **If you leave it blank**, the app runs
with a mock extractor that returns realistic sample data — useful for development
and demos without any API cost.

### 4. Run the API Server

```bash
python run_api.py
```

The API runs at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### 5. Run the Review UI

In a separate terminal:

```bash
python run_ui.py
```

The Streamlit UI opens at `http://localhost:8501`.

### 6. Try It Out

**Option A — via the UI:**
1. Open `http://localhost:8501`
2. Upload a PDF on the Upload page
3. Review extracted fields on the Review Queue page
4. Approve and export from the Approved page

**Option B — via the API:**
```bash
# Upload and extract
curl -X POST http://localhost:8000/api/upload -F "file=@contract.pdf"

# List extractions
curl http://localhost:8000/api/extractions

# Approve
curl -X POST http://localhost:8000/api/extractions/{id}/approve

# Export
curl http://localhost:8000/api/extractions/{id}/export
```

## Canonical Schema

Every extracted field is wrapped in `ExtractedValue` with:
- `value` — the extracted data
- `confidence` — 0.0 to 1.0 score
- `source_page` — PDF page number
- `source_text` — raw text snippet (provenance)
- `needs_review` — flagged if below confidence threshold
- `reviewer_override` — human-corrected value

Top-level structure of a `ContractExtraction`:

| Section | Description |
|---------|-------------|
| `metadata` | Agreement number, version, dates, carrier, customer, account |
| `service_terms[]` | Per-service pricing: type, zones, discount %, conditions |
| `surcharges[]` | Surcharge name, application, modification, discount % |
| `dim_rules[]` | DIM divisor, applicable services, conditions |
| `special_terms[]` | Money-back guarantee, earned discounts, special provisions |
| `amendments[]` | Amendment-specific overrides with their own terms |
| `active_terms_snapshot` | Resolved view after applying all amendments by date |

See `data/samples/` for complete example outputs.

## OCR Setup (For Scanned PDFs)

If you need to process scanned/image-based PDFs:

**Windows:**
1. Install Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
2. Install Poppler: download from https://github.com/oschwartz10612/poppler-windows/releases
3. Add both to your PATH

**macOS:**
```bash
brew install tesseract poppler
```

**Linux:**
```bash
sudo apt-get install tesseract-ocr poppler-utils
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/upload` | Upload PDF and run extraction |
| GET | `/api/extractions` | List all extractions (optional `?status=` filter) |
| GET | `/api/extractions/{id}` | Get single extraction |
| PUT | `/api/extractions/{id}/review` | Submit review edits |
| POST | `/api/extractions/{id}/approve` | Approve extraction |
| POST | `/api/extractions/{id}/reject` | Reject extraction |
| GET | `/api/extractions/{id}/export` | Export as JSON |
| DELETE | `/api/extractions/{id}` | Delete extraction |

## Configuration

All settings via environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (none) | OpenAI API key; blank = mock mode |
| `OPENAI_MODEL` | `gpt-4o` | Model for extraction |
| `DATA_DIR` | `./data` | Base data directory |
| `CONFIDENCE_THRESHOLD` | `0.7` | Below this → flagged for review |
| `API_HOST` | `0.0.0.0` | API bind address |
| `API_PORT` | `8000` | API port |
| `LOG_LEVEL` | `INFO` | Logging level |

## Phase 2 Roadmap (TODO)

The following are planned for Phase 2 — invoice audit engine:

- [ ] **Invoice ingestion pipeline** — parse carrier invoices (CSV/EDI/PDF)
- [ ] **Rules engine** — compare invoice line items against contract terms
- [ ] **Discrepancy detection** — flag overcharges, missed discounts, wrong DIM
- [ ] **Audit dashboard** — visualization of savings opportunities
- [ ] **Multi-carrier support** — UPS, DHL, USPS rate structures
- [ ] **Database migration** — move from JSON files to PostgreSQL
- [ ] **User authentication** — role-based access for reviewers
- [ ] **Batch processing** — handle multiple contracts concurrently
- [ ] **Webhook notifications** — alert on low-confidence extractions
- [ ] **Contract versioning** — full history and diff between versions
- [ ] **ML confidence calibration** — train on reviewer corrections to improve scoring

## License

Proprietary — 71lbs / VCG
