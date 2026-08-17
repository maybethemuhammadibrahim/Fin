"""[A] The four database-backed tools the verification agent may call. Phase 8.

Plain functions, `session` first, no LLM inside any of them, and no writes —
the agent's tool-calling loop lives in `verification_agent.py`; this module is
just the DB-reading half, independently testable without an agent, a model or
a live endpoint (see `tests/test_agent_tools.py`).

Each function returns `core.db.queries` row shapes — the same display-safe,
already-rounded dataclasses both frontends already use — rather than ORM
objects, for the same reason `queries.py` does: nothing here should ever
raise `DetachedInstanceError` on a caller that inspects the result after the
tool has returned.
"""

from __future__ import annotations

from datetime import date
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import ActualTransaction
from core.db.queries import ClauseRefRow, TransactionRow, get_clause_reference

#: check_split_payments only ever looks at already-flagged anomalies (ADR-006),
#: so the per-client window is a handful of transactions, not thousands —
#: brute-forcing combinations up to this size is cheap and exhaustive enough
#: to catch the two- and three-way splits real bank behaviour produces.
_MAX_COMBINATION_SIZE = 3


def _rows(session: Session, run_id: int, client_id: int | None, start: date, end: date) -> list[TransactionRow]:
    """Shared query behind search_invoices / search_bank_transactions."""
    stmt = select(ActualTransaction).where(
        ActualTransaction.run_id == run_id,
        ActualTransaction.transaction_date >= start,
        ActualTransaction.transaction_date <= end,
    )
    if client_id is not None:
        stmt = stmt.where(ActualTransaction.client_id == client_id)
    stmt = stmt.order_by(ActualTransaction.transaction_date)

    return [
        TransactionRow(
            id=t.id,
            client_id=t.client_id,
            client_name=None,
            transaction_date=t.transaction_date,
            amount=round(float(t.amount or 0.0), 2),
            description=t.description,
            source_type=t.source_type,
            document_filename=None,
        )
        for t in session.scalars(stmt)
    ]


def search_invoices(session: Session, client_id: int, start: date, end: date) -> list[TransactionRow]:
    """Every transaction on file for one client in [start, end], oldest first.

    Needs a `run_id` to scope the search, but the agent only ever knows a
    client within the run it is already verifying — a client belongs to
    exactly one run (`clients.run_id`), so that run is looked up from the
    client itself and the tool signature stays exactly `(client_id, start,
    end)` per interfaces.md.
    """
    run_id = _run_id_for_client(session, client_id)
    if not run_id:
        return []
    return _rows(session, run_id, client_id, start, end)


def read_contract_clause(session: Session, clause_ref_id: int | None) -> str:
    """The clause's own text, verbatim, for the agent to re-read.

    Never raises and never returns None — a missing id is a fact the agent
    can reason about ("no clause on file"), not a crash.
    """
    if clause_ref_id is None:
        return "No clause reference is attached to this finding."
    ref: ClauseRefRow | None = get_clause_reference(session, clause_ref_id)
    if ref is None:
        return f"Clause reference {clause_ref_id} does not exist."
    return ref.clause_text


def search_bank_transactions(
    session: Session,
    run_id: int,
    amount_min: float,
    amount_max: float,
    start: date,
    end: date,
) -> list[TransactionRow]:
    """Every transaction in this run whose amount falls in [amount_min, amount_max].

    Deliberately NOT scoped to one client — this is the tool for "is there an
    unattributed or misattributed payment near the missing amount", which is
    exactly the question client-scoped search_invoices cannot answer.
    """
    lo, hi = (amount_min, amount_max) if amount_min <= amount_max else (amount_max, amount_min)
    stmt = (
        select(ActualTransaction)
        .where(
            ActualTransaction.run_id == run_id,
            ActualTransaction.amount >= lo,
            ActualTransaction.amount <= hi,
            ActualTransaction.transaction_date >= start,
            ActualTransaction.transaction_date <= end,
        )
        .order_by(ActualTransaction.transaction_date)
    )
    return [
        TransactionRow(
            id=t.id,
            client_id=t.client_id,
            client_name=None,
            transaction_date=t.transaction_date,
            amount=round(float(t.amount or 0.0), 2),
            description=t.description,
            source_type=t.source_type,
            document_filename=None,
        )
        for t in session.scalars(stmt)
    ]


def check_split_payments(
    session: Session,
    client_id: int,
    target: float,
    start: date,
    end: date,
    tol: float = 0.02,
) -> list[list[TransactionRow]]:
    """Every combination of this client's transactions in [start, end] that
    sums to `target` within a `tol` fraction of it (default 2%).

    This is the ADR-006 payoff: reconciliation aggregates per client-month
    for a reason (matching transaction-to-invoice is a combinatorial
    assignment problem across the whole run), and this tool pays that
    precision back cheaply — on the handful of transactions behind one
    already-flagged anomaly, not the run's full ledger.

    Returns the smallest combinations first (a single matching transaction,
    if one exists, before any multi-transaction split), so the agent's first
    reasonable read of the result is also the simplest explanation.
    """
    if target <= 0:
        return []
    txns = _rows(session, _run_id_for_client(session, client_id), client_id, start, end)
    tolerance = abs(target) * tol

    matches: list[list[TransactionRow]] = []
    for size in range(1, min(_MAX_COMBINATION_SIZE, len(txns)) + 1):
        for combo in combinations(txns, size):
            if abs(sum(t.amount for t in combo) - target) <= tolerance:
                matches.append(list(combo))
    return matches


def _run_id_for_client(session: Session, client_id: int) -> int:
    from core.db.models import Client

    client = session.get(Client, client_id)
    return client.run_id if client else 0
