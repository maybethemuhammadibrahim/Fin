"""[B] Page 1: upload documents, review detected revenue leaks. Phase 2/4.

The v1 mockup, built against real database rows.

Reads (all via `core/db/queries.py`):
  get_summary_stats  -> the four cards and the grounding note
  list_clients       -> the client confirmation block
  list_documents     -> the upload status list
  list_anomalies     -> the findings table
  get_anomaly        -> the selected finding's detail
  get_clause_reference -> the clause viewer

Writes: `documents` (upload component, Phase 2); `actual_transactions` +
`column_mappings` once a pending CSV's columns are confirmed (Phase 4); and,
since Phase 6, `contract_rules` + `expected_timeline` + `anomalies` through
`app/components/reconcile_panel.py`, which calls `core/engine/pipeline.py`.

Every number rendered here is a database aggregate. There is no hardcoded dict
anywhere on this page — that is the rule that made Phase 6 a data change instead
of an integration project (ADR-008): the findings table below did not change one
line when its rows stopped being seeded and started being computed.
"""

from __future__ import annotations

import streamlit as st

from app import state
from app.components.anomaly_table import (
    render_anomaly_detail,
    render_anomaly_table,
    render_filters,
)
from app.components.clause_viewer import render_clause_viewer, render_placeholder
from app.components.client_confirm import render_client_confirm
from app.components.file_uploader import (
    render_document_list,
    render_file_uploaders,
    render_pending_csv_mappings,
)
from app.components.reconcile_panel import render_extract_panel, render_reconcile_panel
from app.components.summary_cards import (
    render_grounding_note,
    render_summary_cards,
    render_type_breakdown,
)
from core.db import database
from core.db.queries import (
    count_contract_rules,
    get_anomaly,
    get_clause_reference,
    get_document,
    get_summary_stats,
    list_anomalies,
    list_clients,
    list_documents,
)

st.set_page_config(page_title="FinSight · Revenue Integrity", page_icon="📊", layout="wide")

# ---------------------------------------------------------------------------
# Guard: no database, no page.
# ---------------------------------------------------------------------------

ok, message = database.check_connection()
if not ok:
    st.title("📊 Revenue Integrity Dashboard")
    st.error(f"**Database unreachable.**\n\n```\n{message}\n```")
    st.caption("The DB Health page in the sidebar explains how to fix this.")
    st.stop()

run_id = state.render_run_selector()

st.title("📊 Revenue Integrity Dashboard")

if run_id is None:
    st.info(
        "No runs in the database yet. Seed the demo data to see the dashboard "
        "with real rows.",
        icon="🌱",
    )
    st.code("python scripts/seed_demo.py", language="bash")
    st.stop()

# ---------------------------------------------------------------------------
# Everything below reads one session's worth of rows.
# ---------------------------------------------------------------------------

with state.db() as session:
    stats = get_summary_stats(session, run_id)
    clients = list_clients(session, run_id)
    documents = list_documents(session, run_id)

render_summary_cards(stats)
st.divider()
render_type_breakdown(stats)
render_grounding_note(stats)

# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

st.divider()
st.subheader("1 · Upload")

with state.db() as session:
    saved = render_file_uploaders(session, run_id)
if saved:
    st.rerun()

with st.expander(f"Documents in this run ({len(documents)})"):
    render_document_list(documents)

pending_csvs = [d for d in documents if d.category == "statement" and d.extraction_status == "pending"]
if pending_csvs:
    st.markdown("**Confirm CSV columns before parsing amounts (ADR-010):**")
    with state.db() as session:
        finalized = render_pending_csv_mappings(session, documents)
    if finalized:
        st.rerun()

# ---------------------------------------------------------------------------
# Confirm clients
# ---------------------------------------------------------------------------

st.divider()
st.subheader("2 · Confirm clients")

if render_client_confirm(clients):
    st.success("Confirmed. Reconcile below to rebuild this run's findings.", icon="✅")

# ---------------------------------------------------------------------------
# Reconcile — the first action in this app that computes rather than reads
# ---------------------------------------------------------------------------

st.divider()
st.subheader("3 · Reconcile")

with state.db() as session:
    contract_count = count_contract_rules(session, run_id)
    if render_reconcile_panel(session, run_id, contract_count):
        state.clear_selected_anomaly()

with st.expander("Extract contract rules from uploaded contracts (needs a live endpoint)"):
    with state.db() as session:
        if render_extract_panel(session, run_id, documents):
            st.rerun()

# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

st.divider()
st.subheader("4 · Findings")

with state.db() as session:
    all_anomalies = list_anomalies(session, run_id)

if not all_anomalies:
    st.info("No findings in this run yet.", icon="✅")
    st.stop()

chosen_type, chosen_status = render_filters(all_anomalies)

with state.db() as session:
    anomalies = list_anomalies(session, run_id, status=chosen_status, anomaly_type=chosen_type)

st.caption(
    f"Showing {len(anomalies)} of {len(all_anomalies)} findings · "
    f"${sum(a.gap for a in anomalies):,.0f} of ${stats.total_leaked:,.0f}"
)

clicked = render_anomaly_table(anomalies)
if clicked is not None:
    state.set_selected_anomaly(clicked)

st.caption("👆 Click any row to see the contract clause that proves it.")

# ---------------------------------------------------------------------------
# Drill-down
# ---------------------------------------------------------------------------

st.divider()
st.subheader("5 · Evidence")

selected_id = state.get_selected_anomaly()

if selected_id is None:
    render_placeholder()
else:
    with state.db() as session:
        anomaly = get_anomaly(session, selected_id)
        clause = (
            get_clause_reference(session, anomaly.clause_reference_id)
            if anomaly and anomaly.clause_reference_id
            else None
        )
        # Phase 7: the viewer needs the document behind the clause to render its
        # page — a stored PDF, or the extracted text typeset into one (ADR-021).
        clause_document = (
            get_document(session, clause.document_id) if clause and clause.document_id else None
        )

    if anomaly is None:
        # The selection survived a run switch or a reseed. Not an error.
        state.clear_selected_anomaly()
        render_placeholder()
    else:
        render_anomaly_detail(anomaly)
        render_clause_viewer(clause, clause_document)
        if st.button("Clear selection"):
            state.clear_selected_anomaly()
            st.rerun()
