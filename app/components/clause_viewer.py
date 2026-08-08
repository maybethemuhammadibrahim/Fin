"""[B] Renders the contract page with the violated clause highlighted. Phase 7.

**Phase 2 builds the honest placeholder, not the renderer.** It shows the real
clause text, the real page number and the real `locate_method`, all read from
`clause_references` — but not a rendered PDF page, because
`core/extraction/pdf_renderer.py` is a Phase 7 stub and the seeded documents
have no bytes behind them.

Reads: `queries.get_clause_reference(session, clause_ref_id) -> ClauseRefRow | None`.

The three states this must handle, per ADR-005:

1. **Located** — page and bbox present. Phase 7 draws the highlight; today we
   say which page it is on.
2. **Quoted but not located** — `source_page` is NULL. The quote is real, the
   locator could not place it. Show the text, say so plainly. **Never crash.**
3. **No clause at all** — the caller passed None. The finding is unproven and
   must be labelled as such (hard rule 5).
"""

from __future__ import annotations

import streamlit as st

from core.db.queries import ClauseRefRow

LOCATE_EXPLANATIONS: dict[str, str] = {
    "exact": "Found verbatim in the PDF.",
    "fuzzy": "Matched approximately — the PDF text differs slightly from the quote, "
             "usually OCR noise or a line break.",
    "failed": "Could not be found in the PDF.",
}


def render_clause_viewer(clause: ClauseRefRow | None) -> None:
    """Show the evidence behind a finding, degrading honestly when it is thin."""
    if clause is None:
        st.error(
            "**No clause reference for this finding.** Every anomaly is supposed "
            "to trace to a specific contract clause, so treat this one as "
            "unproven until it does.",
            icon="🚫",
        )
        return

    header = f"📄 {clause.document_filename or 'contract'}"
    if clause.source_page is not None:
        header += f" — page {clause.source_page}"
    st.markdown(f"**{header}**")

    st.markdown(
        f"<blockquote style='border-left:4px solid #ff4b4b;margin:0.5rem 0;"
        f"padding:0.6rem 0.9rem;background:rgba(128,128,128,0.08);"
        f"font-style:italic'>{_escape(clause.clause_text)}</blockquote>",
        unsafe_allow_html=True,
    )

    _render_location_status(clause)


def _render_location_status(clause: ClauseRefRow) -> None:
    """Say exactly how much we can prove about where this quote came from."""
    method = clause.locate_method or "unknown"
    explanation = LOCATE_EXPLANATIONS.get(method, "Location status unknown.")

    if clause.is_grounded:
        st.success(
            f"Located on page {clause.source_page} · `{method}` — {explanation} "
            "The page image with the clause highlighted arrives in Phase 7.",
            icon="🎯",
        )
        with st.expander("Coordinates"):
            st.caption("PDF points, [x0, y0, x1, y1] — what Phase 7 will draw a box around.")
            st.code(str(clause.source_bbox), language=None)
    else:
        st.warning(
            f"**Quote could not be located in the document** (`{method}`). "
            f"{explanation} The text above is what the extractor returned "
            "verbatim, but there is no page highlight to show — and a quote that "
            "cannot be found may have been invented, so this finding is "
            "flagged low-confidence.",
            icon="📄",
        )

    if clause.clause_type:
        st.caption(f"Clause type: `{clause.clause_type}`")


def render_placeholder() -> None:
    """Shown before any row is selected."""
    st.info("👆 Select a finding above to see the contract clause that proves it.", icon="📄")


def _escape(text: str) -> str:
    """Escape HTML so clause text cannot inject markup into the blockquote."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )
