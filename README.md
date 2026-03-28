# 71lbs Contract Extraction Pipeline

Convert FedEx and UPS contract PDFs into structured JSON for pricing analysis and auditing.

## What This Project Does

The pipeline processes one PDF and returns:
- contract metadata (customer, account, agreement, dates, carrier)
- service discounts (zones, weight tiers, percentages)
- surcharge changes
- DIM rules
- special terms and amendments

It uses deterministic parsing first, then optional LLM fallback for ambiguous text only.

## 5-Minute Setup (Recommended for New Users)

### 1) Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2) Create your local env file

Windows PowerShell:
```powershell
Copy-Item .env.example .env
```

macOS/Linux:
```bash
cp .env.example .env
```

### 3) Add an LLM key (Gemini free tier recommended)

1. Create a free key at [Google AI Studio](https://aistudio.google.com/apikey)
2. Open `.env`
3. Set:

```bash
LLM_API_KEY=your_key_here
```

That is all you need. Defaults already point to Gemini.

### 4) Run extraction on a PDF

```bash
python -m extraction_v2.run_pipeline path/to/contract.pdf
```

### 5) Find output JSON

Output files are written to `extraction_v2/test_outputs/`.

## LLM Options

The project supports any OpenAI-compatible endpoint through these env vars:
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`

### Default (already configured): Gemini
- free key, quick signup, strong usage limits for student/testing workflows

### Optional: Ollama (local, no cloud key)
If you want no external API calls:
1. Install [Ollama](https://ollama.com)
2. Run `ollama pull llama3.1`
3. In `.env`, set:

```bash
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.1
```

## Pipeline Flow

1. `pdf_parser` reads PDF pages and tables (OCR fallback when needed)
2. `extraction_v2` extracts structured pricing data
3. `confidence` scores field-level certainty
4. `resolver` applies amendment logic to produce active terms

## Core Files

- `app/config.py`: environment-based runtime configuration
- `app/pipeline/pdf_parser.py`: PDF parsing and OCR fallback
- `extraction_v2/extractor.py`: refined extraction engine
- `extraction_v2/table_parser.py`: deterministic table logic
- `extraction_v2/run_pipeline.py`: end-to-end test runner

## Optional API and UI

```bash
python run_api.py
```

FastAPI docs: `http://localhost:8000/docs`

```bash
python run_ui.py
```

Streamlit review UI: `http://localhost:8501`
