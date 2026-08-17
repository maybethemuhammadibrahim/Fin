#!/usr/bin/env python3
"""[A+B] Phase 9's definition of done, measured.

    python scripts/eval_decision.py               # offline: no model, no database
    python scripts/eval_decision.py --live        # also ask the real model to phrase it
    python scripts/eval_decision.py --run-id 2    # use a real run's figures

The plan's Phase 9 definition of done is: *"Three different strategic questions
produce correct verdicts, and every number in the explanation matches the computed
figure."* Both halves are checked here, and the second is the one worth caring
about — it is the plan's own nominated *"most likely place in the whole project
for a plausible-sounding wrong number to reach a user."*

**Part 1 — the verdicts.** Six questions (three required, three edge cases) over
fixed figures, each with a hand-computed expected verdict and expected
`after_decision`. No database and no model: the questions are parsed by
`decision_analyzer.parse_locally` and the arithmetic is `cashflow`. This part
must pass on any machine, offline, and it is what `pytest` also covers.

**Part 2 — the numbers in the prose.** Every explanation produced, by the model
and by the deterministic fallback alike, is run through
`decision_analyzer.offending_numbers`. Any numeral that is not in
`ScenarioResult.allowed_figures()` is a failure, reported with the offending
value. Without `--live` this exercises the fallback prose only, which is still
worth checking: the fallback is what users see whenever no notebook is running.

Results land in `data/eval/phase9_decision.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ai import decision_analyzer as da  # noqa: E402
from core.engine import cashflow  # noqa: E402

OUT = ROOT / "data" / "eval" / "phase9_decision.json"

#: A year of steady revenue, so the mean is exact and the expectations below can
#: be worked out by hand rather than trusted.
REVENUE = {f"2025-{m:02d}": 22_500.0 for m in range(1, 13)}


@dataclass
class Case:
    name: str
    question: str
    #: monthly running costs the "user" supplied; None means a revenue basis
    expenses: float | None
    #: gaps of the run's CONFIRMED anomalies
    confirmed: list[float]
    months_covered: int
    expected_verdict: str
    expected_monthly_cost: float
    #: hand-computed; None when the verdict is "unknown"
    expected_after: float | None
    why: str


CASES = [
    # ---- the plan's three ----
    Case(
        name="affordable outright",
        question="Can I afford to hire a $5,000/month senior designer starting in September?",
        expenses=10_000.0,                       # surplus 12,500
        confirmed=[1_200.0],                     # 100/month over 12
        months_covered=12,
        expected_verdict="yes",
        expected_monthly_cost=5_000.0,
        expected_after=7_600.0,                  # 12,500 + 100 - 5,000
        why="The surplus alone covers it; recovery widens the margin.",
    ),
    Case(
        name="affordable only after recovery",
        question="Could we take on a $5,000 per month contractor?",
        expenses=18_000.0,                       # surplus 4,500
        confirmed=[12_000.0],                    # 1,000/month
        months_covered=12,
        expected_verdict="yes",
        expected_monthly_cost=5_000.0,
        expected_after=500.0,                    # 4,500 + 1,000 - 5,000
        why="Turns on the recovered money — the point of the whole product.",
    ),
    Case(
        name="not affordable at all",
        question="Is $9,000 a month for a bigger office doable?",
        expenses=18_000.0,                       # surplus 4,500
        confirmed=[12_000.0],                    # 1,000/month
        months_covered=12,
        expected_verdict="no",
        expected_monthly_cost=9_000.0,
        expected_after=-3_500.0,                 # 4,500 + 1,000 - 9,000
        why="Even fully recovered, the surplus does not reach it.",
    ),
    # ---- three that have bitten during development ----
    Case(
        name="annual figure, converted once",
        question="We're considering $72,000 a year on a bigger office. Doable?",
        expenses=10_000.0,                       # surplus 12,500
        confirmed=[6_000.0],                     # 500/month
        months_covered=12,
        expected_verdict="yes",
        expected_monthly_cost=6_000.0,           # 72,000 / 12
        expected_after=7_000.0,                  # 12,500 + 500 - 6,000
        why="An annual amount must be divided exactly once, by Python, not the model.",
    ),
    Case(
        name="no expenses supplied — refuses a verdict",
        question="Can I afford a $5,000/month designer?",
        expenses=None,
        confirmed=[12_000.0],
        months_covered=12,
        expected_verdict="unknown",
        expected_monthly_cost=5_000.0,
        expected_after=None,
        why="ADR-024: no invented surplus, and no Yes/No pretending to know one.",
    ),
    Case(
        name="six-month run is not divided by twelve",
        question="Can I afford a $5,000/month designer?",
        expenses=18_000.0,                       # surplus 4,500
        confirmed=[3_600.0],                     # 600/month over SIX months
        months_covered=6,
        expected_verdict="yes",
        expected_monthly_cost=5_000.0,
        expected_after=100.0,                    # 4,500 + 600 - 5,000
        why="The plan hardcodes /12; that would read 300/month and flip this to No.",
    ),
]


@dataclass
class Outcome:
    name: str
    question: str
    passed: bool = False
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    verdict: str = ""
    monthly_cost: float = 0.0
    after_decision: float | None = None
    explanation: str = ""
    explanation_source: str = ""
    offending: list[float] = field(default_factory=list)


def run_case(case: Case, *, live: bool) -> Outcome:
    out = Outcome(name=case.name, question=case.question)

    def check(label: str, ok: bool, detail: str = "") -> None:
        (out.checks if ok else out.failures).append(f"{label}{f' — {detail}' if detail else ''}")

    # 1. the question -> a monthly cost, deterministically
    parsed = da.parse_locally(case.question) if not live else da.parse_question(case.question)
    out.monthly_cost = parsed.monthly_cost or 0.0
    check(
        "monthly cost read from the question",
        parsed.monthly_cost == case.expected_monthly_cost,
        f"got {parsed.monthly_cost}, expected {case.expected_monthly_cost}",
    )

    # 2. the arithmetic
    baseline = cashflow.baseline_from_monthly(REVENUE, monthly_expenses=case.expenses)
    recovery = cashflow.recovery_from_anomalies(case.confirmed, months_covered=case.months_covered)
    result = cashflow.evaluate(baseline, recovery, monthly_cost=parsed.monthly_cost or 0.0)

    out.verdict = result.verdict
    out.after_decision = result.after_decision
    check(
        "verdict",
        result.verdict == case.expected_verdict,
        f"got {result.verdict}, expected {case.expected_verdict}",
    )
    check(
        "after-decision figure",
        result.after_decision == case.expected_after,
        f"got {result.after_decision}, expected {case.expected_after}",
    )

    # 3. the prose, and every number in it
    explanation = da.explain_verdict(result, parsed)
    out.explanation = explanation.text
    out.explanation_source = explanation.source
    offending = da.offending_numbers(explanation.text, result)
    out.offending = offending
    check(
        "every number in the explanation is a computed figure",
        not offending,
        f"invented {offending}" if offending else "",
    )
    check("an explanation was produced", bool(explanation.text.strip()))

    out.passed = not out.failures
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="also let the real model parse and phrase")
    ap.add_argument("--run-id", type=int, help="report a real run's baseline alongside the fixed cases")
    args = ap.parse_args()

    print("FinSight Phase 9 — decision engine, measured\n")
    if args.live:
        from core.ai import endpoints

        endpoint = endpoints.active()
        print(f"  live mode: {endpoint.label} ({'configured' if endpoint.configured else 'NOT configured'})\n")

    outcomes = [run_case(c, live=args.live) for c in CASES]

    for case, out in zip(CASES, outcomes):
        flag = "PASS" if out.passed else "FAIL"
        print(f"  [{flag}] {out.name}")
        print(f"        {out.question}")
        after = "n/a" if out.after_decision is None else f"${out.after_decision:,.2f}"
        print(f"        verdict {out.verdict:8s} cost ${out.monthly_cost:,.2f}  after {after}")
        print(f"        {case.why}")
        for failure in out.failures:
            print(f"        !! {failure}")
        print(f"        [{out.explanation_source}] {out.explanation[:150]}")
        print()

    # a real run, for context — this part needs a database
    run_note = None
    if args.run_id is not None:
        from core.db.database import get_session

        session = get_session()
        try:
            baseline = cashflow.compute_baseline(session, args.run_id, months=12)
            recovery = cashflow.compute_recovery(session, args.run_id)
            run_note = {
                "run_id": args.run_id,
                "months_observed": baseline.months_observed,
                "monthly_revenue": baseline.monthly_revenue,
                "confidence": baseline.confidence,
                "confirmed_count": recovery.confirmed_count,
                "confirmed_total": recovery.confirmed_total,
                "months_covered": recovery.months_covered,
                "monthly_recovery": recovery.monthly,
                "unverified_total": recovery.unverified_total,
            }
            print(f"  run {args.run_id}: revenue ${baseline.monthly_revenue:,.2f}/mo over "
                  f"{baseline.months_observed} month(s) ({baseline.confidence}); "
                  f"{recovery.confirmed_count} confirmed worth ${recovery.monthly:,.2f}/mo "
                  f"over {recovery.months_covered} month(s); "
                  f"${recovery.unverified_total:,.2f} unverified and excluded\n")
        finally:
            session.close()

    passed = sum(1 for o in outcomes if o.passed)
    invented = [v for o in outcomes for v in o.offending]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "phase": 9,
                "live": args.live,
                "cases_passed": passed,
                "cases_total": len(outcomes),
                "invented_numbers": invented,
                "run": run_note,
                "outcomes": [asdict(o) for o in outcomes],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  written: {OUT.relative_to(ROOT)}\n")

    if invented:
        print(f"  FAILED: {len(invented)} invented number(s) reached an explanation: {invented}")
    if passed != len(outcomes):
        print(f"  FAILED: {len(outcomes) - passed} of {len(outcomes)} cases")
        return 1

    print(f"  All {passed} cases produce the correct verdict, and no explanation "
          f"quoted a figure it was not given.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
