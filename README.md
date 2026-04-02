# 71lbs Contract Extraction Pipeline

Converts FedEx and UPS contract PDFs into structured JSON with confidence scoring, validation, and a review UI.

Built for [71lbs](https://www.71lbs.com/) by VCG.

---

## Setup

```bash
git clone https://github.com/sydneyhlee/71lbs-project.git
cd 71lbs-project
git checkout aidan-merge
pip install -r requirements.txt
```

That's it. No API keys, no Docker, no database. Everything runs locally out of the box.

---

## Usage

### Extract a contract PDF (CLI)

```bash
python run_pipeline.py "path/to/contract.pdf"
```

This runs the full pipeline (parse, extract, validate, score) and saves a JSON result to `extraction/test_outputs/`.

To save to a specific file:

```bash
python run_pipeline.py "path/to/contract.pdf" --output result.json
```

### Launch the review UI

```bash
python run_ui.py
```

Opens at **http://localhost:8501**. From here you can:

- **Upload** a PDF and extract contract data
- **Review** extractions with confidence scores for every field
- **Approve / Reject** extractions
- **Download** approved results as JSON
- **Toggle dark / light mode** from the sidebar

### Parse-only mode (no extraction)

```bash
python run_ingestion.py "path/to/contract.pdf"
```

Shows raw page structure, sections, and table previews without running extraction.

### Start the REST API

```bash
python run_api.py
```

FastAPI server at **http://localhost:8000**. Interactive docs at `/docs`.

| Endpoint | Method | Description |
|---|---|---|
| `/api/upload` | POST | Upload and extract a PDF |
| `/api/extractions` | GET | List all extractions |
| `/api/extractions/{id}` | GET | Get one extraction |
| `/api/extractions/{id}/approve` | POST | Approve an extraction |
| `/api/extractions/{id}/reject` | POST | Reject an extraction |
| `/api/extractions/{id}/export` | GET | Export as JSON |
| `/api/extractions/{id}` | DELETE | Delete an extraction |

---

## What it extracts

| Category | Fields |
|---|---|
| **Metadata** | Customer name, account number, agreement number, effective date, term dates, carrier |
| **Service Terms** | Service type, zones, discount percentages, weight conditions |
| **Surcharges** | Surcharge name, modification type, discount percentage |
| **DIM Rules** | Dimensional weight divisors, applicable services |
| **Special Terms** | Money-back guarantee waivers, payment terms, earned discounts |
| **Amendments** | Amendment number, effective date, superseded version, modified terms |

Every field includes a **confidence score**, **source page number**, and **source text snippet**.

---

## How it works

```
PDF  -->  Parse (pdfplumber + OCR fallback)
     -->  Classify sections (pricing, surcharge, terms, boilerplate)
     -->  Extract data (deterministic regex + table parsing)
     -->  LLM fallback (only if deterministic extraction is sparse)
     -->  Validate (missing fields, invalid ranges, duplicates)
     -->  Score confidence (field-level + overall)
     -->  Resolve amendments (merge chronologically)
     -->  JSON output
```

The pipeline is **deterministic-first**. LLM is only called when table/regex extraction finds fewer than ~30 data points. No LLM is needed for most well-structured contracts.

---

## Project structure

```
run_pipeline.py            Full extraction CLI
run_ingestion.py           Parse-only CLI
run_api.py                 FastAPI server
app/review/ui.py           Streamlit review UI

ingestion/                 PDF parsing
  pdf_reader.py              Text extraction + OCR fallback
  layout_parser.py           Header / table / paragraph detection
  section_classifier.py      Section type classification
  document.py                Data models

extraction/                Structured data extraction
  extractor.py               Main extraction engine
  table_parser.py            Deterministic table parsing
  metadata_extractor.py      Metadata regex extraction

validation/                Quality checks
  validators.py              Issue detection
  confidence.py              Confidence scoring
  normalization.py           Service name / percent normalization
  models.py                  Issue and summary models
  issues.py                  Issue code constants

vendors/                   Carrier detection (FedEx, UPS, 3PL, Freight)
app/api/                   REST API routes
app/storage/               JSON file storage
app/pipeline/              Pipeline orchestration
domain_models/             Future DB-ready Pydantic models
```

---

## Optional: LLM fallback

If you want LLM-assisted extraction for messy or scanned PDFs:

```bash
ollama pull llama3.2
cp .env.example .env
```

Edit `.env` to point to your LLM endpoint. Works with Ollama, OpenAI, or Groq.

The pipeline works without an LLM. It only calls one when deterministic extraction doesn't find enough data.
