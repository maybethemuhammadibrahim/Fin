#!/usr/bin/env python3
"""[A] Load a built scenario into the database, return a run_id. Phase 2.

    python scripts/seed_demo.py                    # create a demo run
    python scripts/seed_demo.py --label baseline   # name it
    python scripts/seed_demo.py --replace          # delete existing demo runs first
    python scripts/seed_demo.py --list             # show what is already seeded

**Why the numbers are generated, not typed.** The plan asks for rows that are
internally consistent: every anomaly's `gap` must equal
`expected_amount - actual_amount`, and the dashboard total must equal the sum of
the gaps. If a summary card and the table below it disagree, that has to be a
bug in the UI, not in the fixture — otherwise Phase 2 debugging is worthless.

So nothing here is hand-entered twice. Contracts are declared once in
`SCENARIO`; the expected timeline is computed from them by the same arithmetic
Phase 6 will use; actual transactions are the expected timeline with named
deviations applied; and anomaly rows are *derived from the difference between
those two*. Consistency is structural, not checked.

This is a deliberately small stand-in for `data_sourcing/scenario_builder.py`,
which does the same job in Phase 3 from real CUAD contracts and writes
`ground_truth.json` (ADR-007). The contracts below are invented and plausible;
no model produced them, and none is claimed to be real.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from core.db import database  # noqa: E402
from core.db.models import (  # noqa: E402
    ActualTransaction,
    Anomaly,
    ClauseReference,
    Client,
    ContractRule,
    Discount,
    Document,
    ExpectedTimeline,
    Milestone,
    PriceEscalation,
    Run,
)
from core.db.queries import create_run  # noqa: E402

# ---------------------------------------------------------------------------
# Scenario declaration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlantedAnomaly:
    """A deviation to introduce, and the leak type it should read as.

    `month` is the 1-12 index within the scenario year. `actual` is what the
    client really paid; `None` means nothing arrived at all.
    """

    month: int
    anomaly_type: str
    actual: float | None
    confidence: float
    #: Which clause proves it — a key into the contract's `clauses` dict.
    clause_key: str
    #: Applies to the milestone row rather than that month's recurring fee.
    on_milestone: bool = False


@dataclass(frozen=True)
class ClauseSpec:
    """A quote from the contract, and whether we managed to locate it.

    `page=None` models a real ADR-005 outcome: the model returned a verbatim
    quote that `clause_locator` could not find in the PDF. The UI must degrade
    to a text-only view rather than crash, so the demo data has to contain one.
    """

    clause_type: str
    text: str
    page: int | None
    bbox: list[float] | None
    locate_method: str


@dataclass(frozen=True)
class ContractSpec:
    name: str
    filename: str
    monthly_amount: float
    payment_terms: str
    contract_start: date
    clauses: dict[str, ClauseSpec]
    escalation_pct: float | None = None
    escalation_after_months: int | None = None
    #: Month index (1-12) from which the escalated rate applies this year.
    escalation_effective_month: int | None = None
    discount_pct: float | None = None
    discount_duration_months: int | None = None
    milestone: tuple[str, float, int] | None = None  # (description, amount, month)
    planted: list[PlantedAnomaly] = field(default_factory=list)


YEAR = 2025

#: Five clients, three of them leaking, seven findings covering all four types.
SCENARIO: list[ContractSpec] = [
    ContractSpec(
        name="Starter Labs Ltd.",
        filename="starter_labs_2025.pdf",
        monthly_amount=6000.0,
        payment_terms="Net 30",
        contract_start=date(2024, 2, 1),
        escalation_pct=8.0,
        escalation_after_months=12,
        escalation_effective_month=2,
        discount_pct=10.0,
        discount_duration_months=3,
        clauses={
            "base_fee": ClauseSpec(
                "base_fee",
                "The Client shall pay a monthly retainer of six thousand dollars "
                "($6,000) for the Services described in Schedule A.",
                2,
                [72.0, 512.0, 468.0, 548.0],
                "exact",
            ),
            "escalation": ClauseSpec(
                "escalation",
                "Fees shall increase by eight percent (8%) on each anniversary of "
                "the Effective Date.",
                3,
                [72.0, 340.5, 468.0, 366.0],
                "exact",
            ),
            "discount": ClauseSpec(
                "discount",
                "A ten percent (10%) introductory discount shall apply to the "
                "first three (3) monthly invoices only.",
                3,
                [72.0, 402.0, 468.0, 438.0],
                "fuzzy",
            ),
            "payment_terms": ClauseSpec(
                "payment_terms",
                "All invoices are payable within thirty (30) days of receipt.",
                5,
                [72.0, 118.0, 468.0, 140.0],
                "exact",
            ),
        },
        planted=[
            PlantedAnomaly(2, "forgotten_raise", 6000.0, 0.94, "escalation"),
            PlantedAnomaly(3, "forgotten_raise", 6000.0, 0.94, "escalation"),
            PlantedAnomaly(6, "zombie_discount", 5832.0, 0.88, "discount"),
        ],
    ),
    ContractSpec(
        name="Nexus Digital LLC",
        filename="nexus_digital_2025.pdf",
        monthly_amount=8000.0,
        payment_terms="Net 15",
        contract_start=date(2024, 6, 1),
        milestone=("Website launch milestone", 15000.0, 4),
        clauses={
            "base_fee": ClauseSpec(
                "base_fee",
                "Client shall pay eight thousand dollars ($8,000) per calendar "
                "month for ongoing platform maintenance.",
                1,
                [90.0, 430.0, 486.0, 466.0],
                "exact",
            ),
            # ADR-005 in the demo data on purpose: a verbatim quote the locator
            # could not place. The clause viewer must degrade, not crash — and
            # this is the largest finding, so the degradation is impossible to
            # miss in a screenshot.
            "milestone": ClauseSpec(
                "milestone",
                "A one-time payment of fifteen thousand dollars ($15,000) shall "
                "become due upon public launch of the redesigned website.",
                None,
                None,
                "failed",
            ),
            "payment_terms": ClauseSpec(
                "payment_terms",
                "Payment is due within fifteen (15) days of invoice date.",
                4,
                [90.0, 236.0, 486.0, 258.0],
                "exact",
            ),
        },
        planted=[
            PlantedAnomaly(4, "ghost_invoice", None, 0.97, "milestone", on_milestone=True),
            PlantedAnomaly(9, "ghost_invoice", None, 0.91, "base_fee"),
        ],
    ),
    ContractSpec(
        name="Bloom Agency",
        filename="bloom_agency_2025.pdf",
        monthly_amount=10000.0,
        payment_terms="Net 45",
        contract_start=date(2024, 9, 1),
        clauses={
            "base_fee": ClauseSpec(
                "base_fee",
                "The monthly service fee shall be ten thousand dollars ($10,000), "
                "invoiced in advance.",
                2,
                [80.0, 596.0, 470.0, 622.0],
                "exact",
            ),
            "payment_terms": ClauseSpec(
                "payment_terms",
                "Invoices shall be settled in full within forty-five (45) days. "
                "Partial payment does not constitute settlement.",
                2,
                [80.0, 640.0, 470.0, 676.0],
                "exact",
            ),
        },
        planted=[
            PlantedAnomaly(5, "short_change", 8500.0, 0.79, "payment_terms"),
            PlantedAnomaly(11, "short_change", 9200.0, 0.72, "payment_terms"),
        ],
    ),
    ContractSpec(
        name="Corvid Media Group",
        filename="corvid_media_2025.pdf",
        monthly_amount=4500.0,
        payment_terms="Net 30",
        contract_start=date(2024, 11, 1),
        escalation_pct=5.0,
        escalation_after_months=12,
        escalation_effective_month=11,
        clauses={
            "base_fee": ClauseSpec(
                "base_fee",
                "A recurring fee of four thousand five hundred dollars ($4,500) "
                "shall be payable monthly.",
                1,
                [72.0, 380.0, 460.0, 406.0],
                "exact",
            ),
            "escalation": ClauseSpec(
                "escalation",
                "The fee shall be adjusted upward by five percent (5%) after "
                "twelve (12) months of continuous service.",
                2,
                [72.0, 210.0, 460.0, 246.0],
                "fuzzy",
            ),
        },
        planted=[],  # pays correctly, including the escalation. The control case.
    ),
    ContractSpec(
        name="Halcyon Partners",
        filename="halcyon_partners_2025.pdf",
        monthly_amount=7200.0,
        payment_terms="Net 30",
        contract_start=date(2024, 4, 1),
        discount_pct=15.0,
        discount_duration_months=2,
        clauses={
            "base_fee": ClauseSpec(
                "base_fee",
                "Consulting services shall be billed at seven thousand two "
                "hundred dollars ($7,200) per month.",
                1,
                [72.0, 455.0, 470.0, 481.0],
                "exact",
            ),
            "discount": ClauseSpec(
                "discount",
                "A fifteen percent (15%) discount applies for the first two (2) "
                "months of the engagement.",
                None,
                None,
                "failed",
            ),
        },
        planted=[],  # discount correctly ended. The other control case.
    ),
]

BANK_STATEMENT = "bank_statement_2025.csv"


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _expected_amount(spec: ContractSpec, month: int) -> tuple[float, bool, float]:
    """(amount, applied_escalation, applied_discount_pct) for one month.

    The same arithmetic Phase 6's timeline_generator will do, kept deliberately
    simple: escalation applies from its effective month onward; the intro
    discount is long expired by the scenario year, so it is never applied to
    what was *expected*. That is precisely what makes a zombie discount a leak.
    """
    amount = spec.monthly_amount
    escalated = False
    if spec.escalation_pct and spec.escalation_effective_month and month >= spec.escalation_effective_month:
        amount = round(amount * (1 + spec.escalation_pct / 100), 2)
        escalated = True
    return amount, escalated, 0.0


def _normalize(name: str) -> str:
    """Lowercase, drop corporate suffixes and punctuation. Mirrors what Phase 5's
    client_matcher will do; reconciliation fuzzy-matches on this, not `name`."""
    cleaned = name.lower()
    for suffix in (" ltd.", " ltd", " llc", " inc.", " inc", " group", " partners", " agency"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    return "".join(ch for ch in cleaned if ch.isalnum() or ch.isspace()).strip()


def seed_run(session: Session, scenario_dir: str | None = None, label: str = "demo_v1") -> int:
    """Write a complete, internally consistent run into every table the UI reads.

    Returns the new `run_id`.

    `scenario_dir` is accepted for the Phase 3 contract in `interfaces.md` but
    is not yet used — Phase 2 has no built scenarios on disk, so the built-in
    `SCENARIO` above is always used. Passing a path raises rather than silently
    seeding something other than what was asked for.
    """
    if scenario_dir is not None:
        raise NotImplementedError(
            "Loading a scenario from disk lands in Phase 3, with "
            "data_sourcing/scenario_builder.py. Omit scenario_dir to use the "
            "built-in demo scenario."
        )

    run_id = create_run(session, label)

    statement = Document(
        run_id=run_id,
        filename=BANK_STATEMENT,
        file_type="csv",
        category="statement",
        extraction_status="complete",
        storage_url=f"seed://{BANK_STATEMENT}",
    )
    session.add(statement)
    session.flush()

    for spec in SCENARIO:
        _seed_contract(session, run_id, spec, statement)

    return run_id


def _seed_contract(session: Session, run_id: int, spec: ContractSpec, statement: Document) -> None:
    """One client end to end: document, contract, clauses, timeline, actuals, findings."""
    document = Document(
        run_id=run_id,
        filename=spec.filename,
        file_type="pdf",
        category="contract",
        extraction_status="complete",
        storage_url=f"seed://{spec.filename}",
    )
    client = Client(run_id=run_id, name=spec.name, normalized_name=_normalize(spec.name))
    session.add_all([document, client])
    session.flush()

    rule = ContractRule(
        client_id=client.id,
        document_id=document.id,
        base_amount=spec.monthly_amount,
        currency="USD",
        billing_frequency="monthly",
        contract_start=spec.contract_start,
        contract_end=date(YEAR, 12, 31),
        payment_terms=spec.payment_terms,
        raw_extraction={
            "client_name": spec.name,
            "base_amount": spec.monthly_amount,
            "seeded": True,
        },
    )
    session.add(rule)
    session.flush()

    # ---- clauses ----
    refs: dict[str, ClauseReference] = {}
    for key, clause in spec.clauses.items():
        ref = ClauseReference(
            contract_rule_id=rule.id,
            document_id=document.id,
            clause_type=clause.clause_type,
            clause_text=clause.text,
            source_page=clause.page,
            source_bbox=clause.bbox,
            locate_method=clause.locate_method,
        )
        session.add(ref)
        refs[key] = ref
    session.flush()

    if spec.escalation_pct and spec.escalation_after_months:
        session.add(
            PriceEscalation(
                contract_rule_id=rule.id,
                clause_reference_id=refs["escalation"].id,
                percentage=spec.escalation_pct,
                after_months=spec.escalation_after_months,
            )
        )
    if spec.discount_pct and spec.discount_duration_months:
        session.add(
            Discount(
                contract_rule_id=rule.id,
                clause_reference_id=refs["discount"].id,
                percentage=spec.discount_pct,
                duration_months=spec.discount_duration_months,
            )
        )
    if spec.milestone:
        description, amount, month = spec.milestone
        session.add(
            Milestone(
                contract_rule_id=rule.id,
                clause_reference_id=refs["milestone"].id,
                description=description,
                amount=amount,
                due_condition="on public launch of the redesigned website",
                due_date=date(YEAR, month, 28),
            )
        )

    planted_recurring = {p.month: p for p in spec.planted if not p.on_milestone}
    planted_milestone = next((p for p in spec.planted if p.on_milestone), None)

    # ---- twelve months of expected vs actual ----
    for month in range(1, 13):
        expected_amount, escalated, discount_pct = _expected_amount(spec, month)
        billing_date = date(YEAR, month, 1)

        entry = ExpectedTimeline(
            run_id=run_id,
            client_id=client.id,
            contract_rule_id=rule.id,
            billing_date=billing_date,
            expected_amount=expected_amount,
            payment_type="recurring",
            applied_escalation=escalated,
            applied_discount_pct=discount_pct,
            source_clause_ref_id=refs["escalation"].id if escalated else refs["base_fee"].id,
            notes="post-escalation rate" if escalated else "base rate",
        )
        session.add(entry)
        session.flush()

        planted = planted_recurring.get(month)
        actual_amount = expected_amount if planted is None else planted.actual

        transaction = None
        if actual_amount is not None:
            transaction = ActualTransaction(
                run_id=run_id,
                document_id=statement.id,
                client_id=client.id,
                transaction_date=billing_date + timedelta(days=3 + (month % 5)),
                amount=actual_amount,
                description=f"{spec.name.upper()} INV-{YEAR}{month:02d}",
                source_type="bank",
            )
            session.add(transaction)
            session.flush()

        if planted is not None:
            _add_anomaly(
                session, run_id, client, entry, transaction, refs[planted.clause_key],
                planted.anomaly_type, expected_amount, actual_amount or 0.0, planted.confidence,
            )

    # ---- the milestone, billed as its own timeline row ----
    if spec.milestone:
        description, amount, month = spec.milestone
        entry = ExpectedTimeline(
            run_id=run_id,
            client_id=client.id,
            contract_rule_id=rule.id,
            billing_date=date(YEAR, month, 28),
            expected_amount=amount,
            payment_type="milestone",
            applied_escalation=False,
            applied_discount_pct=0.0,
            source_clause_ref_id=refs["milestone"].id,
            notes=description,
        )
        session.add(entry)
        session.flush()

        if planted_milestone is not None:
            _add_anomaly(
                session, run_id, client, entry, None, refs[planted_milestone.clause_key],
                planted_milestone.anomaly_type, amount, planted_milestone.actual or 0.0,
                planted_milestone.confidence,
            )
        else:  # pragma: no cover - no such contract in SCENARIO today
            session.add(
                ActualTransaction(
                    run_id=run_id, document_id=statement.id, client_id=client.id,
                    transaction_date=date(YEAR, month, 28) + timedelta(days=6),
                    amount=amount, description=f"{spec.name.upper()} MILESTONE",
                    source_type="bank",
                )
            )


def _add_anomaly(
    session: Session,
    run_id: int,
    client: Client,
    entry: ExpectedTimeline,
    transaction: ActualTransaction | None,
    clause: ClauseReference,
    anomaly_type: str,
    expected_amount: float,
    actual_amount: float,
    confidence: float,
) -> None:
    """Derive the finding from the numbers already written. Never hand-typed."""
    session.add(
        Anomaly(
            run_id=run_id,
            client_id=client.id,
            expected_timeline_id=entry.id,
            actual_transaction_id=transaction.id if transaction else None,
            clause_reference_id=clause.id,
            anomaly_type=anomaly_type,
            expected_amount=expected_amount,
            actual_amount=actual_amount,
            gap=round(expected_amount - actual_amount, 2),
            confidence_score=confidence,
            status="unverified",
        )
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _summarise(session: Session, run_id: int) -> None:
    from core.db.queries import get_summary_stats, list_anomalies, table_counts

    stats = get_summary_stats(session, run_id)
    counts = table_counts(session, run_id=run_id)

    print(f"\nSeeded run {run_id}:")
    for name, count in counts.items():
        if count:
            print(f"  {name:<22} {count:>5}")

    print(f"\n  total leaked   ${stats.total_leaked:,.2f}")
    print(f"  anomalies      {stats.anomaly_count} across {len(stats.by_type)} types")
    for kind, n in sorted(stats.by_type.items()):
        print(f"    {kind:<20} {n}")
    affected = len({a.client_id for a in list_anomalies(session, run_id)})
    print(f"  clients        {affected} of {stats.client_count} affected")
    print(f"  grounding      {stats.grounded_count}/{stats.anomaly_count} findings have a locatable clause "
          f"({stats.unlinked_count} unlinked, {stats.unlocatable_count} unlocatable)")

    # The consistency the plan asks for, asserted rather than assumed.
    rows = list_anomalies(session, run_id)
    assert all(abs(r.gap - (r.expected_amount - r.actual_amount)) < 0.01 for r in rows), (
        "gap does not equal expected - actual"
    )
    assert abs(stats.total_leaked - sum(r.gap for r in rows)) < 0.01, (
        "summary total does not equal the sum of the gaps"
    )
    print("\n  ✓ gap == expected - actual for every row; total == sum(gaps)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a demo run.")
    parser.add_argument("--label", default="demo_v1", help="run label (default: demo_v1)")
    parser.add_argument("--replace", action="store_true", help="delete runs with this label first")
    parser.add_argument("--list", action="store_true", help="list existing runs and exit")
    args = parser.parse_args()

    ok, message = database.check_connection()
    if not ok:
        print(f"✗ {message}", file=sys.stderr)
        print("  Run `python scripts/init_db.py` first.", file=sys.stderr)
        return 1

    if args.list:
        with database.session_scope() as session:
            runs = session.scalars(select(Run).order_by(Run.id)).all()
            if not runs:
                print("No runs yet.")
            for run in runs:
                print(f"  [{run.id}] {run.label}  {run.created_at:%Y-%m-%d %H:%M}")
        return 0

    with database.session_scope() as session:
        if args.replace:
            doomed = session.scalars(select(Run).where(Run.label == args.label)).all()
            for run in doomed:
                print(f"Deleting existing run [{run.id}] {run.label}")
                session.delete(run)
            session.flush()

        run_id = seed_run(session, label=args.label)
        _summarise(session, run_id)

    print(f"\n✓ Run {run_id} seeded. `streamlit run app/main.py` to see it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
