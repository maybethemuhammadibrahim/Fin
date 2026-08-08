"""[B] Page 2: ask a strategic question, get a verdict. Phase 9.

**Phase 2 builds the whole surface; the thinking arrives in Phase 9.** The
question box accepts text but nothing parses it; the verdict is a template
filled with real figures. Everything numeric on this page comes from the
database — the recovered total is `SummaryStats.total_leaked`, and the
projection is cumulative arithmetic over it.

That distinction matters: the page *looks* finished because the layout and the
data are finished. What is missing is `core/ai/decision_analyzer.py` (parsing
the question) and `core/engine/cashflow.py` (the real projection). Both are
Phase 9, and both are called out on the page rather than hidden.

Reads: `get_summary_stats`, `list_anomalies`.
"""

from __future__ import annotations

import streamlit as st

from app import state
from app.components.cash_flow_chart import render_breakdown, render_cash_flow_chart
from app.components.summary_cards import money
from core.db import database
from core.db.queries import get_summary_stats, list_anomalies

st.set_page_config(page_title="FinSight · Decision Engine", page_icon="🧭", layout="wide")

MONTHS = 12

ok, message = database.check_connection()
if not ok:
    st.title("🧭 Decision Engine")
    st.error(f"**Database unreachable.**\n\n```\n{message}\n```")
    st.stop()

run_id = state.render_run_selector()

st.title("🧭 Decision Engine")
st.caption("What does the recovered money change about the decision you are weighing?")

if run_id is None:
    st.info("No runs yet — seed the demo data first.", icon="🌱")
    st.code("python scripts/seed_demo.py", language="bash")
    st.stop()

with state.db() as session:
    stats = get_summary_stats(session, run_id)
    anomalies = list_anomalies(session, run_id)

if not stats.anomaly_count:
    st.info("Nothing recovered in this run, so there is nothing to factor in.", icon="ℹ️")
    st.stop()

# ---------------------------------------------------------------------------
# The question
# ---------------------------------------------------------------------------

st.subheader("Your question")

question = st.text_input(
    "Ask a strategic question",
    value="Can I afford a $5,000/month senior designer?",
    label_visibility="collapsed",
)

monthly_cost = st.slider(
    "Monthly cost of the commitment",
    min_value=1000, max_value=15000, value=5000, step=250,
    format="$%d",
    help="Phase 9 reads this out of your question. For now, set it here.",
)

st.info(
    "The question box is not parsed yet — `core/ai/decision_analyzer.py` lands "
    "in Phase 9. The numbers below are real; the reading of your sentence is not.",
    icon="🚧",
)

# ---------------------------------------------------------------------------
# The maths — cumulative, over database figures
# ---------------------------------------------------------------------------

recovered_total = stats.total_leaked
recurring_gap = sum(a.gap for a in anomalies if a.anomaly_type != "ghost_invoice")
one_off_gap = recovered_total - recurring_gap

monthly_recovery = recurring_gap / MONTHS
annual_commitment = monthly_cost * MONTHS

baseline: list[float] = []
recovered: list[float] = []
running_baseline = 0.0
running_recovered = one_off_gap
for month in range(MONTHS):
    running_baseline -= monthly_cost
    running_recovered += monthly_recovery - monthly_cost
    baseline.append(round(running_baseline, 2))
    recovered.append(round(running_recovered, 2))

labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Verdict")

covered_months = int(recovered_total // monthly_cost) if monthly_cost else 0
affordable = recovered[-1] >= 0

if affordable:
    st.success(
        f"**Yes — with the recovered revenue, this looks affordable.** "
        f"Collecting the {money(recovered_total)} you are owed covers roughly "
        f"{covered_months} month(s) of a {money(monthly_cost)}/month commitment "
        f"outright, and the recurring leaks are worth about "
        f"{money(monthly_recovery)}/month once corrected.",
        icon="✅",
    )
else:
    shortfall = abs(recovered[-1])
    st.warning(
        f"**Not on recovered revenue alone.** The {money(recovered_total)} you are "
        f"owed covers about {covered_months} month(s) of a {money(monthly_cost)}/month "
        f"commitment, leaving roughly {money(shortfall)} to find over "
        f"{MONTHS} months from elsewhere.",
        icon="⚠️",
    )

st.caption(
    "⚠️ Template verdict. Phase 9 replaces this with a reasoned answer, and the "
    "model will phrase it around these already-computed figures — it will not "
    "produce the numbers itself."
)

# ---------------------------------------------------------------------------
# Breakdown and chart
# ---------------------------------------------------------------------------

left, right = st.columns([2, 3])

with left:
    st.markdown("**Where the money comes from**")
    render_breakdown(
        [
            ("Recoverable now (one-off)", round(one_off_gap, 2)),
            ("Recurring leaks, annualised", round(recurring_gap, 2)),
            ("Total recovered", round(recovered_total, 2)),
            (f"Commitment ({MONTHS} months)", -annual_commitment),
            ("Net after 12 months", round(recovered[-1], 2)),
        ]
    )
    st.caption(
        "Ghost invoices are treated as one-off recoveries; the other three leak "
        "types recur until the contract is corrected. Phase 9's "
        "`core/engine/cashflow.py` will do this properly."
    )

with right:
    st.markdown("**Twelve-month cash position**")
    render_cash_flow_chart(
        baseline=baseline,
        recovered=recovered,
        labels=labels,
        threshold=0.0,
        threshold_label="Break-even",
    )

with st.expander("What is still missing here"):
    st.markdown(
        """
- **The question is not read.** `core/ai/decision_analyzer.py` (Phase 9) will
  extract the amount, the cadence and the kind of commitment from your sentence.
- **The projection is arithmetic, not a model.** `core/engine/cashflow.py`
  (Phase 9) will handle payment terms, collection probability and timing.
- **The verdict is a template.** Phase 9 phrases it with the model — around
  these figures, never producing them. The LLM does no arithmetic, ever.
        """
    )
