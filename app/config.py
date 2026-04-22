"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))

UPLOADS_DIR = DATA_DIR / "uploads"
EXTRACTED_DIR = DATA_DIR / "extracted"
APPROVED_DIR = DATA_DIR / "approved"
SAMPLES_DIR = DATA_DIR / "samples"
AUDIT_DIR = DATA_DIR / "audits"
REFERENCE_DIR = DATA_DIR / "reference"
AUDIT_LOG_DIR = DATA_DIR / "audit_runs"

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

# Optional carrier billing API credentials (API-first invoice ingestion).
FEDEX_BILLING_API_BASE_URL = os.getenv("FEDEX_BILLING_API_BASE_URL", "")
FEDEX_BILLING_API_KEY = os.getenv("FEDEX_BILLING_API_KEY", "")
UPS_BILLING_API_BASE_URL = os.getenv("UPS_BILLING_API_BASE_URL", "")
UPS_BILLING_API_KEY = os.getenv("UPS_BILLING_API_KEY", "")

CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

for _dir in [
    UPLOADS_DIR,
    EXTRACTED_DIR,
    APPROVED_DIR,
    SAMPLES_DIR,
    AUDIT_DIR,
    REFERENCE_DIR,
    AUDIT_LOG_DIR,
]:
    _dir.mkdir(parents=True, exist_ok=True)
