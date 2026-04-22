"""
Render PDF pages to images for OCR without requiring Poppler (pdfinfo).

pdf2image uses Poppler; when it is missing, PyMuPDF can rasterize pages
directly. Used by pdf_parser and ingestion.pdf_reader.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List

logger = logging.getLogger(__name__)


def ocr_page_images(
    pdf_path: Path,
    *,
    first_page: int = 1,
    last_page: int | None = None,
    dpi: int = 200,
) -> List[Any]:
    """
    Return one PIL image per page in [first_page, last_page] (1-indexed, inclusive).

    Tries pdf2image (Poppler) first, then PyMuPDF rasterization.
    """
    path = Path(pdf_path)
    last = last_page if last_page is not None else None

    try:
        from pdf2image import convert_from_path
        from pdf2image.exceptions import PDFInfoNotInstalledError

        try:
            kwargs: dict = {"dpi": dpi, "first_page": first_page}
            if last is not None:
                kwargs["last_page"] = last
            imgs = convert_from_path(str(path), **kwargs)
            if imgs:
                return imgs
        except (PDFInfoNotInstalledError, FileNotFoundError, OSError) as exc:
            logger.info(
                "pdf2image/Poppler unavailable (%s); trying PyMuPDF for %s",
                exc,
                path.name,
            )
        except Exception as exc:
            logger.info(
                "pdf2image failed (%s); trying PyMuPDF for %s",
                exc,
                path.name,
            )
    except ImportError:
        logger.info("pdf2image not installed; trying PyMuPDF for %s", path.name)

    return _render_with_pymupdf(path, first_page=first_page, last_page=last, dpi=dpi)


def _render_with_pymupdf(
    pdf_path: Path,
    *,
    first_page: int,
    last_page: int | None,
    dpi: int,
) -> List[object]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "OCR rasterization needs Poppler (for pdf2image) or PyMuPDF. "
            "Install one of: brew install poppler   OR   pip install pymupdf"
        ) from exc

    from PIL import Image as PILImage

    doc = fitz.open(pdf_path)
    try:
        n = doc.page_count
        lo = max(0, first_page - 1)
        hi = n if last_page is None else min(n, last_page)
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        out: List[Any] = []
        for i in range(lo, hi):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            mode = "RGB" if pix.n < 4 else "RGBA"
            img = PILImage.frombytes(mode, (pix.width, pix.height), pix.samples)
            if img.mode == "RGBA":
                img = img.convert("RGB")
            out.append(img)
        if not out:
            raise RuntimeError(f"PyMuPDF produced no images for {pdf_path.name}")
        logger.info(
            "Rendered %d page(s) via PyMuPDF for OCR (%s).",
            len(out),
            pdf_path.name,
        )
        return out
    finally:
        doc.close()
