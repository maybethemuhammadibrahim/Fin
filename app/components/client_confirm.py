"""[B] The 'we found 4 clients' confirmation step after fuzzy grouping. Phase 5.

**Phase 2 builds the display; Phase 5 adds the fuzzy grouping behind it.**
Today the clients shown are the ones already in the database, so confirming is
a no-op that advances the UI. Once `core/ai/client_matcher.py` exists, this same
component will show *proposed* groupings ("ACME LTD" and "Acme Ltd." are one
client) for a human to correct before anything is reconciled.

That human checkpoint is the point of the component, and it is the same
reasoning as ADR-010's CSV mapping: an automatic grouping that is silently wrong
poisons every downstream number with no visible error.

Reads: `queries.list_clients(session, run_id) -> list[ClientRow]`.
"""

from __future__ import annotations

import streamlit as st

from core.db.queries import ClientRow


def render_client_confirm(clients: list[ClientRow]) -> bool:
    """Show the identified clients. Returns True when the user confirms."""
    if not clients:
        st.caption("No clients identified yet — upload contracts to get started.")
        return False

    st.markdown(f"**We identified {len(clients)} client(s):**")

    for client in clients:
        contracts = client.contract_count
        suffix = "contract" if contracts == 1 else "contracts"
        st.markdown(f"✅ **{client.name}** — {contracts} {suffix}")

    with st.expander("How names were matched"):
        st.caption(
            "Reconciliation matches bank descriptions against a normalised form "
            "of each name, not the name itself (ADR-006). Fuzzy grouping of "
            "near-duplicate names arrives in Phase 5; today these are the names "
            "exactly as stored."
        )
        st.dataframe(
            [{"Client": c.name, "Matched as": c.normalized_name} for c in clients],
            hide_index=True,
            use_container_width=True,
        )

    return st.button("Confirm & Analyze", type="primary", use_container_width=True)
