# 71lbs Agreement + Invoice Audit

Extracts structured pricing data from FedEx/UPS **pricing agreements**, routes
through LLM verification + human approval, then audits invoice discrepancies
against approved company terms.

---

## Get started

Open **one terminal** and run these commands in order, one after the other:

```bash
git clone https://github.com/sydneyhlee/71lbs-project.git
cd 71lbs-project
git checkout aidan-merge
pip install -r requirements.txt
python run_ui.py
```

After the last command, open **http://localhost:8501** in your browser. That's it -- the UI is running.

> **Note:** `pip install` (and everything before it) only needs to run once. After that you can just do `python run_ui.py` to start the app again.

---

## Configure `.env`

Create `.env` from `.env.example` and set:

```env
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=gsk_your_groq_key_here
LLM_MODEL=llama-3.3-70b-versatile
```

If `LLM_API_KEY` is missing, the verifier stage is skipped gracefully.

---

## Run the Streamlit app

```bash
python run_ui.py
```

Then open [http://localhost:8501](http://localhost:8501).

---

## UI tabs

1. **Upload Pricing Agreement** - upload one or many contract PDFs (grouped by company)
2. **Review Queue** - compare parser vs LLM-corrected values, then approve/reject/edit
3. **Invoice Audit** - select an approved agreement, upload invoice files, run audit, export TXT/JSON
4. **Parallel Study** - upload AI JSON + human CSV and compute precision/recall/F1 with FN export

The UI has a **dark/light mode toggle** in the sidebar.

---

## Agreement PDFs to upload

This tool is **only** for **pricing agreements** -- the PDFs that define your negotiated shipping rates with FedEx or UPS.

**Upload these:**
- Pricing agreements (e.g. `FDX PricingAgreement.pdf`)
- Amendments and addendums (e.g. `FDX Apr25 1.pdf`)
- Rate schedules

**Do NOT upload these:**
- Invoices (monthly shipping bills)
- Shipment receipts
- Tracking documents or shipping labels

Use the **Invoice Audit** tab for invoice PDFs.

---

## Stage flow

1. Deterministic parser extracts structured JSON.
2. Stage-2 LLM verifier reviews parser output and applies targeted corrections only.
3. Human reviewer approves final agreement snapshot.
4. Invoice audit compares invoice line items to approved agreement terms and classifies discrepancies.

Every extracted field has confidence + provenance (`source_page`, `source_text`).

---

## CLI usage (optional)

If you want to run extraction from the command line instead of the UI:

```bash
python run_pipeline.py "path/to/pricing-agreement.pdf"
```

Save to a specific output file:

```bash
python run_pipeline.py "path/to/pricing-agreement.pdf" --output result.json
```

Parse-only mode (no extraction, just shows document structure):

```bash
python run_ingestion.py "path/to/pricing-agreement.pdf"
```

REST API:

```bash
python run_api.py
```

Then open **http://localhost:8000/docs** for the interactive API docs.

---

## Project structure

```
run_ui.py              Start the review UI
run_pipeline.py        CLI extraction
run_ingestion.py       CLI parse-only
run_api.py             REST API server

ingestion/             PDF parsing (text + OCR fallback)
extraction/            Data extraction (regex + tables + LLM fallback)
validation/            Confidence scoring and issue detection
vendors/               Carrier detection (FedEx, UPS, 3PL, Freight)
app/review/ui.py       Streamlit review UI
app/api/               FastAPI REST endpoints
app/storage/           JSON file storage
```

---

## LLM provider (default: Groq Llama 3.3 70B)

Set your Groq key in `.env`:

```bash
cp .env.example .env
```

Then edit `.env`:

```env
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=gsk_your_own_key_here
LLM_MODEL=llama-3.3-70b-versatile
```

Get your key from [Groq Console](https://console.groq.com).
Each user who downloads this project must generate their own API key and add it to `.env`.

## Reference data refresh

Run all refresh tasks:

```bash
python scripts/refresh_reference_data.py --task all
```

Or run individual scripts directly:

```bash
python scripts/scrape_fuel_surcharges.py
python scripts/download_das_zips.py
python scripts/download_zone_maps.py
python scripts/download_service_guides.py
```

- Fuel: weekly
- DAS ZIPs: quarterly
- Zone/transit: quarterly
- Service guides: annually (post-GRI)

Each run writes timestamped versions under `data/reference/**/versions/`.

## Invoice Ingestion Priority

Invoice ingestion is now API-first (FedEx/UPS billing API) with PDF/CSV fallback:

- Set optional env vars in `.env`:
  - `FEDEX_BILLING_API_BASE_URL`, `FEDEX_BILLING_API_KEY`
  - `UPS_BILLING_API_BASE_URL`, `UPS_BILLING_API_KEY`
- In the **Invoice Audit** tab, provide carrier invoice IDs (optional) plus uploaded files.
- Post-parse validation enforces required fields (`ship_date`, `service_code`, `rated_weight_lbs`) and stops audit runs for human review if missing.
