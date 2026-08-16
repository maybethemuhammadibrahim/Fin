"""[B] Renders the contract page with the violated clause highlighted. Phase 7.

**Phase 2 built the honest placeholder; Phase 7 draws the page.** The quote, the
page number and the `locate_method` all still come from `clause_references` —
what is new is the picture: `pdf_renderer.render_document_page` returns the page
as PNG bytes with an amber box over the clause.

Reads: `queries.get_clause_reference(...)` and `queries.get_document(...)`.

The three states, per ADR-005 — build all three, and never crash on the third:

1. **Located** (`exact`) — page image, highlight, quote below.
2. **Located approximately** (`fuzzy`) — the same, plus a note saying the match
   was approximate, because the box may sit on the right paragraph and the wrong
   line.
3. **Not located** (`failed` / NULL) — the page with **no** highlight and a plain
   statement that the quote could not be placed. A confident box in the wrong
   place is worse than no box, and a finding whose quote is nowhere in the
   document may be a hallucination, which the user is told outright.

A fourth state exists that the plan does not name: **no page to render at all.**
The clause has no document, or the document has neither PDF bytes nor extracted
text. The quote is shown alone. See ADR-021 for why that state is now rare — a
text-only filing is typeset into a PDF rather than left unrenderable.
"""

from __future__ import annotations

import streamlit as st

from core.db.queries import ClauseRefRow, DocumentRow
from core.extraction.pdf_renderer import render_document_page

LOCATE_EXPLANATIONS: dict[str, str] = {
    "exact": "Found verbatim in the document.",
    "fuzzy": "Matched approximately — the rendered text differs slightly from the quote, "
             "usually a ligature, a dash or a line break.",
    "failed": "Could not be found in the document.",
}


def render_clause_viewer(clause: ClauseRefRow | None, document: DocumentRow | None = None) -> None:
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

    image, typeset = _page_image(clause, document)

    left, right = st.columns([3, 2], gap="medium")

    with left:
        if image is not None:
            st.image(
                image,
                caption=_caption(clause, typeset),
                use_container_width=True,
            )
        else:
            st.caption(
                "No page to render: this document has neither a stored PDF nor "
                "extracted text behind it."
            )

    with right:
        st.markdown(
            f"<blockquote style='border-left:4px solid #ff4b4b;margin:0.5rem 0;"
            f"padding:0.6rem 0.9rem;background:rgba(128,128,128,0.08);"
            f"font-style:italic'>{_escape(clause.clause_text)}</blockquote>",
            unsafe_allow_html=True,
        )
        _render_location_status(clause, has_image=image is not None)


def _page_image(clause: ClauseRefRow, document: DocumentRow | None) -> tuple[bytes | None, bool]:
    """The page, highlighted when we know where to draw. `(png, is_typeset)`."""
    if document is None:
        return None, False
    rendered = render_document_page(
        storage_url=document.storage_url,
        extracted_text=document.extracted_text,
        filename=document.filename,
        file_type=document.file_type,
        page=clause.source_page,
        # ADR-005: no box when the quote was not placed. The page still renders.
        bbox=clause.source_bbox if clause.is_grounded else None,
    )
    if rendered is None:
        return None, False
    return rendered


def _caption(clause: ClauseRefRow, typeset: bool) -> str:
    parts = []
    if clause.is_grounded:
        parts.append(f"Page {clause.source_page}, highlighted")
    elif clause.source_page:
        parts.append(f"Page {clause.source_page} — no highlight, the quote was not placed")
    else:
        parts.append("Page 1 — the quote was not placed anywhere in this document")
    if typeset:
        # ADR-021. Saying this is the whole reason the typeset page is allowed to
        # count as evidence.
        parts.append(
            "typeset by FinSight from the filing's own text — the original is HTML, not a PDF"
        )
    return " · ".join(parts)


def _render_location_status(clause: ClauseRefRow, *, has_image: bool) -> None:
    """Say exactly how much we can prove about where this quote came from."""
    method = clause.locate_method or "unknown"
    explanation = LOCATE_EXPLANATIONS.get(method, "Location status unknown.")

    if clause.is_grounded and method == "exact":
        st.success(f"Located on page {clause.source_page}. {explanation}", icon="🎯")
    elif clause.is_grounded:
        st.info(
            f"Located approximately on page {clause.source_page}. {explanation} "
            "The highlight marks the paragraph, which may be a line out.",
            icon="📍",
        )
    else:
        st.warning(
            f"**Quote could not be located in the document** (`{method}`). "
            f"{explanation} The text above is what the extractor returned verbatim, "
            + ("so the page is shown without a highlight" if has_image else "and there is no page to show")
            + " — a highlight in the wrong place would be worse than none. A quote "
            "that cannot be found may have been invented, so treat this finding as "
            "low-confidence.",
            icon="📄",
        )

    if clause.clause_type:
        st.caption(f"Clause type: `{clause.clause_type}`")
    if clause.is_grounded:
        with st.expander("Coordinates"):
            st.caption("PDF points, [x0, y0, x1, y1] — the box drawn on the page above.")
            st.code(str(clause.source_bbox), language=None)


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
