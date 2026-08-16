"""[A] Locate a verbatim clause in a PDF and return a real bbox (ADR-005). Phase 5, hardened at Phase 7.

The model returns a sentence. This module decides where that sentence is. Three
outcomes, and the third one matters most:

  exact   PyMuPDF found the string. Real rectangles in PDF points.
  fuzzy   found it after allowing for ligatures, dashes and line-break hyphenation.
  None    the quote is not in the document, so the model invented it.

That third outcome is a free hallucination detector — no manual checking, no
second model call. The caller flags the rule low-confidence and the UI shows the
page with no highlight, because a confidently *wrong* highlight destroys trust
in a way a missing one does not (ADR-005; `source_page`/`source_bbox` are
nullable by design).

**What Phase 7 changed**, all of it in service of a highlight a human would
accept:

* **The box covers the whole quote, not its first line.** `search_for` returns
  one rectangle per line a match spans; Phase 5 kept `hits[0]`, which boxed
  about eleven words of a four-line clause. They are now unioned.
* **Longest probe wins.** The search starts with the full quote and shortens
  only when that fails, so a clause that *can* be found whole is boxed whole.
* **Typography is normalised before comparing** — ligatures (ﬁ), curly quotes,
  en/em dashes, non-breaking spaces, and the hyphen a PDF inserts when it breaks
  a word across lines. Every one of these is a character the model copies
  faithfully from extracted text and that then fails a literal PDF search.
* **A clause that spans a page break is located**, on the page where it starts,
  by falling back to its opening words.

Import note: `import pymupdf`, never `import fitz` — the alias still works but
emits a DeprecationWarning on the installed version (known issue #12).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from thefuzz import fuzz

from core.ai.schemas import ClauseLocation

log = logging.getLogger(__name__)

#: Probe lengths to try, longest first. The first is "the whole quote"; the rest
#: are fallbacks for a clause that wraps awkwardly, spans a page, or differs from
#: the PDF by a word the extractor picked up from a header.
PROBE_LADDER = (None, 240, 160, 80)

#: Shorter than this and a match is coincidence, not evidence.
MIN_PROBE_CHARS = 20

#: Below this, treat the block as a different sentence rather than a noisy
#: rendering of the same one. Applied to `_window_ratio`, which is a stricter
#: measure than the `partial_ratio` Phase 5 thresholded at 80 — the smaller
#: number is not a looser bar.
FUZZY_THRESHOLD = 75

#: A fuzzy candidate must be at least this share of the quote's length.
#:
#: Without it, `partial_ratio` is actively dangerous: it scores its *shorter*
#: argument as the pattern, so a table-of-contents block containing the single
#: character "5" scores **100** against any quote containing a 5. Phase 7 shipped
#: a highlight over exactly that character on a contents page before this guard
#: existed — a confident box in the wrong place, which ADR-005 exists to prevent.
MIN_BLOCK_RATIO = 0.5

#: …and it must actually share the quote's distinctive words. Short, common
#: words are dropped first, because "the of and shall" matches everything in a
#: contract and proves nothing.
MIN_TOKEN_OVERLAP = 0.35
_STOPWORDS = frozenset(
    "the of and or to in for a an by on at as is be shall will with from that this "
    "such any all each per its it not".split()
)

#: Characters a PDF renders one way and an extractor reports another. Applied to
#: both sides before comparing, never to the text shown to a user.
_TRANSLATIONS = {
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "ft", "ﬆ": "st",
    "“": '"', "”": '"', "„": '"', "‟": '"', "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "–": "-", "—": "-", "―": "-", "−": "-", "‑": "-", "‐": "-",
    " ": " ", " ": " ", " ": " ", " ": " ", "﻿": "",
    "…": "...",
}

#: A word broken across a line: "pay-\nment" is one word, and searching for
#: "payment" must find it.
_HYPHEN_BREAK = re.compile(r"-\s*\n\s*")


def normalise_for_match(text: str) -> str:
    """The comparison form: typography folded, whitespace collapsed.

    Never shown to anybody. The quote a user reads is always the verbatim string
    from `clause_references.clause_text`; this is only what the search runs on.
    """
    if not text:
        return ""
    folded = _HYPHEN_BREAK.sub("", text)
    for source, target in _TRANSLATIONS.items():
        folded = folded.replace(source, target)
    return re.sub(r"\s+", " ", folded).strip()


#: Ellipses and stray quotation marks wrapped around a quote. Both a model and a
#: human transcriber bracket an excerpt like "...the fee shall increase...", and
#: the document contains no such dots — so a literal search for the quote as
#: given fails on a clause that is right there in the text. Trimming them is the
#: difference between an `exact` hit and a fuzzy guess on the wrong paragraph.
_QUOTE_EDGES = re.compile(r'^[\s.·…"\'‘’“”]+|[\s.·…"\'‘’“”]+$')


def _probes(clause_text: str) -> list[str]:
    """The needles to try, longest first, de-duplicated."""
    whole = _QUOTE_EDGES.sub("", normalise_for_match(clause_text))
    out: list[str] = []
    for limit in PROBE_LADDER:
        candidate = whole if limit is None else whole[:limit]
        candidate = candidate.strip()
        if len(candidate) >= MIN_PROBE_CHARS and candidate not in out:
            out.append(candidate)
    return out


def _tokens(text: str) -> set[str]:
    """The words worth matching on: four characters or longer, or numeric."""
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9,.$%-]*", text.lower())
        if token not in _STOPWORDS and (len(token) >= 4 or any(c.isdigit() for c in token))
    }


def _window_ratio(needle: str, haystack: str) -> tuple[int, int]:
    """Best `fuzz.ratio` between the quote and any same-length slice, and where.

    Returns `(score, offset)`. Symmetric in length, so a match cannot be
    manufactured by the haystack being much longer or much shorter than what is
    being looked for — which is exactly how `partial_ratio` produces a confident
    box around a single digit on a contents page.
    """
    size = len(needle)
    if len(haystack) <= size * 1.2:
        return int(fuzz.ratio(needle, haystack)), 0

    step = max(size // 4, 8)
    best_score, best_at = 0, 0
    for start in range(0, len(haystack) - size + 1, step):
        score = int(fuzz.ratio(needle, haystack[start : start + size]))
        if score > best_score:
            best_score, best_at = score, start
            if score >= 97:  # nothing left to find
                break
    return best_score, best_at


@dataclass(frozen=True)
class _PageIndex:
    """A page as one searchable string, with every character traceable to a word.

    Built once per page and reused across every clause in the document. The
    fuzzy tier needs this because a PDF text *block* is only ever part of the
    picture: in a typeset page each line is its own block, so a three-line clause
    can never score well against any single one of them. Matching page-wide and
    mapping the winning window back to word rectangles fixes both the misses and
    the box.
    """

    text: str
    tokens: set[str]
    #: (start, end, rect) per word, offsets into `text`.
    spans: list[tuple[int, int, tuple[float, float, float, float]]]


def _index_page(page) -> _PageIndex:
    parts: list[str] = []
    spans: list[tuple[int, int, tuple[float, float, float, float]]] = []
    cursor = 0
    for word in page.get_text("words"):
        token = normalise_for_match(str(word[4]))
        if not token:
            continue
        parts.append(token)
        spans.append((cursor, cursor + len(token), (float(word[0]), float(word[1]), float(word[2]), float(word[3]))))
        cursor += len(token) + 1
    text = " ".join(parts)
    return _PageIndex(text=text.lower(), tokens=_tokens(text), spans=spans)


def _box_for_window(index: _PageIndex, start: int, length: int) -> list[float] | None:
    """The union of every word the matched window touches."""
    end = start + length
    rects = [rect for (a, b, rect) in index.spans if a < end and b > start]
    if not rects:
        return None
    return [
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    ]


def _fuzzy_locate(pages_index: list[tuple[int, _PageIndex]], probe: str) -> ClauseLocation | None:
    """The fuzzy tier: best same-length window anywhere in the document."""
    needle = probe.lower()
    needle_tokens = _tokens(needle)

    best_score, best_page, best_at, best_index = 0, None, 0, None
    for page_number, index in pages_index:
        if len(index.text) < MIN_PROBE_CHARS:
            continue
        if needle_tokens:
            shared = needle_tokens & index.tokens
            if len(shared) / len(needle_tokens) < MIN_TOKEN_OVERLAP:
                continue  # this page does not even use the quote's vocabulary
        score, at = _window_ratio(needle, index.text)
        if score > best_score:
            best_score, best_page, best_at, best_index = score, page_number, at, index

    if best_score < FUZZY_THRESHOLD or best_page is None or best_index is None:
        log.info("no location for a %d-char quote (best window score %d)", len(probe), best_score)
        return None

    box = _box_for_window(best_index, best_at, len(needle))
    if box is None:
        return None
    return ClauseLocation(page=best_page, bbox=box, method="fuzzy")


def _union(rects) -> list[float]:
    """One box around every rectangle a match spans.

    `search_for` returns a rectangle per line, so a four-line clause comes back
    as four boxes. Their union is the paragraph region, which is what a reader
    expects a highlight to cover.
    """
    x0 = min(r.x0 for r in rects)
    y0 = min(r.y0 for r in rects)
    x1 = max(r.x1 for r in rects)
    y1 = max(r.y1 for r in rects)
    return [float(x0), float(y0), float(x1), float(y1)]


def locate_clause(pdf_path: str | Path | bytes, clause_text: str) -> ClauseLocation | None:
    """exact -> fuzzy -> None. None means the model likely hallucinated the quote.

    Never raises: an unreadable or missing PDF is a `None`, the same as a quote
    that is not there. The caller's handling is identical either way.

    Accepts raw PDF bytes as well as a path, so a document held in memory or
    fetched from Storage does not have to be written to disk first.
    """
    if not clause_text or not clause_text.strip():
        return None

    probes = _probes(clause_text)
    if not probes:
        # A short quote matches by coincidence. Refusing to locate it is the
        # honest answer, not a limitation.
        return None

    document = _open(pdf_path)
    if document is None:
        return None

    try:
        # 1. EXACT — longest probe first, so a clause that can be found whole is
        #    boxed whole rather than by its opening line.
        for probe in probes:
            for page_number, page in enumerate(document, start=1):
                hits = page.search_for(probe)
                if hits:
                    return ClauseLocation(
                        page=page_number, bbox=_union(hits), method="exact"
                    )

        # 2. FUZZY — the PDF's own text differs from the quote: OCR noise, a
        #    stray header word, a transcriber's ellipsis. Matched page-wide, not
        #    block by block, so a clause spanning several lines can still win.
        # 3. UNGROUNDED is what `_fuzzy_locate` returning None means.
        index = [(number, _index_page(page)) for number, page in enumerate(document, start=1)]
        return _fuzzy_locate(index, probes[0])
    finally:
        document.close()


def locate_all(pdf_path: str | Path | bytes, clause_texts: list[str]) -> list[ClauseLocation | None]:
    """Locate several quotes, opening the document once.

    A contract with five clauses would otherwise be five `pymupdf.open()` calls
    over the same file. Same results, same order, one open.
    """
    if not clause_texts:
        return []

    document = _open(pdf_path)
    if document is None:
        return [None] * len(clause_texts)

    try:
        pages = list(enumerate(document, start=1))
        index: list[tuple[int, _PageIndex]] = []
        results: list[ClauseLocation | None] = []

        for clause_text in clause_texts:
            probes = _probes(clause_text or "")
            if not probes:
                results.append(None)
                continue

            found: ClauseLocation | None = None
            for probe in probes:
                for page_number, page in pages:
                    hits = page.search_for(probe)
                    if hits:
                        found = ClauseLocation(
                            page=page_number, bbox=_union(hits), method="exact"
                        )
                        break
                if found:
                    break

            if found is None:
                # Page indexes are built once for the whole document and reused
                # by every clause — the expensive half of the fuzzy tier.
                if not index:
                    index.extend((number, _index_page(page)) for number, page in pages)
                found = _fuzzy_locate(index, probes[0])

            results.append(found)
        return results
    finally:
        document.close()


def _open(source: str | Path | bytes):
    try:
        if isinstance(source, bytes):
            return pymupdf.open(stream=source, filetype="pdf")
        return pymupdf.open(str(source))
    except Exception as exc:
        log.warning("cannot open %s: %s", source if not isinstance(source, bytes) else "<bytes>", exc)
        return None


def grounding_rate(locations: list[ClauseLocation | None]) -> dict[str, float]:
    """Exact / fuzzy / ungrounded shares, for the Phase 5 definition of done and
    the Phase 11 report. Percentages, one decimal, summing to 100."""
    total = len(locations)
    if not total:
        return {"exact": 0.0, "fuzzy": 0.0, "ungrounded": 0.0, "grounded": 0.0}
    exact = sum(1 for item in locations if item and item.method == "exact")
    fuzzy = sum(1 for item in locations if item and item.method == "fuzzy")
    return {
        "exact": round(100 * exact / total, 1),
        "fuzzy": round(100 * fuzzy / total, 1),
        "ungrounded": round(100 * (total - exact - fuzzy) / total, 1),
        "grounded": round(100 * (exact + fuzzy) / total, 1),
    }
