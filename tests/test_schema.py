"""[A] The Phase 1 schema contract, as repeatable assertions. Closes known issue #15.

Phase 1 verified all of this once, from a scratch script that was never committed,
against both SQLite and Postgres. Phase 6 was said to own the port into pytest and
did not do it, so from Phase 1 until the 2026-08-17 audit the schema was the one
part of the build with no repeatable check — the `information_schema` queries that
confirmed ADR-005 and the six `CheckConstraint`s lived only in a terminal
scrollback.

**These assertions are about the schema, not about data.** They create the tables
on a temporary SQLite file and interrogate them through SQLAlchemy's `Inspector`
plus real INSERTs, so they run anywhere `pytest` runs — no Supabase, no network,
no model. Point `FINSIGHT_TEST_DATABASE_URL` at a Postgres database to run the
identical assertions there; that is how Phase 1's "identical results on both
backends" claim becomes something a later session can re-check rather than
believe.

Run: `pytest tests/test_schema.py -v`
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db import models

#: Every table the plan's Phase 1 promises. Twelve, not the eleven the plan's own
#: ER diagram draws — `milestones` is missing from that diagram (known issue #14)
#: while both the plan text and `models.py` require it.
EXPECTED_TABLES = {
    "runs",
    "documents",
    "clients",
    "contract_rules",
    "clause_references",
    "price_escalations",
    "discounts",
    "milestones",
    "expected_timeline",
    "actual_transactions",
    "anomalies",
    "column_mappings",
}

#: (table, column, allowed values) for each `CheckConstraint` `_one_of()` builds.
#: Six of them, which is the number Phase 1 confirmed in `information_schema`.
ONE_OF_CONSTRAINTS = [
    ("documents", "extraction_status", models.EXTRACTION_STATUSES),
    ("contract_rules", "billing_frequency", models.BILLING_FREQUENCIES),
    ("clause_references", "locate_method", models.LOCATE_METHODS),
    ("expected_timeline", "payment_type", models.PAYMENT_TYPES),
    ("anomalies", "anomaly_type", models.ANOMALY_TYPES),
    ("anomalies", "status", models.ANOMALY_STATUSES),
]


@pytest.fixture()
def engine(tmp_path):
    """A throwaway database with all 12 tables.

    Honours `FINSIGHT_TEST_DATABASE_URL` so the same assertions can be pointed at
    Postgres. When they are, the tables are dropped afterwards — the whole point
    is to be able to run this against a real Supabase instance without leaving
    anything behind.
    """
    url = os.environ.get("FINSIGHT_TEST_DATABASE_URL")
    if url:
        eng = create_engine(url)
        models.Base.metadata.drop_all(eng)
        models.Base.metadata.create_all(eng)
        yield eng
        models.Base.metadata.drop_all(eng)
        eng.dispose()
        return

    eng = create_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    # Without this, SQLite silently ignores every FK, and the cascade assertion
    # below would pass for the wrong reason. `database.py` installs the same
    # PRAGMA on the real engine.
    from sqlalchemy import event

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _record):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    models.Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine) as db:
        yield db


def _run(session) -> models.Run:
    run = models.Run(label="schema-test", llm_provider="colab_tunnel", model_name="Qwen/Qwen2.5-3B-Instruct")
    session.add(run)
    session.commit()
    return run


# ---------------------------------------------------------------------------
# 1. The tables exist, and there are exactly twelve of them
# ---------------------------------------------------------------------------


def test_all_twelve_tables_are_created(engine):
    actual = set(inspect(engine).get_table_names())
    assert EXPECTED_TABLES <= actual, f"missing: {sorted(EXPECTED_TABLES - actual)}"


def test_no_unexpected_tables(engine):
    """A new table should be a deliberate schema decision, not a surprise."""
    actual = {t for t in inspect(engine).get_table_names() if not t.startswith("sqlite_")}
    assert actual == EXPECTED_TABLES, f"unexpected: {sorted(actual - EXPECTED_TABLES)}"


def test_milestones_table_exists_despite_the_er_diagram(engine):
    """Known issue #14: the plan's ER diagram draws 11 tables and omits this one.

    `ContractRules.milestones` and `payment_type='milestone'` both need it, so the
    diagram is what is wrong. Asserted by name so nobody "tidies" it away.
    """
    assert "milestones" in inspect(engine).get_table_names()


# ---------------------------------------------------------------------------
# 2. ADR-005 — an unlocatable clause is storable
# ---------------------------------------------------------------------------


def test_source_page_and_bbox_are_nullable(engine):
    """ADR-005. A quote the locator could not place must still be recordable, or
    the UI's degrade-to-page-level path is unreachable and extraction throws away
    a clause it read correctly."""
    cols = {c["name"]: c for c in inspect(engine).get_columns("clause_references")}
    assert cols["source_page"]["nullable"] is True
    assert cols["source_bbox"]["nullable"] is True


def test_a_clause_with_no_location_can_be_inserted(session):
    """The same guarantee as the column metadata, proven by INSERT rather than by
    reading a flag — this is the one that would have caught a NOT NULL added to
    either column by a later migration."""
    run = _run(session)
    client = models.Client(run_id=run.id, name="Acme", normalized_name="acme")
    session.add(client)
    session.commit()
    # No run_id here: a contract rule reaches its run through its client.
    rule = models.ContractRule(client_id=client.id, base_amount=6000.0, billing_frequency="monthly")
    session.add(rule)
    session.commit()

    clause = models.ClauseReference(
        contract_rule_id=rule.id,
        clause_type="base_fee",
        clause_text="The Client shall pay $6,000 per month.",
        source_page=None,
        source_bbox=None,
        locate_method="failed",
    )
    session.add(clause)
    session.commit()

    stored = session.get(models.ClauseReference, clause.id)
    assert stored is not None
    assert stored.source_page is None
    assert stored.is_grounded is False, "a clause with no page must not claim to be grounded"


def test_expected_timeline_carries_its_proving_clause(engine):
    """Known issue #14's second half: `source_clause_ref_id` is declared by
    `TimelineEntry` in interfaces.md and missing from the plan's diagram. Without
    it an anomaly cannot inherit the clause that proves it."""
    cols = {c["name"]: c for c in inspect(engine).get_columns("expected_timeline")}
    assert "source_clause_ref_id" in cols
    assert cols["source_clause_ref_id"]["nullable"] is True


# ---------------------------------------------------------------------------
# 3. The six CheckConstraints actually reject bad values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table,column,allowed", ONE_OF_CONSTRAINTS)
def test_check_constraint_is_declared(engine, table, column, allowed):
    """Declared in the DDL, on whichever backend is under test."""
    names = {c["name"] for c in inspect(engine).get_check_constraints(table)}
    assert f"ck_{column}" in names, f"{table}.{column} has no ck_{column}: {sorted(names)}"


def test_there_are_exactly_six_one_of_constraints(engine):
    total = sum(
        len([c for c in inspect(engine).get_check_constraints(t) if (c["name"] or "").startswith("ck_")])
        for t in EXPECTED_TABLES
    )
    assert total == 6, f"expected 6 ck_* constraints across the schema, found {total}"


def test_the_four_leak_types_are_the_only_ones_allowed(session):
    """The taxonomy is enforced by the database, not merely by convention — the
    four types are mutually exclusive *by design* and a fifth would silently
    break every total the dashboard reports."""
    assert set(models.ANOMALY_TYPES) == {
        "ghost_invoice",
        "forgotten_raise",
        "zombie_discount",
        "short_change",
    }

    run = _run(session)
    client = models.Client(run_id=run.id, name="Acme", normalized_name="acme")
    session.add(client)
    session.commit()

    session.add(
        models.Anomaly(
            run_id=run.id,
            client_id=client.id,
            anomaly_type="mystery_leak",  # not one of the four
            expected_amount=100.0,
            actual_amount=0.0,
            gap=100.0,
            confidence_score=0.5,
            status="unverified",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_an_unknown_anomaly_status_is_rejected(session):
    run = _run(session)
    client = models.Client(run_id=run.id, name="Acme", normalized_name="acme")
    session.add(client)
    session.commit()

    session.add(
        models.Anomaly(
            run_id=run.id,
            client_id=client.id,
            anomaly_type="ghost_invoice",
            expected_amount=100.0,
            actual_amount=0.0,
            gap=100.0,
            confidence_score=0.5,
            status="probably_fine",  # not one of the four lifecycle values
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_an_unknown_extraction_status_is_rejected(session):
    run = _run(session)
    session.add(
        models.Document(
            run_id=run.id,
            filename="c.pdf",
            file_type="pdf",
            storage_url="file:///tmp/c.pdf",
            category="contract",
            extraction_status="halfway",  # not one of the four
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ---------------------------------------------------------------------------
# 4. Run scoping and cascade — what scripts/reset_run.py depends on
# ---------------------------------------------------------------------------


def test_deleting_a_run_removes_its_rows(session):
    """`scripts/reset_run.py` wipes one run and keeps the others. If the cascade
    is not real, it leaves orphans that every run-scoped query then picks up."""
    run = _run(session)
    other = models.Run(label="keep-me", llm_provider="colab_tunnel", model_name="m")
    session.add(other)
    session.commit()

    client = models.Client(run_id=run.id, name="Acme", normalized_name="acme")
    keeper = models.Client(run_id=other.id, name="Beta", normalized_name="beta")
    session.add_all([client, keeper])
    session.commit()

    session.add(
        models.Document(
            run_id=run.id,
            filename="c.pdf",
            file_type="pdf",
            storage_url="file:///tmp/c.pdf",
            category="contract",
            extraction_status="complete",
        )
    )
    session.commit()

    session.delete(run)
    session.commit()

    assert session.scalars(select(models.Client).where(models.Client.run_id == run.id)).all() == []
    assert session.scalars(select(models.Document).where(models.Document.run_id == run.id)).all() == []
    # the other run is untouched
    assert len(session.scalars(select(models.Client).where(models.Client.run_id == other.id)).all()) == 1


def test_one_client_name_per_run_but_repeatable_across_runs(session):
    """`uq_client_run_normalized`. Two runs must be able to hold the same client —
    that is the whole point of re-running a demo without wiping the database —
    while one run may not hold it twice."""
    run = _run(session)
    other = models.Run(label="second", llm_provider="colab_tunnel", model_name="m")
    session.add(other)
    session.commit()

    session.add(models.Client(run_id=run.id, name="Acme Corp", normalized_name="acme corp"))
    session.commit()

    # same normalized name, different run — allowed
    session.add(models.Client(run_id=other.id, name="Acme Corp", normalized_name="acme corp"))
    session.commit()

    # same normalized name, same run — rejected
    session.add(models.Client(run_id=run.id, name="ACME CORP", normalized_name="acme corp"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_column_mapping_signature_is_unique(session):
    """ADR-010 caches a confirmed mapping by header signature; two rows for one
    signature would make "which mapping did we confirm?" ambiguous."""
    session.add(models.ColumnMapping(header_signature="abc123", mapping={"date": "Date"}))
    session.commit()
    session.add(models.ColumnMapping(header_signature="abc123", mapping={"date": "Txn Date"}))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ---------------------------------------------------------------------------
# 5. Everything run-scoped actually carries run_id (ADR: run_id on everything)
# ---------------------------------------------------------------------------

#: Carries `run_id` directly — these are the tables a run-scoped query filters on.
RUN_SCOPED = [
    "documents",
    "clients",
    "expected_timeline",
    "actual_transactions",
    "anomalies",
]

#: Scoped *transitively* instead, each through the FK named here. Worth asserting
#: explicitly, because "no run_id" reads like an oversight when you are grepping
#: for it: `contract_rules` reaches a run through its client, and the four clause
#: and rule-detail tables reach one through their contract rule. Nothing here is
#: reachable from two runs at once, which is the property that actually matters.
TRANSITIVELY_SCOPED = {
    "contract_rules": "client_id",
    "clause_references": "contract_rule_id",
    "price_escalations": "contract_rule_id",
    "discounts": "contract_rule_id",
    "milestones": "contract_rule_id",
}


@pytest.mark.parametrize("table", RUN_SCOPED)
def test_run_scoped_tables_have_run_id(engine, table):
    """So a baseline and a fine-tuned run can sit side by side in one database —
    Phase 11's comparison depends on it."""
    cols = {c["name"] for c in inspect(engine).get_columns(table)}
    assert "run_id" in cols


@pytest.mark.parametrize("table,fk_column", sorted(TRANSITIVELY_SCOPED.items()))
def test_transitively_scoped_tables_reach_a_run_through_a_parent(engine, table, fk_column):
    cols = {c["name"] for c in inspect(engine).get_columns(table)}
    assert "run_id" not in cols, f"{table} gained a run_id — update this test deliberately"
    assert fk_column in cols


def test_every_table_is_either_run_scoped_or_deliberately_not(engine):
    """No table escapes classification. A new one shows up here as a failure,
    which is the point: run scoping is what lets demos be re-run without wiping
    the database, and a table nobody scoped is a table that leaks across runs."""
    unscoped = {"runs", "column_mappings"}  # the run list itself, and the ADR-010 cache
    classified = set(RUN_SCOPED) | set(TRANSITIVELY_SCOPED) | unscoped
    assert classified == EXPECTED_TABLES, f"unclassified: {sorted(EXPECTED_TABLES - classified)}"
