"""[A] Detect a file's type and route it to the right extractor. Phase 4.

Single entry point (implementation_plan.md's mermaid diagram): a text PDF or a
scanned one both end up as an `ExtractedDoc`; a CSV gets a raw passthrough preview
here, since its real structured parsing is a different shape entirely
(csv_parser.parse_transactions returns list[TransactionRow], not ExtractedDoc
blocks, and needs a human-confirmed column mapping first — ADR-010).

Plain `.txt` is routed too, as `doc_type="text"`. That branch was added on
2026-08-17, after an audit found `app/components/file_uploader.py` had been
offering "txt" and "docx" as contract formats since Phase 2 while `detect_type`
rejected both — every such upload landed as `extraction_status='failed'`. `.txt`
is now genuinely read (it is the shape the EDGAR corpus already arrives in);
"docx" was removed from the uploader instead, because reading it needs a new
dependency and therefore an ADR.

**Anything that raises here must stay a ValueError with a readable message.**
`core.ingest.extract_upload` catches exactly that and turns it into
`extraction_status='failed'` plus the message; a different exception type would
reach Streamlit and take the page down (known issue #37).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from core.ai.schemas import DocBlock, ExtractedDoc
from core.extraction import ocr_cloud, pdf_extractor

DocType = Literal["text_pdf", "scanned", "image", "csv", "text"]

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_TEXT_SUFFIXES = {".txt", ".text"}


def detect_type(file_path: str | Path) -> DocType:
    """Peek at a file and say which extraction path it needs. Raises ValueError
    on a genuinely unsupported extension — callers should catch this and record
    it as a failed document, not let it bubble up as a crash."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix in _TEXT_SUFFIXES:
        return "text"
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

    if kind == "text":
        # A plain-text contract. This is the shape the whole EDGAR corpus arrives
        # in — the SEC serves HTML, which `data_sourcing` writes to disk as .txt
        # (known issue #43, which is why `ExtractedDoc.doc_type` has a "text"
        # value at all). `page_count=1` because the source genuinely has no
        # pages: pagination is assigned later, and only for display, by
        # `pdf_renderer.typeset_pdf` (ADR-021).
        text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        if not text.strip():
            return ExtractedDoc(
                doc_type="text", blocks=[], full_text="", page_count=0, warnings=["file is empty"]
            )
        return ExtractedDoc(
            doc_type="text",
            blocks=[DocBlock(page_number=1, text=text)],
            full_text=text,
            page_count=1,
        )

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
