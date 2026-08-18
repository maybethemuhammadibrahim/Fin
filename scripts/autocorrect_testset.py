#!/usr/bin/env python3
"""[A] Repair the reviewed test-set answers that contradict their own contract.

    python scripts/autocorrect_testset.py --dry-run   # show every change, write nothing
    python scripts/autocorrect_testset.py             # apply
    python scripts/autocorrect_testset.py --report    # what still needs a human eye

**Why this exists.** The first review pass approved 28 of 28 cards, but 19 of
those answers failed a hard check — nine said "no fee" where the excerpt plainly
reads "$12,500 per month", and about seven attached an escalation with no
percentage. An answer key that contradicts its own contract is worse than no
answer key: a model that correctly reads $12,500 would be scored WRONG, and
Phase 11's base-vs-tuned number would be noise wearing the costume of a result.

**What it is allowed to do.** Only repairs that are decidable from the text by
rule, never by interpretation:

* `amount is null` -> take the recurring fee **literally present** in the
  excerpt, and only when exactly one candidate is bound to a period word.
* `escalation.percentage is null` -> `escalation = null`. A clause saying the
  fee will be *reviewed* annually is not a fixed rise, and an escalation object
  with no percentage cannot generate a timeline. This is a schema truth, not a
  reading of the contract.
* `escalation.clause_text not in the document` -> `escalation = null`. A quote
  that cannot be located was not copied from this contract, so nothing about it
  can be asserted (architecture rule 2 applies to ground truth too).

**What it refuses to do.** Choose between competing fees. ArtistDirect states
$3,500 and $8,500; the draft answered $12,000, which is their sum — arithmetic
the architecture forbids. Which one is "the" recurring fee is a judgement, so
those are marked `needs_human` and **excluded from the eval set** until someone
looks. A smaller clean exam beats a bigger guessed one.

Every change records how it was decided, so `--report` can list exactly which
answers rest on a rule and which still want an eye. Provenance is written into
`decisions.json` and surfaces in the final `eval_set.jsonl`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_testset import appears_verbatim, run_checks  # noqa: E402

HELDOUT = ROOT / "data" / "corpus" / "heldout"
PROPOSALS = HELDOUT / "proposals.json"
DECISIONS = HELDOUT / "decisions.json"

#: "$12,500 per month", "monthly fee of $3,375", "$25,000.00 per month".
#: Deliberately narrow: the amount must be bound to a period word, which is what
#: makes it a RECURRING fee rather than a deposit, a cap or a penalty.
FEE_PATTERNS = [
    re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)\s*per\s+(month|quarter|year|annum)", re.I),
    re.compile(
        r"(monthly|quarterly|annual)\s+(?:base\s+)?(?:fee|retainer|compensation|charge)"
        r"[^.$]{0,40}\$\s?([\d,]+(?:\.\d{2})?)",
        re.I,
    ),
]
PERIOD_TO_FREQUENCY = {
    "month": "monthly", "monthly": "monthly",
    "quarter": "quarterly", "quarterly": "quarterly",
    "year": "annual", "annum": "annual", "annual": "annual",
}

#: An amount next to a time word is NOT necessarily the contract's fee. Checked
#: by hand against the first run of this script, which "repaired" three answers
#: into nonsense: Central Garden's $1,000/month is an **automobile allowance**
#: in an employment agreement, Prestige's $5,000,000 is an **insurance limit per
#: occurrence**, and AssetMark's $1 is a nominal renewal fee. This is known issue
#: #34's trap a third time (an "18% per annum" late-payment clause scored as a
#: fee rise) and #24's a second time — proximity is not meaning. Any candidate
#: whose surrounding sentence matches one of these is not a recurring service
#: fee, and if that leaves nothing, the honest answer is "ask a human".
NOT_A_FEE = re.compile(
    r"insurance|liabilit|coverage|per occurrence|aggregate limit|indemnif"
    r"|allowance|reimburs|expense|deposit|security"
    r"|penalt|liquidated damages|late|overdue|interest"
    r"|salary|bonus|severance|vacation"
    r"|renewal fee|renewabl|nominal",
    re.I,
)
CONTEXT = 150

#: A recurring fee in a B2B service contract is not one dollar. AssetMark's
#: excerpt offers "an additional annual fee of $1" — a peppercorn renewal, real
#: text but not a billing rule anything could be reconciled against. Below this
#: the answer is "ask a human", never a silent repair.
IMPLAUSIBLE_FEE = 100.0


def candidate_fees(text: str) -> list[tuple[float, str]]:
    """(amount, frequency) for every recurring SERVICE fee literally in the text.

    Each hit is judged in its surrounding sentence, not in isolation — that is
    the difference between "$1,000 per month" as a fee and as a car allowance.
    """
    flat = re.sub(r"\s+", " ", text)
    found: list[tuple[float, str]] = []
    for pattern in FEE_PATTERNS:
        for match in pattern.finditer(flat):
            window = flat[max(0, match.start() - CONTEXT) : match.end() + CONTEXT]
            if NOT_A_FEE.search(window):
                continue
            groups = match.groups()
            raw_amount = groups[1] if groups[0] and not groups[0][0].isdigit() else groups[0]
            period = groups[1] if raw_amount is groups[0] else groups[0]
            try:
                amount = float(str(raw_amount).replace(",", ""))
            except (TypeError, ValueError):
                continue
            frequency = PERIOD_TO_FREQUENCY.get(str(period).lower(), "monthly")
            found.append((amount, frequency))
    seen: dict[float, str] = {}
    for amount, frequency in found:
        seen.setdefault(amount, frequency)
    return sorted(seen.items())


def correct(rules: dict, excerpt: str) -> tuple[dict, list[str], list[str]]:
    """(repaired_rules, changes_made, reasons_a_human_is_still_needed)."""
    fixed = json.loads(json.dumps(rules))  # deep copy
    changes: list[str] = []
    human: list[str] = []

    # ---- 1. a missing fee that is present in the text ----
    amount = fixed.get("base_amount")
    numbers_present = amount is not None and any(
        abs(float(amount) - value) < 0.01
        for value in (float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", excerpt))
    )
    if amount is None or not numbers_present:
        candidates = [c for c in candidate_fees(excerpt) if c[0] >= IMPLAUSIBLE_FEE]
        if len(candidates) == 1:
            value, frequency = candidates[0]
            changes.append(f"[rule] base_amount {amount!r} -> {value} (only recurring fee in the text)")
            fixed["base_amount"] = value
            if fixed.get("billing_frequency") != frequency:
                changes.append(f"[rule] billing_frequency -> {frequency} (from the same sentence)")
                fixed["billing_frequency"] = frequency
        elif len(candidates) > 1:
            human.append(
                f"{len(candidates)} competing fees {[c[0] for c in candidates]} — "
                f"which one is the recurring fee is a judgement, not a rule"
            )
        else:
            human.append("no recurring fee is stated in the excerpt at all")

    # ---- 2. an escalation that cannot generate a timeline ----
    esc = fixed.get("escalation")
    if isinstance(esc, dict):
        quote = esc.get("clause_text") or ""
        if esc.get("percentage") is None:
            changes.append("[rule] escalation -> null (no percentage: a fee *review* is not a fixed rise)")
            fixed["escalation"] = None
        elif not appears_verbatim(quote, excerpt):
            changes.append("[rule] escalation -> null (quoted clause is not in the document)")
            fixed["escalation"] = None
        elif f"{float(esc['percentage']):g}" not in re.sub(r"[^\d.]", " ", quote):
            human.append(
                f"escalation says {esc['percentage']}% but that figure is not in its own quote"
            )

    # ---- 3. clauses quoting text that is not there ----
    for key in ("discounts", "milestones"):
        kept = []
        for item in fixed.get(key) or []:
            if isinstance(item, dict) and appears_verbatim(item.get("clause_text") or "", excerpt):
                kept.append(item)
            else:
                changes.append(f"[rule] dropped one {key[:-1]} (its quote is not in the document)")
        fixed[key] = kept

    fixed.setdefault("currency", "USD")
    fixed.setdefault("contract_end_date", None)
    fixed.setdefault("payment_terms", None)
    return fixed, changes, human


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    proposals = {p["filename"]: p for p in json.loads(PROPOSALS.read_text(encoding="utf-8"))["proposals"]}
    decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))

    repaired = 0
    still_failing = 0
    needs_human: list[tuple[str, list[str]]] = []
    untouched = 0

    for name, raw in decisions.items():
        verdict = raw.get("verdict") if isinstance(raw, dict) else raw
        if verdict != "keep" or name not in proposals:
            continue
        proposal = proposals[name]
        current = (raw.get("rules") if isinstance(raw, dict) else None) or proposal["rules"]
        if not current:
            continue

        before = [c for c in run_checks(current, proposal["excerpt"]) if not c.passed and c.label.startswith("!")]
        if not before:
            untouched += 1
            continue

        fixed, changes, human = correct(current, proposal["excerpt"])
        after = [c for c in run_checks(fixed, proposal["excerpt"]) if not c.passed and c.label.startswith("!")]

        if args.report or args.dry_run:
            print(f"\n{name[:58]}")
            for line in changes:
                print(f"   {line}")
            for line in human:
                print(f"   [HUMAN] {line}")
            if after:
                print(f"   -> still failing: {'; '.join(c.label[2:].strip() for c in after)}")

        if human or after:
            needs_human.append((name, human or [c.label[2:].strip() for c in after]))
            still_failing += 1
        else:
            repaired += 1

        if not (args.dry_run or args.report):
            decisions[name] = {
                "verdict": "keep" if not (human or after) else "needs_human",
                "rules": fixed,
                "corrections": changes,
                "open_questions": human or [c.label[2:].strip() for c in after],
            }

    if not (args.dry_run or args.report):
        DECISIONS.write_text(json.dumps(decisions, indent=2), encoding="utf-8")

    print(f"\n{'would repair' if (args.dry_run or args.report) else 'repaired'}: {repaired}")
    print(f"already clean: {untouched}")
    print(f"still needing a human: {still_failing}  (held OUT of eval_set.jsonl)")
    if needs_human:
        print("\nthese want your eye when you are up to it:")
        for name, reasons in needs_human:
            print(f"  {name[:46]:46} {reasons[0][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
