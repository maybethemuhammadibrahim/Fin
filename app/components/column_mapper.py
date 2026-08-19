"""[B] CSV header confirmation UI over the proposed column mapping. Phase 4.

**The proposal and the parse both live in `core/ingest.py`; this only asks.**
`web/` renders the same three dropdowns as an HTML form (ADR-025), so the
proposing, the caching by header signature and the writing of transactions are
core's — otherwise the two frontends could disagree about what a confirmed
mapping means, which is precisely the disagreement ADR-010 exists to prevent.

Today the proposal comes from `core/extraction/csv_parser.sniff_columns()`'s
deterministic header-matching heuristic rather than a live LLM call. The
human-confirmation step (ADR-010) is identical either way: nobody's transaction
data is parsed from a mapping a person did not look at, whether the first guess
came from a model or from `thefuzz`.

Writes nothing itself. `core.ingest.apply_mapping` records the confirmation.
"""

from __future__ import annotations

import streamlit as st

from core.ingest import REQUIRED_FIELDS, MappingProposal


def render_column_mapper(proposal: MappingProposal, key_prefix: str) -> dict[str, str] | None:
    """Show a proposed mapping; return it once the user accepts, else None.

    A header layout that was confirmed before skips the form and returns the
    remembered answer directly — the same CSV shape never asks twice.
    """
    if proposal.cached is not None:
        st.caption("✅ Recognised this column layout — reusing a previously confirmed mapping.")
        return proposal.cached

    st.markdown("**Confirm column mapping**")
    st.caption(
        "Matched by column name, not read by a model yet — check it before we parse "
        "amounts from it."
    )

    if proposal.proposal.sample_rows:
        st.dataframe(proposal.proposal.sample_rows[:3], hide_index=True, use_container_width=True)

    confirmed: dict[str, str] = {}
    cols = st.columns(len(REQUIRED_FIELDS))
    for widget, field in zip(cols, REQUIRED_FIELDS):
        with widget:
            options = ["(none)"] + proposal.columns
            default = proposal.suggested.get(field)
            index = options.index(default) if default in options else 0
            choice = st.selectbox(field.capitalize(), options, index=index, key=f"{key_prefix}_{field}")
            if choice != "(none)":
                confirmed[field] = choice

    from core.ingest import missing_fields

    missing = missing_fields(confirmed)
    if missing:
        st.warning(f"Map at least date and amount to continue (missing: {', '.join(missing)}).")

    if st.button("Confirm mapping", key=f"{key_prefix}_confirm", disabled=bool(missing)):
        return confirmed
    return None
