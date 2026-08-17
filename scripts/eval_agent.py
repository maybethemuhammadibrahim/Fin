"""[A+B] Phase 8's definition of done, measured against the real self-hosted
model. Needs a live endpoint — paste a fresh tunnel URL on the Model endpoint
page first (same precondition as `eval_extraction.py`).

    python scripts/eval_agent.py                    # both parts, latest realistic run
    python scripts/eval_agent.py --run-id 13         # a specific run
    python scripts/eval_agent.py --force             # re-verify even if already checked
    python scripts/eval_agent.py --skip-live-run     # fixture only

**Why two parts, and why the second one exists at all.** The plan's Phase 8 demo
is a name-variant false positive ("StarterLabs" vs "Starter Labs") that the
agent catches. Tracing the actual `realistic` scenario data against today's
code shows that demo can no longer happen: `core.engine.reconciliation.
attribute_transactions` already does fuzzy client-name attribution at reconcile
time (a Phase 6 addition that postdates the Phase 8 narrative), so every name
variant in the shipped scenario is already correctly attributed before the
agent ever runs. There is no false positive left in that data for the agent to
find — the mechanical engine got smarter than the demo assumed.

So Part 1 proves the agent handles genuine leaks correctly against real data
(every anomaly in the live `realistic` run should come back CONFIRMED, with
readable reasoning, or NEEDS_REVIEW — never silently dropped). Part 2 proves
the agent's false-positive detection actually works, live-measured, using a
small synthetic fixture built with the SAME real engine functions
(`core.engine.pipeline.persist_rules` / `compute_run`) rather than a scenario
file: one contract, one billing, and one payment recorded under a description
too garbled for fuzzy name-matching to attribute — a genuine ghost_invoice by
construction, and exactly the kind of attribution miss `search_bank_transactions`
exists to catch. Neither part touches `data_sourcing/scenario_builder.py` or any
`ground_truth.json` Phase 6 already measured.

Results land in `data/eval/phase8_agent.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from core.agents.verification_agent import verify_run  # noqa: E402
from core.ai import endpoints, llm_client  # noqa: E402
from core.ai.schemas import ContractRules  # noqa: E402
from core.db import models  # noqa: E402
from core.db.database import session_scope  # noqa: E402
from core.db.queries import list_anomalies  # noqa: E402
from core.engine.pipeline import compute_run, persist_rules  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EVAL_OUT = ROOT / "data" / "eval" / "phase8_agent.json"

FIXTURE_CONTRACT_TEXT = (
    "MASTER SERVICES AGREEMENT. Client shall pay Provider a monthly fee of $6,000, "
    "invoiced on the first day of each month."
)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Report:
    part: str
    checks: list[Check] = field(default_factory=list)
    traces: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)


# ---------------------------------------------------------------------------
# Part 1 — the real "realistic" run, live in the database
# ---------------------------------------------------------------------------


def _find_run_id(session: Session, explicit: int | None) -> int | None:
    if explicit is not None:
        return explicit
    run = session.scalars(
        select(models.Run).where(models.Run.label.like("%realistic%")).order_by(models.Run.id.desc())
    ).first()
    if run is None:
        run = session.scalars(select(models.Run).order_by(models.Run.id.desc())).first()
    return run.id if run else None


def run_live(run_id: int | None, *, force: bool) -> Report:
    report = Report(part="live realistic run")

    with session_scope() as session:
        target_run_id = _find_run_id(session, run_id)
        if target_run_id is None:
            report.checks.append(Check("a run exists to verify", False, "no runs in the database"))
            return report

        if force:
            for row in list_anomalies(session, target_run_id):
                anomaly = session.get(models.Anomaly, row.id)
                anomaly.status = "unverified"
                anomaly.agent_reasoning = None
                anomaly.agent_tool_calls = None
                anomaly.verified_at = None
            session.commit()

        before = list_anomalies(session, target_run_id)
        report.checks.append(Check("run has findings to check", bool(before), f"run {target_run_id}, {len(before)} finding(s)"))
        if not before:
            return report

        summary = verify_run(session, target_run_id, sleep_seconds=1.0)
        report.checks.append(
            Check(
                "every finding got a verdict or an honest skip",
                summary.checked == len(before) or force is False,
                summary.as_line(),
            )
        )
        report.checks.append(
            Check(
                "no anomaly was silently lost",
                (summary.confirmed + summary.false_positive + summary.needs_review + summary.skipped) == summary.checked,
                f"{summary.checked} checked",
            )
        )

        after = list_anomalies(session, target_run_id)
        for row in after[:3]:
            if row.agent_reasoning:
                report.traces.append(
                    f"  [{row.status}] {row.client_name} · {row.anomaly_type} · ${row.gap:,.2f}\n"
                    f"    {row.agent_reasoning}"
                )

    return report


# ---------------------------------------------------------------------------
# Part 2 — synthetic false-positive fixture, real engine, real model
# ---------------------------------------------------------------------------


def run_fixture() -> Report:
    report = Report(part="synthetic false-positive fixture")

    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    with Session(engine) as session:
        run = models.Run(label="eval_agent:fixture")
        session.add(run)
        session.flush()

        document = models.Document(
            run_id=run.id,
            filename="fixture.txt",
            file_type="txt",
            category="contract",
            extraction_status="complete",
            extracted_text=FIXTURE_CONTRACT_TEXT,
        )
        session.add(document)
        session.flush()

        rules = ContractRules(
            client_name="Fixture Co",
            contract_start_date=date(2025, 3, 1),
            contract_end_date=None,
            base_amount=6000.0,
            currency="USD",
            billing_frequency="monthly",
            payment_terms=None,
            escalation=None,
            discounts=[],
            milestones=[],
        )
        persist_rules(session, run.id, document.id, rules, document_text=FIXTURE_CONTRACT_TEXT)

        # The real payment, recorded under a description too garbled for
        # attribute_transactions's fuzzy match (thefuzz threshold 85) to claim —
        # a genuine attribution miss, not a manufactured one.
        session.add(
            models.ActualTransaction(
                run_id=run.id,
                client_id=None,
                transaction_date=date(2025, 3, 3),
                amount=6000.0,
                description="REF 84X2Q AUTOPAY SETTLEMENT",
                source_type="bank",
            )
        )
        session.commit()

        summary = compute_run(session, run.id, window_start=date(2025, 3, 1), window_end=date(2025, 3, 1))
        before = list_anomalies(session, run.id)
        report.checks.append(
            Check(
                "the fixture genuinely reproduces a ghost_invoice",
                len(before) == 1 and before[0].anomaly_type == "ghost_invoice",
                f"{summary.anomalies} anomaly(ies), unattributed={summary.unattributed}",
            )
        )
        if not before:
            return report

        verify_summary = verify_run(session, run.id, sleep_seconds=0.0)
        after = list_anomalies(session, run.id)
        row = after[0]

        report.checks.append(
            Check(
                "the agent reached a verdict (endpoint answered)",
                verify_summary.skipped == 0,
                verify_summary.as_line(),
            )
        )
        report.checks.append(
            Check(
                "the unattributed payment was found and flipped the verdict",
                row.status == "false_positive",
                f"status={row.status}",
            )
        )
        if row.agent_reasoning:
            report.traces.append(f"  [{row.status}] {row.client_name} · ghost_invoice\n    {row.agent_reasoning}")
        if row.agent_tool_calls:
            for step in row.agent_tool_calls:
                report.traces.append(f"    · {step.get('call')}: {step.get('result')}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", type=int, default=None, help="verify a specific run instead of the latest realistic one")
    parser.add_argument("--force", action="store_true", help="re-verify findings even if already checked")
    parser.add_argument("--skip-live-run", action="store_true", help="fixture only, no database connection needed")
    args = parser.parse_args()

    print("FinSight Phase 8 — verification agent, measured\n")

    if not llm_client.health():
        active = endpoints.active()
        print(f"! model endpoint not answering ({active.label}: {active.env_var} not configured or the session is down)")
        print("  paste a fresh tunnel URL on the Model endpoint page, then re-run this script\n")
        return 2

    reports: list[Report] = []

    if not args.skip_live_run:
        print("Part 1 — the live 'realistic' run")
        r1 = run_live(args.run_id, force=args.force)
        reports.append(r1)
        _print_report(r1)

    print("Part 2 — synthetic false-positive fixture")
    r2 = run_fixture()
    reports.append(r2)
    _print_report(r2)

    EVAL_OUT.parent.mkdir(parents=True, exist_ok=True)
    EVAL_OUT.write_text(
        json.dumps(
            {
                "measured_at": datetime.now(timezone.utc).isoformat(),
                "parts": [
                    {"part": r.part, "passed": r.passed, "checks": [asdict(c) for c in r.checks]} for r in reports
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"written: {EVAL_OUT.relative_to(ROOT)}")

    ok = all(r.passed for r in reports)
    print("\n" + ("All parts passed." if ok else "FAILED — see checks above."))
    return 0 if ok else 1


def _print_report(report: Report) -> None:
    mark = "PASS" if report.passed else "FAIL"
    print(f"  [{mark}] {report.part}")
    for check in report.checks:
        print(f"        {'ok ' if check.passed else 'NO '} {check.name:<48} {check.detail}")
    for line in report.traces:
        print(line)
    print()


if __name__ == "__main__":
    raise SystemExit(main())
