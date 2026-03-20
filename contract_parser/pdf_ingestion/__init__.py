from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pdfplumber
import pytesseract
from pdf2image import convert_from_path


def _has_meaningful_text(pdf_path: Path, page_limit: int = 3) -> bool:
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages[:page_limit]:
            if (page.extract_text() or "").strip():
                return True
    return False


def _ocr_cache_path(pdf_path: Path, cache_dir: Path) -> Path:
    digest = hashlib.sha256(str(pdf_path.resolve()).encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def _extract_with_pdfplumber(pdf_path: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            blocks: list[dict[str, Any]] = []
            words = page.extract_words(extra_attrs=["size"])
            for w in words:
                blocks.append(
                    {
                        "type": "text",
                        "content": w["text"],
                        "bbox": [w["x0"], w["top"], w["x1"], w["bottom"]],
                        "font_size": w.get("size"),
                    }
                )
            for table in page.extract_tables() or []:
                if table:
                    blocks.append({"type": "table", "content": table})
            output.append({"page": idx, "blocks": blocks})
    return output


def _extract_with_ocr(pdf_path: Path, cache_dir: Path) -> list[dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = _ocr_cache_path(pdf_path, cache_dir)
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    pages = convert_from_path(str(pdf_path), dpi=250)
    output: list[dict[str, Any]] = []
    for idx, image in enumerate(pages, start=1):
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        blocks: list[dict[str, Any]] = []
        n = len(data["text"])
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            x, y = data["left"][i], data["top"][i]
            w, h = data["width"][i], data["height"][i]
            blocks.append(
                {
                    "type": "text",
                    "content": text,
                    "bbox": [x, y, x + w, y + h],
                    "font_size": None,
                }
            )
        output.append({"page": idx, "blocks": blocks})

    cache_path.write_text(json.dumps(output))
    return output


def ingest_pdf(pdf_path: str, cache_dir: str = ".ocr_cache") -> list[dict[str, Any]]:
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"Missing input PDF: {pdf_path}")
    if _has_meaningful_text(path):
        return _extract_with_pdfplumber(path)
    return _extract_with_ocr(path, Path(cache_dir))
