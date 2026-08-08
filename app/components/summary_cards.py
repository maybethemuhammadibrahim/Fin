"""[B] The four headline metric cards. Phase 2.

Reads: `queries.get_summary_stats(session, run_id) -> SummaryStats`.
Computes nothing. Every figure shown here is already a database aggregate — if
a number looks wrong, the bug is in the query or the data, never here.
"""

from __future__ import annotations

import streamlit as st

from core.db.queries import SummaryStats

#: Display label and colour dot per leak type. The four are mutually exclusive.
LEAK_TYPES: dict[str, tuple[str, str]] = {
    "ghost_invoice": ("🔴", "Ghost Invoice"),
    "forgotten_raise": ("🟡", "Forgotten Raise"),
    "zombie_discount": ("🟠", "Zombie Discount"),
    "short_change": ("🟣", "Short-Change"),
}


def money(amount: float) -> str:
    """$14,280 — no cents, because cents are noise at this scale."""
    return f"${amount:,.0f}"


def render_summary_cards(stats: SummaryStats) -> None:
    """The four cards across the top of the dashboard."""
    total, found, affected, recovery = st.columns(4)

    total.metric(
        "💰 Total Leaked",
        money(stats.total_leaked),
        help="Sum of the gap on every finding in this run.",
    )
    found.metric(
        "🔍 Anomalies Found",
        stats.anomaly_count,
        help="Across all four leak types.",
    )
    affected.metric(
        "👥 Clients Affected",
        f"{stats.affected_client_count} of {stats.client_count}",
        help="Clients with at least one finding.",
    )
    recovery.metric(
        "📈 Recovery Potential",
        f"{money(stats.total_leaked)}/yr",
        help=(
            "The leaked total, annualised. Recurring leaks keep costing you "
            "this much every year until the contract is corrected."
        ),
    )


def render_type_breakdown(stats: SummaryStats) -> None:
    """A row of small counts, one per leak type present."""
    if not stats.by_type:
        return
    cols = st.columns(len(LEAK_TYPES))
    for col, (key, (dot, label)) in zip(cols, LEAK_TYPES.items()):
        count = stats.by_type.get(key, 0)
        col.markdown(
            f"<div style='text-align:center;opacity:{1.0 if count else 0.35}'>"
            f"<div style='font-size:1.6rem'>{dot}</div>"
            f"<div style='font-size:1.5rem;font-weight:600'>{count}</div>"
            f"<div style='font-size:0.78rem;opacity:0.75'>{label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


def render_grounding_note(stats: SummaryStats) -> None:
    """State honestly how much of the total is backed by a locatable clause.

    ADR-005 allows clause location to fail. Hiding that would overstate how
    provable the headline number is, so it is said out loud.
    """
    if not stats.anomaly_count:
        return

    if stats.unlinked_count:
        st.warning(
            f"**{stats.unlinked_count} finding(s) have no clause reference at all** "
            "and are not proven. They are excluded from the evidence trail.",
            icon="⚠️",
        )
    if stats.unlocatable_count:
        st.info(
            f"{stats.unlocatable_count} of {stats.anomaly_count} findings quote a clause "
            "that could not be located in the source PDF, so those show the quoted "
            "text without a page highlight (ADR-005). The finding itself still holds.",
            icon="📄",
        )
