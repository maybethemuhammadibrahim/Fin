"""[A] Real quotes, real PDFs, real coordinates — and the wrong boxes we must never draw. Phase 7.

Every fixture is a PDF built in memory by `pdf_renderer.typeset_pdf`, so these
tests need no network, no database, no corpus on disk and no committed binary.

Two halves, and the second is the one that earns its keep:

* **finding what is there** — whole-quote boxes, ligatures, ellipses, page
  numbers, multi-page documents.
* **refusing what is not.** Three of these are regressions for wrong highlights
  this code actually produced during Phase 7: a box around the digit "5" on a
  contents page, a box on an unrelated paragraph about 3D advertising, and a
  clause that could not be found at all because the quote was wrapped in "...".
  ADR-005 says a confident box in the wrong place is worse than no box, and
  these are the tests that keep that true.

Run: `pytest tests/test_clause_locator.py -v`
"""

from __future__ import annotations

import pymupdf
import pytest

from core.extraction.clause_locator import (
    grounding_rate,
    locate_all,
    locate_clause,
    normalise_for_match,
)
from core.extraction.pdf_renderer import typeset_pdf

CLAUSE = (
    "The monthly fee of $6,000 shall be due and payable not later than the fifteenth (15th) "
    "day of each month, beginning with the first payment due on 15 August 2024."
)
ESCALATION = (
    "Such monthly fees shall increase by ten percent (10%) beginning on each anniversary "
    "date of the Agreement."
)

BODY = f"""MASTER SERVICES AGREEMENT

Section 1. Engagement. The Provider shall supply the Services described in Schedule A
for the term set out below, and the Client shall pay for them as follows.

Section 2. Fees. {CLAUSE}

Section 3. Escalation. {ESCALATION}

Section 4. Miscellaneous. Neither party shall be liable for any indirect or consequential
loss arising under this Agreement, however caused.
"""


@pytest.fixture(scope="module")
def contract() -> bytes:
    return typeset_pdf(BODY, title="master_services_agreement.txt")


def boxed_text(pdf: bytes, location) -> str:
    """What the returned rectangle actually sits on top of. The test that a box
    is *correct* rather than merely present."""
    document = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        text = document[location.page - 1].get_textbox(pymupdf.Rect(*location.bbox))
    finally:
        document.close()
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# finding what is there
# ---------------------------------------------------------------------------


def test_a_whole_clause_is_located_exactly(contract):
    location = locate_clause(contract, CLAUSE)
    assert location is not None
    assert location.method == "exact"
    assert location.page == 1
    assert "$6,000" in boxed_text(contract, location)


def test_the_box_covers_every_line_of_the_quote(contract):
    """Phase 5 returned `hits[0]` — the first line of a four-line clause. The
    union is the difference between highlighting a sentence and highlighting
    eleven words of it."""
    location = locate_clause(contract, CLAUSE)
    x0, y0, x1, y1 = location.bbox
    assert y1 - y0 > 20  # more than a single ~14pt line
    assert x1 > x0
    text = boxed_text(contract, location)
    assert "monthly fee" in text and "August 2024" in text


def test_typography_the_extractor_folds_still_matches(contract):
    """Curly quotes, en dashes and a ligature are what a model copies out of
    extracted text; the PDF has none of them."""
    quote = CLAUSE.replace("(15th)", "(15th)").replace("$6,000", "$6,000")
    quote = quote.replace("fifteenth", "ﬁfteenth").replace("-", "–")
    assert locate_clause(contract, quote) is not None


def test_a_quote_wrapped_in_ellipses_is_still_found(contract):
    """Regression. Both a model and a human transcriber bracket an excerpt with
    "...", and a literal PDF search for those dots fails on a clause that is
    right there — which sent a real Phase 7 run to a fuzzy box on the wrong
    paragraph."""
    location = locate_clause(contract, f"...{ESCALATION[:-1]}...")
    assert location is not None
    assert location.method == "exact"
    assert "ten percent" in boxed_text(contract, location)


def test_hyphenation_across_a_line_break_is_normalised():
    assert normalise_for_match("pay-\nment terms") == "payment terms"
    assert normalise_for_match("fees   shall\n\nincrease") == "fees shall increase"


def test_a_clause_deep_in_a_long_document_reports_its_real_page():
    filler = "\n\n".join(f"Section {n}. Boilerplate of no consequence." for n in range(400))
    pdf = typeset_pdf(f"{filler}\n\n{CLAUSE}\n\n{filler}", title="long.txt")
    location = locate_clause(pdf, CLAUSE)
    assert location is not None
    assert location.page > 1
    assert "$6,000" in boxed_text(pdf, location)


def test_locate_all_matches_locate_clause_one_at_a_time(contract):
    quotes = [CLAUSE, ESCALATION, "A sentence that appears nowhere in this agreement at all."]
    batched = locate_all(contract, quotes)
    one_by_one = [locate_clause(contract, q) for q in quotes]
    assert [(l.page, l.method) if l else None for l in batched] == [
        (l.page, l.method) if l else None for l in one_by_one
    ]


# ---------------------------------------------------------------------------
# refusing what is not there
# ---------------------------------------------------------------------------


def test_an_invented_quote_is_not_located(contract):
    """The free hallucination detector. No second model call, no human check."""
    invented = (
        "The Provider shall deliver one unicorn per fiscal quarter to the Client's "
        "registered office, at the Client's expense."
    )
    assert locate_clause(contract, invented) is None


def test_a_short_quote_is_refused_rather_than_matched_by_coincidence(contract):
    assert locate_clause(contract, "the fee") is None
    assert locate_clause(contract, "$6,000") is None


def test_a_contents_page_digit_is_never_matched():
    """Regression for the worst bug Phase 7 produced. `fuzz.partial_ratio`
    normalises by its *shorter* argument, so a block containing only "5" scored
    100 against a clause containing a 5 — and the viewer drew a confident amber
    box around that digit on a table of contents."""
    contents = "\n\n".join(
        ["TABLE OF CONTENTS", "Section 2.05.", "5", "Section 2.06.", "5", "Section 2.07.", "6"]
    )
    pdf = typeset_pdf(contents, title="contents_only.txt")
    location = locate_clause(pdf, "$12,500 per month in which service is provided, as a Service Charge.")
    assert location is None


def test_a_paragraph_that_merely_shares_vocabulary_is_not_matched():
    """Regression. A long paragraph using "payment", "month" and "shall" is not
    the fee clause, and `partial_ratio` alone said it was."""
    decoy = (
        "In each case, such Advertising Services will be properly conditioned to meet the "
        "specifications of equipment providers, and the Licensee shall pay or reimburse the "
        "Provider for any and all third party licensing fees incurred in connection with the "
        "monthly delivery of such Services during the term."
    )
    pdf = typeset_pdf(f"AGREEMENT\n\n{decoy}\n\n", title="decoy.txt")
    assert locate_clause(pdf, CLAUSE) is None


def test_a_missing_or_unreadable_file_returns_none_rather_than_raising(tmp_path):
    assert locate_clause(tmp_path / "nope.pdf", CLAUSE) is None
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a PDF at all")
    assert locate_clause(broken, CLAUSE) is None
    assert locate_clause(b"neither is this", CLAUSE) is None


def test_an_empty_quote_is_not_located(contract):
    assert locate_clause(contract, "") is None
    assert locate_clause(contract, "   \n  ") is None


def test_locate_all_on_an_unreadable_document_returns_one_none_per_quote():
    assert locate_all(b"not a pdf", ["a", "b", "c"]) == [None, None, None]


# ---------------------------------------------------------------------------
# the metric the report quotes
# ---------------------------------------------------------------------------


def test_grounding_rate_shares_sum_to_a_hundred(contract):
    locations = locate_all(contract, [CLAUSE, ESCALATION, "not in this document anywhere at all"])
    rate = grounding_rate(locations)
    assert rate["grounded"] == pytest.approx(66.7, abs=0.1)
    assert rate["exact"] + rate["fuzzy"] + rate["ungrounded"] == pytest.approx(100.0, abs=0.1)


def test_grounding_rate_of_nothing_is_zero_not_a_crash():
    assert grounding_rate([]) == {"exact": 0.0, "fuzzy": 0.0, "ungrounded": 0.0, "grounded": 0.0}
