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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

for _dir in [UPLOADS_DIR, EXTRACTED_DIR, APPROVED_DIR, SAMPLES_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)
