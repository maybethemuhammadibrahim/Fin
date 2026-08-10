"""Phase 3 de-risk spike — does CUAD actually contain FinSight-shaped billing rules?

NOT a Phase 3 deliverable. This is a throwaway probe that answers one question
before any Phase 3 code gets written (Risk R1 in implementation_plan.md):

    The plan's filter keeps a contract if it matches ANY ONE keyword. A merger
    agreement that says "discount" once survives that. So retention can look
    healthy (15-25%) while the number of contracts carrying a FULL billing rule
    set -- recurring fee + escalation -- is near zero. If nothing has an
    escalation clause, `forgotten_raise` has nothing to stand on.

Measured answer on all 510 CUAD contracts:
    248 (48.6%) pass the plan's ANY-keyword filter        <- looks healthy
      8  (1.6%) have a real amount AND a real escalation  <- the truth
      3          survive being read by hand

Two traps that number hides, both quantified in VERDICT.md:
    1. bare `escalat*` matches 81 docs, but 68 mean the DISPUTE escalation
       procedure ("escalate to senior management"), not a price rise.
    2. 121 docs (23.7%) redact financials with [***] -- perfect clause, no number.

Scoring lives in scripts/contract_scoring.py, shared with edgar_probe.py so both
sources are judged identically.

Usage:
    python scripts/cuad_probe.py              # full run
    python scripts/cuad_probe.py --limit 40   # quick smoke test
    python scripts/cuad_probe.py --min-cats 3 # stage-1 survivor bar (default 3)

Output lands in data/corpus/cuad_probe/ (gitignored). Read VERDICT.md first.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from pathlib import Path

import pymupdf
from huggingface_hub import snapshot_download

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract_scoring import (  # noqa: E402
    CATEGORIES,
    ContractResult,
    scan_text,
    summarise,
)

REPO_ID = "theatticusproject/cuad"
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "corpus" / "cuad_probe"
RAW_DIR = OUT_DIR / "raw"
TEXT_DIR = OUT_DIR / "text"
SURVIVOR_DIR = OUT_DIR / "survivors"
EVIDENCE_DIR = OUT_DIR / "evidence"
GOLD_DIR = OUT_DIR / "gold"
TEMPLATE_DIR = OUT_DIR / "templates"

#: Maps a result name back to its source PDF, so buckets can copy real files.
_PDF_BY_NAME: dict[str, Path] = {}


def download_cuad(limit: int | None) -> list[Path]:
    """Pull the CUAD PDF corpus. Public dataset -- HF_TOKEN is not required."""
    print(f"[1/4] Downloading {REPO_ID} PDFs -> {RAW_DIR} (~100 MB, cached after first run)")
    local = snapshot_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        local_dir=RAW_DIR,
        allow_patterns=["CUAD_v1/full_contract_pdf/**", "CUAD_v1/master_clauses.csv"],
    )
    pdfs = sorted(
        p for p in Path(local).rglob("*")
        if p.suffix.lower() == ".pdf" and "full_contract_pdf" in str(p)
    )
    print(f"      {len(pdfs)} PDFs on disk")
    return pdfs[:limit] if limit else pdfs


def extract_text(pdf: Path) -> tuple[str, int]:
    """Text + page count. Returns ('', 0) on an unreadable file rather than raising."""
    cache = TEXT_DIR / f"{pdf.stem}.txt"
    if cache.exists():
        text = cache.read_text(encoding="utf-8", errors="ignore")
        return text, text.count("\f") + 1
    try:
        with pymupdf.open(pdf) as doc:
            pages = [page.get_text() for page in doc]
    except Exception as exc:  # a handful of CUAD PDFs are malformed
        print(f"      ! unreadable: {pdf.name} ({type(exc).__name__})")
        return "", 0
    text = "\f".join(pages)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text, len(pages)


def write_evidence(res: ContractResult) -> None:
    pdf = _PDF_BY_NAME.get(res.name)
    lines = [
        f"# {res.name}",
        "",
        f"- CUAD folder: `{res.origin}`",
        f"- Source PDF: `{pdf}`",
        f"- {res.n_pages} pages, {res.n_chars:,} chars",
        f"- Tier: **{res.tier}**",
        f"- Categories matched ({res.score}/5): **{', '.join(sorted(res.categories)) or 'none'}**",
        f"- Recurring fee + escalation: **{'YES' if res.has_core_pair else 'no'}**",
        f"- Financials redacted: **{'YES' if res.redacted else 'no'}**",
        "",
        "## Verify by hand",
        "",
        "Read the snippets below. For each, ask: *is this a real billing rule I could",
        "build an expected timeline from, or an incidental use of the word?*",
        "",
    ]
    for cat in CATEGORIES:
        hits = [h for h in res.hits if h.category == cat]
        lines.append(f"### {cat} — {len(hits)} match(es)")
        lines.append(f"*{CATEGORIES[cat][0]}*")
        lines.append("")
        if not hits:
            lines.append("_no match_\n")
            continue
        for h in hits:
            lines.append(f"- **p.{h.page}** …{h.snippet}…")
        lines.append("")
    (EVIDENCE_DIR / f"{res.name}.md").write_text("\n".join(lines), encoding="utf-8")


def write_verdict(results: list[ContractResult]) -> Path:
    """The file to read first -- it answers the go/no-go question."""
    s = summarise(results)
    total = s["total"] or 1
    gold = sorted((r for r in results if r.is_gold), key=lambda r: r.name)
    templates = sorted((r for r in results if r.is_template), key=lambda r: r.name)
    bare_esc = [r for r in results if "escalation" in r.categories]
    false_friends = [r for r in bare_esc if not r.concrete_escalation]

    def pct(n: int) -> str:
        return f"{n / total * 100:.1f}%"

    lines = [
        "# VERDICT — can CUAD carry FinSight's four leak types?",
        "",
        "Stage 1 (`REPORT.md`) applies a generous five-category keyword filter.",
        "Stage 2, below, demands **concrete unredacted values** — the only thing",
        "`scenario_builder.py` can actually derive a ledger from.",
        "",
        "## Two traps stage 1 hides",
        "",
        f"**1. `escalat*` is a false friend.** {len(bare_esc)} contracts match it, but "
        f"**{len(false_friends)}** of them mean the *dispute* escalation procedure "
        '("escalate to senior management"), not a price rise. Any filter containing bare '
        "`escalat` will silently import them as forgotten_raise candidates.",
        "",
        f"**2. CUAD redacts financials.** {s['redacted']} contracts ({pct(s['redacted'])}) "
        "contain `[***]` where a rate or amount should be — they are EDGAR exhibits filed "
        "with confidential treatment. A contract can have a perfect escalation clause and "
        "still be unusable because the percentage itself is redacted.",
        "",
        "## The numbers that decide the phase",
        "",
        "| Measure | Count | Share |",
        "|---|---:|---:|",
        f"| Plan's ANY-keyword filter | {s['plan_filter']} | {pct(s['plan_filter'])} |",
        f"| Concrete recurring amount (real `$X per month/year`) | {s['concrete_fee']} | {pct(s['concrete_fee'])} |",
        f"| Concrete escalation (real `N%` or CPI tied to a fee) | {s['concrete_esc']} | {pct(s['concrete_esc'])} |",
        f"| **GOLD — buildable as-is** | **{s['gold']}** | **{pct(s['gold'])}** |",
        f"| **TEMPLATE — right shape, numbers missing** | **{s['template']}** | **{pct(s['template'])}** |",
        "",
        f"## GOLD ({len(gold)}) — read these by hand",
        "",
        "PDFs are copied into `gold/`. Each entry shows the two clauses that matched.",
        "",
    ]
    for r in gold:
        lines += [
            f"### {r.name}",
            f"- CUAD folder: `{r.origin}` · {r.n_pages} pages · redacted: "
            f"{'YES' if r.redacted else 'no'}",
            f"- **recurring:** …{r.concrete_recurring}…",
            f"- **escalation:** …{r.concrete_escalation}…",
            "",
        ]
    lines += [
        f"## TEMPLATE ({len(templates)}) — fill-in-the-blank pool",
        "",
        "Real lawyer-written prose with the right clause shapes, but the figures are",
        "redacted or live in an exhibit that was never filed. Write dummy numbers over",
        "these and the *tested on genuine legal prose* claim survives. PDFs in `templates/`.",
        "",
        "| Contract | Redacted | Recurring shape |",
        "|---|:---:|---|",
    ]
    for r in templates[:80]:
        shape = (r.shape_recurring or "")[:110].replace("|", "/")
        lines.append(f"| `{r.name[:55]}` | {'yes' if r.redacted else 'no'} | …{shape}… |")

    lines += [
        "",
        "## How to judge a GOLD candidate",
        "",
        "1. Is the recurring amount a **fee this contract obliges someone to pay**, or an",
        "   incidental figure (an advertising spend floor, a liability cap, a volume commitment)?",
        "2. Does the escalation apply to **that same fee**, on a **time** trigger",
        "   (anniversary / per year) — not per-unit, per-processor, or per-volume-tier?",
        "3. Are both numbers **unredacted**?",
        "",
        "Three yeses means you can plant a known anomaly and check the engine against it.",
        "",
    ]
    path = OUT_DIR / "VERDICT.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_report(results: list[ContractResult], survivors: list[ContractResult], min_cats: int) -> Path:
    total = len(results) or 1
    s = summarise(results)
    by_score = Counter(r.score for r in results)
    per_cat = {c: sum(1 for r in results if c in r.categories) for c in CATEGORIES}

    def pct(n: int) -> str:
        return f"{n / total * 100:.1f}%"

    lines = [
        "# CUAD stage-1 detail — Risk R1",
        "",
        f"Corpus: **{s['total']} CUAD v1 contracts**. Survivor bar: **>= {min_cats} of 5 categories**.",
        "",
        "Read `VERDICT.md` first — this file is the supporting detail.",
        "",
        "## Headline",
        "",
        "| Measure | Count | Share |",
        "|---|---:|---:|",
        f"| Plan's filter (ANY one keyword) | {s['plan_filter']} | {pct(s['plan_filter'])} |",
        f"| >= {min_cats} of 5 rule categories | {len(survivors)} | {pct(len(survivors))} |",
        f"| recurring_fee AND escalation (stage 1) | {s['core_pair']} | {pct(s['core_pair'])} |",
        f"| **GOLD (stage 2)** | **{s['gold']}** | **{pct(s['gold'])}** |",
        "",
        "> The first row is the number that looks healthy. The last row is the number",
        "> that decides whether the product has a data foundation.",
        "",
        "## Per-category presence",
        "",
        "| Category | Contracts | Share | Why it matters |",
        "|---|---:|---:|---|",
    ]
    for cat, (desc, _p) in CATEGORIES.items():
        lines.append(f"| `{cat}` | {per_cat[cat]} | {pct(per_cat[cat])} | {desc} |")

    lines += ["", "## Category-count distribution", "", "| Categories matched | Contracts |", "|---:|---:|"]
    for sc in range(5, -1, -1):
        lines.append(f"| {sc} | {by_score.get(sc, 0)} |")

    lines += [
        "",
        f"## Stage-1 survivors ({len(survivors)}) — ranked, best first",
        "",
        "PDFs in `survivors/`, prefixed by score. Evidence snippets in `evidence/`.",
        "",
        "| # | Score | Core pair | Tier | CUAD folder | Contract |",
        "|---:|---:|:---:|:---:|---|---|",
    ]
    for i, r in enumerate(survivors, 1):
        lines.append(
            f"| {i} | {r.score}/5 | {'yes' if r.has_core_pair else '—'} | {r.tier} "
            f"| {r.origin} | `{r.name[:60]}` |"
        )
    path = OUT_DIR / "REPORT.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only scan the first N PDFs")
    ap.add_argument("--min-cats", type=int, default=3, help="stage-1 survivor bar, out of 5")
    args = ap.parse_args()

    for d in (TEXT_DIR, SURVIVOR_DIR, EVIDENCE_DIR, GOLD_DIR, TEMPLATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    for d in (SURVIVOR_DIR, EVIDENCE_DIR, GOLD_DIR, TEMPLATE_DIR):
        for f in d.iterdir():
            f.unlink()

    pdfs = download_cuad(args.limit)

    print(f"[2/4] Extracting text from {len(pdfs)} PDFs")
    results: list[ContractResult] = []
    for i, pdf in enumerate(pdfs, 1):
        if i % 100 == 0:
            print(f"      {i}/{len(pdfs)}")
        text, n_pages = extract_text(pdf)
        if not text.strip():
            continue
        _PDF_BY_NAME[pdf.stem] = pdf
        results.append(
            scan_text(
                name=pdf.stem,
                source="cuad",
                origin=pdf.parts[-2] if len(pdf.parts) >= 2 else "?",
                text=text,
                n_pages=n_pages,
            )
        )

    print(f"[3/4] Scoring {len(results)} readable contracts")
    survivors = sorted(
        (r for r in results if r.score >= args.min_cats),
        key=lambda r: (r.is_gold, r.has_core_pair, r.score, r.n_chars),
        reverse=True,
    )

    gold = [r for r in results if r.is_gold]
    templates = [r for r in results if r.is_template]

    print(f"[4/4] Writing {len(survivors)} survivors, {len(gold)} gold, {len(templates)} templates")
    for r in survivors:
        write_evidence(r)
        shutil.copy2(
            _PDF_BY_NAME[r.name],
            SURVIVOR_DIR / f"{r.score}of5_{'CORE' if r.has_core_pair else 'part'}_{r.name[:80]}.pdf",
        )
    for bucket, target in ((gold, GOLD_DIR), (templates, TEMPLATE_DIR)):
        for r in bucket:
            write_evidence(r)  # a gold/template entry may miss the stage-1 bar
            shutil.copy2(_PDF_BY_NAME[r.name], target / f"{r.name[:90]}.pdf")

    report = write_report(results, survivors, args.min_cats)
    verdict = write_verdict(results)
    s = summarise(results)

    print()
    print("=" * 74)
    print("  STAGE 1 — keyword filters")
    print(f"    contracts scanned                     {s['total']}")
    print(f"    plan's ANY-keyword filter passes      {s['plan_filter']}  ({s['plan_filter']/s['total']*100:.1f}%)")
    print(f"    >= {args.min_cats}/5 rule categories               {len(survivors)}  ({len(survivors)/s['total']*100:.1f}%)")
    print(f"    recurring_fee AND escalation          {s['core_pair']}  ({s['core_pair']/s['total']*100:.1f}%)")
    print("  STAGE 2 — concrete, unredacted values")
    print(f"    real recurring $ amount               {s['concrete_fee']}  ({s['concrete_fee']/s['total']*100:.1f}%)")
    print(f"    real % / CPI escalation on a fee      {s['concrete_esc']}  ({s['concrete_esc']/s['total']*100:.1f}%)")
    print(f"    'escalation' = disputes only          {s['dispute_only']}")
    print(f"    GOLD     (buildable as-is)            {s['gold']}  ({s['gold_pct']}%)  <-- the number that decides")
    print(f"    TEMPLATE (fill in the blanks)         {s['template']}  ({s['template_pct']}%)")
    print("=" * 74)
    print(f"\n  READ FIRST:  {verdict}")
    print(f"  Gold:        {GOLD_DIR}")
    print(f"  Templates:   {TEMPLATE_DIR}")
    print(f"  Stage 1:     {report}")
    print(f"  Survivors:   {SURVIVOR_DIR}")
    print(f"  Evidence:    {EVIDENCE_DIR}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
