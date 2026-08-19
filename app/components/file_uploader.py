"""[B] Dual upload zones (contracts / actuals), drawn in Streamlit. Phase 2/4.

**The sequence lives in `core/ingest.py`, not here.** This file is the Streamlit
half: two drop zones, a status table, and the column-mapping form. Saving a file,
recording it, reading it and parsing a confirmed statement are all
`core.ingest`, because `web/` performs the same steps behind an HTML form
(ADR-025) and two implementations of "what does `extraction_status` mean" is the
divergence this project keeps a single core to prevent.

Writes: `documents` and `actual_transactions`, both through `core.ingest`. This
is the one component that writes analysis input — never a finding.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.components.column_mapper import render_column_mapper
from core import ingest
from core.db.models import Document
from core.ingest import ACTUALS_TYPES, CONTRACT_TYPES
from core.storage import files


def _uploads(raw) -> list[tuple[str, bytes]]:
    """Streamlit's `UploadedFile` objects as the `(name, bytes)` core wants."""
    return [(u.name, u.getvalue()) for u in raw or []]


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
        saved += ingest.ingest_files(
            session, run_id, _uploads(uploads), category="contract"
        ).recorded

    with right:
        st.markdown("**🧾 Invoices & bank statements**")
        st.caption(
            "What actually got billed and paid. A .csv asks you to confirm its "
            "columns before anything is read from it; a PDF or an image has its "
            "text pulled out straight away."
        )
        uploads = st.file_uploader(
            "Drop invoices or statements here",
            type=ACTUALS_TYPES,
            accept_multiple_files=True,
            key="upload_actuals",
            label_visibility="collapsed",
        )
        # Split by what each file *is*, not by what a control said it would be.
        # See `core.ingest.actuals_category` for the bug this replaced.
        statements, invoices = ingest.split_actuals(_uploads(uploads))
        saved += ingest.ingest_files(session, run_id, statements, category="statement").recorded
        saved += ingest.ingest_files(session, run_id, invoices, category="invoice").recorded

    st.caption(f"Uploads are stored on {files.describe()}.")

    if saved:
        st.success(f"Recorded {saved} file(s) and extracted what we could immediately.", icon="📥")
    return saved


# ---------------------------------------------------------------------------
# CSV actuals: human-confirmed column mapping, then parse (ADR-010, Phase 4)
# ---------------------------------------------------------------------------


def render_pending_csv_mappings(session, documents) -> int:
    """For every pending CSV `documents` row, show the column-mapper and, once
    confirmed, hand it to `core.ingest.apply_mapping`. Returns how many documents
    were finalized (complete or failed), so the caller knows to rerun.

    The parsing, the transaction rows and the remembered mapping are all core's;
    what is left here is the asking.
    """
    pending = [
        d for d in documents if d.category == "statement" and d.extraction_status == "pending"
    ]
    if not pending:
        return 0

    finalized = 0
    for doc in pending:
        st.markdown(f"**{doc.filename}**")
        doc_row = session.get(Document, doc.id)

        if Path(doc.filename).suffix.lower() != ".csv":
            # The uploader can no longer produce this: `ingest.actuals_category`
            # sends only .csv down the statement path. A row written by a script
            # or an older build still can, so it is caught rather than assumed
            # away.
            doc_row.extraction_status = "failed"
            doc_row.error_message = (
                "only .csv is parsed into transactions — export this as CSV and re-upload"
            )
            st.error(doc_row.error_message)
            finalized += 1
            continue

        proposal = ingest.propose_mapping(session, doc_row)
        if proposal is None:
            doc_row.extraction_status = "failed"
            doc_row.error_message = "could not read the uploaded file back from storage"
            st.error(doc_row.error_message)
            finalized += 1
            continue

        mapping = render_column_mapper(proposal, key_prefix=f"csvmap_{doc.id}")
        if mapping is None:
            continue  # awaiting confirmation this run

        outcome = ingest.apply_mapping(session, doc_row, mapping)
        if outcome.status == "complete":
            st.success(
                f"Parsed {outcome.transactions} transaction(s) from **{doc.filename}**.",
                icon="✅",
            )
        else:
            st.error(f"{doc.filename}: {outcome.error}")
        finalized += 1

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
