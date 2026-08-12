"""[A] pdfplumber text + table extraction, page-tagged. Phase 4.

The primary path — 90% of the work, per implementation_plan.md. CUAD and EDGAR
contracts are digital-text PDFs, so this never needs OCR; core/extraction/ocr_cloud.py
is a fallback branch this pipeline rarely touches.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from core.ai.schemas import DocBlock, ExtractedDoc

#: More than ~50 characters per page means the PDF carries a real text layer.
#: Below it, document_router routes to the scanned/OCR path instead.
CHARS_PER_PAGE_THRESHOLD = 50


def _open(path: str | Path):
    """pdfplumber.open, but a corrupt or non-PDF file raises a message the UI can
    show instead of a raw pdfminer exception ("No /Root object! - Is this really
    a PDF?"). Found live: uploading a garbage .pdf crashed the whole page instead
    of landing as extraction_status='failed' — the plan's Phase 4 definition of
    done explicitly requires a readable error, not a stack trace."""
    try:
        return pdfplumber.open(path)
    except Exception as exc:
        raise ValueError(f"file is not a readable PDF ({type(exc).__name__})") from exc


def char_density(path: str | Path) -> list[int]:
    """Characters of extractable text per page — the cheapest possible peek,
    used by document_router to decide text_pdf vs. scanned before doing full
    extraction (table detection especially is not free). Raises ValueError, not
    a library-specific exception, on an unreadable file."""
    with _open(path) as pdf:
        return [len((page.extract_text() or "")) for page in pdf.pages]


def extract_text_pdf(path: str | Path) -> ExtractedDoc:
    """Extract paragraph text and tables from a digital-text PDF, one block per
    page (plus one block per detected table). Raises ValueError only when the
    file can't be opened at all; an unreadable individual page just contributes
    no blocks, and an empty result surfaces as a warning so the caller can mark
    extraction_status='failed' instead of 'complete' on nothing."""
    blocks: list[DocBlock] = []
    with _open(path) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                blocks.append(DocBlock(page_number=i, text=text, is_table=False))
            for table in page.extract_tables():
                table_text = _table_to_text(table)
                if table_text:
                    blocks.append(DocBlock(page_number=i, text=table_text, is_table=True))

    warnings = [] if blocks else ["no extractable text on any page"]
    full_text = "\n\n".join(b.text for b in blocks)
    return ExtractedDoc(
        doc_type="text_pdf",
        blocks=blocks,
        full_text=full_text,
        page_count=page_count,
        warnings=warnings,
    )


def _table_to_text(table: list[list[str | None]]) -> str:
    rows = [" | ".join(cell.strip() if cell else "" for cell in row) for row in table]
    return "\n".join(r for r in rows if r.strip(" |"))
