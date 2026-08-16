"""[A+B] Phase 6's definition of done, measured. No AI, no database, no network.

Runs the three scenarios `data_sourcing/scenario_builder.py` built and checks the
engine against their answer keys:

* **easy** and **realistic** must reproduce `ground_truth.json` *exactly* — every
  expected amount, every anomaly, every type, and the total to the cent.
* **edge** must produce **zero** anomalies. That is the one that proves the
  arithmetic discriminates instead of flagging everything, and it is the first
  question an examiner asks.

Run it::

    python scripts/eval_engine.py                 # all three
    python scripts/eval_engine.py --scenario easy
    python scripts/eval_engine.py --verbose       # per-month diffs on failure

Results land in `data/eval/phase6_engine.json`. Exit code is 0 only when every
scenario passes, so it can gate a commit.

`data/` is gitignored: if `data/scenarios/` is missing, rebuild it with
``python -m data_sourcing.scenario_builder`` (known issues #35, #44).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.ai.schemas import ContractRules, TransactionRow  # noqa: E402
from core.engine.reconciliation import (  # noqa: E402
    ClientRef,
    attribute_transactions,
    reconcile_detail,
)
from core.engine.timeline_generator import generate_timeline  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "data" / "scenarios"
EVAL_OUT = ROOT / "data" / "eval" / "phase6_engine.json"
SCENARIO_NAMES = ("easy", "realistic", "edge")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ScenarioReport:
    scenario: str
    checks: list[Check] = field(default_factory=list)
    expected_total_gap: float = 0.0
    actual_total_gap: float = 0.0
    expected_anomalies: int = 0
    actual_anomalies: int = 0
    unattributed: int = 0
    unmatched: int = 0
    diffs: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _load_actuals(path: Path) -> list[TransactionRow]:
    rows: list[TransactionRow] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for index, raw in enumerate(csv.DictReader(handle), start=1):
            rows.append(
                TransactionRow(
                    id=index,  # stands in for actual_transactions.id
                    transaction_date=date.fromisoformat(raw["date"]),
                    amount=float(raw["amount"]),
                    description=raw["description"],
                    source_type="bank",
                )
            )
    return rows


def run_scenario(name: str, *, verbose: bool = False) -> ScenarioReport:
    folder = SCENARIOS / name
    truth = json.loads((folder / "ground_truth.json").read_text(encoding="utf-8"))
    report = ScenarioReport(scenario=name)

    year = truth["observation_year"]
    window_start, window_end = date(year, 1, 1), date(year, 12, 1)

    clients: list[ClientRef] = []
    rules_by_contract: dict[int, ContractRules] = {}
    expected_rows = []
    truth_by_month: dict[tuple[int, int], dict] = {}

    for client_id, client in enumerate(truth["clients"], start=1):
        rules = ContractRules.model_validate(client["rules"])
        clients.append(ClientRef(client_id=client_id, name=client["name"]))
        rules_by_contract[client_id] = rules

        timeline = generate_timeline(
            rules,
            client_id=client_id,
            contract_rule_id=client_id,  # one contract per client in every scenario
            window_start=window_start,
            window_end=window_end,
        )
        # Stand in for expected_timeline.id, which only exists once persisted.
        for entry in timeline:
            entry.id = len(expected_rows) + 1
            expected_rows.append(entry)

        for month_row in client["timeline"]:
            truth_by_month[(client_id, month_row["month"])] = month_row

    # ---- expected timeline vs the answer key, to the cent --------------------
    amount_diffs = []
    for entry in expected_rows:
        key = (entry.client_id, entry.billing_date.month)
        want = truth_by_month.get(key)
        if want is None:
            amount_diffs.append(f"{key} has no ground-truth row")
            continue
        if abs(want["expected_amount"] - entry.expected_amount) > 0.005:
            amount_diffs.append(
                f"client {key[0]} month {key[1]}: expected {want['expected_amount']:.2f}, "
                f"generated {entry.expected_amount:.2f}"
            )
        if bool(want["applied_escalation"]) != entry.applied_escalation:
            amount_diffs.append(
                f"client {key[0]} month {key[1]}: applied_escalation "
                f"{want['applied_escalation']} vs {entry.applied_escalation}"
            )
        if abs(want["applied_discount_pct"] - entry.applied_discount_pct) > 0.005:
            amount_diffs.append(
                f"client {key[0]} month {key[1]}: discount "
                f"{want['applied_discount_pct']} vs {entry.applied_discount_pct}"
            )

    report.checks.append(
        Check(
            "timeline reproduces every expected amount",
            not amount_diffs and len(expected_rows) == len(truth_by_month),
            f"{len(expected_rows)} rows, {len(amount_diffs)} mismatches",
        )
    )
    report.diffs.extend(amount_diffs)

    # ---- attribution ---------------------------------------------------------
    raw_actuals = _load_actuals(folder / "actuals.csv")
    attributions = attribute_transactions(raw_actuals, clients)
    attributed = [a.transaction for a in attributions if a.matched]
    unattributed = [a for a in attributions if not a.matched]
    report.unattributed = len(unattributed)

    # Every row the builder wrote for a client must find that client. The noise
    # rows (bank fees, interest) must find nobody — being unattributed is the
    # correct answer for them, not a miss.
    noise_words = ("BANK SVC", "WIRE TRANSFER FEE", "INTEREST", "MISC CREDIT", "CHECK #")
    wrongly_dropped = [
        a for a in unattributed if not any(w in (a.transaction.description or "") for w in noise_words)
    ]
    report.checks.append(
        Check(
            "every client payment attributed, noise rows left alone",
            not wrongly_dropped,
            f"{len(attributed)}/{len(raw_actuals)} attributed, {len(unattributed)} left out",
        )
    )
    report.diffs.extend(
        f"unattributed client payment: {a.transaction.description!r} (best score {a.score})"
        for a in wrongly_dropped
    )

    # ---- reconciliation ------------------------------------------------------
    result = reconcile_detail(expected_rows, attributed, rules_by_contract=rules_by_contract)
    report.unmatched = len(result.unmatched)
    report.actual_anomalies = len(result.anomalies)
    report.actual_total_gap = result.total_gap
    report.expected_anomalies = truth["anomaly_count"]
    report.expected_total_gap = truth["total_gap"]

    found = {
        (a.client_id, a.billing_date.month): (a.anomaly_type, round(a.gap, 2)) for a in result.anomalies
    }
    wanted = {
        key: (row["anomaly_type"], round(row["gap"], 2))
        for key, row in truth_by_month.items()
        if row["is_anomaly"]
    }

    missed = sorted(set(wanted) - set(found))
    spurious = sorted(set(found) - set(wanted))
    mistyped = [k for k in set(found) & set(wanted) if found[k][0] != wanted[k][0]]
    misvalued = [
        k for k in set(found) & set(wanted) if abs(found[k][1] - wanted[k][1]) > 0.005
    ]

    report.checks.append(Check("no anomaly missed", not missed, f"{len(missed)} missed"))
    report.checks.append(
        Check("no false positive", not spurious, f"{len(spurious)} spurious")
    )
    report.checks.append(
        Check("every anomaly the right type", not mistyped, f"{len(mistyped)} mistyped")
    )
    report.checks.append(
        Check("every gap to the cent", not misvalued, f"{len(misvalued)} wrong")
    )
    report.checks.append(
        Check(
            "total recoverable matches ground truth",
            abs(result.total_gap - truth["total_gap"]) < 0.005,
            f"{result.total_gap:,.2f} vs {truth['total_gap']:,.2f}",
        )
    )

    report.diffs.extend(f"missed: client {c} month {m} ({wanted[(c, m)][0]})" for c, m in missed)
    report.diffs.extend(f"false positive: client {c} month {m} ({found[(c, m)][0]})" for c, m in spurious)
    report.diffs.extend(
        f"mistyped: client {c} month {m}: {found[(c, m)][0]} should be {wanted[(c, m)][0]}"
        for c, m in mistyped
    )
    report.diffs.extend(
        f"wrong gap: client {c} month {m}: {found[(c, m)][1]:.2f} should be {wanted[(c, m)][1]:.2f}"
        for c, m in misvalued
    )

    if verbose and report.diffs:
        for line in report.diffs:
            print(f"      · {line}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIO_NAMES, help="run just one")
    parser.add_argument("--verbose", action="store_true", help="print every diff")
    args = parser.parse_args()

    names = [args.scenario] if args.scenario else list(SCENARIO_NAMES)
    missing = [n for n in names if not (SCENARIOS / n / "ground_truth.json").exists()]
    if missing:
        print(f"! no scenario on disk: {', '.join(missing)}")
        print("  data/ is gitignored — rebuild with: python -m data_sourcing.scenario_builder")
        return 2

    print("FinSight Phase 6 — engine vs ground truth\n")
    reports = []
    for name in names:
        report = run_scenario(name, verbose=args.verbose)
        reports.append(report)
        mark = "PASS" if report.passed else "FAIL"
        print(
            f"  [{mark}] {name:<10} anomalies {report.actual_anomalies}/{report.expected_anomalies}"
            f"   gap ${report.actual_total_gap:,.2f} / ${report.expected_total_gap:,.2f}"
            f"   unattributed {report.unattributed}  unmatched {report.unmatched}"
        )
        for check in report.checks:
            print(f"        {'ok ' if check.passed else 'NO '} {check.name:<44} {check.detail}")
        if not report.passed and not args.verbose:
            for line in report.diffs[:10]:
                print(f"          · {line}")
        print()

    EVAL_OUT.parent.mkdir(parents=True, exist_ok=True)
    EVAL_OUT.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario": r.scenario,
                        "passed": r.passed,
                        "anomalies": {"found": r.actual_anomalies, "expected": r.expected_anomalies},
                        "total_gap": {"found": r.actual_total_gap, "expected": r.expected_total_gap},
                        "unattributed": r.unattributed,
                        "unmatched": r.unmatched,
                        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in r.checks],
                        "diffs": r.diffs,
                    }
                    for r in reports
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  written: {EVAL_OUT.relative_to(ROOT)}")

    ok = all(r.passed for r in reports)
    print("\n" + ("All scenarios reproduce their ground truth." if ok else "FAILED — see the diffs above."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
