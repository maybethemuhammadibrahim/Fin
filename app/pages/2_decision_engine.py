"""[B] Page 2: ask a strategic question, get a verdict. Phase 9.

The page is now wired end to end: the question is read (`core/ai/
decision_analyzer.parse_question`), the figures are computed
(`core/engine/cashflow`), and the prose is phrased around those figures by the
model — or by a deterministic fallback when no endpoint is answering.

**Three things on this page are deliberate and easy to mistake for gaps.**

1. **The monthly running-costs box.** No table in the schema holds expenses
   (ADR-024), so a surplus is not derivable from the database. The user supplies
   it. Left blank, the page refuses to print a Yes/No and reports the commitment
   as a share of revenue instead — an honest "cannot answer" beats a verdict
   computed against an assumed expense figure, which nobody could see was wrong.

2. **The amount is read by pattern, and shown back.** `decision_analyzer`
   extracts it deterministically and the caption quotes the substring it matched,
   so the number driving the verdict is visibly the user's own. When only the
   model could find a figure, the page says so and asks for confirmation
   (`needs_confirmation`) before that figure is used — the same LLM-proposed /
   human-confirmed shape as ADR-010's column mapping.

3. **Only `confirmed` findings count.** Not `unverified`, not `false_positive`.
   That is what Phase 8 exists for, and the page names the unverified total it is
   *excluding* so the figure can be reconciled against the dashboard headline.

Reads: `cashflow.compute_baseline`, `cashflow.compute_recovery`, `get_summary_stats`.
"""

from __future__ import annotations

import streamlit as st

from app import state
from app.components.cash_flow_chart import render_breakdown, render_cash_flow_chart
from app.components.summary_cards import money
from core.ai import decision_analyzer, endpoints
from core.db import database
from core.db.queries import get_summary_stats
from core.engine import cashflow

st.set_page_config(page_title="FinSight · Decision Engine", page_icon="🧭", layout="wide")

DEFAULT_QUESTION = "Can I afford to hire a $5,000/month senior designer starting in September?"

VERDICT_RENDER = {
    "yes": (st.success, "✅", "Yes"),
    "no": (st.error, "🚫", "No"),
    "unknown": (st.warning, "❓", "Not answerable yet"),
}

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

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

st.subheader("1 · Your question")

question = st.text_input(
    "Ask a strategic question",
    value=DEFAULT_QUESTION,
    label_visibility="collapsed",
    key="decision_question",
)

left, right = st.columns([3, 2])

with left:
    expenses_known = st.checkbox(
        "I know my monthly running costs",
        value=True,
        help=(
            "FinSight reads your revenue from your own transactions, but nothing in "
            "the system knows what you spend — payroll, rent, software. Without that "
            "figure a surplus cannot be computed and no affordability verdict is "
            "possible (ADR-024). Untick this to see what can still be said."
        ),
    )
    monthly_expenses = None
    if expenses_known:
        monthly_expenses = float(
            st.number_input(
                "Monthly running costs",
                min_value=0.0,
                max_value=10_000_000.0,
                value=18_000.0,
                step=500.0,
                format="%.2f",
                help="Everything that leaves the business each month, excluding the decision you are weighing.",
            )
        )

with right:
    window = int(
        st.slider(
            "Months of history to average",
            min_value=1, max_value=24, value=12,
            help="How far back to average your revenue. Fewer than 3 months is flagged as low confidence.",
        )
    )
    horizon = int(st.slider("Months to project", min_value=3, max_value=36, value=12))

analyse = st.button("Analyse", type="primary", icon="🧭")

if not analyse and "decision_last_run" not in st.session_state:
    st.info("Set your figures and press **Analyse**.", icon="👆")
    st.stop()

st.session_state["decision_last_run"] = True

# ---------------------------------------------------------------------------
# 2 · Read the question  (the model's first end)
# ---------------------------------------------------------------------------

st.divider()
st.subheader("2 · What we read from your question")

with st.spinner("Reading the question…"):
    parsed = decision_analyzer.parse_question(question)

read_left, read_right = st.columns([3, 2])
with read_left:
    st.markdown(
        f"**Commitment:** {parsed.what or '_not named_'}  \n"
        f"**Monthly cost:** {money(parsed.monthly_cost) if parsed.has_cost else '_none found_'}  \n"
        f"**Starting:** {parsed.start_month or '_not stated_'}"
    )
with read_right:
    if parsed.matched_text:
        st.caption(f"Read from your own words: “{parsed.matched_text}”")
    st.caption(f"Source: `{parsed.source}` · endpoint: {endpoints.active().label}")

for warning in parsed.warnings:
    st.caption(f"⚠️ {warning}")

monthly_cost = parsed.monthly_cost or 0.0

if parsed.needs_confirmation and parsed.has_cost:
    st.warning(
        f"This amount was not found verbatim in your question — confirm it before "
        f"relying on the verdict.",
        icon="🔍",
    )
    monthly_cost = float(
        st.number_input(
            "Confirm the monthly cost",
            min_value=0.0, max_value=10_000_000.0,
            value=float(parsed.monthly_cost or 0.0), step=250.0, format="%.2f",
        )
    )

if not parsed.has_cost:
    st.error(
        "No amount was found in your question, so there is nothing to test against. "
        "Add a figure — for example “a $5,000/month designer”.",
        icon="🚫",
    )
    st.stop()

# ---------------------------------------------------------------------------
# 3 · Compute  (Python only — no model touches a number)
# ---------------------------------------------------------------------------

with state.db() as session:
    baseline = cashflow.compute_baseline(
        session, run_id, months=window, monthly_expenses=monthly_expenses
    )
    recovery = cashflow.compute_recovery(session, run_id)
    stats = get_summary_stats(session, run_id)

result = cashflow.evaluate(baseline, recovery, monthly_cost=monthly_cost, horizon=horizon)

st.divider()
st.subheader("3 · Verdict")

if baseline.confidence != "ok":
    st.warning(baseline.reason, icon="📉")

render, icon, label = VERDICT_RENDER[result.verdict]

with st.spinner("Phrasing the answer…"):
    explanation = decision_analyzer.explain_verdict(result, parsed)

# Both the deterministic fallback and a well-behaved model open with "Yes"/"No",
# so prefixing the label unconditionally produced "**No.** No. Even with...".
# Lead with the label only when the prose does not already say it.
body = explanation.text
if body.lower().startswith(label.split()[0].lower()):
    render(f"**{body}**" if len(body) < 90 else body, icon=icon)
else:
    render(f"**{label}.** {body}", icon=icon)

if explanation.source == "fallback":
    st.caption(
        "✍️ Written by FinSight, not by the model — "
        + (
            f"the model quoted {len(explanation.rejected_numbers)} figure(s) it was not "
            "given, so its answer was rejected."
            if explanation.rejected_numbers
            else "no model endpoint answered."
        )
    )
else:
    st.caption(
        f"✍️ Phrased by {endpoints.active().label} around the figures below — the model "
        "is given the numbers and may not change them. Every figure it wrote was checked "
        "against the computed set before this was shown."
    )

# ---------------------------------------------------------------------------
# 4 · The working
# ---------------------------------------------------------------------------

st.divider()
st.subheader("4 · The working")

work_left, work_right = st.columns([2, 3])

with work_left:
    rows: list[tuple[str, float]] = [
        (f"Monthly revenue (mean of {baseline.months_observed} mo)", baseline.monthly_revenue),
    ]
    if baseline.monthly_expenses is not None:
        rows.append(("Your monthly running costs", -baseline.monthly_expenses))
        rows.append(("Current monthly surplus", baseline.monthly_surplus or 0.0))
    rows.append((f"Recovered leaks ({recovery.confirmed_count} confirmed)", recovery.monthly))
    if result.corrected_surplus is not None:
        rows.append(("Corrected monthly surplus", result.corrected_surplus))
    rows.append(("The commitment", -result.monthly_cost))
    if result.after_decision is not None:
        rows.append(("Left over each month", result.after_decision))

    render_breakdown(rows)

    st.caption(result.rationale)

    if recovery.unverified_count:
        st.info(
            f"**{money(recovery.unverified_total)} excluded.** "
            f"{recovery.unverified_count} finding(s) are still unverified, so they do not "
            f"count toward recovered revenue. Verify them on the Revenue Integrity page "
            f"(step 4) to include them.",
            icon="🕵️",
        )
    if recovery.false_positive_count:
        st.caption(
            f"{recovery.false_positive_count} finding(s) were ruled out by the "
            f"verification agent and are excluded."
        )
    if not recovery.confirmed_count:
        st.caption(
            f"Nothing is confirmed in this run yet, so recovered revenue is $0.00. "
            f"The dashboard's headline total is {money(stats.total_leaked)}."
        )

with work_right:
    st.markdown(f"**{horizon}-month cumulative position**")
    if result.projection:
        render_cash_flow_chart(
            baseline=[without for _, without, _ in result.projection],
            recovered=[with_ for _, _, with_ in result.projection],
            labels=[label for label, _, _ in result.projection],
            threshold=0.0,
            threshold_label="Break-even",
        )
        st.caption(
            "Cumulative, starting from zero — the two lines are the position with and "
            "without recovering the confirmed leaks. Months are labelled M1…Mn because "
            "the engine takes no clock (it cannot know what month it is)."
        )
    else:
        st.caption("No projection: this run has no transaction history to project from.")

with st.expander("What the model did and did not do here"):
    st.markdown(
        f"""
- **It read your sentence.** The commitment's description came from the model; the
  **amount did not** — `decision_analyzer.extract_cost` found `{parsed.matched_text or "—"}`
  by pattern, so the figure driving the verdict is provably the one you typed.
- **It phrased the answer.** It was handed {len(decision_analyzer.figures_for(result))}
  pre-formatted figures and the computed verdict, and told it may not introduce a number.
- **It computed nothing.** Every figure above comes from `core/engine/cashflow.py`,
  which takes no model and no clock.
- **Its output was checked.** Any numeral in the explanation that is not in the
  computed set causes the answer to be rejected and retried once, then replaced by
  FinSight's own sentence. This run rejected
  {len(explanation.rejected_numbers)} figure(s) over {explanation.attempts} attempt(s).
        """
    )
