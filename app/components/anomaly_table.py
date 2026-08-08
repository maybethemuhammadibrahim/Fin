"""[B] Anomaly table with row-click drill-down. Phase 2.

Reads: `queries.list_anomalies(session, run_id, status=, anomaly_type=)`.

Row selection uses `st.dataframe(selection_mode="single-row")` rather than a
column of buttons: a button per row re-renders the whole table on every click
and loses the sort order. The dataframe returns positional indices, so the
displayed order and the backing list must stay in lockstep — hence one list
built once and indexed, never re-sorted for display.
"""

from __future__ import annotations

import streamlit as st

from app.components.summary_cards import LEAK_TYPES, money
from core.db.queries import AnomalyRow

STATUS_LABELS: dict[str, str] = {
    "unverified": "⏳ Unverified",
    "confirmed": "✅ Confirmed",
    "false_positive": "🚫 False positive",
    "needs_review": "🔎 Needs review",
}


def type_label(anomaly_type: str) -> str:
    dot, label = LEAK_TYPES.get(anomaly_type, ("⚪", anomaly_type))
    return f"{dot} {label}"


def render_anomaly_table(anomalies: list[AnomalyRow]) -> int | None:
    """Render the findings table. Returns the clicked anomaly's id, or None.

    Returning an id rather than a row keeps the caller re-reading from the
    database, which is what ADR-008 requires.
    """
    if not anomalies:
        st.info(
            "No findings in this run. Either nothing leaked, or the analysis "
            "has not run yet.",
            icon="✅",
        )
        return None

    rows = [
        {
            "Client": a.client_name,
            "Type": type_label(a.anomaly_type),
            "Date": a.billing_date.strftime("%b %Y") if a.billing_date else "—",
            "Expected": a.expected_amount,
            "Actual": a.actual_amount,
            "Gap": a.gap,
            "Confidence": a.confidence_score,
            "Status": STATUS_LABELS.get(a.status, a.status),
            "Evidence": "📄" if a.has_clause else "—",
        }
        for a in anomalies
    ]

    event = st.dataframe(
        rows,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Client": st.column_config.TextColumn(width="medium"),
            "Type": st.column_config.TextColumn(width="medium"),
            "Expected": st.column_config.NumberColumn(format="$%.0f"),
            "Actual": st.column_config.NumberColumn(format="$%.0f"),
            "Gap": st.column_config.NumberColumn(format="$%.0f"),
            "Confidence": st.column_config.ProgressColumn(
                min_value=0.0, max_value=1.0, format="%.2f",
                help="From the rule engine. The agent adjusts it in Phase 8.",
            ),
            "Evidence": st.column_config.TextColumn(
                width="small", help="📄 means a contract clause backs this finding."
            ),
        },
    )

    selected = event.selection.rows if event and event.selection else []
    if not selected:
        return None

    index = selected[0]
    if 0 <= index < len(anomalies):
        return anomalies[index].id
    return None


def render_filters(anomalies: list[AnomalyRow]) -> tuple[str | None, str | None]:
    """Type and status filter controls. Returns (anomaly_type, status), None = all.

    Options come from what is actually present in the data, so a filter can
    never select an empty set.
    """
    present_types = sorted({a.anomaly_type for a in anomalies})
    present_statuses = sorted({a.status for a in anomalies})

    left, right = st.columns(2)
    chosen_type = left.selectbox(
        "Leak type",
        options=[None, *present_types],
        format_func=lambda t: "All types" if t is None else type_label(t),
    )
    chosen_status = right.selectbox(
        "Status",
        options=[None, *present_statuses],
        format_func=lambda s: "All statuses" if s is None else STATUS_LABELS.get(s, s),
    )
    return chosen_type, chosen_status


def render_anomaly_detail(anomaly: AnomalyRow) -> None:
    """The figures for one finding, above the clause viewer."""
    st.markdown(f"### {type_label(anomaly.anomaly_type)} — {anomaly.client_name}")

    expected, actual, gap, confidence = st.columns(4)
    expected.metric("Expected", money(anomaly.expected_amount))
    actual.metric("Actual", money(anomaly.actual_amount))
    gap.metric("Gap", money(anomaly.gap), delta=f"-{money(anomaly.gap)}", delta_color="inverse")
    confidence.metric("Confidence", f"{anomaly.confidence_score:.0%}")

    if anomaly.billing_date:
        st.caption(f"Billing period: {anomaly.billing_date:%B %Y}")

    if anomaly.agent_reasoning:
        with st.expander("🤖 Verification agent notes"):
            st.write(anomaly.agent_reasoning)
    elif anomaly.status == "unverified":
        st.caption("Not yet checked by the verification agent — that lands in Phase 8.")
