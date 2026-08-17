"""[B] The LangGraph ReAct loop's control flow — hard cap, persistence, and
the "never lose an anomaly" guarantee. No network, no model: every LLM turn
is a canned `AgentDecision` fed in through a monkeypatched
`core.ai.llm_client.complete_json`, so this proves the GRAPH's behaviour is
correct independent of what a real (and sometimes down, ADR-016) model says.

`scripts/eval_agent.py` is the live-endpoint counterpart that proves the real
model actually reasons well — see its docstring.

Run: `pytest tests/test_verification_agent.py -v`
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.agents.verification_agent import (
    AgentDecision,
    MAX_ITERATIONS,
    build_context,
    verify_anomaly,
    verify_run,
)
from core.ai import llm_client
from core.db import models
from core.db.queries import list_anomalies


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase8_agent.db'}")
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _seed_anomaly(session: Session, *, gap: float = 5000.0) -> int:
    """One run, one client, one contract, one clause, one unverified anomaly.
    Returns the anomaly id.
    """
    run = models.Run(label="agent-test")
    session.add(run)
    session.flush()

    client = models.Client(run_id=run.id, name="Fixture Co", normalized_name="fixtureco")
    session.add(client)
    session.flush()

    rule = models.ContractRule(client_id=client.id, base_amount=100_000.0, currency="USD", billing_frequency="monthly")
    session.add(rule)
    session.flush()

    clause = models.ClauseReference(
        contract_rule_id=rule.id,
        clause_type="escalation",
        clause_text="Fees shall increase by 5% on each anniversary.",
    )
    session.add(clause)
    session.flush()

    timeline = models.ExpectedTimeline(
        run_id=run.id,
        client_id=client.id,
        contract_rule_id=rule.id,
        billing_date=date(2025, 6, 1),
        expected_amount=105_000.0,
        payment_type="recurring",
        applied_escalation=True,
        applied_discount_pct=0.0,
    )
    session.add(timeline)
    session.flush()

    anomaly = models.Anomaly(
        run_id=run.id,
        client_id=client.id,
        expected_timeline_id=timeline.id,
        clause_reference_id=clause.id,
        anomaly_type="forgotten_raise",
        expected_amount=105_000.0,
        actual_amount=105_000.0 - gap,
        gap=gap,
        confidence_score=0.6,
        status="unverified",
    )
    session.add(anomaly)
    session.flush()
    return anomaly.id


def _decision(action: str, **kw) -> AgentDecision:
    return AgentDecision(thought="test", action=action, **kw)


# ---------------------------------------------------------------------------
# 1. No contradicting evidence -> confirmed, tool trace recorded
# ---------------------------------------------------------------------------


def test_confirmed_path_records_tool_trace_and_bumps_confidence(session, monkeypatch):
    anomaly_id = _seed_anomaly(session)
    row = [r for r in list_anomalies(session, session.get(models.Anomaly, anomaly_id).run_id) if r.id == anomaly_id][0]
    context = build_context(session, row)

    steps = iter(
        [
            _decision("search_bank_transactions"),
            _decision("check_split_payments"),
            _decision("conclude", verdict="confirmed", explanation="No evidence found; the escalation was never billed."),
        ]
    )
    monkeypatch.setattr(llm_client, "complete_json", lambda *a, **k: next(steps))

    result = verify_anomaly(session, context)

    assert result.verdict == "confirmed"
    assert len(result.tool_calls) == 2
    assert all({"call", "result"} <= step.keys() for step in result.tool_calls)
    assert result.confidence == pytest.approx(0.9)  # max(0.6, 0.9)


# ---------------------------------------------------------------------------
# 2. check_split_payments finds real evidence -> false_positive
# ---------------------------------------------------------------------------


def test_false_positive_path_when_split_payment_covers_the_gap(session, monkeypatch):
    anomaly_id = _seed_anomaly(session, gap=6000.0)
    run_id = session.get(models.Anomaly, anomaly_id).run_id
    client_id = session.get(models.Anomaly, anomaly_id).client_id

    session.add_all(
        [
            models.ActualTransaction(
                run_id=run_id, client_id=client_id, transaction_date=date(2025, 6, 3),
                amount=3000.0, description="FIXTURE CO PART", source_type="bank",
            ),
            models.ActualTransaction(
                run_id=run_id, client_id=client_id, transaction_date=date(2025, 6, 14),
                amount=3000.0, description="FIXTURE CO PART", source_type="bank",
            ),
        ]
    )
    session.flush()

    row = [r for r in list_anomalies(session, run_id) if r.id == anomaly_id][0]
    context = build_context(session, row)

    steps = iter(
        [
            _decision("check_split_payments"),
            _decision(
                "conclude",
                verdict="false_positive",
                explanation="Two transactions eleven days apart sum to the missing amount.",
            ),
        ]
    )
    monkeypatch.setattr(llm_client, "complete_json", lambda *a, **k: next(steps))

    result = verify_anomaly(session, context)

    assert result.verdict == "false_positive"
    assert "3,000" in result.tool_calls[0]["result"] or "3000" in result.tool_calls[0]["result"]
    assert result.confidence == pytest.approx(0.1)  # min(0.6, 0.1)


# ---------------------------------------------------------------------------
# 3. Hard cap: 5 iterations max, forced needs_review, no 6th model call
# ---------------------------------------------------------------------------


def test_hard_cap_forces_needs_review_without_a_sixth_call(session, monkeypatch):
    anomaly_id = _seed_anomaly(session)
    row = [r for r in list_anomalies(session, session.get(models.Anomaly, anomaly_id).run_id) if r.id == anomaly_id][0]
    context = build_context(session, row)

    call_count = 0

    def never_concludes(*a, **k):
        nonlocal call_count
        call_count += 1
        return _decision("search_bank_transactions")

    monkeypatch.setattr(llm_client, "complete_json", never_concludes)

    result = verify_anomaly(session, context)

    assert result.verdict == "needs_review"
    assert call_count == MAX_ITERATIONS
    assert len(result.tool_calls) == MAX_ITERATIONS
    assert result.confidence == pytest.approx(0.6)  # needs_review leaves confidence unchanged


# ---------------------------------------------------------------------------
# 4. Endpoint unreachable -> anomaly is left completely untouched
# ---------------------------------------------------------------------------


def test_model_unavailable_leaves_anomaly_unverified(session, monkeypatch):
    anomaly_id = _seed_anomaly(session)
    run_id = session.get(models.Anomaly, anomaly_id).run_id

    monkeypatch.setattr(llm_client, "complete_json", lambda *a, **k: None)
    monkeypatch.setattr(llm_client, "last_error", lambda: "endpoint unreachable")

    summary = verify_run(session, run_id, sleep_seconds=0)

    assert summary.checked == 1
    assert summary.skipped == 1
    assert summary.confirmed == summary.false_positive == summary.needs_review == 0

    anomaly = session.get(models.Anomaly, anomaly_id)
    assert anomaly.status == "unverified"
    assert anomaly.agent_reasoning is None
    assert anomaly.verified_at is None


# ---------------------------------------------------------------------------
# 5. verify_run persists a real DB row, and the trace is web/-compatible
# ---------------------------------------------------------------------------


def test_verify_run_persists_status_and_trace_readable_by_web_presenter(session, monkeypatch):
    anomaly_id = _seed_anomaly(session)
    run_id = session.get(models.Anomaly, anomaly_id).run_id

    steps = iter(
        [
            _decision("read_contract_clause"),
            _decision("conclude", verdict="confirmed", explanation="Clause confirms the escalation; no offsetting payment found."),
        ]
    )
    monkeypatch.setattr(llm_client, "complete_json", lambda *a, **k: next(steps))

    summary = verify_run(session, run_id, sleep_seconds=0)
    assert summary.confirmed == 1

    anomaly = session.get(models.Anomaly, anomaly_id)
    assert anomaly.status == "confirmed"
    assert anomaly.verified_at is not None
    assert isinstance(anomaly.agent_tool_calls, list) and anomaly.agent_tool_calls

    from web.presenters.live import _tool_calls

    row = [r for r in list_anomalies(session, run_id) if r.id == anomaly_id][0]
    parsed = _tool_calls(row)
    assert parsed and parsed[0].call and parsed[0].result != ""
