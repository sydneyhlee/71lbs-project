# 71lbs Contract Extraction Pipeline

Convert FedEx and UPS PDFs into structured JSON for pricing analysis and auditing.

## Quick Start (No Keys Needed)

This repo is configured to run on **local Ollama** by default.

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

### 2) Install and start Ollama

1. Install from [ollama.com](https://ollama.com)
2. Pull the default model:

```bash
ollama pull llama3.2
```

### 3) Create `.env` (optional but recommended)

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

### 4) Run extraction

```bash
python -m extraction_v2.run_pipeline path/to/contract.pdf
```

Output JSON files are saved in `extraction_v2/test_outputs/`.

## What It Extracts

- Metadata (customer, account, agreement, dates, carrier)
- Service terms and discounts
- Surcharges
- DIM rules
- Special terms and amendments

The pipeline is deterministic-first. LLM fallback is only used for ambiguous, low-coverage docs.

## LLM Configuration

Default (local Ollama):

```bash
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2
```

You can still switch providers (Gemini/OpenAI/Groq) by changing `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` in `.env`.

## Pipeline Flow

1. `pdf_parser`: reads PDF text + tables (OCR fallback when needed)
2. `extraction_v2`: deterministic extraction (plus optional LLM fallback)
3. `confidence`: scores extracted fields
4. `resolver`: resolves amendment effects to active terms

## Optional API and UI

```bash
python run_api.py
```

FastAPI docs: `http://localhost:8000/docs`

```bash
python run_ui.py
```

Streamlit UI: `http://localhost:8501`
