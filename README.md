# 71lbs Contract Extraction Pipeline

Converts FedEx and UPS shipping contract PDFs into structured JSON for pricing analysis and invoice auditing.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure your LLM

Copy the example env file:

```bash
cp .env.example .env
```

The default `.env` uses **local Ollama** — no API key needed:

```
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2
```

To use Ollama, install it from [ollama.com](https://ollama.com) then run:

```bash
ollama pull llama3.2
```

Alternatively, edit `.env` to use OpenAI, Gemini, or Groq (see `.env.example` for examples).

---

## Run extraction on a PDF

```bash
python3 -m extraction_v2.run_pipeline "path/to/contract.pdf"
```

Output is saved as JSON in `extraction_v2/test_outputs/`.

---

## What it extracts

| Field | Description |
|---|---|
| Metadata | Customer name, account number, agreement number, carrier, effective date |
| Service Terms | Service type, applicable zones, discount percentage, weight conditions |
| Surcharges | Name, modification type, discount percentage, applicable zones |
| DIM Rules | Dimensional weight divisor and applicable services |
| Special Terms | Earned discounts, money-back guarantee waivers, other provisions |
| Amendments | Amendment number, effective date, modified terms |

---

## How it works

```
PDF
 └── ingestion/          layout-aware parsing — headers, tables, section classification
      └── extraction_v2/ deterministic extraction → LLM fallback for ambiguous content
           └── app/       confidence scoring, amendment resolution, JSON output
```

The pipeline is deterministic-first. LLM is only called when structured parsing yields low coverage.
