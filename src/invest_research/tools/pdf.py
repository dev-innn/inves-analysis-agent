from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf


def extract_pdf(path: str | Path, max_pages: int = 300) -> list[dict]:
    """Return page-numbered text; empty/scanned pages remain visible as gaps."""
    file_path = Path(path)
    if file_path.stat().st_size > 20_000_000:
        raise ValueError("PDF exceeds size limit")
    with pymupdf.open(file_path) as pdf:
        if not pdf.is_pdf:
            raise ValueError("Not a PDF")
        pages = [{"page": i + 1, "text": pdf[i].get_text("text")[:25000]} for i in range(min(len(pdf), max_pages))]
    if not any(p["text"].strip() for p in pages):
        raise ValueError("PDF has no extractable text; OCR/manual review required")
    return pages


def content_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
