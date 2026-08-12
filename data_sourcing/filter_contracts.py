"""[A] Keep only service/retainer contracts with real billing language. Phase 3.

ADR-013: filters on CONCRETE, UNREDACTED VALUES, not keyword presence. The plan's
`KEEP` any-one-keyword list (implementation_plan.md) gives 48.6% retention on CUAD and
1.6% usable ("gold") — see docs/progress.md "Pre-Phase-3 spike" and docs/state.json
known_issues #24. **Never add bare `escalat` to a keep-list**: 68 of its 81 CUAD matches
are the *dispute* escalation procedure ("escalate to senior management"), not a price
rise. The patterns below are the measured versions from the spike
(scripts/contract_scoring.py), folded in here as the real Phase 3 code.

`fill_document()` is folded in from scripts/fill_blanks.py per ADR-014: redacted values
are filled deterministically, never by a model, and the substitution goes into the
contract TEXT itself (not just an answer key), so extraction is never asked to read a
number that isn't on the page. `choose_value()` REFUSES when a blank's type cannot be
read with confidence — an early version guessed and silently corrupted a rate card.
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Stage 2 -- the sharp test. Measured on all 510 CUAD contracts: bare `escalat*`
# matched 81 documents, and 68 of them meant the DISPUTE escalation procedure, not a
# price rise. This is why the filter demands a real percentage or CPI reference tied
# to a fee, never a bare keyword.
# ---------------------------------------------------------------------------
REDACTION_RE = r"\[\s*\*{2,}\s*\]|\[\*+\]|\[redacted\]|\*{5,}|\[\s*\.{3,}\s*\]"

CONCRETE_ESCALATION = [
    r"(?:fee|fees|rate|rates|price|prices|payment|compensation)(?:.{0,120}?)(?:increase|escalat|adjust)(?:.{0,120}?)\d+(?:\.\d+)?\s?(?:%|percent)",
    r"(?:increase|escalat|adjust)(?:.{0,120}?)\d+(?:\.\d+)?\s?(?:%|percent)(?:.{0,120}?)(?:per year|annually|each year|per annum|anniversary)",
    r"\d+(?:\.\d+)?\s?(?:%|percent)(?:.{0,80}?)(?:increase|escalat)(?:.{0,80}?)(?:per year|annually|each year|per annum|anniversary)",
    r"(?:fee|price|rate)(?:.{0,120}?)(?:increase|adjust)(?:.{0,120}?)consumer price index",
]

CONCRETE_RECURRING = [
    r"\$\s?[\d,]{3,}(?:\.\d{2})?\s*(?:per|/|each)\s*(?:month|year|annum|quarter)",
    r"(?:monthly|annual|quarterly)\s+(?:fee|retainer|payment|charge|rate)[^.]{0,80}?\$\s?[\d,]{3,}",
    r"\$\s?[\d,]{3,}(?:\.\d{2})?[^.]{0,60}?(?:per month|monthly|per annum|annually|per year)",
    r"retainer[^.]{0,100}?\$\s?[\d,]{3,}",
]

# ---------------------------------------------------------------------------
# TEMPLATE tier -- right shape, missing numbers. Looks for the LANGUAGE of a rule
# without requiring the figure, so a redacted or unfiled-exhibit contract still
# qualifies as fill-in-the-blank material.
# ---------------------------------------------------------------------------
SHAPE_RECURRING = [
    r"(?:monthly|annual|quarterly)\s+(?:fee|fees|retainer|payment|charge|rate)",
    r"\bretainer\b",
    r"payable (?:monthly|quarterly|annually)",
    r"(?:fee|fees)(?:.{0,60}?)(?:per month|per annum|per year|each month)",
    r"(?:fees|compensation|amounts)(?:.{0,60}?)set forth in (?:exhibit|schedule|appendix|annex)",
]

SHAPE_ESCALATION = [
    r"(?:fee|fees|rate|rates|price|prices|compensation)(?:.{0,120}?)(?:shall|will|may) (?:be )?(?:increase|escalat|adjust)",
    r"(?:increase|escalat|adjust)(?:.{0,100}?)(?:annually|each year|per annum|anniversary|calendar year)",
    r"(?:annual|yearly)(?:.{0,40}?)(?:price|fee|rate)(?:.{0,40}?)(?:increase|adjustment|escalation)",
    r"consumer price index|\bcpi\b",
    r"price (?:increase|escalation|adjustment)",
]

# ---------------------------------------------------------------------------
# Duplicate detection. Measured on the 288-document EDGAR probe run: 51 documents
# scored GOLD but carried only 21 distinct escalation clauses, because one
# administrator sends every fund trust the same fee letter. Counting documents
# overstates the corpus ~2.5x. Dedupe on the CLAUSE, not the filename, and cap one
# document per filer.
# ---------------------------------------------------------------------------
# Order matters: bracketed forms must be tried before bare `***`, or a marker like
# `[…***…]` gets partially matched and the substitution leaves `[…5…]` behind.
BLANK_RE = re.compile(
    r"\[\s*[.…]*\s*\*+\s*[.…]*\s*\]"  # [***]  [*]  […***…]  [..**..]
    r"|\[\s*redacted\s*\]"
    r"|\[\s*\.{3,}\s*\]"
    r"|\*{3,}",  # bare **** (last resort)
    re.I,
)

MAX_FILLABLE_BLANKS = 4  # beyond this the whole rate card is gone; not worth faking

# Plausible values, chosen to look like real B2B service terms rather than round demo
# numbers. The engine must handle awkward arithmetic, so 7.5% earns its place.
ESCALATION_PCTS = [3.0, 3.5, 4.0, 5.0, 5.0, 6.0, 7.5, 8.0]
MONTHLY_FEES = [2500, 3500, 4000, 5000, 6000, 7500, 8500, 12000]
ANNUAL_FEES = [30000, 42000, 48000, 60000, 75000, 90000, 120000]
GENERIC_COUNTS = [2, 3, 5, 10, 12]


def _normalise(text: str) -> str:
    """Lowercased, whitespace-collapsed. All patterns assume this shape."""
    return re.sub(r"\s+", " ", text).lower()


def _first(patterns: list[str], flat: str, pad: int = 110) -> str | None:
    for pat in patterns:
        m = re.search(pat, flat)
        if m:
            return flat[max(0, m.start() - pad) : m.end() + pad].strip()
    return None


@dataclass
class ScoredContract:
    """Source-agnostic score for one contract, read fresh from disk each call so
    filter_service_contracts() and deduplicate() never need a metadata sidecar."""

    path: Path
    redacted: bool
    concrete_escalation: str | None
    concrete_recurring: str | None
    shape_escalation: str | None
    shape_recurring: str | None

    @property
    def is_gold(self) -> bool:
        """Buildable as-is: both values present and unredacted."""
        return bool(self.concrete_escalation and self.concrete_recurring)

    @property
    def is_template(self) -> bool:
        """Right clause shapes, but at least one number is missing or redacted --
        the fill-in-the-blank pool: keep the real prose, supply the figures."""
        if self.is_gold:
            return False
        return bool(self.shape_recurring and self.shape_escalation)

    @property
    def tier(self) -> str:
        if self.is_gold:
            return "gold"
        if self.is_template:
            return "template"
        return "reject"


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        import pymupdf

        with pymupdf.open(path) as doc:
            return "\f".join(page.get_text() for page in doc)
    return path.read_text(encoding="utf-8", errors="ignore")


def score_contract(path: Path) -> ScoredContract:
    """Score one contract file. Reads the file; everything else is pure."""
    flat = _normalise(_read_text(path))
    return ScoredContract(
        path=path,
        redacted=bool(re.search(REDACTION_RE, flat)),
        concrete_escalation=_first(CONCRETE_ESCALATION, flat),
        concrete_recurring=_first(CONCRETE_RECURRING, flat),
        shape_escalation=_first(SHAPE_ESCALATION, flat),
        shape_recurring=_first(SHAPE_RECURRING, flat),
    )


def filter_service_contracts(paths: list[Path]) -> list[Path]:
    """Keep gold (usable as-is) and template (fill-in-the-blank) tier only.
    Expect roughly 15-25% retention on EDGAR's EX-10/EX-99 search results, far above
    CUAD's 1.6% gold rate -- see ADR-013."""
    return [p for p in paths if score_contract(p).tier in ("gold", "template")]


def filer_of(name: str) -> str:
    """Company portion of a fetch_contracts filename (everything before the exhibit tag)."""
    return name.rsplit("_EX", 1)[0]


def clause_fingerprint(clause: str | None) -> str:
    """Stable id for a clause, ignoring punctuation, spacing and digits.

    Digits are stripped deliberately: two fee letters that differ only in the dollar
    amount are the same clause for training purposes.
    """
    s = re.sub(r"[^a-z ]", " ", (clause or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    return hashlib.md5(s[:150].encode()).hexdigest()[:8]


def deduplicate(paths: list[Path]) -> list[Path]:
    """One document per filer AND per distinct clause fingerprint, gold before
    template. Counting documents overstates the corpus ~2.5x -- see module docstring."""
    scored = sorted((score_contract(p) for p in paths), key=lambda s: s.tier != "gold")
    seen_filers: set[str] = set()
    seen_clauses: set[str] = set()
    kept: list[Path] = []
    for s in scored:
        clause = s.concrete_escalation if s.is_gold else s.shape_escalation
        key, filer = clause_fingerprint(clause), filer_of(s.path.stem)
        if key in seen_clauses or filer in seen_filers:
            continue
        seen_clauses.add(key)
        seen_filers.add(filer)
        kept.append(s.path)
    return kept


def count_blanks(*clauses: str | None) -> int:
    """Redaction markers inside the clauses we actually extract from. A contract can
    carry thousands of `****` markers in pricing tables we never read and still be
    perfectly usable."""
    return len(BLANK_RE.findall(" ".join(c or "" for c in clauses)))


def choose_value(before: str, after: str, rng: random.Random) -> tuple[str, str, float] | None:
    """Pick a replacement from the words either side of the blank.

    Returns (rendered_text, kind, numeric_value), or **None when the blank's type
    cannot be read with confidence** -- in which case it is left redacted. Refusing is
    the whole point (ADR-014): a wrong value poisons ground truth invisibly, and we
    only need a handful of usable documents, so precision costs nothing.

    Confident cases only:
        money    a '$' immediately precedes the blank
        percent  a '%' or the word 'percent' immediately follows
        count    'month(s)'/'day(s)' immediately follows AND a duration verb precedes
    """
    tail = before[-70:].lower()
    head = after[:40].lower()

    if re.search(r"\$\s*$", before):
        annual = bool(re.search(r"per annum|annually|per year|annual fee", tail + head))
        amount = rng.choice(ANNUAL_FEES if annual else MONTHLY_FEES)
        return f"{amount:,}", "money", float(amount)

    if re.match(r"\s*(?:%|percent\b)", head):
        pct = rng.choice(ESCALATION_PCTS)
        return f"{pct:g}", "percent", pct

    if re.match(r"\s*(?:month|day|year)s?\b", head) and re.search(
        r"(?:first|initial|any|each|every|within|period of|for)\s*(?:the\s*)?$", tail
    ):
        n = rng.choice(GENERIC_COUNTS)
        return str(n), "count", float(n)

    return None  # not confident -- leave the redaction in place


def fill_document(text: str, row: dict, rng: random.Random) -> tuple[str, list[dict]]:
    """Substitute redacted values INTO the contract text, deterministically, recording
    each as ground truth by construction (ADR-014). Blanks outside the target clauses
    are left redacted on purpose -- a real contract with a confidential pricing table
    elsewhere is still a valid extraction input.

    `row` needs `shape_recurring` and `shape_escalation` (snippets, as produced by
    `ScoredContract` / `score_contract`). Returns (new_text, insertions); an empty
    `insertions` list means no blank was confidently readable.
    """
    targets = [c for c in (row.get("shape_recurring"), row.get("shape_escalation")) if c]
    inserted: list[dict] = []
    flat = re.sub(r"\s+", " ", text)

    for clause in targets:
        anchor = re.sub(r"\s+", " ", clause).strip()[:60]
        idx = flat.lower().find(anchor.lower())
        if idx == -1:
            continue
        window_start, window_end = idx, idx + max(len(anchor), len(clause)) + 200
        window = flat[window_start:window_end]

        def _sub(m: re.Match) -> str:
            chosen = choose_value(window[: m.start()], window[m.end() :], rng)
            if chosen is None:
                return m.group(0)  # leave the redaction exactly as filed
            value, kind, numeric = chosen
            inserted.append(
                {
                    "kind": kind,
                    "value": numeric,
                    "rendered": value,
                    "marker": m.group(0),
                    "context": window[max(0, m.start() - 60) : m.end() + 60].strip(),
                }
            )
            return value

        new_window = BLANK_RE.sub(_sub, window)
        flat = flat[:window_start] + new_window + flat[window_end:]

    # Second pass, document-wide but deliberately narrow: a redacted amount that is
    # explicitly periodic ("$[***] per month"). A window around one clause can leave a
    # second, separately-stated price redacted; tier tables are NOT caught here because
    # "< $ **** **** $ ****" has no period word after each cell.
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


# ---------------------------------------------------------------------------
# Orchestration -- assembles the corpus Phase 3's definition of done requires:
# data/corpus/contracts/ with 30+ real filtered contracts, ready + filled + review.
# ---------------------------------------------------------------------------

OUT_DIR = Path("data/corpus/contracts")
READY_DIR = OUT_DIR / "ready"
FILLED_DIR = OUT_DIR / "filled"
REVIEW_DIR = OUT_DIR / "review"


def build_corpus(paths: list[Path], seed: int = 20260810) -> dict:
    """filter -> deduplicate -> classify -> fill. Writes ready/filled/review buckets
    plus ground_truth_fills.json and MANIFEST.md into data/corpus/contracts/.
    Returns the bucket counts."""
    import json
    import shutil

    kept = deduplicate(filter_service_contracts(paths))
    rng = random.Random(seed)

    for d in (READY_DIR, FILLED_DIR, REVIEW_DIR):
        d.mkdir(parents=True, exist_ok=True)
        for f in d.iterdir():
            f.unlink()

    buckets: dict[str, list[Path]] = {"ready": [], "filled": [], "review": []}
    fills: list[dict] = []

    for path in kept:
        s = score_contract(path)
        text = _read_text(path)
        if s.is_gold:
            buckets["ready"].append(path)
            (READY_DIR / f"{path.stem}.txt").write_text(text, encoding="utf-8")
            continue

        row = {"shape_recurring": s.shape_recurring, "shape_escalation": s.shape_escalation}
        n_blanks = count_blanks(s.shape_recurring, s.shape_escalation)
        if 0 < n_blanks <= MAX_FILLABLE_BLANKS:
            new_text, inserted = fill_document(text, row, rng)
            if inserted:
                buckets["filled"].append(path)
                (FILLED_DIR / f"{path.stem}.txt").write_text(new_text, encoding="utf-8")
                fills.append({"contract": path.stem, "source": str(path), "insertions": inserted})
                continue
        buckets["review"].append(path)
        (REVIEW_DIR / f"{path.stem}.txt").write_text(text, encoding="utf-8")

    (OUT_DIR / "ground_truth_fills.json").write_text(
        json.dumps(
            {
                "seed": seed,
                "note": "Values inserted by data_sourcing/filter_contracts.py:fill_document. "
                "Each is ground truth by construction -- no model chose them (ADR-014).",
                "contracts": fills,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    counts = {k: len(v) for k, v in buckets.items()}
    _write_manifest(counts, fills, buckets["review"])
    return counts


def _write_manifest(counts: dict[str, int], fills: list[dict], review: list[Path]) -> None:
    total = sum(counts.values())
    lines = [
        "# Contract corpus — Phase 3 (ADR-013, ADR-014)",
        "",
        f"**{total} distinct contracts**, deduplicated one per filer and one per distinct",
        "clause wording. Built by data_sourcing/filter_contracts.py:build_corpus from",
        "SEC EDGAR EX-10/EX-99 exhibits fetched by data_sourcing/fetch_contracts.py.",
        "",
        "| Bucket | Count | What it means |",
        "|---|---:|---|",
        f"| `ready/` | {counts['ready']} | Real amount and real escalation already present. Use as-is. |",
        f"| `filled/` | {counts['filled']} | 1-4 redacted values replaced deterministically. Answer key in `ground_truth_fills.json`. |",
        f"| `review/` | {counts['review']} | Clause wording is right but no figure found -- the amount may live in an exhibit that was never filed. **Human check needed.** |",
        "",
        "## The inserted values are ground truth",
        "",
        "Every number in `filled/` was chosen by seeded Python, written into the contract",
        "text, and recorded in `ground_truth_fills.json` as it was written. No model chose",
        "any of them (ADR-011, ADR-014). Re-running with the same seed reproduces the same",
        "corpus exactly.",
        "",
        "## What still needs a human",
        "",
        f"Only `review/` ({counts['review']} contracts). For each, find the recurring fee amount.",
        "If it is genuinely absent -- 'as set forth in Exhibit B', never filed -- the",
        "contract is not usable for a scenario; leave it in review/ as a documented gap.",
        "",
    ]
    if fills:
        lines += ["## Contracts with inserted values", "", "| Contract | Inserted |", "|---|---|"]
        for f in fills:
            vals = ", ".join(
                f"{i['rendered']}{'%' if i['kind'] == 'percent' else ''}" for i in f["insertions"]
            )
            lines.append(f"| `{f['contract'][:60]}` | {vals} |")
    if review:
        lines += ["", "## Review list", "", "| Contract |", "|---|"]
        for p in review:
            lines.append(f"| `{p.stem[:70]}` |")
    (OUT_DIR / "MANIFEST.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    """python -m data_sourcing.filter_contracts [--count N] -- fetch + filter + fill."""
    import argparse

    from data_sourcing.fetch_contracts import fetch_edgar_msa

    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=260, help="EDGAR exhibits to fetch")
    ap.add_argument("--seed", type=int, default=20260810)
    args = ap.parse_args()

    print(f"[1/2] Fetching up to {args.count} EDGAR contract exhibits")
    raw = fetch_edgar_msa(count=args.count)
    print(f"      {len(raw)} exhibits on disk")

    print("[2/2] Filtering, deduplicating, filling")
    counts = build_corpus(raw, seed=args.seed)
    total = sum(counts.values())
    print(f"      corpus: {total} distinct contracts -> {OUT_DIR}")
    for bucket, n in counts.items():
        print(f"        {bucket:<8} {n}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
