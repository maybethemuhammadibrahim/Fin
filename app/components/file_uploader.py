"""[B] Dual upload zones (contracts / actuals) with a type toggle. Phase 2.

Files are accepted, persisted via `core/storage/files.py`, and recorded as
`documents` rows with `extraction_status="pending"`. **Nothing is parsed** —
routing and text extraction are Phase 4. The status column is what makes that
visible instead of mysterious: a pending row is a promise, not a failure.

Writes: `documents`. This is the one component that writes, and it writes only
the upload record — never analysis output.
"""

from __future__ import annotations

import streamlit as st

from core.db.models import Document
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
        st.success(
            f"Recorded {saved} file(s). They are stored and queued, but **not "
            "analysed yet** — extraction lands in Phase 4.",
            icon="📥",
        )
    return saved


def _persist(session, run_id: int, uploads, category: str) -> int:
    """Save each uploaded file once and record a pending `documents` row."""
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

        session.add(
            Document(
                run_id=run_id,
                filename=upload.name,
                file_type=upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else None,
                category=category,
                storage_url=url,
                extraction_status="pending",
            )
        )
        existing.add(upload.name)
        saved += 1

    if saved:
        session.flush()
    return saved


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
