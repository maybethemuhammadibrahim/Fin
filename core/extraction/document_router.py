"""[A] Detect a file's type and route it to the right extractor. Phase 4.

Single entry point (implementation_plan.md's mermaid diagram): a text PDF or a
scanned one both end up as an `ExtractedDoc`; a CSV gets a raw passthrough preview
here, since its real structured parsing is a different shape entirely
(csv_parser.parse_transactions returns list[TransactionRow], not ExtractedDoc
blocks, and needs a human-confirmed column mapping first — ADR-010).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from core.ai.schemas import DocBlock, ExtractedDoc
from core.extraction import ocr_cloud, pdf_extractor

DocType = Literal["text_pdf", "scanned", "image", "csv"]

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def detect_type(file_path: str | Path) -> DocType:
    """Peek at a file and say which extraction path it needs. Raises ValueError
    on a genuinely unsupported extension — callers should catch this and record
    it as a failed document, not let it bubble up as a crash."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix == ".pdf":
        densities = pdf_extractor.char_density(file_path)
        avg = sum(densities) / len(densities) if densities else 0
        return "text_pdf" if avg >= pdf_extractor.CHARS_PER_PAGE_THRESHOLD else "scanned"
    raise ValueError(f"unsupported file type: {suffix or '(no extension)'}")


def extract(file_path: str | Path) -> ExtractedDoc:
    """Route by detect_type() and return a uniform ExtractedDoc. Never raises for
    a supported type — extraction failures show up as `warnings`, so the caller
    (app/components/file_uploader.py) decides complete vs. failed from one place."""
    kind = detect_type(file_path)

    if kind == "text_pdf":
        return pdf_extractor.extract_text_pdf(file_path)

    if kind == "scanned":
        return ocr_cloud.extract_scanned(file_path)

    if kind == "image":
        text = ocr_cloud.ocr_page(Path(file_path).read_bytes())
        if text:
            return ExtractedDoc(
                doc_type="image", blocks=[DocBlock(page_number=1, text=text)], full_text=text, page_count=1
            )
        return ExtractedDoc(doc_type="image", blocks=[], full_text="", page_count=0, warnings=[ocr_cloud.NO_OCR_RESULT])

    # csv: a raw text passthrough for preview/status purposes only. Structured
    # parsing into TransactionRow needs a confirmed column mapping and lives in
    # csv_parser.parse_transactions, called separately once that mapping exists.
    text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    warnings = [] if text.strip() else ["file is empty"]
    return ExtractedDoc(
        doc_type="csv",
        blocks=[DocBlock(page_number=1, text=text, is_table=True)] if text.strip() else [],
        full_text=text,
        page_count=1,
        warnings=warnings,
    )
