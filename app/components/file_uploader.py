"""[B] Dual upload zones (contracts / actuals) with a type toggle. Phase 2/4.

Files are accepted, persisted via `core/storage/files.py`, and recorded as
`documents` rows. **Phase 4**: contracts and invoice/statement images or PDFs are
routed through `core/extraction/document_router.extract()` synchronously at upload
time, so a row lands with `extraction_status` already `complete` or `failed` —
never stuck at `pending`. A CSV actuals upload is the one exception: ADR-010
requires a human-confirmed column mapping before any amount gets parsed, so it
stays `pending` until `render_pending_csv_mappings()` (below) walks the user
through it and writes `actual_transactions`.

Writes: `documents` (this function) and `actual_transactions` (the CSV mapping
step). This is the one component that writes analysis input — never a finding.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from app.components.column_mapper import render_column_mapper
from core.db.models import ActualTransaction, Document
from core.extraction import csv_parser
from core.extraction import document_router as router
from core.storage import files

CONTRACT_TYPES = ["pdf", "docx", "txt"]
ACTUALS_TYPES = ["csv", "xlsx", "pdf", "png", "jpg", "jpeg"]


def render_file_uploaders(session, run_id: int) -> int:
    """Both upload zones. Returns how many new documents were recorded."""
    left, right = st.columns(2)
    saved = 0

    with left:
        st.markdown("**📄 Contracts**")
        st.caption("The agreements that say what you are owed.")
        uploads = st.file_uploader(
            "Drop contracts here",
            type=CONTRACT_TYPES,
            accept_multiple_files=True,
            key="upload_contracts",
            label_visibility="collapsed",
        )
        saved += _persist(session, run_id, uploads, category="contract")

    with right:
        st.markdown("**🧾 Invoices & bank statements**")
        st.caption("What actually got billed and paid.")
        kind = st.radio(
            "Format",
            options=["CSV / spreadsheet", "Scanned image or PDF"],
            horizontal=True,
            key="upload_actuals_kind",
            help="Scanned files take the OCR path in Phase 4.",
        )
        category = "statement" if kind.startswith("CSV") else "invoice"
        uploads = st.file_uploader(
            "Drop invoices or statements here",
            type=ACTUALS_TYPES,
            accept_multiple_files=True,
            key="upload_actuals",
            label_visibility="collapsed",
        )
        saved += _persist(session, run_id, uploads, category=category)

    st.caption(f"Uploads are stored on {files.describe()}.")

    if saved:
        st.success(f"Recorded {saved} file(s) and extracted what we could immediately.", icon="📥")
    return saved


def _extract_and_finalize(data: bytes, filename: str) -> tuple[str, str | None, str | None, int | None]:
    """(extraction_status, error_message, extracted_text, page_count) for one
    upload. Writes to a temp file because document_router.extract() takes a path
    (pdfplumber/pymupdf need one) — the bytes are already in hand from the upload,
    so this never touches storage. Never raises: an unsupported type or an empty
    result both become extraction_status='failed' with a readable message."""
    suffix = Path(filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        try:
            doc = router.extract(tmp_path)
        except ValueError as exc:  # unsupported file type
            return "failed", str(exc), None, None
        if not doc.full_text.strip():
            reason = "; ".join(doc.warnings) or "no extractable text"
            return "failed", reason, None, None
        return "complete", None, doc.full_text, doc.page_count
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _persist(session, run_id: int, uploads, category: str) -> int:
    """Save each uploaded file once and record its `documents` row.

    CSV actuals (`category == "statement"`) stay `extraction_status='pending'` —
    ADR-010 requires a human-confirmed column mapping before parsing, handled by
    `render_pending_csv_mappings()`. Everything else (contracts, and invoice/bank
    images or PDFs) is routed through `document_router.extract()` right here, so
    the row is already `complete` or `failed` by the time this returns.
    """
    if not uploads:
        return 0

    existing = {
        name
        for (name,) in session.query(Document.filename).filter(Document.run_id == run_id).all()
    }

    saved = 0
    for upload in uploads:
        if upload.name in existing:
            continue  # Streamlit re-delivers the same files on every rerun.
        data = upload.getvalue()
        try:
            url = files.save_upload(data, upload.name, run_id)
        except files.StorageError as exc:
            # Loud, not silent: a dropped upload would leave a documents row
            # pointing at nothing, discovered only at extraction time.
            st.error(f"Could not save **{upload.name}**: {exc}")
            continue

        kwargs: dict = dict(
            run_id=run_id,
            filename=upload.name,
            file_type=upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else None,
            category=category,
            storage_url=url,
        )
        if category == "statement":
            kwargs["extraction_status"] = "pending"
        else:
            status, error, text, pages = _extract_and_finalize(data, upload.name)
            kwargs.update(
                extraction_status=status, error_message=error, extracted_text=text, extracted_page_count=pages
            )

        session.add(Document(**kwargs))
        existing.add(upload.name)
        saved += 1

    if saved:
        session.flush()
    return saved


# ---------------------------------------------------------------------------
# CSV actuals: human-confirmed column mapping, then parse (ADR-010, Phase 4)
# ---------------------------------------------------------------------------


def render_pending_csv_mappings(session, documents) -> int:
    """For every pending CSV `documents` row, show the column-mapper and, once
    confirmed, parse and write `actual_transactions`. Returns how many documents
    were finalized (complete or failed) this run, so the caller knows to rerun."""
    pending_csvs = [
        d for d in documents if d.category == "statement" and d.extraction_status == "pending"
    ]
    if not pending_csvs:
        return 0

    finalized = 0
    for doc in pending_csvs:
        st.markdown(f"**{doc.filename}**")
        if Path(doc.filename).suffix.lower() != ".csv":
            doc_row = session.get(Document, doc.id)
            doc_row.extraction_status = "failed"
            doc_row.error_message = "only .csv is parsed today — xlsx support is not wired up yet"
            finalized += 1
            continue

        data = files.load(doc.storage_url)
        if data is None:
            doc_row = session.get(Document, doc.id)
            doc_row.extraction_status = "failed"
            doc_row.error_message = "could not read the uploaded file back from storage"
            finalized += 1
            continue

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            mapping = render_column_mapper(session, tmp_path, key_prefix=f"csvmap_{doc.id}")
            if mapping is None:
                continue  # awaiting confirmation this run

            rows = csv_parser.parse_transactions(tmp_path, mapping)
            doc_row = session.get(Document, doc.id)
            if not rows:
                doc_row.extraction_status = "failed"
                doc_row.error_message = "no rows could be parsed with the confirmed mapping"
                finalized += 1
                continue

            for row in rows:
                session.add(
                    ActualTransaction(
                        run_id=doc.run_id,
                        document_id=doc.id,
                        client_id=None,  # resolved later by Phase 5's client_matcher
                        transaction_date=row.transaction_date,
                        amount=row.amount,
                        description=row.description,
                        source_type="bank",
                    )
                )
            doc_row.extraction_status = "complete"
            doc_row.error_message = None
            doc_row.extracted_text = f"{len(rows)} transaction(s) parsed from columns: {', '.join(mapping.values())}"
            session.flush()
            st.success(f"Parsed {len(rows)} transaction(s) from **{doc.filename}**.", icon="✅")
            finalized += 1
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    return finalized


def render_document_list(documents) -> None:
    """Everything uploaded in this run, with its extraction status."""
    if not documents:
        st.caption("No documents in this run yet.")
        return

    icons = {"pending": "⏳", "processing": "⚙️", "complete": "✅", "failed": "❌"}
    st.dataframe(
        [
            {
                "File": d.filename,
                "Kind": d.category or "—",
                "Status": f"{icons.get(d.extraction_status, '•')} {d.extraction_status}",
                "Error": d.error_message or "",
            }
            for d in documents
        ],
        hide_index=True,
        use_container_width=True,
    )

    extracted = [d for d in documents if d.extracted_text]
    if extracted:
        with st.expander("Preview extracted text"):
            for d in extracted:
                pages = f" · {d.extracted_page_count} page(s)" if d.extracted_page_count else ""
                st.caption(f"**{d.filename}**{pages}")
                st.text(d.extracted_text[:1000] + ("…" if len(d.extracted_text) > 1000 else ""))
