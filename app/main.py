"""
FastAPI application entry point.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import LOG_LEVEL
from app.api.routes import router

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="71lbs Contract Extraction API",
    description=(
        "Phase 1 MVP: AI-powered extraction of structured pricing and "
        "audit rules from shipping carrier contract PDFs."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    return {
        "service": "71lbs Contract Extraction",
        "version": "0.1.0",
        "docs": "/docs",
        # TODO: Phase 2 — add /health endpoint with dependency checks
    }
