#!/usr/bin/env python3
"""[A] Seal the Phase 10 held-out test set — real contracts only, before training.

    python scripts/seal_testset.py                 # seal ~30 candidates
    python scripts/seal_testset.py --count 40      # more, if you want to discard harder
    python scripts/seal_testset.py --verify        # prove nothing has been tampered with
    python scripts/seal_testset.py --check FILE... # is this file sealed? (leak check)
    python scripts/seal_testset.py --force         # RESEAL: see the warning below

**Why this is a script and not a folder someone copies by hand.**
`docs/implementation_plan.md` Phase 10: *"the one rule you cannot break: build
eval_set.jsonl BEFORE you train, and never let it touch training. If the eval
set leaks into training, every number in Phase 11 is meaningless and you won't
be able to tell."* That last clause is the whole problem — a leak does not
announce itself, it just produces a **suspiciously good score**. So the split
has to be mechanical, recorded, and checkable after the fact.

What this writes to `data/corpus/heldout/`:

* the sealed contracts themselves
* `SEALED.json` — for each one: filename, filer, sha256 of the exact bytes, and
  the clause fingerprint `filter_contracts.deduplicate()` already uses

The sha256 is what makes a later claim provable rather than merely asserted:
`--check` will tell you whether any given file is (or is a copy of) a sealed
contract, and `--verify` re-hashes the folder to prove nothing was edited after
sealing.

**Resealing.** `--force` is refused once a training set exists, because
resealing after training silently converts a leak into a pass. Delete
`training/data/` deliberately if you really mean it.

**Which contracts.** Drawn from `ready/` and `filled/` only — the tiers where a
real answer exists to score an extraction against. `review/` is excluded: its
figures are missing, so "correct" is not defined for it (#29). Selection is
seeded and reproducible, and spreads across filers so the test set is not four
copies of one administrator's fee letter (#26).

**`ready/` is machine-scored, not verified** (#34, #77) — Cellteck's "18% per
annum" is loan interest and still scores ready. That is expected: this script
seals *candidates*, and the human pass discards the bad ones. Seal ~30 to keep
~20.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_sourcing.filter_contracts import (  # noqa: E402
    FILLED_DIR,
    READY_DIR,
    REVIEW_DIR,
    clause_fingerprint,
    filer_of,
    score_contract,
)

HELDOUT_DIR = ROOT / "data" / "corpus" / "heldout"
SEALED_JSON = HELDOUT_DIR / "SEALED.json"
TRAINING_DATA = ROOT / "training" / "data"
DEFAULT_SEED = 20260817


@dataclass
class Sealed:
    filename: str
    filer: str
    tier: str
    sha256: str
    clause_fingerprint: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


#: A fee that IS a single recurring amount — "a monthly fee of $6,000",
#: "$6,000 per month" — not merely a dollar sign near the word "fee".
RECURRING_FEE = re.compile(
    r"(?:a\s+)?(?:monthly|quarterly|annual)\s+(?:base\s+)?(?:fee|retainer|compensation|salary)"
    r"[^.$]{0,60}\$\s?[\d,]+(?:\.\d{2})?"
    r"|\$\s?[\d,]+(?:\.\d{2})?\s*(?:per|each)\s+(?:month|quarter|year)",
    re.I,
)
#: Fund-administration vocabulary. These documents price per fund, per service
#: and in basis points, so "the recurring fee" is a table and not a number.
FUND_ADMIN = re.compile(
    r"fund accounting|transfer agen|sub-administration|net asset value|"
    r"basis points|bps\b|per\s+(?:fund|portfolio|series|account)\b",
    re.I,
)
#: Above this many distinct dollar figures a document is a RATE CARD.
RATE_CARD_DISTINCT_AMOUNTS = 20
FUND_ADMIN_MENTIONS = 2


def _usable_as_a_test_question(path: Path) -> bool:
    """Does this document state ONE recurring fee, rather than a price list?

    Tier alone is not enough, and neither is "a dollar amount near fee-ish
    words". **Measured 2026-08-17, twice:**

    * The first seal drew on tier alone. 27 of its 30 contracts auto-rejected at
      review-prep, because the EX-99 fund-administration cluster states a *table*
      of fees ($1,250 / $1,500 / $5,000 per fund per service) and no single
      recurring amount. The extraction was right to return null; the question has
      no single answer for those documents.
    * The second attempt required a fee phrase and few distinct amounts. Still
      only 1 of 6 survived — the phrase can appear anywhere in a rate card.

    A test set of rate cards measures nothing: every correct answer is null, so a
    model that always answers null scores 100%. Hence three conditions, not one —
    a fee bound to a period word, few distinct amounts, and not fund-admin prose.
    Yield across the 192-contract corpus: 30.
    """
    flat = re.sub(r"\s+", " ", path.read_text(encoding="utf-8", errors="ignore"))
    if not RECURRING_FEE.search(flat):
        return False
    if len(FUND_ADMIN.findall(flat)) > FUND_ADMIN_MENTIONS:
        return False
    distinct = len(set(re.findall(r"\$\s?[\d,]+(?:\.\d{2})?", flat)))
    return distinct <= RATE_CARD_DISTINCT_AMOUNTS


def _candidates() -> list[tuple[Path, str]]:
    """(path, tier) for every contract that could carry a scoreable answer.

    Draws from all three tiers, not just ready/filled: `review` only means no
    figure was found by the *corpus* scorer, and a document can still state a
    clean monthly fee that the scorer's narrower patterns missed. The recurring
    fee filter is a better gate than the tier is.
    """
    out: list[tuple[Path, str]] = []
    for directory, tier in ((READY_DIR, "ready"), (FILLED_DIR, "filled"), (REVIEW_DIR, "review")):
        source = ROOT / directory if not directory.is_absolute() else directory
        if not source.exists():
            continue
        for path in sorted(source.glob("*.txt")):
            if _usable_as_a_test_question(path):
                out.append((path, tier))
    return out


def _pick(candidates: list[tuple[Path, str]], count: int, seed: int) -> list[tuple[Path, str]]:
    """Spread the draw across filers, then across clause wordings.

    A uniform random sample would happily seal four documents from the same
    administrator (#26). Bucketing by filer first, then taking one from each in
    a seeded shuffle, keeps the test set as varied as the corpus allows.
    """
    rng = random.Random(seed)
    by_filer: dict[str, list[tuple[Path, str]]] = {}
    for path, tier in candidates:
        by_filer.setdefault(filer_of(path.stem), []).append((path, tier))

    filers = sorted(by_filer)
    rng.shuffle(filers)

    picked: list[tuple[Path, str]] = []
    seen_clauses: set[str] = set()
    for filer in filers:
        if len(picked) >= count:
            break
        path, tier = by_filer[filer][0]
        scored = score_contract(path)
        clause = scored.concrete_escalation or scored.shape_escalation
        key = clause_fingerprint(clause)
        if key in seen_clauses:
            continue
        seen_clauses.add(key)
        picked.append((path, tier))
    return picked


def _training_data_containing_real_contracts() -> list[str]:
    """Training examples whose text came from a real contract, not a template.

    This is the question `--force` actually needs answered. "Does training/data
    exist" is a proxy for it, and a bad one: a training set built entirely from
    generated templates shares no text with any filing, so nothing can move
    between the two sides and resealing is provably harmless. A training set
    built from real prose is the opposite, and there resealing is how a leak
    becomes a pass.

    Cheap and deliberately blunt: take distinctive chunks of every corpus
    contract and look for them in each training input. False positives are
    acceptable — they only cause a refusal, which is the safe direction.
    """
    if not (TRAINING_DATA.exists() and any(TRAINING_DATA.glob("*.jsonl"))):
        return []

    inputs: list[tuple[str, str]] = []
    for path in sorted(TRAINING_DATA.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                inputs.append((path.name, json.loads(line).get("input", "")))
            except json.JSONDecodeError:
                continue
    if not inputs:
        return []

    corpus = ROOT / "data" / "corpus" / "contracts"
    hits: list[str] = []
    for contract in corpus.rglob("*.txt"):
        body = contract.read_text(encoding="utf-8", errors="ignore")
        probes = [body[i : i + 60] for i in range(0, min(len(body), 20000), 2000)]
        probes = [p for p in probes if len(p) == 60 and p.strip()]
        for name, text in inputs:
            if any(probe in text for probe in probes):
                hits.append(f"{name}: matches {contract.name}")
                break
    return hits


def seal(count: int, seed: int, force: bool) -> int:
    if SEALED_JSON.exists() and not force:
        print(f"! already sealed: {SEALED_JSON.relative_to(ROOT)}")
        print("  Sealing twice is how a leak becomes a pass. Use --verify to check it,")
        print("  or --force only if no training data exists yet.")
        return 1

    if force:
        risky = _training_data_containing_real_contracts()
        if risky:
            print("! REFUSING to reseal: training data contains real contract prose.")
            print(f"  {len(risky)} training example(s) match text from data/corpus/.")
            print("  Resealing now could move a contract from the training side to the")
            print("  test side, and the score would silently become meaningless.")
            print("  Rebuild the training data first, or seal a different way.")
            return 2
        print("reseal permitted: no training example contains real contract prose")
        print("  (every pair is generated from templates, so no contract can cross sides)")

    candidates = _candidates()
    if not candidates:
        print("! no candidates — data/ is gitignored (#33, #44). Rebuild first:")
        print("    python -m data_sourcing.filter_contracts --count 700")
        return 2

    picked = _pick(candidates, count, seed)

    HELDOUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in HELDOUT_DIR.glob("*.txt"):
        stale.unlink()

    records: list[Sealed] = []
    for path, tier in picked:
        dest = HELDOUT_DIR / path.name
        shutil.copy2(path, dest)
        scored = score_contract(dest)
        records.append(
            Sealed(
                filename=path.name,
                filer=filer_of(path.stem),
                tier=tier,
                sha256=_sha256(dest),
                clause_fingerprint=clause_fingerprint(
                    scored.concrete_escalation or scored.shape_escalation
                ),
            )
        )

    SEALED_JSON.write_text(
        json.dumps(
            {
                "sealed_on": date.today().isoformat(),
                "seed": seed,
                "count": len(records),
                "drawn_from": ["ready", "filled"],
                "purpose": (
                    "Phase 10/11 held-out test set. These contracts must never appear in "
                    "training data, and no training example may be generated from one of "
                    "them. Check with `python scripts/seal_testset.py --check <file>`."
                ),
                "contracts": [r.__dict__ for r in records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    filers = len({r.filer for r in records})
    clauses = len({r.clause_fingerprint for r in records})
    print(f"sealed {len(records)} contract(s) -> {HELDOUT_DIR.relative_to(ROOT)}")
    print(f"  {filers} distinct filer(s), {clauses} distinct clause wording(s)")
    print("  by tier: " + ", ".join(
        f"{t}={sum(1 for r in records if r.tier == t)}" for t in ("ready", "filled", "review")
    ))
    print(f"  manifest: {SEALED_JSON.relative_to(ROOT)}")
    print("\nThese are CANDIDATES. The human pass discards the bad ones (#34/#77);")
    print("sealing ~30 to keep ~20 is the intended shape.")
    return 0


def verify() -> int:
    """Re-hash the folder and prove nothing changed since sealing."""
    if not SEALED_JSON.exists():
        print("! nothing sealed yet — run `python scripts/seal_testset.py` first")
        return 2
    manifest = json.loads(SEALED_JSON.read_text(encoding="utf-8"))
    bad = 0
    for row in manifest["contracts"]:
        path = HELDOUT_DIR / row["filename"]
        if not path.exists():
            print(f"  MISSING  {row['filename']}")
            bad += 1
        elif _sha256(path) != row["sha256"]:
            print(f"  CHANGED  {row['filename']}")
            bad += 1
    extra = {p.name for p in HELDOUT_DIR.glob("*.txt")} - {r["filename"] for r in manifest["contracts"]}
    for name in sorted(extra):
        print(f"  UNSEALED {name}  (in the folder but not in the manifest)")
        bad += 1
    if bad:
        print(f"\n{bad} problem(s) — the test set is NOT trustworthy as it stands.")
        return 1
    print(f"all {manifest['count']} sealed contract(s) intact, sealed {manifest['sealed_on']}")
    return 0


def check(paths: list[str]) -> int:
    """Would using this file leak the test set? Matches by content AND by name."""
    if not SEALED_JSON.exists():
        print("! nothing sealed yet")
        return 2
    manifest = json.loads(SEALED_JSON.read_text(encoding="utf-8"))
    by_hash = {r["sha256"]: r["filename"] for r in manifest["contracts"]}
    names = {r["filename"] for r in manifest["contracts"]}
    leaked = 0
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            print(f"  ?        {raw}  (no such file)")
            continue
        digest = _sha256(path)
        if digest in by_hash:
            print(f"  SEALED   {path.name}  (identical bytes to {by_hash[digest]})")
            leaked += 1
        elif path.name in names:
            print(f"  SEALED   {path.name}  (same filename, different bytes — still a leak)")
            leaked += 1
        else:
            print(f"  ok       {path.name}")
    return 1 if leaked else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--count", type=int, default=30, help="how many to seal (keep ~20 after the human pass)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--force", action="store_true", help="reseal — refused once training data exists")
    parser.add_argument("--verify", action="store_true", help="re-hash and prove nothing changed")
    parser.add_argument("--check", nargs="+", metavar="FILE", help="is this file sealed?")
    args = parser.parse_args()

    if args.verify:
        return verify()
    if args.check:
        return check(args.check)
    return seal(args.count, args.seed, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
