"""[A] Locate a verbatim clause in a PDF and return a real bbox (ADR-005). Phase 5.

The model returns a sentence. This module decides where that sentence is. Three
outcomes, and the third one matters most:

  exact   PyMuPDF found the string. Real rectangles in PDF points.
  fuzzy   found it after allowing for ligatures and line-break hyphenation.
  None    the quote is not in the document, so the model invented it.

That third outcome is a free hallucination detector — no manual checking, no
second model call. The caller flags the rule low-confidence and the UI shows the
page with no highlight, because a confidently *wrong* highlight destroys trust
in a way a missing one does not (ADR-005; `source_page`/`source_bbox` are
nullable by design).

Import note: `import pymupdf`, never `import fitz` — the alias still works but
emits a DeprecationWarning on the installed version (known issue #12).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pymupdf
from thefuzz import fuzz

from core.ai.schemas import ClauseLocation

log = logging.getLogger(__name__)

#: Long enough to be unique in a contract, short enough to survive the line
#: wrapping that makes a whole sentence unfindable as one string.
PROBE_CHARS = 80

#: Below this, treat the block as a different sentence rather than a noisy
#: rendering of the same one.
FUZZY_THRESHOLD = 80


def _probe(clause_text: str) -> str:
    """The needle: whitespace collapsed, trimmed to a findable length.

    PyMuPDF's `search_for` matches across line breaks but not across arbitrary
    runs of whitespace, so the newlines a model copies out of a PDF have to go.
    """
    return re.sub(r"\s+", " ", clause_text).strip()[:PROBE_CHARS]


def locate_clause(pdf_path: str | Path, clause_text: str) -> ClauseLocation | None:
    """exact -> fuzzy -> None. None means the model likely hallucinated the quote.

    Never raises: an unreadable or missing PDF is a `None`, the same as a quote
    that is not there. The caller's handling is identical either way.
    """
    if not clause_text or not clause_text.strip():
        return None

    probe = _probe(clause_text)
    if len(probe) < 20:
        # A short quote matches by coincidence. Refusing to locate it is the
        # honest answer, not a limitation.
        return None

    try:
        document = pymupdf.open(str(pdf_path))
    except Exception as exc:
        log.warning("cannot open %s: %s", pdf_path, exc)
        return None

    try:
        # 1. EXACT — PyMuPDF returns real rectangles in PDF points.
        for page_number, page in enumerate(document, start=1):
            hits = page.search_for(probe)
            if hits:
                box = hits[0]
                return ClauseLocation(
                    page=page_number,
                    bbox=[box.x0, box.y0, box.x1, box.y1],
                    method="exact",
                )

        # 2. FUZZY — OCR noise, ligatures, line-break hyphenation.
        best_score = 0
        best_page: int | None = None
        best_box: list[float] | None = None
        needle = probe.lower()
        for page_number, page in enumerate(document, start=1):
            for block in page.get_text("blocks"):
                score = fuzz.partial_ratio(needle, str(block[4]).lower())
                if score > best_score:
                    best_score = score
                    best_page = page_number
                    best_box = [float(value) for value in block[:4]]

        if best_score >= FUZZY_THRESHOLD and best_page and best_box:
            return ClauseLocation(page=best_page, bbox=best_box, method="fuzzy")

        # 3. UNGROUNDED.
        log.info("no location for a %d-char quote (best fuzzy score %d)", len(probe), best_score)
        return None
    finally:
        document.close()


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
