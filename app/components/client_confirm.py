"""[B] The 'we found 4 clients' confirmation step after fuzzy grouping. Phase 5.

**Phase 2 built the display; Phase 5 adds the fuzzy grouping behind it.**
`core/ai/client_matcher.py` now exists, so two things happen here:

* `render_client_confirm` still lists the clients already in the database, and
  additionally warns when two of those rows look like the same company.
* `render_group_confirm` takes the raw `client_name` strings the extractor
  produced and shows the *proposed* grouping for a human to correct before
  anything is reconciled.

That human checkpoint is the point of the component, and it is the same
reasoning as ADR-010's CSV mapping: an automatic grouping that is silently wrong
poisons every downstream number with no visible error. A wrong merge reconciles
one client's invoices against another client's contract.

Reads: `queries.list_clients(session, run_id) -> list[ClientRow]`.
"""

from __future__ import annotations

import streamlit as st

from core.ai.client_matcher import group_clients
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

    # Phase 5: the same fuzzy grouping the extractor uses, applied to what is
    # already stored. Two rows that collapse into one group are usually one
    # client that got entered twice.
    groups = group_clients([client.name for client in clients])
    duplicates = {name: variants for name, variants in groups.items() if len(variants) > 1}
    if duplicates:
        st.warning(
            "**These look like the same client under different names.** Their "
            "contracts and payments are currently reconciled separately, which "
            "will under-report the gap for each.",
            icon="🔗",
        )
        for canonical, variants in duplicates.items():
            st.markdown(f"- **{canonical}** ← {', '.join(v for v in variants if v != canonical)}")

    with st.expander("How names were matched"):
        st.caption(
            "Reconciliation matches bank descriptions against a normalised form "
            "of each name, not the name itself (ADR-006). Near-duplicate names "
            "are grouped by `client_matcher.group_clients`, which compares names "
            "with corporate suffixes and punctuation removed."
        )
        st.dataframe(
            [{"Client": c.name, "Matched as": c.normalized_name} for c in clients],
            hide_index=True,
            use_container_width=True,
        )

    return st.button("Confirm & Analyze", type="primary", use_container_width=True)


def render_group_confirm(
    names: list[str], *, key: str = "client_groups"
) -> dict[str, list[str]] | None:
    """Show the extractor's proposed client grouping for correction.

    `names` are the raw `client_name` strings, one per extracted contract.
    Returns the confirmed `{canonical: [variants]}` mapping once the user
    accepts it, and `None` until then — so the caller can simply not proceed.

    The user can rename any group (the label carries into the database) and can
    split a group whose members are genuinely different companies. Merging two
    groups the matcher kept apart is deliberately not offered: it is rare, and
    the fix is to rename one to match the other.
    """
    if not names:
        st.caption("No client names extracted yet.")
        return None

    proposed = group_clients(names)
    st.markdown(
        f"**We read {len(names)} contract(s) and found {len(proposed)} client(s):**"
    )

    corrected: dict[str, list[str]] = {}
    for index, (canonical, variants) in enumerate(proposed.items()):
        label_column, split_column = st.columns([3, 1])
        with label_column:
            chosen = st.text_input(
                f"Client {index + 1}",
                value=canonical,
                key=f"{key}_name_{index}",
            )
        with split_column:
            st.write("")
            st.write("")
            split = (
                st.checkbox("Not the same", key=f"{key}_split_{index}")
                if len(variants) > 1
                else False
            )
        if len(variants) > 1:
            st.caption("Grouped from: " + ", ".join(variants))

        if split:
            for variant in variants:
                corrected[variant] = [variant]
        else:
            corrected[chosen or canonical] = variants

    st.caption(
        "Getting this wrong reconciles one client's payments against another's "
        "contract, so it is worth ten seconds."
    )
    if st.button("Confirm clients", type="primary", key=f"{key}_confirm"):
        return corrected
    return None
