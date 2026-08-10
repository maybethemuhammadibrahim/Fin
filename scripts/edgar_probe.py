"""Phase 3 de-risk spike, part 2 — does SEC EDGAR beat CUAD as a contract source?

NOT a Phase 3 deliverable. Companion to scripts/cuad_probe.py; both import
scripts/contract_scoring.py so the two sources are judged identically.

CUAD's result, measured on all 510: only 8 contracts (1.6%) carry both a real
recurring amount and a real escalation clause, and only ~3 survive reading by
hand. The open question is whether EDGAR does better once you can AIM the query
at master services agreements instead of taking CUAD's M&A-heavy mix.

Caveat worth stating up front: CUAD was itself built from EDGAR, so the
redaction problem ([***] where the rate should be) will NOT improve. What
changes is volume and aim -- millions of filings, searchable by phrase.

Buckets written to disk:
    gold/       usable as-is (real amount + real escalation, unredacted)
    templates/  right clause shapes, numbers redacted or in an unfiled exhibit
                -> write dummy figures on top, keep the real prose
    text/       extracted plain text for every document fetched

Usage:
    python scripts/edgar_probe.py                  # ~300 docs, the real run
    python scripts/edgar_probe.py --target 40      # quick smoke test
    python scripts/edgar_probe.py --no-fetch       # re-score what's cached

SEC fair-access rules: a descriptive User-Agent with a contact address is
mandatory, and the documented ceiling is 10 requests/second. This script stays
well under that and will back off on a 429.
"""

from __future__ import annotations

import argparse
import gzip
import html as html_mod
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path

from contract_scoring import ContractResult, scan_text, summarise

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "corpus" / "edgar_probe"
TEXT_DIR = OUT_DIR / "text"
RAW_DIR = OUT_DIR / "raw"
GOLD_DIR = OUT_DIR / "gold"
TEMPLATE_DIR = OUT_DIR / "templates"

# SEC requires a real contact address in the User-Agent. This is the repo owner's.
USER_AGENT = "FinSight academic research mibrahimfiftysix@gmail.com"
FTS_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data"

REQUEST_DELAY = 0.15  # ~6 req/s, comfortably under SEC's documented 10/s

# Queries aimed at the document type FinSight actually targets. Each is a
# phrase search; EDGAR ranks exact-phrase hits first.
QUERIES = [
    '"master services agreement" "monthly fee"',
    '"master services agreement" "per month"',
    '"professional services agreement" "monthly fee"',
    '"services agreement" "shall increase" "per month"',
    '"consulting agreement" "monthly retainer"',
    '"master services agreement" "annual increase"',
    '"services agreement" "monthly retainer"',
    '"maintenance agreement" "annual fee" "increase"',
    '"services agreement" "consumer price index" "fee"',
    '"statement of work" "monthly fee" "increase"',
]

# We only want contract exhibits. EX-10 is "material contracts"; EX-99 sometimes
# carries them too. Everything else (financial statements, opinions) is noise.
WANTED_PREFIXES = ("EX-10", "EX-99")


def _http(url: str, tries: int = 4) -> bytes:
    """GET with gzip, SEC-compliant headers, and back-off on 429/503."""
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    )
    for attempt in range(tries):
        try:
            resp = urllib.request.urlopen(req, timeout=45)
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < tries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def search(query: str, page: int = 0) -> list[dict]:
    """One page of EDGAR full-text search results (10 per page)."""
    params = {"q": query, "from": page * 10}
    try:
        data = json.loads(_http(f"{FTS_URL}?{urllib.parse.urlencode(params)}"))
    except Exception as exc:
        print(f"      ! search failed ({type(exc).__name__}) for {query[:50]}")
        return []
    return data.get("hits", {}).get("hits", [])


def doc_url(hit: dict) -> str | None:
    try:
        accession, filename = hit["_id"].split(":", 1)
        cik = hit["_source"]["ciks"][0].lstrip("0")
    except (KeyError, IndexError, ValueError):
        return None
    return f"{ARCHIVE}/{cik}/{accession.replace('-', '')}/{filename}"


def html_to_text(raw: bytes) -> str:
    """EDGAR exhibits are HTML. Strip to plain text without adding a dependency."""
    doc = raw.decode("utf-8", errors="ignore")
    doc = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", doc)
    # Turn block boundaries into newlines so sentences don't run together.
    doc = re.sub(r"(?i)</(p|div|tr|h[1-6]|li|table)>", "\n", doc)
    doc = re.sub(r"(?i)<br\s*/?>", "\n", doc)
    doc = re.sub(r"<[^>]+>", " ", doc)
    doc = html_mod.unescape(doc)
    doc = doc.replace("\xa0", " ")
    doc = re.sub(r"[ \t]+", " ", doc)
    doc = re.sub(r"\n\s*\n+", "\n\n", doc)
    return doc.strip()


def safe_name(hit: dict) -> str:
    accession, filename = hit["_id"].split(":", 1)
    company = (hit["_source"].get("display_names") or ["unknown"])[0]
    company = re.sub(r"\s*\(.*?\)\s*", "", company).strip()
    company = re.sub(r"[^A-Za-z0-9 _-]", "", company)[:45].strip().replace(" ", "_")
    ftype = re.sub(r"[^A-Za-z0-9.-]", "", hit["_source"].get("file_type") or "EX")
    return f"{company}_{ftype}_{accession}"


def collect_hits(target: int) -> list[dict]:
    """Fan out across queries, keep contract exhibits, dedupe by accession:file."""
    seen: set[str] = set()
    hits: list[dict] = []
    page = 0
    while len(hits) < target and page < 8:
        for query in QUERIES:
            if len(hits) >= target:
                break
            batch = search(query, page)
            time.sleep(REQUEST_DELAY)
            for hit in batch:
                ftype = hit["_source"].get("file_type") or ""
                if not ftype.upper().startswith(WANTED_PREFIXES):
                    continue
                if hit["_id"] in seen:
                    continue
                seen.add(hit["_id"])
                hits.append(hit)
        page += 1
        print(f"      page {page}: {len(hits)} contract exhibits so far")
    return hits[:target]


def fetch_and_score(hits: list[dict], no_fetch: bool) -> list[ContractResult]:
    results: list[ContractResult] = []
    for i, hit in enumerate(hits, 1):
        name = safe_name(hit)
        cache = TEXT_DIR / f"{name}.txt"

        if cache.exists():
            text = cache.read_text(encoding="utf-8", errors="ignore")
        elif no_fetch:
            continue
        else:
            url = doc_url(hit)
            if not url:
                continue
            try:
                raw = _http(url)
            except Exception as exc:
                print(f"      ! fetch failed {name[:40]} ({type(exc).__name__})")
                time.sleep(REQUEST_DELAY)
                continue
            time.sleep(REQUEST_DELAY)
            (RAW_DIR / f"{name}.html").write_bytes(raw)
            text = html_to_text(raw)
            cache.write_text(text, encoding="utf-8")

        if len(text) < 3000:  # amendments and cover letters, not contracts
            continue

        results.append(
            scan_text(
                name=name,
                source="edgar",
                origin=hit["_id"],
                text=text,
                n_pages=max(1, len(text) // 3000),  # EDGAR HTML has no real pages
            )
        )
        if i % 25 == 0:
            print(f"      {i}/{len(hits)} fetched, {len(results)} scored")
    return results


def write_outputs(results: list[ContractResult]) -> Path:
    s = summarise(results)
    gold = [r for r in results if r.is_gold]
    templates = [r for r in results if r.is_template]

    for bucket, target in ((gold, GOLD_DIR), (templates, TEMPLATE_DIR)):
        for r in bucket:
            src = TEXT_DIR / f"{r.name}.txt"
            if src.exists():
                (target / f"{r.name}.txt").write_text(
                    src.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8"
                )

    (OUT_DIR / "results.json").write_text(
        json.dumps([asdict(r) for r in results], indent=2, default=str), encoding="utf-8"
    )

    n = s["total"] or 1
    lines = [
        "# EDGAR probe — is EDGAR a better contract source than CUAD?",
        "",
        f"Documents scored: **{s['total']}** contract exhibits (EX-10 / EX-99), aimed at",
        "master services / professional services / consulting agreements.",
        "",
        "## Head-to-head",
        "",
        "| Measure | EDGAR | CUAD (510 docs) |",
        "|---|---:|---:|",
        f"| Usable as-is (**gold**) | {s['gold']} ({s['gold_pct']}%) | 8 (1.6%) |",
        f"| Fill-in-the-blank (**template**) | {s['template']} ({s['template_pct']}%) | see cuad_probe |",
        f"| Real recurring $ amount | {s['concrete_fee']} ({s['concrete_fee']/n*100:.1f}%) | 55 (10.8%) |",
        f"| Real % / CPI escalation | {s['concrete_esc']} ({s['concrete_esc']/n*100:.1f}%) | 18 (3.5%) |",
        f"| Redacted financials | {s['redacted']} ({s['redacted']/n*100:.1f}%) | 121 (23.7%) |",
        f"| 'escalation' = dispute procedure only | {s['dispute_only']} | 68 |",
        "",
        "## Decision rule",
        "",
        "Set before the run: **15+ gold out of ~300** means EDGAR carries Phase 3.",
        "Fewer than that and the fill-in-the-blank route (templates) becomes the plan.",
        "",
        f"### Gold ({len(gold)}) — usable as-is",
        "",
    ]
    for r in sorted(gold, key=lambda r: r.name):
        lines += [
            f"**{r.name}**  ",
            f"- recurring: …{(r.concrete_recurring or '')[:300]}…",
            f"- escalation: …{(r.concrete_escalation or '')[:300]}…",
            "",
        ]
    lines += [
        f"### Templates ({len(templates)}) — right shape, numbers missing",
        "",
        "Real legal prose with the figures redacted or pushed into an unfiled exhibit.",
        "Write dummy numbers over these and the 'genuine legal prose' claim survives.",
        "",
        "| Contract | Redacted | Recurring shape |",
        "|---|:---:|---|",
    ]
    for r in sorted(templates, key=lambda r: r.name)[:60]:
        shape = (r.shape_recurring or "")[:110].replace("|", "/")
        lines.append(f"| `{r.name[:55]}` | {'yes' if r.redacted else 'no'} | …{shape}… |")

    lines += [
        "",
        "## Known limitation of this probe",
        "",
        "EDGAR serves HTML, not PDF. Phase 7's clause viewer locates quotes with",
        "PyMuPDF `page.search_for()`, which needs a PDF. Either convert these to PDF",
        "before they enter `data/corpus/contracts/`, or accept page-level degradation",
        "(ADR-005 already allows a null bbox). Not solved here.",
        "",
    ]
    path = OUT_DIR / "REPORT.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=300, help="documents to fetch")
    ap.add_argument("--no-fetch", action="store_true", help="re-score cached text only")
    args = ap.parse_args()

    for d in (TEXT_DIR, RAW_DIR, GOLD_DIR, TEMPLATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    for d in (GOLD_DIR, TEMPLATE_DIR):
        for f in d.iterdir():
            f.unlink()

    if args.no_fetch:
        print("[1/3] --no-fetch: scoring cached text")
        hits = [
            {"_id": f"cached:{p.stem}", "_source": {"display_names": [p.stem], "file_type": "EX"}}
            for p in sorted(TEXT_DIR.glob("*.txt"))
        ]
        results = []
        for p in sorted(TEXT_DIR.glob("*.txt")):
            text = p.read_text(encoding="utf-8", errors="ignore")
            if len(text) < 3000:
                continue
            results.append(
                scan_text(p.stem, "edgar", "cached", text, max(1, len(text) // 3000))
            )
    else:
        print(f"[1/3] Searching EDGAR for up to {args.target} contract exhibits")
        hits = collect_hits(args.target)
        print(f"      {len(hits)} candidates")
        print(f"[2/3] Fetching and scoring")
        results = fetch_and_score(hits, args.no_fetch)

    if not results:
        print("No documents scored — nothing to report.")
        return 1

    print(f"[3/3] Writing report for {len(results)} documents")
    report = write_outputs(results)
    s = summarise(results)

    print()
    print("=" * 74)
    print(f"  documents scored                {s['total']}")
    print(f"  real recurring $ amount         {s['concrete_fee']}")
    print(f"  real % / CPI escalation         {s['concrete_esc']}")
    print(f"  redacted financials             {s['redacted']}")
    print(f"  'escalation' = disputes only    {s['dispute_only']}")
    print(f"  GOLD     (usable as-is)         {s['gold']}  ({s['gold_pct']}%)   CUAD: 8 (1.6%)")
    print(f"  TEMPLATE (fill in the blanks)   {s['template']}  ({s['template_pct']}%)")
    print("=" * 74)
    print(f"\n  Report:    {report}")
    print(f"  Gold:      {GOLD_DIR}")
    print(f"  Templates: {TEMPLATE_DIR}\n")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
