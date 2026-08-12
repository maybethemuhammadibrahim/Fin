"""[B] Reads the Surya-on-Colab OCR text layer for scanned pages. Phase 4.

Offline batch step, never live, never a vision API (ADR-001, ADR-011). This module
does not call any OCR service. Surya runs separately, in a Colab notebook, before a
scanned file ever reaches this app, and writes a real text layer back into the PDF —
that batch step is not built yet (implementation_plan.md marks it optional, off the
critical path: CUAD and EDGAR contracts are all digital-text). What this module does
is check whether that has already happened, and give the caller an honest, specific
reason when it hasn't, rather than a stack trace or a silent empty result.
"""

from __future__ import annotations

from pathlib import Path

from core.ai.schemas import ExtractedDoc
from core.extraction.pdf_extractor import CHARS_PER_PAGE_THRESHOLD, char_density, extract_text_pdf

NO_OCR_PASS_YET = (
    "scanned document has no text layer -- run the offline Surya-on-Colab OCR pass "
    "first (implementation_plan.md Phase 4, fallback branch, not yet built)"
)
NO_OCR_RESULT = (
    "image upload has no OCR result -- the offline Surya-on-Colab pass is not wired "
    "up yet; this is a Phase 4 fallback branch, not the primary pipeline"
)


def has_text_layer(path: str | Path) -> bool:
    """True when a Surya pass already wrote real text into this PDF, so it can be
    read exactly like a digital-text PDF from here on."""
    densities = char_density(path)
    return bool(densities) and (sum(densities) / len(densities)) >= CHARS_PER_PAGE_THRESHOLD


def extract_scanned(path: str | Path) -> ExtractedDoc:
    """A scanned PDF that already carries a Surya text layer extracts like any other
    text PDF. One that doesn't gets an empty ExtractedDoc with a specific warning,
    which document_router turns into a readable extraction_status='failed' message —
    never a crash, never a silently empty 'success'."""
    if has_text_layer(path):
        doc = extract_text_pdf(path)
        return doc.model_copy(update={"doc_type": "scanned"})
    return ExtractedDoc(doc_type="scanned", blocks=[], full_text="", page_count=0, warnings=[NO_OCR_PASS_YET])


def ocr_page(image_bytes: bytes) -> str | None:
    """No live OCR call exists in this app (ADR-001, ADR-011) — always returns None.
    Kept as the documented interface point: once a Surya batch step is wired to write
    results somewhere lookup-able, this function's body is the only thing that changes.
    document_router treats None as a failed extraction with NO_OCR_RESULT, not a crash.
    """
    return None


__all__ = ["NO_OCR_PASS_YET", "NO_OCR_RESULT", "has_text_layer", "extract_scanned", "ocr_page"]
