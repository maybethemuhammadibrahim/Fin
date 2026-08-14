"""[A] Phase 5's definition of done, measured. Run it, read the two numbers.

    python scripts/eval_extraction.py                 # EDGAR corpus, 10 contracts
    python scripts/eval_extraction.py --pdfs 5        # + CUAD PDFs, page/bbox grounding
    python scripts/eval_extraction.py --limit 3 --no-cache

Two thresholds, both from the plan:

    valid ContractRules        >= 8 of 10
    clause grounding rate      >= 80%  (exact + fuzzy)

**"Grounding" means two different measurements, and this script reports both.**

* *Text grounding* — is the quoted sentence actually in the document? Runs on
  every contract regardless of format, and is what stops a hallucinated quote
  reaching the database. `contract_extractor` applies it unconditionally.
* *PDF grounding* — which page, which rectangle? Needs a real PDF, so it cannot
  run on the EDGAR corpus at all (EDGAR serves HTML; known issue #28). It is
  measured on CUAD PDFs instead, which is precisely the extraction-development
  role ADR-013 demoted CUAD to.

Reporting a single "grounding rate" without saying which one is measured would
be the kind of number that reads well and means nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ai import contract_extractor, endpoints  # noqa: E402
from core.ai.schemas import ContractRules, DocBlock, ExtractedDoc  # noqa: E402
from core.extraction import pdf_extractor  # noqa: E402
from core.extraction.clause_locator import grounding_rate, locate_clause  # noqa: E402

CORPUS = Path("data/corpus/contracts")
VALID_TARGET = 0.8
GROUNDING_TARGET = 80.0


@dataclass
class Row:
    name: str
    ok: bool
    seconds: float
    chunks_sent: int = 0
    chunks_parsed: int = 0
    client_name: str | None = None
    base_amount: float | None = None
    frequency: str | None = None
    escalation: bool = False
    discounts: int = 0
    milestones: int = 0
    grounded_clauses: int = 0
    dropped_clauses: int = 0
    #: Rules returned with no quote at all. Discarded like a dropped one, but
    #: not evidence of fabrication — see contract_extractor.is_absent.
    blank_clauses: int = 0
    located: list[str] = field(default_factory=list)
    error: str | None = None


def load_text_document(path: Path) -> ExtractedDoc:
    """A sourced .txt contract as an ExtractedDoc, without pretending it is a PDF."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    return ExtractedDoc(
        doc_type="text",
        blocks=[DocBlock(page_number=1, text=text)],
        full_text=text,
        page_count=1,
    )


def pick_contracts(limit: int) -> list[Path]:
    """Prefer `filled` (values inserted deterministically, so they definitely
    carry figures — ADR-014) then `ready`. `review` is excluded: nobody has read
    those, and known issue #29 expects a quarter of them to be unusable."""
    chosen: list[Path] = []
    for bucket in ("filled", "ready"):
        for path in sorted((CORPUS / bucket).glob("*.txt")):
            chosen.append(path)
            if len(chosen) == limit:
                return chosen
    return chosen


def clause_texts(rules: ContractRules) -> list[str]:
    quotes = [rules.escalation.clause_text] if rules.escalation else []
    quotes += [d.clause_text for d in rules.discounts]
    quotes += [m.clause_text for m in rules.milestones]
    return quotes


def run_text_corpus(limit: int, use_cache: bool) -> list[Row]:
    rows: list[Row] = []
    for path in pick_contracts(limit):
        started = time.monotonic()
        document = load_text_document(path)
        report = contract_extractor.extract_rules_verbose(document)
        elapsed = round(time.monotonic() - started, 1)

        row = Row(
            name=path.stem[:52],
            ok=report.ok,
            seconds=elapsed,
            chunks_sent=report.chunks_sent,
            chunks_parsed=report.chunks_parsed,
            grounded_clauses=report.grounded,
            dropped_clauses=len(report.dropped),
            blank_clauses=len(getattr(report, "blank", [])),
            error=report.error,
        )
        if report.rules:
            rules = report.rules
            row.client_name = rules.client_name
            row.base_amount = rules.base_amount
            row.frequency = rules.billing_frequency
            row.escalation = rules.escalation is not None
            row.discounts = len(rules.discounts)
            row.milestones = len(rules.milestones)
        rows.append(row)
        print(
            f"  {'OK ' if row.ok else 'MISS'} {row.name:<54} "
            f"{elapsed:>5.1f}s  chunks {row.chunks_parsed}/{row.chunks_sent}  "
            f"grounded {row.grounded_clauses}  dropped {row.dropped_clauses}"
            + (f"  [{row.error}]" if row.error else ""),
            flush=True,
        )
    return rows


def run_pdf_corpus(pdf_paths: list[Path]) -> tuple[list[Row], dict[str, float]]:
    """The full pipeline on real PDFs, so page and bbox can actually be measured."""
    rows: list[Row] = []
    locations = []
    for path in pdf_paths:
        started = time.monotonic()
        try:
            document = pdf_extractor.extract_text_pdf(path)
        except Exception as exc:
            rows.append(Row(name=path.stem[:52], ok=False, seconds=0.0, error=str(exc)[:120]))
            continue

        report = contract_extractor.extract_rules_verbose(document)
        row = Row(
            name=path.stem[:52],
            ok=report.ok,
            seconds=round(time.monotonic() - started, 1),
            chunks_sent=report.chunks_sent,
            chunks_parsed=report.chunks_parsed,
            grounded_clauses=report.grounded,
            dropped_clauses=len(report.dropped),
            error=report.error,
        )
        if report.rules:
            for quote in clause_texts(report.rules):
                location = locate_clause(path, quote)
                locations.append(location)
                row.located.append(location.method if location else "ungrounded")
        rows.append(row)
        print(
            f"  {'OK ' if row.ok else 'MISS'} {row.name:<54} "
            f"{row.seconds:>5.1f}s  locations {row.located or '-'}",
            flush=True,
        )
    return rows, grounding_rate(locations)


def fetch_cuad_pdfs(count: int) -> list[Path]:
    """A handful of CUAD PDFs — the corpus ADR-013 kept for extraction dev."""
    from huggingface_hub import snapshot_download

    local = Path(
        snapshot_download(
            repo_id="theatticusproject/cuad",
            repo_type="dataset",
            allow_patterns=["CUAD_v1/full_contract_pdf/**"],
        )
    )
    pdfs = sorted(p for p in local.rglob("*") if p.suffix.lower() == ".pdf")
    return pdfs[:count]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10, help="EDGAR contracts to extract")
    parser.add_argument("--pdfs", type=int, default=0, help="CUAD PDFs for page/bbox grounding")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--out", default="data/eval/phase5_extraction.json")
    args = parser.parse_args()

    health = endpoints.probe(timeout=20)
    print(f"Endpoint: {endpoints.describe()} — {health.detail}")
    if not health.ok:
        print(
            "\nThe model endpoint is not answering, so there is nothing to measure.\n"
            "Start a session (docs/serving_setup.md) and paste its URL, then re-run.",
            file=sys.stderr,
        )
        return 1
    print(f"Model:    {endpoints.model()}\n")

    if args.no_cache:
        from core.ai import cache

        print(f"Cleared {cache.clear()} cache entries.\n")

    print(f"[1] EDGAR corpus — {args.limit} contracts, text grounding")
    text_rows = run_text_corpus(args.limit, not args.no_cache)

    pdf_rows: list[Row] = []
    pdf_rates = {}
    if args.pdfs:
        print(f"\n[2] CUAD PDFs — {args.pdfs} contracts, page/bbox grounding")
        pdf_rows, pdf_rates = run_pdf_corpus(fetch_cuad_pdfs(args.pdfs))

    # ---- the two numbers the phase is judged on --------------------------
    valid = sum(1 for row in text_rows if row.ok)
    total = len(text_rows)
    quotes = sum(row.grounded_clauses + row.dropped_clauses for row in text_rows)
    kept = sum(row.grounded_clauses for row in text_rows)
    text_grounding = round(100 * kept / quotes, 1) if quotes else 0.0

    print("\n" + "=" * 70)
    print("PHASE 5 DEFINITION OF DONE")
    print("=" * 70)
    valid_ok = total and valid / total >= VALID_TARGET
    print(f"  valid ContractRules      {valid}/{total}"
          f"{'':<8}{'PASS' if valid_ok else 'FAIL'}  (target >= 8/10)")
    ground_ok = text_grounding >= GROUNDING_TARGET
    print(f"  text grounding rate      {text_grounding}%  of {quotes} quotes"
          f"{'':<3}{'PASS' if ground_ok else 'FAIL'}  (target >= 80%)")
    if pdf_rates:
        pdf_ok = pdf_rates["grounded"] >= GROUNDING_TARGET
        print(f"  PDF grounding rate       {pdf_rates['grounded']}% "
              f"(exact {pdf_rates['exact']}%, fuzzy {pdf_rates['fuzzy']}%)"
              f"  {'PASS' if pdf_ok else 'FAIL'}")
    else:
        print("  PDF grounding rate       not measured (pass --pdfs N)")
    print("=" * 70)

    # ---- coverage: did it find what is actually there? -------------------
    # Grounding alone rewards silence. Prompt v1 scored 80% by producing 15
    # quotes across 10 contracts and finding a fee in 2 of them; v2 found a fee
    # in 5 and scored 51.5%. By grounding alone the useless version wins.
    #
    # Every contract in ready/ and filled/ was selected *because* it states a
    # recurring amount and an escalation (see data/corpus/contracts/MANIFEST.md),
    # so a perfect reader would score 10/10 on both. This is a floor, not exact
    # ground truth — it is the number Phase 10 has to move to prove tuning did
    # anything, which is why it is tracked from here on. NOT a phase gate.
    found_base = sum(1 for r in text_rows if r.base_amount is not None)
    found_freq = sum(1 for r in text_rows if r.frequency not in (None, "unknown"))
    found_esc = sum(1 for r in text_rows if r.escalation)
    with_any = sum(1 for r in text_rows if r.grounded_clauses > 0)
    coverage = round(100 * (found_base + found_freq + found_esc) / (3 * total), 1) if total else 0.0
    blanks = sum(r.blank_clauses for r in text_rows)

    print("FIELD COVERAGE — did it find what the contract states? (tracking, not a gate)")
    print(f"  recurring amount         {found_base}/{total}")
    print(f"  billing frequency        {found_freq}/{total}")
    print(f"  escalation clause        {found_esc}/{total}")
    print(f"  contracts with >=1 grounded clause  {with_any}/{total}")
    print(f"  combined coverage        {coverage}%")
    if blanks:
        print(f"  (plus {blanks} rule(s) returned with no quote — absent, not fabricated)")
    print("=" * 70)

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "model": endpoints.model(),
                "provider": endpoints.active_provider(),
                "when": time.strftime("%Y-%m-%d %H:%M"),
                "valid": valid,
                "total": total,
                "text_grounding_pct": text_grounding,
                "quotes": quotes,
                "prompt_version": getattr(__import__("core.ai.prompts", fromlist=["x"]), "PROMPT_VERSION", "?"),
                "coverage": {
                    "base_amount": found_base,
                    "billing_frequency": found_freq,
                    "escalation": found_esc,
                    "contracts_with_a_clause": with_any,
                    "combined_pct": coverage,
                    "blank_clauses": blanks,
                },
                "pdf_grounding": pdf_rates,
                "text_rows": [asdict(row) for row in text_rows],
                "pdf_rows": [asdict(row) for row in pdf_rows],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWritten to {output}")
    return 0 if (valid_ok and ground_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
