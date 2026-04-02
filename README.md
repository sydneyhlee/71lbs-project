# 71lbs Contract Extraction Pipeline

Extracts structured pricing data from FedEx and UPS shipping contract PDFs.

---

## First-time setup

### Step 1 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 2 — Set up your LLM

The pipeline uses an LLM as a fallback when it can't parse something deterministically. You have two options:

**Option A — Local (free, no account needed)**

1. Download Ollama from [ollama.com](https://ollama.com) and install it
2. Open a terminal and run:
   ```bash
   ollama pull llama3.2
   ```
3. Keep Ollama running in the background

**Option B — Cloud (OpenAI, Gemini, or Groq)**

Sign up for an API key from any of those providers.

### Step 3 — Create your config file

```bash
cp .env.example .env
```

If you chose **Option A (Ollama)**, you don't need to change anything in `.env` — the defaults work out of the box.

If you chose **Option B**, open `.env` and swap in your provider's settings. Examples are pre-written in `.env.example` — just uncomment the right block.

---

## Running the pipeline

### Step 1 — Activate the virtual environment

You must do this every time you open a new terminal window. From the project folder:

```bash
source venv/bin/activate
```

Your terminal prompt will change to show `(venv)` on the left — that means it's active and ready. If you don't see `(venv)`, the pipeline won't find its dependencies.

### Step 2 — Add your PDF

Place your contract or invoice PDF inside the `ingestion/data/` folder:

```
ingestion/data/
└── your-contract.pdf
```

Subfolders are fine too:

```
ingestion/data/
├── fedex/
│   └── armoire-fedex-contract.pdf
└── ups/
    └── armoire-ups-contract.pdf
```

### Step 3 — Run extraction

```bash
python3 -m extraction_v2.run_pipeline "ingestion/data/your-contract.pdf" 2>&1
```

> The `2>&1` at the end is required — it makes the output print to your terminal. Without it you will see nothing.

Wrap the file path in quotes if the filename has spaces (most carrier contracts do).

### Step 4 — Read the terminal output

The terminal will print a summary like:

```
Metadata:
  Customer:     G-FULFILLMENT LLC (conf=0.88)
  Carrier:      UPS (conf=0.98)

Service Terms: 12 extracted
Surcharges:    47 extracted
DIM Rules:      3 extracted

Overall Confidence: 0.91
Fields Needing Review: 0
```

### Step 5 — Find the full JSON output

The complete structured result is saved automatically to:

```
extraction_v2/test_outputs/your-contract_extraction.json
```

---

## What it currently extracts

Given a shipping contract PDF, the pipeline outputs:

| Field | Example |
|---|---|
| **Carrier** | FedEx, UPS |
| **Customer name** | Armoire Style LLC |
| **Account number** | 2070-7117-5 |
| **Agreement number** | UPS-2024-00123 |
| **Effective date** | January 1, 2024 |
| **Contract term** | Jan 1 2024 → Dec 31 2025 |
| **Service terms** | FedEx Ground, zones 2–8, 10% discount, 1–150 lbs |
| **Surcharges** | Residential delivery — 20% discount off published rate |
| **DIM rules** | Divisor 139, applies to all domestic services |
| **Special terms** | Earned discount tiers, money-back guarantee waivers |
| **Amendments** | Amendment number, effective date, what changed |

> **Note:** The pipeline also accepts invoice PDFs. It detects the document type automatically and extracts invoice signals (totals, service charges, surcharge line items) instead of contract terms.

---

## How it works internally

```
Your PDF
  │
  ├─ ingestion/
  │   Layout-aware parsing. Detects headers, tables, and paragraphs.
  │   Classifies sections as PRICING, SURCHARGE, TERMS, etc.
  │   Handles both digital PDFs and scanned documents (OCR).
  │
  ├─ extraction_v2/
  │   Reads the classified sections and extracts structured fields.
  │   Uses deterministic regex/table parsing first.
  │   Falls back to LLM only when structured parsing gets low coverage.
  │
  └─ app/
      Scores confidence on every extracted field.
      Merges amendments into a resolved active-terms snapshot.
      Saves results as JSON.
```

Every extracted field carries a **confidence score** (0–1) and a **source snippet** showing exactly where in the document it came from. Fields below the confidence threshold are flagged for human review.

---

## What it does not do yet

- Map extracted contract terms to invoice line items for auditing
- Support batch processing of multiple PDFs in one command
- Provide a UI for reviewing flagged fields
