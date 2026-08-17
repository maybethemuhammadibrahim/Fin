"""[B] The button that runs the verification agent over a run's findings. Phase 8.

Same shape as `reconcile_panel.render_reconcile_panel`: a status caption
naming the active model endpoint, a button, a spinner, and an honest summary
that reports what happened rather than hiding it. `web/` needs no equivalent
— it reads `agent_reasoning` / `agent_tool_calls` already (ADR-018) and picks
up whatever this panel writes with no template change.
"""

from __future__ import annotations

import streamlit as st

from core.agents.verification_agent import VerifyRunSummary, verify_run
from core.ai import endpoints


def render_verify_panel(session, run_id: int, unverified_count: int) -> bool:
    """The verify action. Returns True when at least one row's status changed."""
    if unverified_count == 0:
        st.info(
            "Nothing to verify — every finding in this run has already been checked "
            "by the agent, or there are no findings yet.",
            icon="✅",
        )
        return False

    active = endpoints.active()
    left, right = st.columns([3, 1])
    with left:
        st.markdown(
            f"**{unverified_count} finding(s) not yet checked.** The verification agent "
            "re-reads each one — its contract clause, nearby bank transactions, whether "
            "a payment was split — and either confirms it, marks it a false positive, or "
            "flags it for manual review. It never changes a figure, only a status."
        )
        st.caption(
            f"Endpoint: {active.label}"
            + ("" if active.configured else " — **no URL set**, so this will fail")
        )
    with right:
        pressed = st.button("Verify findings", type="primary", use_container_width=True)

    if not pressed:
        return False

    with st.spinner(f"Reviewing {unverified_count} finding(s), one at a time…"):
        summary = verify_run(session, run_id)

    _render_summary(summary)
    return summary.checked > summary.skipped


def _render_summary(summary: VerifyRunSummary) -> None:
    if summary.skipped == summary.checked and summary.checked > 0:
        st.error(
            f"The model endpoint did not answer for any of {summary.checked} finding(s). "
            "They remain unverified. Check the Model endpoint page for a live tunnel URL.",
            icon="🛑",
        )
        return

    st.success(summary.as_line(), icon="🤖")

    columns = st.columns(4)
    columns[0].metric("Confirmed", summary.confirmed)
    columns[1].metric("False positive", summary.false_positive)
    columns[2].metric("Needs review", summary.needs_review)
    columns[3].metric("Skipped", summary.skipped)

    if summary.skipped:
        st.warning(
            f"{summary.skipped} finding(s) could not be reached and are still unverified — "
            "the agent never overwrites a status it could not actually check.",
            icon="⚠️",
        )
