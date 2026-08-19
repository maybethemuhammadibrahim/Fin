"""[A] One harness, run unchanged against baseline and fine-tuned. Phase 11.

    python training/evaluate.py --dry-run                       # no GPU, no network
    python training/evaluate.py --url https://xyz.trycloudflare.com \
        --base Qwen/Qwen2.5-3B-Instruct --tuned finsight-tuned  # the real exam

**One process sits both papers.** Not two invocations, not two scripts. The
plan's promise is "same endpoint, same prompt, one variable" — running the two
models from one loop is what makes that structurally true rather than a claim
someone has to check. The only thing that changes between the two passes is
`endpoints.set_model()`, and the value is restored afterwards.

The exam is `training/data/eval_set.jsonl`: real EDGAR contracts, sealed before
a single training example existed, then human-reviewed (Phase 10, steps 2-5).
The prompt is `prompts.EXTRACTION_SYSTEM` + `prompts.extraction_user()` — the
exact pair `core/ai/contract_extractor.py` sends in production and the exact
pair `training/finetune_colab.ipynb` trains on.

**Marked out of 20, not 22.** Two of the sealed answers carry a discount with a
null percentage/duration, which `ContractRules` rejects — the answer key itself
does not parse, so there is nothing to mark against. They are detected here by
validating every gold answer, never by hardcoded row numbers, and both the count
and the reason are printed and written into the results file. Editing a sealed
test set to make a scorer happy is the one repair that is not available.

### What is marked

Six measures, fixed before any number existed (Phase 10, step 7a):

| Measure | Question |
|---|---|
| `usable` | did a `ContractRules` come back at all? |
| `amount` | is `base_amount` right — including right to be absent? |
| `frequency` | is `billing_frequency` right? |
| `escalation` | is the price rise found, absent when absent, and the right %? |
| `quotes_grounded` | is every quoted sentence really in the contract? |
| `found_something` | did it extract any rule at all? |

`found_something` exists because an empty `ContractRules` is structurally valid
and proves nothing: 3 of 10 contracts scored as passes in Phase 5 while
extracting zero clauses (known issue #49). Without this row a model that shrugs
at everything marks respectably.

Every measure is scored against what the gold answer *states*. Where gold says
`base_amount` is absent, the model is marked correct for also saying absent —
not inventing is part of the job, and the corpus deliberately contains contracts
with nothing to find.

Nothing here writes to the database and nothing here calls the engine.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from core.ai import contract_extractor, endpoints, llm_client, prompts  # noqa: E402
from core.ai.schemas import ContractRules  # noqa: E402

EVAL_SET = Path("training/data/eval_set.jsonl")
OUT_DIR = Path("data/eval")

#: A percentage is "the same" within this, so 8.0 and 8.00 do not disagree.
PCT_TOLERANCE = 0.01
#: Money likewise. Amounts are floats in the run's base currency (interfaces.md).
MONEY_TOLERANCE = 0.01
#: Sequential calls with a small pause: the scarce resource is requests per
#: minute, not GPU memory, and bursting is what trips a limit (CLAUDE.md).
CALL_PAUSE_SECONDS = 0.4


# ---------------------------------------------------------------------------
# The exam paper
# ---------------------------------------------------------------------------


@dataclass
class Question:
    """One sealed contract and its human-approved answer."""

    source: str
    contract_text: str
    gold: ContractRules


@dataclass
class Skipped:
    source: str
    reason: str


def load_exam(path: Path = EVAL_SET) -> tuple[list[Question], list[Skipped]]:
    """Every row whose *answer key* parses. The rest are reported, not repaired.

    Detecting the unmarkable rows by validating them means the harness stays
    correct if the sealed set is ever re-cut — a hardcoded "skip rows 6 and 11"
    would silently mark the wrong questions the moment the file changed.
    """
    if not path.exists():
        raise SystemExit(
            f"{path} not found. It is tracked in git (an explicit .gitignore\n"
            "exception) — if it is missing, the checkout is incomplete."
        )

    questions: list[Question] = []
    skipped: list[Skipped] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        source = row.get("source", "?")
        try:
            gold = ContractRules.model_validate_json(row["output"])
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            where = ".".join(str(p) for p in first.get("loc", ()))
            skipped.append(Skipped(source, f"answer key does not parse: {where} {first.get('msg', '')}".strip()))
            continue
        questions.append(Question(source=source, contract_text=row["input"], gold=gold))
    return questions, skipped


# ---------------------------------------------------------------------------
# Marking one paper
# ---------------------------------------------------------------------------


@dataclass
class Mark:
    """One contract, one model. Every field is a fact about this answer."""

    source: str
    usable: bool
    amount: bool = False
    frequency: bool = False
    escalation: bool = False
    found_something: bool = False
    quotes_total: int = 0
    quotes_grounded: int = 0
    error: str | None = None
    #: What it said vs what it should have said, for the eyeball pass. A score
    #: nobody can audit is a score nobody should trust.
    got_amount: float | None = None
    want_amount: float | None = None
    got_frequency: str | None = None
    want_frequency: str | None = None
    got_escalation_pct: float | None = None
    want_escalation_pct: float | None = None


def _same_money(got: float | None, want: float | None) -> bool:
    if got is None or want is None:
        return got is None and want is None
    return abs(got - want) <= MONEY_TOLERANCE


def _same_pct(got: float | None, want: float | None) -> bool:
    if got is None or want is None:
        return got is None and want is None
    return abs(got - want) <= PCT_TOLERANCE


def _quotes(rules: ContractRules) -> list[str]:
    """Every sentence this answer claims to have copied out of the contract."""
    out: list[str] = []
    if rules.escalation is not None:
        out.append(rules.escalation.clause_text)
    out.extend(d.clause_text for d in rules.discounts)
    out.extend(m.clause_text for m in rules.milestones)
    return out


def mark(question: Question, answer: ContractRules | None, error: str | None = None) -> Mark:
    """Six measures. Absent-is-correct wherever the gold answer says absent."""
    if answer is None:
        return Mark(source=question.source, usable=False, error=error)

    gold = question.gold
    got_esc = answer.escalation.percentage if answer.escalation else None
    want_esc = gold.escalation.percentage if gold.escalation else None

    # Grounding uses the app's own verbatim test, so the number here means the
    # same thing as the number on the Phase 5 report. A quote the model declined
    # to give ("null") is not counted as a quote at all — calling an absent
    # quote a hallucination overstates the rate (contract_extractor.is_absent).
    quotes = [q for q in _quotes(answer) if not contract_extractor.is_absent(q)]
    grounded = sum(1 for q in quotes if contract_extractor.is_verbatim(q, question.contract_text))

    return Mark(
        source=question.source,
        usable=True,
        amount=_same_money(answer.base_amount, gold.base_amount),
        frequency=answer.billing_frequency == gold.billing_frequency,
        escalation=(answer.escalation is None) == (gold.escalation is None) and _same_pct(got_esc, want_esc),
        found_something=bool(
            answer.base_amount is not None or answer.escalation or answer.discounts or answer.milestones
        ),
        quotes_total=len(quotes),
        quotes_grounded=grounded,
        got_amount=answer.base_amount,
        want_amount=gold.base_amount,
        got_frequency=answer.billing_frequency,
        want_frequency=gold.billing_frequency,
        got_escalation_pct=got_esc,
        want_escalation_pct=want_esc,
    )


# ---------------------------------------------------------------------------
# Sitting one paper
# ---------------------------------------------------------------------------


@dataclass
class Scorecard:
    model: str
    label: str
    marks: list[Mark] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.marks)

    def count(self, attr: str) -> int:
        return sum(1 for m in self.marks if getattr(m, attr))

    def pct(self, attr: str) -> float:
        return round(100 * self.count(attr) / self.total, 1) if self.total else 0.0

    @property
    def quotes_total(self) -> int:
        return sum(m.quotes_total for m in self.marks)

    @property
    def quotes_grounded(self) -> int:
        return sum(m.quotes_grounded for m in self.marks)

    @property
    def grounding_pct(self) -> float:
        return round(100 * self.quotes_grounded / self.quotes_total, 1) if self.quotes_total else 0.0

    def row(self, attr: str) -> str:
        return f"{self.count(attr)}/{self.total} ({self.pct(attr)}%)"


def sit(
    questions: list[Question],
    model: str,
    label: str,
    *,
    use_cache: bool,
    verbose: bool,
    guard: bool = True,
) -> Scorecard:
    """Ask one model every question. `endpoints.set_model` is the one variable.

    The answer is passed through `contract_extractor._ground` before marking, so
    what is scored is **what the product would actually store** — a quote that is
    not in the document, and a rate that is not in its quote, never reach a user
    and so should never reach a scorecard either. `--no-guard` marks the raw
    model output instead, which is how the 2026-08-19 pre-fix numbers in
    docs/phase11_results.md were produced.
    """
    endpoints.set_model(model)
    card = Scorecard(model=model, label=label)

    for index, question in enumerate(questions, start=1):
        answer = llm_client.complete_json(
            prompts.extraction_user(question.contract_text),
            ContractRules,
            system=prompts.EXTRACTION_SYSTEM,
            use_cache=use_cache,
        )
        if answer is not None and guard:
            answer = contract_extractor._ground(answer, question.contract_text)[0]
        result = mark(question, answer, error=None if answer else llm_client.last_error())
        card.marks.append(result)
        if verbose:
            flag = "ok " if result.usable else "FAIL"
            print(f"  [{index:2}/{len(questions)}] {flag} {question.source[:58]}")
        time.sleep(CALL_PAUSE_SECONDS)

    return card


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

MEASURES = [
    ("usable", "gave a usable answer"),
    ("amount", "fee amount right"),
    ("frequency", "billing rhythm right"),
    ("escalation", "price rise right"),
    ("found_something", "found anything at all"),
]


def describe_exam(questions: list[Question]) -> dict:
    """What the paper actually asks — and what guessing alone would score.

    Printed before any result, because two of the six measures rest on a much
    thinner base than the headline percentage suggests, and a reader who is not
    told will over-read them:

    * **billing rhythm** is 18 monthly to 2 annual, so a model that answers
      "monthly" every single time scores 90% without reading anything.
    * **discounts and milestones** appear once each. They are effectively
      unmeasured; do not report a discount capability from this exam.

    This is the same lesson as known issue #49 — a headline that counts passes
    without saying what was on the paper flatters whatever produced it.
    """
    freq: dict[str, int] = {}
    for q in questions:
        freq[q.gold.billing_frequency] = freq.get(q.gold.billing_frequency, 0) + 1
    top = max(freq.values()) if freq else 0
    return {
        "questions": len(questions),
        "with_fee_amount": sum(1 for q in questions if q.gold.base_amount is not None),
        "with_price_rise": sum(1 for q in questions if q.gold.escalation),
        "with_discount": sum(1 for q in questions if q.gold.discounts),
        "with_milestone": sum(1 for q in questions if q.gold.milestones),
        "frequency_mix": freq,
        "always_commonest_frequency_scores": round(100 * top / len(questions), 1) if questions else 0.0,
    }


def print_exam(facts: dict) -> None:
    print(
        f"  fee amount present in {facts['with_fee_amount']}/{facts['questions']}"
        f" · price rise {facts['with_price_rise']}"
        f" · discount {facts['with_discount']}"
        f" · milestone {facts['with_milestone']}"
    )
    print(f"  billing mix {facts['frequency_mix']}")
    print(
        f"  NOTE: answering '{max(facts['frequency_mix'], key=facts['frequency_mix'].get)}' every time"
        f" scores {facts['always_commonest_frequency_scores']}% on billing rhythm without reading anything."
    )
    if facts["with_discount"] < 3 or facts["with_milestone"] < 3:
        print("  NOTE: discounts and milestones are too rare here to support any claim about them.")


def report(cards: list[Scorecard], skipped: list[Skipped]) -> None:
    width = max(len(desc) for _, desc in MEASURES) + 2
    header = f"{'':{width}}" + "".join(f"{c.label:>18}" for c in cards)
    print("\n" + header)
    print("-" * len(header))
    for attr, desc in MEASURES:
        print(f"{desc:{width}}" + "".join(f"{c.row(attr):>18}" for c in cards))
    print(
        f"{'quotes really in text':{width}}"
        + "".join(f"{f'{c.quotes_grounded}/{c.quotes_total} ({c.grounding_pct}%)':>18}" for c in cards)
    )

    if len(cards) == 2:
        base, tuned = cards
        print("\nchange, tuned minus base:")
        for attr, desc in MEASURES:
            delta = tuned.count(attr) - base.count(attr)
            print(f"  {desc:{width}} {delta:+d}")
        print(f"  {'quotes really in text':{width}} {tuned.grounding_pct - base.grounding_pct:+.1f} points")
        print(
            "\nRemember what this can and cannot say: "
            f"{cards[0].total} contracts is a small exam, and a swing of one or two\n"
            "questions is noise. Report the split, not just the headline (known issue #49)."
        )

    if skipped:
        print(f"\nnot marked ({len(skipped)}):")
        for item in skipped:
            print(f"  {item.source[:60]} — {item.reason}")


def write_results(cards: list[Scorecard], skipped: list[Skipped], out: Path, exam_facts: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "prompt_version": prompts.PROMPT_VERSION,
        "questions_marked": cards[0].total if cards else 0,
        "exam_composition": exam_facts,
        "not_marked": [asdict(s) for s in skipped],
        "scorecards": [
            {
                "label": c.label,
                "model": c.model,
                "totals": {attr: {"count": c.count(attr), "pct": c.pct(attr)} for attr, _ in MEASURES},
                "quotes": {
                    "total": c.quotes_total,
                    "grounded": c.quotes_grounded,
                    "pct": c.grounding_pct,
                },
                "marks": [asdict(m) for m in c.marks],
            }
            for c in cards
        ],
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwritten: {out}")


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", help="model name serving the untuned weights")
    parser.add_argument("--tuned", help="model name serving base + the QLoRA adapter")
    parser.add_argument("--url", help="paste this session's tunnel URL (it rotates every restart)")
    parser.add_argument("--provider", default="colab_tunnel", choices=("colab_tunnel", "kaggle_tunnel", "modal", "custom"))
    parser.add_argument("--limit", type=int, help="mark only the first N questions (a smoke run)")
    parser.add_argument("--no-cache", action="store_true", help="ignore the disk cache")
    parser.add_argument("--quiet", action="store_true", help="no per-contract line")
    parser.add_argument(
        "--no-guard",
        action="store_true",
        help="mark RAW model output, skipping the grounding the product applies",
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR / "phase11_base_vs_tuned.json")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="mark the answer key against itself: proves the marking works, needs no GPU",
    )
    args = parser.parse_args()

    questions, skipped = load_exam()
    if args.limit:
        questions = questions[: args.limit]
    print(f"exam: {len(questions)} markable, {len(skipped)} unmarkable, prompt {prompts.PROMPT_VERSION}")
    facts = describe_exam(questions)
    print_exam(facts)

    if args.dry_run:
        # Feed each gold answer back as if the model had produced it. Every
        # measure must read 100%, and the quotes must all be found in their own
        # contract. Anything less is a bug in the marking, not in a model —
        # which is exactly what we want to discover before booking a GPU.
        card = Scorecard(model="(answer key)", label="perfect paper")
        card.marks = [mark(q, q.gold) for q in questions]
        report([card], skipped)
        perfect = all(card.count(attr) == card.total for attr, _ in MEASURES)
        print(
            "\nmarking self-test: PASS" if perfect and card.grounding_pct == 100.0
            else "\nmarking self-test: FAILED — the marker disagrees with the answer key"
        )
        return 0 if perfect else 1

    if not args.base and not args.tuned:
        parser.error("give --base and/or --tuned (or --dry-run)")

    if args.url:
        endpoints.set_url(args.provider, args.url)
    endpoints.set_active(args.provider)

    previous_model = endpoints.model()
    cards: list[Scorecard] = []
    try:
        for label, model in (("base", args.base), ("tuned", args.tuned)):
            if not model:
                continue
            print(f"\n{label}: {model}")
            cards.append(
                sit(questions, model, label, use_cache=not args.no_cache,
                    verbose=not args.quiet, guard=not args.no_guard)
            )
    finally:
        # Leave the switcher exactly as it was found. A harness that silently
        # repoints the whole app at whatever it tested last is a trap for the
        # next person to open the Streamlit UI.
        endpoints.set_model(previous_model)

    report(cards, skipped)
    write_results(cards, skipped, args.out, facts)

    if any(c.count("usable") == 0 for c in cards):
        print("\nEvery answer failed. That is an endpoint problem, not a model result.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
