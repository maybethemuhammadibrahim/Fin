"""[B] Which path an upload takes, and which extensions are offered. Phase 2/4.

Two defects found by driving the real uploader over real files on 2026-08-19,
both of them the kind that a passing test suite would never have noticed because
nothing threw:

* **A .csv could be recorded as `complete` having imported nothing.** The zone
  had a radio — "CSV / spreadsheet" vs "Scanned image or PDF" — and it, not the
  file, decided the category. A .csv dropped on the wrong setting was tagged
  `invoice`, skipped the column-mapping step (the only thing that ever writes
  `actual_transactions`), and showed a green tick over zero rows of money.
  Reconciliation then reads a full expected timeline against no payments and
  calls every billing a ghost invoice. `ingest.actuals_category` replaced the radio.

* **`.xlsx` was offered and always failed**, exactly as `.docx` had before the
  2026-08-17 audit removed it. The list must only advertise what
  `document_router.detect_type()` can route.

These tests are about *routing and advertising*, so they touch no database and no
storage. Extraction itself is covered where it lives.

Run: `pytest tests/test_file_uploader.py -v`
"""

from __future__ import annotations

import pymupdf
import pytest

from core.extraction import document_router
from core.ingest import ACTUALS_TYPES, CONTRACT_TYPES, actuals_category


# ---------------------------------------------------------------------------
# Routing: the file decides, not a control
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    ["statement.csv", "STATEMENT.CSV", "Q1 export.Csv", "weird.name.csv"],
)
def test_every_csv_goes_to_the_column_mapping_path(filename):
    """The regression. A .csv is a statement whatever it is called and whatever
    else was uploaded beside it — `statement` is what holds it at `pending` for
    the mapping step that writes `actual_transactions`."""
    assert actuals_category(filename) == "statement"


@pytest.mark.parametrize(
    "filename", ["invoice.pdf", "scan.PNG", "photo.jpg", "receipt.jpeg"]
)
def test_non_csv_actuals_are_extracted_immediately(filename):
    assert actuals_category(filename) == "invoice"


def test_a_pdf_is_never_held_for_a_column_mapping():
    """A PDF tagged `statement` was a dead end: the mapping step parses only
    .csv, so such a row could only ever finish as `failed`. Nothing may route
    one there."""
    assert actuals_category("bank_statement.pdf") != "statement"


# ---------------------------------------------------------------------------
# Advertising: offer nothing that cannot be read
# ---------------------------------------------------------------------------


def test_every_offered_extension_can_actually_be_routed(tmp_path):
    """The `.docx` / `.xlsx` trap, as a test rather than an audit finding.

    `detect_type` raises ValueError on an extension it cannot place. Offering
    one in the file picker turns that into a failed upload for the user every
    single time, which reads as a broken app rather than an unbuilt feature.
    """
    for extension in set(CONTRACT_TYPES) | set(ACTUALS_TYPES):
        probe = tmp_path / f"probe.{extension}"
        if extension == "pdf":
            # A real one-page PDF. `detect_type` opens a .pdf to measure its
            # character density, and raises the same ValueError for "corrupt" as
            # for "unsupported" — so a fake would fail this test for the wrong
            # reason. (That shared exception type is deliberate: both end up as
            # extraction_status='failed' with a readable message.)
            document = pymupdf.open()
            document.new_page()
            document.save(probe)
            document.close()
        else:
            probe.write_bytes(b"x")
        try:
            document_router.detect_type(probe)
        except ValueError as exc:  # pragma: no cover - the failure we are barring
            pytest.fail(f".{extension} is offered in the uploader but {exc}")


def test_xlsx_is_not_offered():
    """Removed 2026-08-19. Known issue #38 stays open — spreadsheets still are
    not readable — but the uploader no longer claims otherwise. If xlsx support
    is ever built, delete this test in the same commit that adds it."""
    assert "xlsx" not in ACTUALS_TYPES
    with pytest.raises(ValueError):
        document_router.detect_type("book.xlsx")
