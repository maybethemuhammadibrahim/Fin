"""[B] CSV header confirmation UI over the proposed column mapping. Phase 4.

Today the proposal comes from `core/extraction/csv_parser.sniff_columns()`'s
deterministic header-matching heuristic, not a live LLM call — `core/ai/llm_client.py`
doesn't exist until Phase 5 (ADR-012's serving timeline). The human-confirmation step
(ADR-010) is identical either way: nobody's transaction data is parsed from a mapping
a person didn't look at, whether the first guess came from a model or from
`thefuzz`. A confirmed mapping is cached by header signature so the same CSV shape
never asks twice.

Writes: `column_mappings`, and only on explicit confirmation.
"""

from __future__ import annotations

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import ColumnMapping
from core.extraction.csv_parser import REQUIRED_FIELDS, ColumnProposal, sniff_columns


def get_cached_mapping(session: Session, header_signature: str) -> dict[str, str] | None:
    row = session.scalars(
        select(ColumnMapping).where(ColumnMapping.header_signature == header_signature)
    ).first()
    return row.mapping if row else None


def render_column_mapper(session: Session, file_path: str, key_prefix: str) -> dict[str, str] | None:
    """Show the proposed mapping for one CSV; return the confirmed {field: column}
    mapping once the user accepts it, else None. A recognised header layout (same
    signature as a mapping already confirmed) skips the UI and returns it directly.
    """
    proposal: ColumnProposal = sniff_columns(file_path)

    cached = get_cached_mapping(session, proposal.header_signature)
    if cached is not None:
        st.caption("✅ Recognised this column layout — reusing a previously confirmed mapping.")
        return cached

    st.markdown("**Confirm column mapping**")
    st.caption("Matched by column name, not read by a model yet — check it before we parse amounts from it.")

    if proposal.sample_rows:
        st.dataframe(proposal.sample_rows[:3], hide_index=True, use_container_width=True)

    all_columns = list(proposal.sample_rows[0].keys()) if proposal.sample_rows else list(proposal.mapping.values())

    confirmed: dict[str, str] = {}
    cols = st.columns(len(REQUIRED_FIELDS))
    for widget, field in zip(cols, REQUIRED_FIELDS):
        with widget:
            options = ["(none)"] + all_columns
            default = proposal.mapping.get(field)
            index = options.index(default) if default in options else 0
            choice = st.selectbox(field.capitalize(), options, index=index, key=f"{key_prefix}_{field}")
            if choice != "(none)":
                confirmed[field] = choice

    missing = [f for f in ("date", "amount") if f not in confirmed]
    if missing:
        st.warning(f"Map at least date and amount to continue (missing: {', '.join(missing)}).")

    if st.button("Confirm mapping", key=f"{key_prefix}_confirm", disabled=bool(missing)):
        session.add(ColumnMapping(header_signature=proposal.header_signature, mapping=confirmed))
        session.flush()
        return confirmed
    return None
