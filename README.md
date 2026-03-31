# 71lbs Contract Extraction Pipeline

Convert FedEx and UPS PDFs into structured JSON for pricing analysis and auditing.

## Full Setup Instructions (Ollama, No Keys)

This project is configured to run with **local Ollama** by default, so you do not need any API key.

## 0) Prerequisites

- Python 3.10+ installed
- `pip` available
- Ollama installed from [ollama.com](https://ollama.com)

## 1) Open a terminal in this project

Use a terminal at the project root (`71lbs-project`).

Windows (PowerShell):
```powershell
cd "c:\Users\Ajone\71lbs-project"
```

macOS/Linux:
```bash
cd /path/to/71lbs-project
```

## 2) Install Python dependencies

```bash
pip install -r requirements.txt
```

## 3) Start Ollama and download the model

Open a **new terminal window/tab** (keep it separate from your project terminal if you want).

Run:
```bash
ollama pull llama3.2
```

Then verify Ollama is available:
```bash
ollama list
```

You should see `llama3.2` in the list.

## 4) Create local environment file

Back in your project terminal:

Windows PowerShell:
```powershell
Copy-Item .env.example .env
```

macOS/Linux:
```bash
cp .env.example .env
```

Default `.env` values (already set for local Ollama):
```bash
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2
```

## 5) Run extraction on one PDF

```bash
# Tip: on macOS you typically want `python3`
python3 -m extraction_v2.run_pipeline "path/to/contract.pdf"
```

Example (Windows):
```powershell
python -m extraction_v2.run_pipeline "C:\some-folder\contract.pdf"
```

Output JSON files are saved in `extraction_v2/test_outputs/` (default) unless you pass `--output`.

By default, the output filename is derived from the PDF stem, like:
`<pdf_stem>_extraction.json`.

## 5b) Run extraction on a folder of PDFs
If you want to process every `*.pdf` under a directory, you can use a loop like this:
```bash
find "/path/to/pdfs" -name "*.pdf" -print0 | while IFS= read -r -d '' f; do \
  python3 -m extraction_v2.run_pipeline "$f"; \
done
```

## 6) Run built-in FedEx + UPS test set

```bash
python3 -m extraction_v2.run_pipeline --test-all
```

## Troubleshooting

- **`ollama` command not found**: reinstall Ollama, then open a new terminal.
- **Model missing**: run `ollama pull llama3.2`.
- **Connection errors to `localhost:11434`**: make sure Ollama is running.
- **No output file**: check terminal logs and confirm PDF path is correct.

## What It Extracts

- Metadata (customer, account, agreement, dates, carrier)
- Service terms and discounts
- Surcharges
- DIM rules
- Special terms and amendments

The pipeline is deterministic-first. LLM fallback is only used for ambiguous, low-coverage docs.

## Optional API and UI

```bash
python run_api.py
```

FastAPI docs: `http://localhost:8000/docs`

```bash
python run_ui.py
```

Streamlit UI: `http://localhost:8501`

## In Plain English

You give the system a shipping PDF. It reads the pages, finds pricing-related data (discounts, surcharges, DIM rules, dates, account info), and saves a clean JSON file that is much easier to review or use in downstream auditing tools.
