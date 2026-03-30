from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import pdfplumber


@dataclass(frozen=True)
class PageTextBlock:
    page: int
    bbox: tuple[float, float, float, float] | None
    text: str
    block_type: str  # "text" | "table" | "footnote" | "unknown"
    raw: dict[str, Any]


@dataclass(frozen=True)
class ExtractedPDF:
    path: str
    pages: int
    blocks: list[PageTextBlock]
    tables: list[dict[str, Any]]


def _stable_id(prefix: str, payload: str) -> str:
    h = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{h}"


def extract_pdf(path: str) -> ExtractedPDF:
    """
    Layout-aware extraction using pdfplumber:
    - block-ish text (page text)
    - detected tables (stream + lattice attempts)
    """
    blocks: list[PageTextBlock] = []
    tables: list[dict[str, Any]] = []

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            if page_text.strip():
                blocks.append(
                    PageTextBlock(
                        page=i,
                        bbox=None,
                        text=page_text,
                        block_type="text",
                        raw={"method": "page.extract_text", "x_tolerance": 2, "y_tolerance": 2},
                    )
                )

            # Try table extraction; pdfplumber doesn't guarantee bboxes for extract_tables,
            # but we capture raw grids to allow later normalization.
            for flavor in ("stream", "lattice"):
                try:
                    settings = {"vertical_strategy": flavor, "horizontal_strategy": flavor}
                    extracted = page.extract_tables(table_settings=settings) or []
                except Exception:
                    extracted = []
                for grid in extracted:
                    norm_rows = [[(c or "").strip() for c in row] for row in grid if row]
                    flat = "\n".join(["\t".join(r) for r in norm_rows])
                    tid = _stable_id("table", f"{path}|{i}|{flavor}|{flat}")
                    tables.append(
                        {
                            "id": tid,
                            "page": i,
                            "flavor": flavor,
                            "rows": norm_rows,
                            "raw": {"table_settings": settings},
                        }
                    )
                    blocks.append(
                        PageTextBlock(
                            page=i,
                            bbox=None,
                            text=flat,
                            block_type="table",
                            raw={"table_id": tid, "flavor": flavor},
                        )
                    )

    return ExtractedPDF(path=path, pages=(len(pdf.pages) if "pdf" in locals() else 0), blocks=blocks, tables=tables)

