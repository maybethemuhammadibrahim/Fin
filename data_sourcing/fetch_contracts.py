"""[A] Download real contracts from SEC EDGAR (primary) and CUAD v1 (secondary). Phase 3.

ADR-013: EDGAR is PRIMARY, CUAD is secondary and demoted to Phase 5 extraction-dev and
Phase 10 training volume. Measured yield, aimed at master/professional services
agreements: EDGAR's EX-10/EX-99 full-text search gives ~17.7% gold (real amount AND
real escalation) vs CUAD's 1.6% (scripts/edgar_probe.py, scripts/cuad_probe.py; see
docs/progress.md "Pre-Phase-3 spike" and ADR-013/014).

This module only fetches and writes raw text/PDFs to disk. Scoring, filtering,
deduplication and redaction-filling live in filter_contracts.py.
"""

from __future__ import annotations

import gzip
import html as html_mod
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# SEC fair-access rules require a real contact address in the User-Agent.
USER_AGENT = "FinSight data-sourcing (academic project) mibrahimfiftysix@gmail.com"
FTS_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data"
REQUEST_DELAY = 0.15  # ~6 req/s, comfortably under SEC's documented 10 req/s ceiling

# Aimed at the document type FinSight actually targets — not CUAD's M&A-heavy mix
# (ADR-013). Each is a phrase search; EDGAR ranks exact-phrase hits first.
#
# The first ten are Phase 3's original list. Everything below them was added
# 2026-08-17 for Phase 10 (known issue #27): the original set is generic, and
# generic queries all rank the SAME administrator boilerplate first — which is
# how 51 documents collapsed into 21 distinct clauses (#26). Training and the
# base-vs-tuned claim need variety, not volume, so these name the *industry* and
# the *service*, pulling different filers rather than deeper pages of the same
# ones.
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
    # ---- added for Phase 10 (#27): industry-specific, to break the fee-letter cluster ----
    '"software as a service agreement" "monthly fee"',
    '"software license and services agreement" "annual fee" "increase"',
    '"managed services agreement" "monthly fee"',
    '"support and maintenance agreement" "annual fee"',
    '"hosting agreement" "monthly fee"',
    '"marketing services agreement" "monthly fee"',
    '"advertising services agreement" "monthly retainer"',
    '"staffing services agreement" "monthly fee"',
    '"logistics services agreement" "monthly fee"',
    '"transportation services agreement" "monthly fee"',
    '"facilities management agreement" "monthly fee"',
    '"janitorial services agreement" "monthly fee"',
    '"security services agreement" "monthly fee"',
    '"engineering services agreement" "monthly fee"',
    '"clinical research services agreement" "monthly fee"',
    '"laboratory services agreement" "monthly fee"',
    '"billing services agreement" "monthly fee"',
    '"payroll services agreement" "monthly fee"',
    '"information technology services agreement" "monthly fee"',
    '"outsourcing agreement" "monthly fee" "increase"',
    '"development agreement" "monthly fee" "escalation"',
    '"design services agreement" "monthly fee"',
    '"agency agreement" "monthly retainer" "increase"',
    # ---- escalation wording the original list never asked for ----
    '"services agreement" "shall be increased by" "percent"',
    '"services agreement" "annual escalation" "fee"',
    '"services agreement" "fee shall increase" "anniversary"',
    '"agreement" "monthly fee" "shall increase by" "percent"',
    # ---- discount wording: zombie_discount needs examples too ----
    '"services agreement" "discount" "first three months"',
    '"services agreement" "introductory rate" "monthly fee"',
    '"services agreement" "waived" "first" "months" "monthly fee"',
]

# We only want contract exhibits. EX-10 is "material contracts"; EX-99 sometimes
# carries them too. Everything else (financial statements, opinions) is noise.
WANTED_PREFIXES = ("EX-10", "EX-99")

#: Known issue #26: one administrator (Ultimus) sends every fund trust the same
#: fee letter, so an uncapped crawl returns the same clause dozens of times and
#: reports it as corpus size. filter_contracts.deduplicate() catches it later,
#: but only after the bytes are downloaded — capping here means the crawl spends
#: its budget on new filers instead. Distinct clauses are the metric, never
#: document count.
MAX_PER_FILER = 3


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
                time.sleep(2**attempt * 2)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(2**attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def _search(query: str, page: int) -> list[dict]:
    params = {"q": query, "from": page * 10}
    try:
        import json

        data = json.loads(_http(f"{FTS_URL}?{urllib.parse.urlencode(params)}"))
    except Exception:
        return []
    return data.get("hits", {}).get("hits", [])


def _doc_url(hit: dict) -> str | None:
    try:
        accession, filename = hit["_id"].split(":", 1)
        cik = hit["_source"]["ciks"][0].lstrip("0")
    except (KeyError, IndexError, ValueError):
        return None
    return f"{ARCHIVE}/{cik}/{accession.replace('-', '')}/{filename}"


def _filer_of(hit: dict) -> str:
    """The filing company, normalised the same way `_safe_name` renders it.

    Both must agree, or the crawl's per-filer cap and
    `filter_contracts.deduplicate()`'s filer grouping would count different
    things and the cap would silently do nothing.
    """
    company = (hit["_source"].get("display_names") or ["unknown"])[0]
    company = re.sub(r"\s*\(.*?\)\s*", "", company).strip()
    return re.sub(r"[^A-Za-z0-9 _-]", "", company)[:45].strip().lower()


def _safe_name(hit: dict) -> str:
    """`<Filer>_<ExhibitType>_<accession>` — the filer stays readable in the filename,
    which is how filter_contracts.deduplicate() groups by filer without a metadata
    sidecar file."""
    accession, filename = hit["_id"].split(":", 1)
    company = (hit["_source"].get("display_names") or ["unknown"])[0]
    company = re.sub(r"\s*\(.*?\)\s*", "", company).strip()
    company = re.sub(r"[^A-Za-z0-9 _-]", "", company)[:45].strip().replace(" ", "_")
    ftype = re.sub(r"[^A-Za-z0-9.-]", "", hit["_source"].get("file_type") or "EX")
    return f"{company}_{ftype}_{accession}"


def _html_to_text(raw: bytes) -> str:
    """EDGAR exhibits are HTML. Strip to plain text without adding a dependency."""
    doc = raw.decode("utf-8", errors="ignore")
    doc = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", doc)
    doc = re.sub(r"(?i)</(p|div|tr|h[1-6]|li|table)>", "\n", doc)
    doc = re.sub(r"(?i)<br\s*/?>", "\n", doc)
    doc = re.sub(r"<[^>]+>", " ", doc)
    doc = html_mod.unescape(doc)
    doc = doc.replace("\xa0", " ")
    doc = re.sub(r"[ \t]+", " ", doc)
    doc = re.sub(r"\n\s*\n+", "\n\n", doc)
    return doc.strip()


def fetch_edgar_msa(count: int = 60, out_dir: str = "data/corpus/raw_edgar") -> list[Path]:
    """SEC full-text search, aimed at master/professional services agreements.

    Requires a contact address in the User-Agent; stays well under SEC's documented
    10 req/s ceiling and backs off on 429/503. Writes one .txt per exhibit to
    `out_dir`; re-running is cheap because an already-downloaded file is skipped.
    Measured yield: ~17.7% of what this returns is "gold" once
    filter_service_contracts() scores it for a real amount AND a real escalation.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    per_filer: dict[str, int] = {}
    skipped_filer = 0
    hits: list[dict] = []
    page = 0
    while len(hits) < count and page < 12:
        for query in QUERIES:
            if len(hits) >= count:
                break
            batch = _search(query, page)
            time.sleep(REQUEST_DELAY)
            for hit in batch:
                ftype = (hit["_source"].get("file_type") or "").upper()
                if not ftype.startswith(WANTED_PREFIXES) or hit["_id"] in seen:
                    continue
                # Cap per filer BEFORE downloading (#26/#27). Grouping on the
                # display name matches how filter_contracts.deduplicate() reads
                # the filer back out of the filename, so the two agree.
                filer = _filer_of(hit)
                if per_filer.get(filer, 0) >= MAX_PER_FILER:
                    skipped_filer += 1
                    continue
                per_filer[filer] = per_filer.get(filer, 0) + 1
                seen.add(hit["_id"])
                hits.append(hit)
        page += 1

    if skipped_filer:
        print(
            f"  {len(hits)} exhibit(s) from {len(per_filer)} distinct filer(s); "
            f"skipped {skipped_filer} over the {MAX_PER_FILER}-per-filer cap"
        )

    paths: list[Path] = []
    for hit in hits[:count]:
        dest = out / f"{_safe_name(hit)}.txt"
        if dest.exists():
            paths.append(dest)
            continue
        url = _doc_url(hit)
        if not url:
            continue
        try:
            raw = _http(url)
        except Exception:
            time.sleep(REQUEST_DELAY)
            continue
        time.sleep(REQUEST_DELAY)
        text = _html_to_text(raw)
        if len(text) < 3000:  # amendments and cover letters, not contracts
            continue
        dest.write_text(text, encoding="utf-8")
        paths.append(dest)
    return paths


def fetch_cuad(limit: int = 200, out_dir: str = "data/corpus/contracts") -> list[Path]:
    """`theatticusproject/cuad` on HuggingFace — public, no HF_TOKEN needed, real PDFs.
    NOT the plan's `dvgodoy` mirror (docs/state.json known_issues, Phase 0 drift note).

    Demoted by ADR-013 to Phase 5 extraction-dev and Phase 10 training volume — CUAD
    yields ~1.6% usable anomaly scenarios (scripts/cuad_probe.py), so the Phase 3 corpus
    build does not call this. Kept working here for when those later phases need it.
    """
    from huggingface_hub import snapshot_download

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    local = snapshot_download(
        repo_id="theatticusproject/cuad",
        repo_type="dataset",
        local_dir=str(out / "_cuad_raw"),
        allow_patterns=["CUAD_v1/full_contract_pdf/**"],
    )
    pdfs = sorted(
        p for p in Path(local).rglob("*") if p.suffix.lower() == ".pdf" and "full_contract_pdf" in str(p)
    )
    return pdfs[:limit] if limit else pdfs
