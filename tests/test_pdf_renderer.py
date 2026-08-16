"""[B] Pages become pictures, and text-only filings become pages at all. Phase 7.

Covers the three jobs of `core/extraction/pdf_renderer.py`:

* `render_highlighted` — PNG bytes, box or no box, and **never an exception**.
  Every failure mode here (missing file, junk bytes, a page number past the end)
  has to come back as `None`, because the alternative is a dashboard that
  crashes on a bad `source_page`.
* `typeset_pdf` — ADR-021. Determinism is the property that matters: a clause
  located on page 4 must still be on page 4 tomorrow, or every stored
  `source_page` silently rots.
* `ensure_pdf` — pick the real PDF or typeset one, and cache the result.

Run: `pytest tests/test_pdf_renderer.py -v`
"""

from __future__ import annotations

import pymupdf
import pytest

from core.extraction import pdf_renderer
from core.extraction.clause_locator import locate_clause
from core.extraction.pdf_renderer import (
    ensure_pdf,
    page_count,
    render_document_page,
    render_highlighted,
    typeset_pdf,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

TEXT = "\n\n".join(
    [
        "SERVICES AGREEMENT",
        "Section 1. The Provider shall supply the Services described in Schedule A.",
        "Section 2. The monthly fee of $6,000 shall be due on the fifteenth day of each month.",
        *[f"Section {n}. Boilerplate paragraph number {n} of no consequence." for n in range(3, 120)],
    ]
)


@pytest.fixture(scope="module")
def pdf() -> bytes:
    return typeset_pdf(TEXT, title="services_agreement.txt")


# ---------------------------------------------------------------------------
# typesetting a text-only document (ADR-021)
# ---------------------------------------------------------------------------


def test_typeset_output_is_a_real_multi_page_pdf(pdf):
    assert pdf.startswith(b"%PDF")
    assert page_count(pdf) > 1


def test_typesetting_is_deterministic():
    """Same text, same pagination — twice. A clause stored as "page 4" is a lie
    the moment this stops being true."""
    first, second = typeset_pdf(TEXT, title="x.txt"), typeset_pdf(TEXT, title="x.txt")
    assert page_count(first) == page_count(second)
    quote = "The monthly fee of $6,000 shall be due on the fifteenth day of each month."
    assert locate_clause(first, quote).page == locate_clause(second, quote).page


def test_the_typeset_page_is_searchable(pdf):
    """The whole point: a typeset page has to answer `page.search_for`, or the
    locator gains nothing from it."""
    location = locate_clause(pdf, "The monthly fee of $6,000 shall be due on the fifteenth day of each month.")
    assert location is not None and location.method == "exact"


def test_every_page_says_it_was_typeset(pdf):
    document = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        first_page = document[0].get_text()
    finally:
        document.close()
    # ADR-021: a page we laid out is evidence only while it is labelled as one.
    assert "typeset from the filing's text" in first_page


def test_an_unbreakable_token_is_cut_rather_than_run_off_the_page():
    """A 400-character run of dots in a filing's table of contents must not push
    text past the page edge, where `search_for` would never find it again."""
    pdf = typeset_pdf("Fees " + "." * 400 + " 12", title="dots.txt")
    document = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        width = document[0].rect.width
        blocks = document[0].get_text("blocks")
    finally:
        document.close()
    assert blocks and all(block[2] <= width for block in blocks)


def test_empty_text_still_produces_a_page():
    assert page_count(typeset_pdf("", title="empty.txt")) >= 1


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def test_a_highlighted_page_is_a_png(pdf):
    image = render_highlighted(pdf, 1, [56.0, 100.0, 400.0, 140.0])
    assert image and image.startswith(PNG_MAGIC)


def test_a_page_renders_without_a_box(pdf):
    """ADR-005: `bbox=None` renders the page, it does not fail. An ungrounded
    quote still gets its page."""
    image = render_highlighted(pdf, 1, None)
    assert image and image.startswith(PNG_MAGIC)


def test_the_highlight_changes_the_pixels(pdf):
    """Not just 'a PNG came back' — the box has to actually be drawn."""
    plain = render_highlighted(pdf, 1, None, dpi=72)
    boxed = render_highlighted(pdf, 1, [56.0, 100.0, 500.0, 160.0], dpi=72)
    assert plain != boxed


def test_a_page_past_the_end_is_none_not_an_exception(pdf):
    assert render_highlighted(pdf, 9_999, None) is None
    assert render_highlighted(pdf, 0, None) is None


def test_unreadable_input_is_none_not_an_exception(tmp_path):
    assert render_highlighted(b"not a pdf", 1, None) is None
    assert render_highlighted(tmp_path / "missing.pdf", 1, None) is None
    assert page_count(b"not a pdf") == 0


# ---------------------------------------------------------------------------
# ensure_pdf / render_document_page
# ---------------------------------------------------------------------------


def test_a_text_only_document_is_typeset_and_marked_as_such(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_renderer, "CACHE_DIR", tmp_path / "pdf")
    result = ensure_pdf(storage_url=None, extracted_text=TEXT, filename="agreement.txt", file_type="txt")
    assert result is not None
    path, is_typeset = result
    assert is_typeset is True
    assert path.exists() and path.read_bytes().startswith(b"%PDF")


def test_the_second_call_reuses_the_cached_file(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_renderer, "CACHE_DIR", tmp_path / "pdf")
    first, _ = ensure_pdf(storage_url=None, extracted_text=TEXT, filename="a.txt", file_type="txt")
    stamp = first.stat().st_mtime_ns
    second, _ = ensure_pdf(storage_url=None, extracted_text=TEXT, filename="a.txt", file_type="txt")
    assert second == first
    assert second.stat().st_mtime_ns == stamp  # not rewritten


def test_edited_text_lands_in_a_different_cache_entry(tmp_path, monkeypatch):
    """Content-addressed, for the same reason the Storage keys are (issue #20):
    a stale page is worse than a slow one."""
    monkeypatch.setattr(pdf_renderer, "CACHE_DIR", tmp_path / "pdf")
    first, _ = ensure_pdf(storage_url=None, extracted_text=TEXT, filename="a.txt", file_type="txt")
    second, _ = ensure_pdf(storage_url=None, extracted_text=TEXT + " Amended.", filename="a.txt", file_type="txt")
    assert first != second


def test_a_document_with_nothing_behind_it_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_renderer, "CACHE_DIR", tmp_path / "pdf")
    assert ensure_pdf(storage_url=None, extracted_text=None, filename="ghost.csv", file_type="csv") is None
    assert ensure_pdf(storage_url=None, extracted_text="   ", filename="blank.txt", file_type="txt") is None


def test_render_document_page_returns_the_image_and_the_typeset_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_renderer, "CACHE_DIR", tmp_path / "pdf")
    rendered = render_document_page(
        storage_url=None,
        extracted_text=TEXT,
        filename="agreement.txt",
        file_type="txt",
        page=2,
        bbox=[56.0, 100.0, 400.0, 140.0],
    )
    assert rendered is not None
    image, is_typeset = rendered
    assert image.startswith(PNG_MAGIC)
    assert is_typeset is True


def test_a_clause_with_no_page_falls_back_to_the_first(tmp_path, monkeypatch):
    """`page=None` is an ungrounded quote. Showing the document's first page
    beats showing nothing at all."""
    monkeypatch.setattr(pdf_renderer, "CACHE_DIR", tmp_path / "pdf")
    rendered = render_document_page(
        storage_url=None, extracted_text=TEXT, filename="a.txt", file_type="txt", page=None, bbox=None
    )
    assert rendered is not None and rendered[0].startswith(PNG_MAGIC)
