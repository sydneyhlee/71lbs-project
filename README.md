# 71lbs Pricing Agreement Extraction

Extracts structured pricing data from FedEx and UPS **pricing agreement** PDFs.

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

## What to do in the UI

1. **Upload Pricing Agreement** -- drag a FedEx or UPS pricing agreement PDF into the upload area
2. **Review Queue** -- see every extracted field with a confidence score, flag anything that looks wrong
3. **Approved** -- download the final JSON for approved agreements

The UI has a **dark/light mode toggle** in the sidebar.

---

## What kind of PDFs to upload

This tool is **only** for **pricing agreements** -- the PDFs that define your negotiated shipping rates with FedEx or UPS.

**Upload these:**
- Pricing agreements (e.g. `FDX PricingAgreement.pdf`)
- Amendments and addendums (e.g. `FDX Apr25 1.pdf`)
- Rate schedules

**Do NOT upload these:**
- Invoices (monthly shipping bills)
- Shipment receipts
- Tracking documents or shipping labels

Invoices and receipts are completely different documents. This pipeline only understands pricing agreements.

---

## What it extracts

| Category | What the pipeline pulls out |
|---|---|
| **Metadata** | Customer name, account number, agreement number, dates, carrier |
| **Service Terms** | Service type, zone pricing, discount percentages |
| **Surcharges** | Surcharge names, modifications, discount percentages |
| **DIM Rules** | Dimensional weight divisors, which services they apply to |
| **Special Terms** | Money-back guarantee waivers, payment terms, earned discounts |
| **Amendments** | Amendment numbers, effective dates, what they change |

Every field has a **confidence score** (0-100%). Fields below 70% are flagged for human review.

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

## Optional: LLM fallback

The pipeline works without any LLM. It only calls an LLM when the deterministic extraction doesn't find enough data (rare for well-structured pricing agreements).

If you want LLM support:

```bash
ollama pull llama3.2
cp .env.example .env
```
