"""[A] The four Phase-8 tools, exercised directly against a temporary SQLite
file — no agent, no LLM, no network. Same fixture shape as `test_pipeline.py`.

Run: `pytest tests/test_agent_tools.py -v`
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.agents.tools import (
    check_split_payments,
    read_contract_clause,
    search_bank_transactions,
    search_invoices,
)
from core.db import models


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase8_tools.db'}")
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _seed(session: Session) -> dict:
    run = models.Run(label="tools-test")
    session.add(run)
    session.flush()

    client = models.Client(run_id=run.id, name="Fixture Co", normalized_name="fixtureco")
    other = models.Client(run_id=run.id, name="Other Co", normalized_name="otherco")
    session.add_all([client, other])
    session.flush()

    rule = models.ContractRule(client_id=client.id, base_amount=6000.0, currency="USD", billing_frequency="monthly")
    session.add(rule)
    session.flush()

    clause = models.ClauseReference(
        contract_rule_id=rule.id,
        clause_type="base_fee",
        clause_text="Client shall pay a monthly fee of $6,000.",
    )
    session.add(clause)

    txns = [
        models.ActualTransaction(
            run_id=run.id, client_id=client.id, transaction_date=date(2025, 3, 1),
            amount=3000.0, description="FIXTURE CO PART 1", source_type="bank",
        ),
        models.ActualTransaction(
            run_id=run.id, client_id=client.id, transaction_date=date(2025, 3, 11),
            amount=3000.0, description="FIXTURE CO PART 2", source_type="bank",
        ),
        models.ActualTransaction(
            run_id=run.id, client_id=None, transaction_date=date(2025, 3, 5),
            amount=6000.0, description="GARBLED REF 84x2q", source_type="bank",
        ),
        models.ActualTransaction(
            run_id=run.id, client_id=other.id, transaction_date=date(2025, 3, 2),
            amount=9999.0, description="OTHER CO", source_type="bank",
        ),
    ]
    session.add_all(txns)
    session.flush()

    return {
        "run_id": run.id,
        "client_id": client.id,
        "other_id": other.id,
        "clause_id": clause.id,
    }


# ---------------------------------------------------------------------------
# search_invoices
# ---------------------------------------------------------------------------


def test_search_invoices_scopes_to_client_and_window(session):
    ids = _seed(session)
    rows = search_invoices(session, ids["client_id"], date(2025, 3, 1), date(2025, 3, 31))
    assert {r.amount for r in rows} == {3000.0, 3000.0}
    assert all(r.client_id == ids["client_id"] for r in rows)


def test_search_invoices_excludes_other_clients_and_out_of_window(session):
    ids = _seed(session)
    rows = search_invoices(session, ids["client_id"], date(2025, 4, 1), date(2025, 4, 30))
    assert rows == []


def test_search_invoices_unknown_client_returns_empty(session):
    _seed(session)
    assert search_invoices(session, 999_999, date(2025, 1, 1), date(2025, 12, 31)) == []


# ---------------------------------------------------------------------------
# read_contract_clause
# ---------------------------------------------------------------------------


def test_read_contract_clause_returns_verbatim_text(session):
    ids = _seed(session)
    text = read_contract_clause(session, ids["clause_id"])
    assert text == "Client shall pay a monthly fee of $6,000."


def test_read_contract_clause_missing_id_is_readable_not_a_crash(session):
    _seed(session)
    assert "does not exist" in read_contract_clause(session, 999_999)


def test_read_contract_clause_none_id_is_readable_not_a_crash(session):
    _seed(session)
    assert "No clause reference" in read_contract_clause(session, None)


# ---------------------------------------------------------------------------
# search_bank_transactions — deliberately NOT client-scoped
# ---------------------------------------------------------------------------


def test_search_bank_transactions_finds_unattributed_payment_near_amount(session):
    ids = _seed(session)
    rows = search_bank_transactions(session, ids["run_id"], 5000.0, 7000.0, date(2025, 3, 1), date(2025, 3, 31))
    amounts = {r.amount for r in rows}
    assert 6000.0 in amounts
    # The unattributed $6,000 transaction has no client_id yet — exactly the
    # row a misattribution investigation is looking for.
    unattributed = [r for r in rows if r.amount == 6000.0][0]
    assert unattributed.client_id is None


def test_search_bank_transactions_excludes_out_of_range_amounts(session):
    ids = _seed(session)
    rows = search_bank_transactions(session, ids["run_id"], 5000.0, 7000.0, date(2025, 3, 1), date(2025, 3, 31))
    assert 9999.0 not in {r.amount for r in rows}


def test_search_bank_transactions_tolerates_swapped_min_max(session):
    ids = _seed(session)
    rows = search_bank_transactions(session, ids["run_id"], 7000.0, 5000.0, date(2025, 3, 1), date(2025, 3, 31))
    assert 6000.0 in {r.amount for r in rows}


# ---------------------------------------------------------------------------
# check_split_payments — the ADR-006 payoff
# ---------------------------------------------------------------------------


def test_check_split_payments_finds_a_real_combination(session):
    ids = _seed(session)
    combos = check_split_payments(session, ids["client_id"], 6000.0, date(2025, 3, 1), date(2025, 3, 31))
    assert len(combos) >= 1
    best = combos[0]
    assert round(sum(t.amount for t in best), 2) == pytest.approx(6000.0, abs=1e-6)


def test_check_split_payments_finds_nothing_when_nothing_sums(session):
    ids = _seed(session)
    combos = check_split_payments(session, ids["client_id"], 50_000.0, date(2025, 3, 1), date(2025, 3, 31))
    assert combos == []


def test_check_split_payments_respects_tolerance(session):
    ids = _seed(session)
    # 6001 is within 2% of 6000 (default tol), so the pair still counts.
    combos = check_split_payments(session, ids["client_id"], 6001.0, date(2025, 3, 1), date(2025, 3, 31))
    assert len(combos) >= 1
    # But it is NOT within a much tighter tolerance.
    tight = check_split_payments(session, ids["client_id"], 6001.0, date(2025, 3, 1), date(2025, 3, 31), tol=0.0001)
    assert tight == []


def test_check_split_payments_zero_or_negative_target_returns_empty(session):
    ids = _seed(session)
    assert check_split_payments(session, ids["client_id"], 0.0, date(2025, 3, 1), date(2025, 3, 31)) == []
    assert check_split_payments(session, ids["client_id"], -100.0, date(2025, 3, 1), date(2025, 3, 31)) == []
