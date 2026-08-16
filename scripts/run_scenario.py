"""[A+B] Load a built scenario into the database and reconcile it for real. Phase 6.

`scripts/seed_demo.py` writes a run whose findings are *seeded* — the numbers are
consistent by construction because the script wrote both sides. This script
writes only the **inputs** (clients, contracts, clauses, transactions) and then
makes `core/engine/pipeline.compute_run` produce the expected timeline and the
findings. Nothing in `expected_timeline` or `anomalies` is authored here.

That is the difference Phase 6 exists to make, and it is visible in the UI: both
frontends read the same tables either way, so a run created here looks like a
seeded one and *is* a computed one (ADR-008).

    python scripts/run_scenario.py easy
    python scripts/run_scenario.py realistic --label "engine v1"
    python scripts/run_scenario.py edge --recompute 4     # re-run the engine on run 4

The scenario folders are gitignored. Rebuild them with
``python -m data_sourcing.scenario_builder`` (known issues #35, #44).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.ai import client_matcher  # noqa: E402
from core.ai.schemas import ContractRules  # noqa: E402
from core.db import models  # noqa: E402
from core.db.database import session_scope  # noqa: E402
from core.engine.pipeline import compute_run, locate_run_clauses  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "data" / "scenarios"


def _clause(
    session, rule_id: int, document_id: int, clause_type: str, text: str | None, document_text: str
):
    """One clause reference row.

    Coordinates are left NULL here and filled by `pipeline.locate_run_clauses`
    once the whole run is loaded — one pass per document rather than one search
    per clause. `locate_method` starts as `"failed"` when the quote is not even
    in the document's text, which is a stronger statement than "not located on a
    page" and worth recording before any PDF is opened.

    Since Phase 7 those coordinates do get filled for the EDGAR corpus: the
    filing is HTML, so `pdf_renderer` typesets it into a PDF first (ADR-021,
    known issue #28).
    """
    if not text:
        return None
    ref = models.ClauseReference(
        contract_rule_id=rule_id,
        document_id=document_id,
        clause_type=clause_type,
        clause_text=text,
        source_page=None,
        source_bbox=None,
        locate_method=None if _grounded(text, document_text) else "failed",
    )
    session.add(ref)
    return ref


def _grounded(quote: str, document_text: str) -> bool:
    """Is this quote actually in the document? Whitespace-insensitive.

    Scenario clauses are hand-transcribed from the filing, so a few differ from
    the source by a line break or an ellipsis. Recording that honestly costs
    nothing and stops a later grounding metric reading better than the truth.
    """
    squash = lambda s: " ".join(s.split()).lower()  # noqa: E731
    return squash(quote) in squash(document_text)


def load(session, scenario: str, label: str | None) -> int:
    folder = SCENARIOS / scenario
    truth = json.loads((folder / "ground_truth.json").read_text(encoding="utf-8"))
    year = truth["observation_year"]

    run = models.Run(
        label=label or f"scenario:{scenario}",
        llm_provider=None,  # nothing in this path calls a model
        model_name=None,
    )
    session.add(run)
    session.flush()

    statement = models.Document(
        run_id=run.id,
        filename="actuals.csv",
        file_type="csv",
        category="statement",
        extraction_status="complete",
        storage_url=f"scenario://{scenario}/actuals.csv",
    )
    session.add(statement)
    session.flush()

    clients_by_name: dict[str, models.Client] = {}

    for entry in truth["clients"]:
        rules = ContractRules.model_validate(entry["rules"])
        contract_path = folder / "contracts" / entry["source_contract"]
        document_text = contract_path.read_text(encoding="utf-8", errors="replace") if contract_path.exists() else ""

        document = models.Document(
            run_id=run.id,
            filename=entry["source_contract"],
            file_type="txt",
            category="contract",
            extraction_status="complete",
            storage_url=f"scenario://{scenario}/contracts/{entry['source_contract']}",
            extracted_text=document_text or None,
            extracted_page_count=1 if document_text else None,
        )
        session.add(document)

        name = entry["name"]
        client = clients_by_name.get(name)
        if client is None:
            client = models.Client(
                run_id=run.id, name=name, normalized_name=client_matcher.normalise(name)
            )
            session.add(client)
            clients_by_name[name] = client
        session.flush()

        rule = models.ContractRule(
            client_id=client.id,
            document_id=document.id,
            base_amount=rules.base_amount,
            currency=rules.currency,
            billing_frequency=rules.billing_frequency,
            contract_start=rules.contract_start_date,
            contract_end=rules.contract_end_date,
            payment_terms=rules.payment_terms,
            raw_extraction=json.loads(rules.model_dump_json()),
        )
        session.add(rule)
        session.flush()

        base_ref = _clause(
            session, rule.id, document.id, "base_fee", entry.get("proving_clause"), document_text
        )
        esc_ref = (
            _clause(session, rule.id, document.id, "escalation", rules.escalation.clause_text, document_text)
            if rules.escalation
            else None
        )
        discount_refs = [
            _clause(session, rule.id, document.id, "discount", d.clause_text, document_text)
            for d in rules.discounts
        ]
        session.flush()

        if rules.escalation:
            session.add(
                models.PriceEscalation(
                    contract_rule_id=rule.id,
                    clause_reference_id=esc_ref.id if esc_ref else None,
                    percentage=rules.escalation.percentage,
                    after_months=rules.escalation.after_months,
                )
            )
        for index, discount in enumerate(rules.discounts):
            ref = discount_refs[index] if index < len(discount_refs) else None
            session.add(
                models.Discount(
                    contract_rule_id=rule.id,
                    clause_reference_id=ref.id if ref else None,
                    percentage=discount.percentage,
                    duration_months=discount.duration_months,
                )
            )
        if base_ref is None:
            print(f"  ! {name}: no base-fee clause recorded — findings will cite nothing")

    # ---- the actuals, exactly as a CSV upload would land them ---------------
    with (folder / "actuals.csv").open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            session.add(
                models.ActualTransaction(
                    run_id=run.id,
                    document_id=statement.id,
                    client_id=None,  # the engine attributes it, the same as a real upload
                    transaction_date=date.fromisoformat(raw["date"]),
                    amount=float(raw["amount"]),
                    description=raw["description"],
                    source_type="bank",
                )
            )

    session.flush()
    print(f"  loaded run {run.id}: {len(clients_by_name)} clients, observation year {year}")
    return run.id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", default="realistic", choices=["easy", "realistic", "edge"])
    parser.add_argument("--label", help="run label shown in the UI's run picker")
    parser.add_argument(
        "--recompute", type=int, metavar="RUN_ID", help="skip loading; re-run the engine on an existing run"
    )
    args = parser.parse_args()

    if args.recompute is None and not (SCENARIOS / args.scenario / "ground_truth.json").exists():
        print(f"! data/scenarios/{args.scenario}/ is not on disk (data/ is gitignored)")
        print("  rebuild with: python -m data_sourcing.scenario_builder")
        return 2

    with session_scope() as session:
        run_id = args.recompute if args.recompute is not None else load(session, args.scenario, args.label)
        summary = compute_run(session, run_id)
        # Phase 7: place every quote on a page. Separate from compute_run because
        # it reads documents rather than doing arithmetic, and because a re-run of
        # the engine does not need the PDFs re-searched.
        located = locate_run_clauses(session, run_id)

    print(f"  {summary.as_line()}")
    print(f"  {located.as_line()}")
    if located.typeset_documents:
        print(
            f"  {located.typeset_documents} document(s) typeset from text for highlighting "
            "(ADR-021) — the originals are HTML, not PDFs"
        )
    for name in located.unrenderable:
        print(f"  ! no page to show for {name}")
    if summary.by_type:
        print("  by type: " + ", ".join(f"{k} {v}" for k, v in sorted(summary.by_type.items())))
    print(
        f"  transactions: {summary.attributed} newly attributed, "
        f"{summary.unattributed} unattributed, {summary.unmatched} outside every billing window"
    )
    for line in summary.skipped_contracts:
        print(f"  ! skipped {line}")
    for line in summary.unresolved_milestones:
        print(f"  · milestone not checked — {line}")

    if args.recompute is None:
        truth = json.loads((SCENARIOS / args.scenario / "ground_truth.json").read_text(encoding="utf-8"))
        match = (
            abs(summary.total_gap - truth["total_gap"]) < 0.005
            and summary.anomalies == truth["anomaly_count"]
        )
        print(
            f"\n  ground truth: {truth['anomaly_count']} findings, ${truth['total_gap']:,.2f}"
            f"  ->  {'MATCH' if match else 'MISMATCH'}"
        )
        return 0 if match else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
