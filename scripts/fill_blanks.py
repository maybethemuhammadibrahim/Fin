"""Phase 3 de-risk spike, part 3 — assemble the corpus and fill redacted values.

NOT a Phase 3 deliverable. Consumes scripts/edgar_probe.py output and produces
the contract corpus Phase 3's scenario_builder.py will work from.

WHY THE NUMBERS ARE INSERTED BY PYTHON AND NEVER BY A MODEL
-----------------------------------------------------------
A redacted contract says "fees shall increase by [***] percent per annum". The
prose is real; only the figure was withheld under SEC confidential treatment.
We supply the figure.

If a language model picked it, we would have to READ its output to learn what it
chose, then record that as the answer key -- a verification step we do not need.
When Python picks it, the inserted value IS the ground truth, known by
construction, recorded as it is written. Same principle as ADR-007: contracts are
sourced, numbers are derived by arithmetic. It is also what ADR-011 requires --
no vendor API call anywhere.

THE ONE RULE THAT MATTERS
-------------------------
The value is substituted INTO THE CONTRACT TEXT, not just into the answer key.
If the document still said [***] while ground truth claimed 5%, we would be
training the model to invent a number that is not in front of it -- precisely
the behaviour the architecture exists to prevent (rule 1: the LLM never produces
a number the user sees).

Buckets written to corpus/:
    ready/     numbers already present -- untouched originals
    filled/    1-4 values inserted by this script, recorded in ground_truth_fills.json
    review/    clause shapes present but no figure found -- a human must look
    skipped/   whole pricing table redacted -- not worth reconstructing

Usage:
    python scripts/fill_blanks.py             # build the corpus
    python scripts/fill_blanks.py --seed 7    # different but reproducible values
    python scripts/fill_blanks.py --dry-run   # report only, write nothing
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract_scoring import (  # noqa: E402
    BLANK_RE,
    clause_fingerprint,
    count_blanks,
    filer_of,
)

ROOT = Path(__file__).resolve().parent.parent
EDGAR_DIR = ROOT / "data" / "corpus" / "edgar_probe"
CUAD_DIR = ROOT / "data" / "corpus" / "cuad_probe"
OUT_DIR = ROOT / "data" / "corpus" / "contracts_v0"

READY_DIR = OUT_DIR / "ready"
FILLED_DIR = OUT_DIR / "filled"
REVIEW_DIR = OUT_DIR / "review"
SKIPPED_DIR = OUT_DIR / "skipped"

MAX_FILLABLE_BLANKS = 4  # beyond this the whole rate card is gone; not worth faking

# Plausible values, chosen to look like real B2B service terms rather than round
# demo numbers. The engine must handle awkward arithmetic, so 7.5% earns its place.
ESCALATION_PCTS = [3.0, 3.5, 4.0, 5.0, 5.0, 6.0, 7.5, 8.0]
MONTHLY_FEES = [2500, 3500, 4000, 5000, 6000, 7500, 8500, 12000]
ANNUAL_FEES = [30000, 42000, 48000, 60000, 75000, 90000, 120000]
GENERIC_COUNTS = [2, 3, 5, 10, 12]


def load_edgar() -> list[dict]:
    path = EDGAR_DIR / "results.json"
    if not path.exists():
        print(f"! {path} missing — run scripts/edgar_probe.py first")
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def build_corpus(rows: list[dict]) -> list[dict]:
    """One document per filer AND per distinct clause, gold before template."""
    gold = [r for r in rows if r["concrete_escalation"] and r["concrete_recurring"]]
    tpl = [
        r for r in rows
        if r["shape_recurring"] and r["shape_escalation"] and r not in gold
    ]
    seen_filers: set[str] = set()
    seen_clauses: set[str] = set()
    corpus: list[dict] = []
    for r in gold + tpl:
        r = dict(r)
        r["_is_gold"] = r in gold or bool(
            r["concrete_escalation"] and r["concrete_recurring"]
        )
        clause = r["concrete_escalation"] if r["_is_gold"] else r["shape_escalation"]
        key, filer = clause_fingerprint(clause), filer_of(r["name"])
        if key in seen_clauses or filer in seen_filers:
            continue
        seen_clauses.add(key)
        seen_filers.add(filer)
        corpus.append(r)
    return corpus


def classify(row: dict) -> str:
    if row["_is_gold"]:
        return "ready"
    n = count_blanks(row["shape_recurring"], row["shape_escalation"])
    if n == 0:
        return "review"
    if n <= MAX_FILLABLE_BLANKS:
        return "filled"
    return "skipped"


def choose_value(
    before: str, after: str, rng: random.Random
) -> tuple[str, str, float] | None:
    """Pick a replacement from the words either side of the blank.

    Returns (rendered_text, kind, numeric_value), or **None when the blank's type
    cannot be read with confidence** -- in which case it is left redacted.

    Refusing is the whole point. An early version guessed at every blank and
    filled a Vantiv rate card ("Card Activation Monthly Fee ****") with counts
    like 5 and 12, silently corrupting a fee schedule. We need ~6 usable
    documents out of 44, so precision costs us nothing and a wrong value poisons
    ground truth invisibly.

    Confident cases only:
        money    a '$' immediately precedes the blank
        percent  a '%' or the word 'percent' immediately follows
        count    'month(s)'/'day(s)' immediately follows AND a duration verb
                 precedes -- i.e. "during the first [**] months"
    """
    tail = before[-70:].lower()
    head = after[:40].lower()

    # "$ ****" / "$[***]" -> money. The surrounding period picks the magnitude.
    if re.search(r"\$\s*$", before):
        annual = bool(re.search(r"per annum|annually|per year|annual fee", tail + head))
        amount = rng.choice(ANNUAL_FEES if annual else MONTHLY_FEES)
        return f"{amount:,}", "money", float(amount)

    # "****%" / "**** percent" -> a percentage.
    if re.match(r"\s*(?:%|percent\b)", head):
        pct = rng.choice(ESCALATION_PCTS)
        return f"{pct:g}", "percent", pct

    # "during the first [**] months" -> a duration.
    if re.match(r"\s*(?:month|day|year)s?\b", head) and re.search(
        r"(?:first|initial|any|each|every|within|period of|for)\s*(?:the\s*)?$", tail
    ):
        n = rng.choice(GENERIC_COUNTS)
        return str(n), "count", float(n)

    return None  # not confident -- leave the redaction in place


def fill_document(text: str, row: dict, rng: random.Random) -> tuple[str, list[dict]]:
    """Substitute blanks that fall inside the target clauses only.

    Blanks elsewhere in the document are left redacted on purpose -- a real
    contract with confidential pricing tables is still a valid extraction input,
    and reconstructing a whole rate card would be inventing a document.
    """
    targets = [c for c in (row["shape_recurring"], row["shape_escalation"]) if c]
    inserted: list[dict] = []
    flat = re.sub(r"\s+", " ", text)

    for clause in targets:
        # Locate the clause in the real text via a distinctive anchor, since the
        # stored snippet is whitespace-normalised and lowercased.
        anchor = re.sub(r"\s+", " ", clause).strip()[:60]
        idx = flat.lower().find(anchor.lower())
        if idx == -1:
            continue
        window_start, window_end = idx, idx + max(len(anchor), len(clause)) + 200
        window = flat[window_start:window_end]

        def _sub(m: re.Match) -> str:
            chosen = choose_value(window[: m.start()], window[m.end():], rng)
            if chosen is None:
                return m.group(0)  # leave the redaction exactly as filed
            value, kind, numeric = chosen
            inserted.append(
                {
                    "kind": kind,
                    "value": numeric,
                    "rendered": value,
                    "marker": m.group(0),
                    "context": window[max(0, m.start() - 60):m.end() + 60].strip(),
                }
            )
            return value

        new_window = BLANK_RE.sub(_sub, window)
        flat = flat[:window_start] + new_window + flat[window_end:]

    # Second pass, document-wide but deliberately narrow: a redacted amount that
    # is explicitly periodic ("$[***] per month"). Genomatica prices two services
    # in separate sentences, so a window around one clause leaves the other
    # redacted -- a contract quoting $3,500/month for one service and [***] for
    # the other is internally inconsistent and would confuse extraction.
    #
    # Tier tables are NOT caught here: "< $ **** **** $ ****" has no period word
    # after each cell, so Vantiv's rate card stays untouched.
    if inserted:
        def _sub_periodic(m: re.Match) -> str:
            annual = bool(re.search(r"annum|annually|year", m.group("period"), re.I))
            amount = rng.choice(ANNUAL_FEES if annual else MONTHLY_FEES)
            inserted.append(
                {
                    "kind": "money",
                    "value": float(amount),
                    "rendered": f"{amount:,}",
                    "marker": m.group("blank"),
                    "context": m.group(0).strip(),
                    "pass": "periodic",
                }
            )
            return f"${amount:,}{m.group('gap')}{m.group('period')}"

        flat = re.sub(
            r"\$\s*(?P<blank>" + BLANK_RE.pattern + r")"
            r"(?P<gap>[^.$]{0,25}?)"
            r"(?P<period>per\s+month|per\s+annum|per\s+year|monthly|annually)",
            _sub_periodic,
            flat,
            flags=re.I,
        )

    return flat, inserted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260810, help="reproducible values")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = load_edgar()
    if not rows:
        return 1

    corpus = build_corpus(rows)
    rng = random.Random(args.seed)

    if not args.dry_run:
        for d in (READY_DIR, FILLED_DIR, REVIEW_DIR, SKIPPED_DIR):
            d.mkdir(parents=True, exist_ok=True)
            for f in d.iterdir():
                f.unlink()

    buckets: dict[str, list[dict]] = {"ready": [], "filled": [], "review": [], "skipped": []}
    fills: list[dict] = []

    for row in corpus:
        bucket = classify(row)
        src = EDGAR_DIR / "text" / f"{row['name']}.txt"
        if not src.exists():
            continue
        buckets[bucket].append(row)
        if args.dry_run:
            continue

        text = src.read_text(encoding="utf-8", errors="ignore")
        if bucket == "filled":
            text, inserted = fill_document(text, row, rng)
            if not inserted:  # anchor missed; nothing was changed
                buckets["filled"].remove(row)
                buckets["review"].append(row)
                (REVIEW_DIR / f"{row['name']}.txt").write_text(text, encoding="utf-8")
                continue
            fills.append(
                {
                    "contract": row["name"],
                    "source": row["origin"],
                    "insertions": inserted,
                }
            )
            (FILLED_DIR / f"{row['name']}.txt").write_text(text, encoding="utf-8")
        else:
            target = {"ready": READY_DIR, "review": REVIEW_DIR, "skipped": SKIPPED_DIR}[bucket]
            shutil.copy2(src, target / f"{row['name']}.txt")

    if not args.dry_run:
        (OUT_DIR / "ground_truth_fills.json").write_text(
            json.dumps(
                {
                    "seed": args.seed,
                    "note": "Values inserted by scripts/fill_blanks.py. Each is "
                            "ground truth by construction — no model chose them.",
                    "contracts": fills,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        write_manifest(buckets, fills)

    total = sum(len(v) for v in buckets.values())
    print("=" * 66)
    print(f"  corpus (1 per filer, 1 per clause)   {total}")
    print(f"    ready    numbers already present   {len(buckets['ready'])}")
    print(f"    filled   values inserted by script {len(buckets['filled'])}")
    print(f"    review   needs a human look        {len(buckets['review'])}")
    print(f"    skipped  rate card fully redacted  {len(buckets['skipped'])}")
    print(f"  values inserted                      {sum(len(f['insertions']) for f in fills)}")
    print("=" * 66)
    if not args.dry_run:
        print(f"\n  Corpus:       {OUT_DIR}")
        print(f"  Answer key:   {OUT_DIR / 'ground_truth_fills.json'}")
        print(f"  What to read: {OUT_DIR / 'MANIFEST.md'}\n")
    return 0


def write_manifest(buckets: dict[str, list[dict]], fills: list[dict]) -> None:
    total = sum(len(v) for v in buckets.values())
    lines = [
        "# Contract corpus v0 — Phase 3 input",
        "",
        f"**{total} distinct contracts**, deduplicated one per filer and one per",
        "distinct clause wording. Built by `scripts/fill_blanks.py` from the EDGAR probe.",
        "",
        "| Bucket | Count | What it means |",
        "|---|---:|---|",
        f"| `ready/` | {len(buckets['ready'])} | Real amount and real escalation already present. Use as-is. |",
        f"| `filled/` | {len(buckets['filled'])} | 1–4 redacted values replaced by this script. Answer key in `ground_truth_fills.json`. |",
        f"| `review/` | {len(buckets['review'])} | Clause wording is right but no figure found — the amount may live in an exhibit that was never filed. **Human check needed.** |",
        f"| `skipped/` | {len(buckets['skipped'])} | Entire rate card redacted. Not worth reconstructing. |",
        "",
        "## The inserted values are ground truth",
        "",
        "Every number in `filled/` was chosen by seeded Python, written into the",
        "contract text, and recorded in `ground_truth_fills.json` as it was written.",
        "No model chose any of them, so nothing needs verifying (ADR-011, ADR-014).",
        "",
        f"Seed is fixed, so re-running reproduces the same corpus exactly.",
        "",
        "## What still needs a human",
        "",
        f"Only `review/` ({len(buckets['review'])} contracts). For each, find the recurring fee",
        "amount. If it is genuinely absent — 'as set forth in Exhibit B', and Exhibit B",
        "was never filed — move it to `skipped/`. Expect to lose roughly a quarter.",
        "",
        "## Contracts with inserted values",
        "",
        "| Contract | Inserted |",
        "|---|---|",
    ]
    for f in fills:
        vals = ", ".join(
            f"{i['rendered']}{'%' if i['kind'] == 'percent' else ''}" for i in f["insertions"]
        )
        lines.append(f"| `{f['contract'][:60]}` | {vals} |")

    lines += ["", "## Review list", "", "| Contract |", "|---|"]
    for r in buckets["review"]:
        lines.append(f"| `{r['name'][:70]}` |")

    (OUT_DIR / "MANIFEST.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
