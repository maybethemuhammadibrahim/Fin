"""[B] Extraction output -> database rows -> computed findings. Phase 6.

`test_timeline.py` and `test_reconciliation.py` prove the arithmetic. This file
proves the part between the arithmetic and the screen: that a `ContractRules`
becomes real `contract_rules` / `clause_references` rows, that `compute_run`
turns those into `expected_timeline` and `anomalies`, and that running it twice
leaves one answer in the database rather than two.

Runs against a **temporary SQLite file**, so it needs no Supabase, no network and
no model — the same 12 tables, created and thrown away per test.

Run: `pytest tests/test_pipeline.py -v`
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from core.ai.schemas import ContractRules, Discount, Escalation, Milestone
from core.db import models
from core.engine.pipeline import compute_run, load_contract_plans, persist_rules

CONTRACT_TEXT = (
    "The Company shall pay a monthly fee of $6,000 for the Services. "
    "Such monthly fee shall increase by eight percent (8%) on each anniversary of this Agreement. "
    "A discount of ten percent (10%) shall apply for the first three months."
)


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase6.db'}")
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _rules(**overrides) -> ContractRules:
    base = dict(
        client_name="Northwind Studio",
        contract_start_date=date(2024, 1, 1),
        contract_end_date=None,
        base_amount=6000.0,
        currency="USD",
        billing_frequency="monthly",
        payment_terms="Net 30",
        escalation=Escalation(
            percentage=8.0,
            after_months=12,
            clause_text="Such monthly fee shall increase by eight percent (8%) on each anniversary of this Agreement.",
        ),
        discounts=[],
        milestones=[],
    )
    base.update(overrides)
    return ContractRules(**base)


def _run_with_contract(session: Session, rules: ContractRules) -> tuple[int, int]:
    run = models.Run(label="test")
    session.add(run)
    session.flush()

    document = models.Document(
        run_id=run.id,
        filename="northwind.txt",
        file_type="txt",
        category="contract",
        extraction_status="complete",
        extracted_text=CONTRACT_TEXT,
    )
    session.add(document)
    session.flush()

    rule_id = persist_rules(session, run.id, document.id, rules, document_text=CONTRACT_TEXT)
    return run.id, rule_id


def _pay(session: Session, run_id: int, when: date, amount: float, description="NORTHWIND STUDIO"):
    session.add(
        models.ActualTransaction(
            run_id=run_id,
            transaction_date=when,
            amount=amount,
            description=description,
            source_type="bank",
        )
    )


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------


def test_persist_rules_writes_the_contract_and_its_clauses(session):
    run_id, rule_id = _run_with_contract(session, _rules())

    rule = session.get(models.ContractRule, rule_id)
    assert rule.base_amount == 6000.0
    assert rule.contract_start == date(2024, 1, 1)
    assert rule.raw_extraction["client_name"] == "Northwind Studio"

    escalations = session.scalars(
        select(models.PriceEscalation).where(models.PriceEscalation.contract_rule_id == rule_id)
    ).all()
    assert [(e.percentage, e.after_months) for e in escalations] == [(8.0, 12)]
    assert escalations[0].clause_reference_id is not None


def test_a_quote_that_is_in_the_document_is_not_marked_failed(session):
    run_id, rule_id = _run_with_contract(session, _rules())
    refs = session.scalars(
        select(models.ClauseReference).where(models.ClauseReference.contract_rule_id == rule_id)
    ).all()
    escalation = next(r for r in refs if r.clause_type == "escalation")
    assert escalation.locate_method is None  # present in the text, just not on a page
    assert escalation.source_page is None and escalation.source_bbox is None


def test_a_quote_that_is_not_in_the_document_is_marked_failed(session):
    rules = _rules(
        escalation=Escalation(
            percentage=8.0, after_months=12, clause_text="Fees rise by 8% every year, as agreed."
        )
    )
    _run_id, rule_id = _run_with_contract(session, rules)
    ref = session.scalar(
        select(models.ClauseReference).where(
            models.ClauseReference.contract_rule_id == rule_id,
            models.ClauseReference.clause_type == "escalation",
        )
    )
    assert ref.locate_method == "failed"


def test_a_second_contract_for_the_same_client_reuses_the_client_row(session):
    run_id, _ = _run_with_contract(session, _rules())
    persist_rules(session, run_id, None, _rules(client_name="Northwind Studio, Inc."))
    count = session.scalar(select(func.count()).select_from(models.Client).where(models.Client.run_id == run_id))
    assert count == 1


def test_load_contract_plans_round_trips_the_rules(session):
    run_id, _ = _run_with_contract(
        session,
        _rules(discounts=[Discount(percentage=10.0, duration_months=3, clause_text="A discount of ten percent (10%) shall apply for the first three months.")]),
    )
    plans = load_contract_plans(session, run_id)
    assert len(plans) == 1
    plan = plans[0]
    assert plan.rules.base_amount == 6000.0
    assert plan.rules.escalation.percentage == 8.0
    assert [d.percentage for d in plan.rules.discounts] == [10.0]
    assert plan.clause_refs.escalation is not None
    assert plan.clause_refs.discounts  # the discount's own clause, not the base fee's


# ---------------------------------------------------------------------------
# compute_run
# ---------------------------------------------------------------------------


def test_compute_run_writes_a_timeline_and_finds_the_forgotten_raise(session):
    run_id, _ = _run_with_contract(session, _rules())
    for month in range(1, 13):
        _pay(session, run_id, date(2025, month, 1), 6000.0)  # never applied the 8%
    session.flush()

    summary = compute_run(session, run_id, commit=False)

    assert summary.contracts == 1
    assert summary.timeline_rows == 12
    assert summary.anomalies == 12
    assert summary.by_type == {"forgotten_raise": 12}
    assert summary.total_gap == pytest.approx(12 * 480.0)
    assert summary.attributed == 12  # matched by name, written back to the rows

    stored = session.scalars(select(models.Anomaly).where(models.Anomaly.run_id == run_id)).all()
    assert {a.status for a in stored} == {"unverified"}
    assert all(a.expected_timeline_id is not None for a in stored)
    assert all(a.agent_reasoning for a in stored)


def test_a_finding_cites_the_clause_that_proves_its_type(session):
    """A forgotten_raise must point at the escalation clause, not at the rate
    card the row happened to be billed under."""
    run_id, rule_id = _run_with_contract(session, _rules())
    for month in range(1, 4):
        _pay(session, run_id, date(2025, month, 1), 6000.0)
    session.flush()
    compute_run(session, run_id, commit=False)

    escalation_ref = session.scalar(
        select(models.ClauseReference.id).where(
            models.ClauseReference.contract_rule_id == rule_id,
            models.ClauseReference.clause_type == "escalation",
        )
    )
    anomalies = session.scalars(select(models.Anomaly).where(models.Anomaly.run_id == run_id)).all()
    assert {a.clause_reference_id for a in anomalies} == {escalation_ref}


def test_a_client_who_paid_correctly_produces_no_rows_in_anomalies(session):
    run_id, _ = _run_with_contract(session, _rules())
    for month in range(1, 13):
        _pay(session, run_id, date(2025, month, 1), 6480.0)
    session.flush()

    summary = compute_run(session, run_id, commit=False)
    assert summary.timeline_rows == 12
    assert summary.anomalies == 0
    assert session.scalar(select(func.count()).select_from(models.Anomaly)) == 0


def test_recomputing_replaces_rather_than_duplicates(session):
    run_id, _ = _run_with_contract(session, _rules())
    for month in range(1, 13):
        _pay(session, run_id, date(2025, month, 1), 6000.0)
    session.flush()

    first = compute_run(session, run_id, commit=False)
    second = compute_run(session, run_id, commit=False)

    assert (first.anomalies, first.timeline_rows) == (second.anomalies, second.timeline_rows)
    assert session.scalar(select(func.count()).select_from(models.ExpectedTimeline)) == 12
    assert session.scalar(select(func.count()).select_from(models.Anomaly)) == 12


def test_unattributable_money_is_counted_not_absorbed(session):
    run_id, _ = _run_with_contract(session, _rules())
    for month in range(1, 13):
        _pay(session, run_id, date(2025, month, 1), 6480.0)
    _pay(session, run_id, date(2025, 3, 2), -35.0, description="BANK SVC FEE")
    session.flush()

    summary = compute_run(session, run_id, commit=False)
    assert summary.anomalies == 0
    assert summary.unattributed == 1


def test_an_undated_milestone_is_reported_not_billed(session):
    rules = _rules(
        milestones=[
            Milestone(
                description="Website launch",
                amount=15000.0,
                due_condition="on website launch",
                clause_text="$15,000 payable on launch",
            )
        ]
    )
    run_id, _ = _run_with_contract(session, rules)
    for month in range(1, 13):
        _pay(session, run_id, date(2025, month, 1), 6480.0)
    session.flush()

    summary = compute_run(session, run_id, commit=False)
    assert summary.timeline_rows == 12  # no milestone billing invented
    assert summary.anomalies == 0
    assert len(summary.unresolved_milestones) == 1
    assert "Website launch" in summary.unresolved_milestones[0]


def test_a_contract_with_no_start_date_is_skipped_and_said_so(session):
    run_id, _ = _run_with_contract(session, _rules(contract_start_date=None))
    _pay(session, run_id, date(2025, 1, 1), 6000.0)
    session.flush()

    summary = compute_run(session, run_id, commit=False)
    assert summary.timeline_rows == 0
    assert summary.anomalies == 0
    assert summary.skipped_contracts and "Northwind Studio" in summary.skipped_contracts[0]


def test_the_window_follows_the_transactions_not_the_clock(session):
    """Reconciling a 2019 statement must produce 2019 billings, whatever year it
    is when the run is computed."""
    run_id, _ = _run_with_contract(session, _rules(contract_start_date=date(2018, 1, 1)))
    for month in range(1, 4):
        _pay(session, run_id, date(2019, month, 1), 6480.0)
    session.flush()

    compute_run(session, run_id, commit=False)
    billings = session.scalars(select(models.ExpectedTimeline.billing_date)).all()
    assert {d.year for d in billings} == {2019}
    assert len(billings) == 3
