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

**Amended 2026-08-17 — both parts used to grade themselves on bookkeeping.**
Part 1 asserted only that every finding got *some* verdict and that the counts
added up; Part 2 asserted a single status string under a label claiming
evidence had been found. Run live for the first time, the agent marked 4 of the
5 planted `realistic` anomalies `false_positive` — $21,480 of $22,500 of
ground-truth-verified leaks deleted — and this script printed "All parts
passed." Part 1 now grades every verdict against `ground_truth.json` (whose
anomalies are true by construction, so `false_positive` is always wrong there),
and Part 2 now asserts that `search_bank_transactions` was actually called and
that a `false_positive` rests on a tool that returned a match. A missing
`data/scenarios/` fails loudly rather than passing quietly.

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
SCENARIOS = ROOT / "data" / "scenarios"

#: Verdicts that do not destroy a genuine finding. `needs_review` is tolerated
#: because it is an honest hedge that still reaches a human; `false_positive` on
#: a planted anomaly is a real leak silently deleted.
SURVIVING_VERDICTS = frozenset({"confirmed", "needs_review", "unverified"})

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


def _scenario_for_label(label: str) -> str | None:
    """Which built scenario a run was loaded from, read off its label.

    `scripts/run_scenario.py` labels runs "engine realistic" / "phase7 easy",
    so the scenario name is a substring. Returns None for a run that did not
    come from a scenario (a seeded demo, an upload), which is not gradeable.
    """
    for name in ("realistic", "easy", "edge"):
        if name in (label or "").lower():
            return name
    return None


def _genuine_findings(scenario: str) -> list[tuple[str, str, float]] | None:
    """Every anomaly the scenario planted, as (client, type, gap).

    These are true by construction — `data_sourcing/scenario_builder.py` derived
    the actuals from the contract and wrote the answer key. So the ONLY correct
    agent verdict for each is `confirmed` (or an honest `needs_review`).

    Returns None when the scenario is not on disk; `data/` is gitignored, and a
    missing corpus must not read as a pass (known issues #33, #44).
    """
    path = SCENARIOS / scenario / "ground_truth.json"
    if not path.exists():
        return None
    truth = json.loads(path.read_text(encoding="utf-8"))
    planted: list[tuple[str, str, float]] = []
    for client in truth.get("clients", []):
        for entry in client.get("timeline", []):
            if entry.get("is_anomaly"):
                planted.append((client["name"], entry["anomaly_type"], round(float(entry["gap"]), 2)))
    return planted


def _is_planted(row, planted: list[tuple[str, str, float]]) -> bool:
    return (row.client_name, row.anomaly_type, round(float(row.gap), 2)) in planted


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

        # ---- the check this eval existed without until 2026-08-17 ----
        # Counting verdicts only proves the agent answered. It cannot tell a
        # right answer from a wrong one, and an agent that rules out every
        # genuine leak passed the count-only version of this script while
        # deleting 95% of the recoverable money.
        run = session.get(models.Run, target_run_id)
        scenario = _scenario_for_label(run.label if run else "")
        planted = _genuine_findings(scenario) if scenario else None

        if planted is None:
            report.checks.append(
                Check(
                    "graded against the scenario's ground truth",
                    False,
                    f"run {target_run_id} ({run.label if run else '?'}) — "
                    + (
                        f"data/scenarios/{scenario}/ is not on disk; rebuild with "
                        "`python -m data_sourcing.scenario_builder`"
                        if scenario
                        else "this run did not come from a scenario, so no answer key exists"
                    ),
                )
            )
        else:
            report.checks.append(
                Check(
                    "the run still reproduces ground truth before verification",
                    len(after) == len(planted) and all(_is_planted(r, planted) for r in after),
                    f"{len(after)} finding(s) vs {len(planted)} planted in '{scenario}'",
                )
            )

            destroyed = [r for r in after if _is_planted(r, planted) and r.status not in SURVIVING_VERDICTS]
            lost = sum(r.gap for r in destroyed)
            total = sum(r.gap for r in after if _is_planted(r, planted))
            report.checks.append(
                Check(
                    "no genuine finding was ruled out",
                    not destroyed,
                    f"{len(destroyed)} of {len(planted)} planted finding(s) marked false_positive"
                    + (f" — ${lost:,.2f} of ${total:,.2f} destroyed" if destroyed else ""),
                )
            )

            hedged = [r for r in after if _is_planted(r, planted) and r.status == "needs_review"]
            report.checks.append(
                Check(
                    "genuine findings were confirmed, not merely hedged",
                    len(hedged) < max(1, len(planted)),
                    f"{len(hedged)} of {len(planted)} left as needs_review",
                )
            )

            for row in destroyed:
                report.traces.append(
                    f"  WRONG [{row.status}] {row.client_name} · {row.anomaly_type} · ${row.gap:,.2f}\n"
                    f"    ground truth says this leak is real. The agent said:\n"
                    f"    {row.agent_reasoning}"
                )

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
        # ---- the checks this part existed without until 2026-08-17 ----
        # The old single check read `row.status == "false_positive"` under a
        # label claiming the payment "was found". A status string cannot say
        # that: the agent reached false_positive having searched, found
        # NOTHING, and concluded the money was never missing — the exact
        # inversion prompts.py rule 5 forbids ("never conclude false_positive
        # on reasoning alone"). It also never called the one tool the whole
        # fixture exists to exercise. Both are now asserted directly.
        calls = [str(step.get("call", "")) for step in (row.agent_tool_calls or [])]
        results = [str(step.get("result", "")) for step in (row.agent_tool_calls or [])]

        searched_bank = any(c.startswith("search_bank_transactions") for c in calls)
        report.checks.append(
            Check(
                "the agent searched unattributed bank activity",
                searched_bank,
                "search_bank_transactions called"
                if searched_bank
                else f"never called it; used {[c.split('(')[0] for c in calls] or 'no tools at all'}",
            )
        )
        # `_format_transactions` / `_format_combinations` open with "Found" only
        # when a tool actually returned rows — the same signal the model is told
        # to reason from, so this asserts evidence rather than parsing prose.
        found_evidence = [r for r in results if r.startswith("Found")]
        report.checks.append(
            Check(
                "the false-positive verdict rests on evidence, not a clean search",
                row.status != "false_positive" or bool(found_evidence),
                f"status={row.status}, {len(found_evidence)} of {len(results)} tool call(s) returned a match",
            )
        )
        report.checks.append(
            Check(
                "the fixture's planted payment was correctly ruled a false positive",
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
