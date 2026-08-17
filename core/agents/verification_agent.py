"""[B] LangGraph ReAct loop that verifies or rejects a flagged anomaly. Phase 8.

`verify_anomaly` runs ONE already-flagged anomaly through a REASON -> ACT ->
OBSERVE loop (`docs/implementation_plan.md`'s Phase 8 diagram), capped at 5
turns, and returns a `VerificationResult` — it touches the database only to
read (via `core.agents.tools`), never to write. `verify_run` is the bridge
that turns those results into `anomalies` rows, the same separation Phase 6
drew between `core/engine/reconciliation.py` (pure) and
`core/engine/pipeline.py` (the only place engine output becomes rows).

Three guarantees this file exists to keep, verbatim from the phase prompt:
  - hard cap of 5 iterations; on cap the verdict is "needs_review", with no
    extra model call spent trying to force a conclusion out of it
  - every tool call is recorded to `anomalies.agent_tool_calls`
  - an agent that cannot reach the model never loses an anomaly — the row's
    status is simply left alone, exactly as `unverified` as it started
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, TypedDict

from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.agents import tools as agent_tools
from core.ai import llm_client
from core.ai.prompts import AGENT_SYSTEM, AGENT_VERSION, agent_user
from core.db.models import Anomaly
from core.db.queries import AnomalyRow, TransactionRow, get_clause_reference, list_anomalies

log = logging.getLogger(__name__)

#: Hard cap from the phase prompt. Not configurable — a caller that wants a
#: different cap is asking for a different guarantee than this file makes.
MAX_ITERATIONS = 5

_ACTIONS = (
    "search_invoices",
    "search_bank_transactions",
    "check_split_payments",
    "read_contract_clause",
    "conclude",
)


class AgentDecision(BaseModel):
    """One ReAct turn's structured output. See `core.ai.prompts.AGENT_SYSTEM`.

    The model never supplies an id or a run-scoping value — only the optional
    search-widening knobs. Every identifier used by a tool call comes from
    `AnomalyContext`, built from the database before the model ever runs.
    """

    thought: str = ""
    action: Literal[
        "search_invoices",
        "search_bank_transactions",
        "check_split_payments",
        "read_contract_clause",
        "conclude",
    ]
    verdict: Literal["confirmed", "false_positive", "needs_review"] | None = None
    explanation: str | None = None
    widen_days: int | None = None
    amount_slack_pct: float | None = None
    tolerance_pct: float | None = None


@dataclass(frozen=True)
class AnomalyContext:
    """Everything the agent is allowed to know about one finding, gathered
    once before the loop starts. Nothing in this loop reaches back into the
    database except through `core.agents.tools`."""

    anomaly_id: int
    run_id: int
    client_id: int
    client_name: str
    anomaly_type: str
    expected_amount: float
    actual_amount: float
    gap: float
    billing_date: date | None
    clause_reference_id: int | None
    clause_text: str | None
    original_confidence: float

    def summary(self) -> str:
        clause = f'"{self.clause_text}"' if self.clause_text else "(no clause on file)"
        period = self.billing_date.strftime("%B %Y") if self.billing_date else "unknown period"
        return (
            f"Client: {self.client_name}\n"
            f"Anomaly type: {self.anomaly_type}\n"
            f"Billing period: {period}\n"
            f"Expected amount: ${self.expected_amount:,.2f}\n"
            f"Actual amount received: ${self.actual_amount:,.2f}\n"
            f"Missing amount (gap): ${self.gap:,.2f}\n"
            f"Proving clause: {clause}\n"
            f"Engine's original confidence: {self.original_confidence:.0%}"
        )


@dataclass
class VerificationResult:
    """What one `verify_anomaly` call decided.

    `verdict is None` means the agent could not reach the model at all — the
    caller (`verify_run`) must treat that as "leave this anomaly alone", not
    as a verdict of any kind.
    """

    verdict: Literal["confirmed", "false_positive", "needs_review"] | None
    explanation: str
    tool_calls: list[dict[str, str]] = field(default_factory=list)
    confidence: float | None = None
    iterations: int = 0


@dataclass
class VerifyRunSummary:
    """What one `verify_run` call did, for the UI to report honestly."""

    run_id: int
    checked: int = 0
    confirmed: int = 0
    false_positive: int = 0
    needs_review: int = 0
    skipped: int = 0  # agent unavailable — left unverified, not a verdict

    def as_line(self) -> str:
        return (
            f"Checked {self.checked} finding(s): {self.confirmed} confirmed, "
            f"{self.false_positive} false positive, {self.needs_review} needs review"
            + (f", {self.skipped} skipped (model endpoint unavailable)" if self.skipped else "")
        )


# ---------------------------------------------------------------------------
# Building the context
# ---------------------------------------------------------------------------


def build_context(session: Session, anomaly_row: AnomalyRow) -> AnomalyContext:
    """AnomalyRow (+ its clause, if any) -> everything the agent may read."""
    clause_text = None
    if anomaly_row.clause_reference_id is not None:
        ref = get_clause_reference(session, anomaly_row.clause_reference_id)
        clause_text = ref.clause_text if ref else None

    return AnomalyContext(
        anomaly_id=anomaly_row.id,
        run_id=anomaly_row.run_id,
        client_id=anomaly_row.client_id,
        client_name=anomaly_row.client_name,
        anomaly_type=anomaly_row.anomaly_type,
        expected_amount=anomaly_row.expected_amount,
        actual_amount=anomaly_row.actual_amount,
        gap=anomaly_row.gap,
        billing_date=anomaly_row.billing_date,
        clause_reference_id=anomaly_row.clause_reference_id,
        clause_text=clause_text,
        original_confidence=anomaly_row.confidence_score,
    )


# ---------------------------------------------------------------------------
# Tool execution — turns a model action into a real (session, context) call
# ---------------------------------------------------------------------------

#: Default search window either side of the billing date when the model
#: does not ask to widen it. Wide enough to catch a payment that landed a
#: little early or late without the agent having to think about it.
_DEFAULT_WINDOW_DAYS = 45


def _window(context: AnomalyContext, widen_days: int | None) -> tuple[date, date]:
    anchor = context.billing_date or date.today()
    span = _DEFAULT_WINDOW_DAYS + max(widen_days or 0, 0)
    return anchor - timedelta(days=span), anchor + timedelta(days=span)


def _amount_range(context: AnomalyContext, slack_pct: float | None) -> tuple[float, float]:
    target = context.gap if context.gap > 0 else context.expected_amount
    slack = max(slack_pct or 15.0, 1.0) / 100.0
    return target * (1 - slack), target * (1 + slack)


def _format_transactions(rows: list[TransactionRow]) -> str:
    if not rows:
        return "No matching transactions found."
    lines = [f"  - {t.transaction_date} · ${t.amount:,.2f} · {t.description or '(no description)'}" for t in rows]
    return f"Found {len(rows)} transaction(s):\n" + "\n".join(lines)


def _format_combinations(combos: list[list[TransactionRow]]) -> str:
    if not combos:
        return "No combination of this client's transactions adds up to the missing amount."
    lines = []
    for combo in combos:
        total = sum(t.amount for t in combo)
        parts = ", ".join(f"${t.amount:,.2f} on {t.transaction_date}" for t in combo)
        lines.append(f"  - {parts} = ${total:,.2f}")
    return f"Found {len(combos)} matching combination(s):\n" + "\n".join(lines)


def _execute_tool(session: Session, context: AnomalyContext, decision: AgentDecision) -> tuple[str, str]:
    """(call_description, result_text) for one tool action.

    Every identifier (client_id, run_id, clause_reference_id) comes from
    `context`, never from the model — see AgentDecision's docstring.
    """
    action = decision.action

    if action == "read_contract_clause":
        text = agent_tools.read_contract_clause(session, context.clause_reference_id)
        return "read_contract_clause()", text

    if action == "search_invoices":
        start, end = _window(context, decision.widen_days)
        rows = agent_tools.search_invoices(session, context.client_id, start, end)
        return f"search_invoices(start={start}, end={end})", _format_transactions(rows)

    if action == "search_bank_transactions":
        start, end = _window(context, decision.widen_days)
        lo, hi = _amount_range(context, decision.amount_slack_pct)
        rows = agent_tools.search_bank_transactions(session, context.run_id, lo, hi, start, end)
        return (
            f"search_bank_transactions(amount_min={lo:.2f}, amount_max={hi:.2f}, start={start}, end={end})",
            _format_transactions(rows),
        )

    if action == "check_split_payments":
        start, end = _window(context, decision.widen_days)
        tol = max(decision.tolerance_pct or 2.0, 0.1) / 100.0
        target = context.gap if context.gap > 0 else context.expected_amount
        combos = agent_tools.check_split_payments(session, context.client_id, target, start, end, tol=tol)
        return f"check_split_payments(target={target:.2f}, start={start}, end={end})", _format_combinations(combos)

    # Unreachable given AgentDecision's Literal, but never trust a small
    # model's output completely — fall through to a readable no-op rather
    # than raising out of the graph.
    return f"{action}()", "Unknown action; no tool executed."


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


class _LoopState(TypedDict):
    history: str  # rendered transcript of every prior thought/action/observation
    tool_calls: list[dict[str, str]]
    iteration: int
    verdict: str | None
    explanation: str | None


def _build_graph(session: Session, context: AnomalyContext):
    """A fresh small graph per call, closing over `session`/`context`.

    No checkpointing is used (one synchronous `invoke()` per anomaly), so the
    state can stay a plain dict instead of forcing every field to be
    JSON-serialisable — simpler than threading session/context through a
    typed state schema for a graph that never crosses a process boundary.
    """
    from langgraph.graph import END, StateGraph

    summary = context.summary()

    def reason(state: _LoopState) -> _LoopState:
        if state["iteration"] >= MAX_ITERATIONS:
            # The hard cap holds even if the model refuses to conclude —
            # no further model call is spent trying to argue it into one.
            return {**state, "verdict": "needs_review", "explanation": "Reached the iteration cap without a conclusion."}

        prompt = agent_user(summary, state["history"])
        decision = llm_client.complete_json(prompt, AgentDecision, system=AGENT_SYSTEM, temperature=0.0)

        if decision is None:
            # The model is unreachable. Distinguish this from a real verdict
            # with a sentinel the router below checks for explicitly.
            return {**state, "verdict": "__unavailable__", "explanation": llm_client.last_error() or "model endpoint unavailable"}

        if decision.action == "conclude":
            verdict = decision.verdict or "needs_review"
            explanation = decision.explanation or "The agent concluded without stating a reason."
            return {**state, "verdict": verdict, "explanation": explanation}

        call, result = _execute_tool(session, context, decision)
        entry = {"call": call, "result": result}
        trail = state["history"] + f"\n\nTurn {state['iteration'] + 1}:\nThought: {decision.thought}\nAction: {call}\nObservation: {result}"
        return {
            **state,
            "history": trail,
            "tool_calls": [*state["tool_calls"], entry],
            "iteration": state["iteration"] + 1,
        }

    def route(state: _LoopState) -> str:
        return "end" if state["verdict"] is not None else "reason"

    graph = StateGraph(_LoopState)
    graph.add_node("reason", reason)
    graph.set_entry_point("reason")
    graph.add_conditional_edges("reason", route, {"reason": "reason", "end": END})
    return graph.compile()


def verify_anomaly(session: Session, context: AnomalyContext) -> VerificationResult:
    """Run one anomaly through the ReAct loop. Never raises."""
    graph = _build_graph(session, context)
    try:
        final: _LoopState = graph.invoke(
            {"history": "", "tool_calls": [], "iteration": 0, "verdict": None, "explanation": None}
        )
    except Exception as exc:  # the loop must never take the caller down with it
        log.exception("verification agent crashed on anomaly %s", context.anomaly_id)
        return VerificationResult(verdict=None, explanation=f"agent error: {exc}", tool_calls=[])

    if final["verdict"] == "__unavailable__":
        return VerificationResult(
            verdict=None,
            explanation=final["explanation"] or "model endpoint unavailable",
            tool_calls=final["tool_calls"],
            iterations=final["iteration"],
        )

    return VerificationResult(
        verdict=final["verdict"],
        explanation=final["explanation"] or "",
        tool_calls=final["tool_calls"],
        confidence=_confidence_for(context.original_confidence, final["verdict"]),
        iterations=final["iteration"],
    )


def _confidence_for(original: float, verdict: str | None) -> float | None:
    """The agent's disclosed effect on confidence_score.

    Deliberately simple and stated plainly rather than hidden in a formula:
    a confirmed finding is now at least as certain as a strong prior; a
    false positive is now at most a weak one; needs_review changes nothing,
    because the agent explicitly could not decide.
    """
    if verdict == "confirmed":
        return max(original, 0.9)
    if verdict == "false_positive":
        return min(original, 0.1)
    return original


# ---------------------------------------------------------------------------
# Persistence — the only place this phase writes to the database
# ---------------------------------------------------------------------------


def verify_run(
    session: Session,
    run_id: int,
    *,
    only_status: str = "unverified",
    limit: int | None = None,
    sleep_seconds: float = 1.0,
) -> VerifyRunSummary:
    """Verify every matching anomaly in a run and persist the verdicts.

    Sequential with a pause between calls, per the API-budget note in
    CLAUDE.md — this is at most a handful of round trips (already-flagged
    anomalies only, ADR-006), not a burst against a per-minute rate limit.

    An anomaly whose agent call fails (`VerificationResult.verdict is None`)
    is counted in `.skipped` and left completely untouched in the database —
    still `unverified`, exactly as it was before this call. That is the
    "agent failure must never lose an anomaly" guarantee, enforced here
    rather than trusted to every caller.
    """
    summary = VerifyRunSummary(run_id=run_id)
    rows = list_anomalies(session, run_id, status=only_status)
    if limit is not None:
        rows = rows[:limit]

    for index, row in enumerate(rows):
        context = build_context(session, row)
        result = verify_anomaly(session, context)
        summary.checked += 1

        if result.verdict is None:
            summary.skipped += 1
            log.warning("anomaly %s left unverified: %s", row.id, result.explanation)
            if index < len(rows) - 1:
                time.sleep(sleep_seconds)
            continue

        _persist(session, row.id, result)
        setattr(summary, result.verdict, getattr(summary, result.verdict) + 1)

        if index < len(rows) - 1:
            time.sleep(sleep_seconds)

    session.commit()
    return summary


def _persist(session: Session, anomaly_id: int, result: VerificationResult) -> None:
    anomaly = session.get(Anomaly, anomaly_id)
    if anomaly is None:  # deleted between the read and here — nothing to do
        return
    anomaly.status = result.verdict
    anomaly.agent_reasoning = result.explanation
    anomaly.agent_tool_calls = result.tool_calls
    anomaly.confidence_score = result.confidence if result.confidence is not None else anomaly.confidence_score
    anomaly.verified_at = datetime.now(timezone.utc)
    session.flush()
