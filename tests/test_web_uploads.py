"""[B] `web/` uploads: the write path, end to end. ADR-025.

Drives the real routes against a real (temporary) database and real files —
`TestClient` posts multipart exactly as a browser does, `core.ingest` saves and
reads for real, and the assertions are about what ends up in the tables.

Three of these exist because of bugs found by running the thing, not by reading
it, and they are the ones to keep if this file is ever trimmed:

* **an empty file input is not an empty list.** A browser posts a part with
  `filename=""` for a zone the user left alone. Starlette parses that as a
  string, so a `list[UploadFile]` parameter 422s — on the ordinary path of
  "contracts today, no statement".
* **a `.csv` must never finish on the POST.** It has to reach the column
  mapping, because that is the only thing that writes `actual_transactions`.
  The version of this bug in the Streamlit uploader showed a green tick over
  zero imported rows.
* **every write clears the read cache.** With `WEB_CACHE_SECONDS` at 300 a
  missed `clear()` means the upload appears not to have happened for five
  minutes.

Run: `pytest tests/test_web_uploads.py -v`
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core.db import database  # noqa: E402
from core.db.models import ActualTransaction, Document  # noqa: E402
from core.db.queries import create_run  # noqa: E402

CSV = b"date,description,amount\n2025-01-02,Regal INV-1,6000.00\n2025-02-02,Regal INV-2,6000.00\n"
CONTRACT = b"MASTER SERVICES AGREEMENT\n\nFees: $6,000 per month, payable monthly in advance.\n"

#: A browser sends this for a file input the user never touched.
EMPTY_PART = ("", b"", "application/octet-stream")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A live-mode app over a throwaway SQLite file and local file storage.

    **Setting environment variables here would not be enough, and the first
    version of this fixture that tried it wrote eleven runs and nine documents
    into the project's real Supabase database and its Storage bucket.** The
    reason is one line in `core/config.py`: `settings = get_settings()` builds a
    frozen instance at *import* time, and `core/db/database.py` and
    `core/storage/files.py` then do `from core.config import settings`, binding
    that object directly. By the time a fixture runs, changing `os.environ` and
    clearing the `lru_cache` changes nothing anybody is still reading.

    So the object itself is swapped, in every module that holds a reference —
    and then the resolved URL is *asserted* to be SQLite before a single row is
    written. The assertion is the part that matters: patching can be got wrong
    again, and the cost of getting it wrong is silent writes to production data
    that look exactly like a passing test.
    """
    import dataclasses

    import core.config
    from core.db import database as db_module
    from core.storage import files as files_module

    fake = dataclasses.replace(
        core.config.settings,
        database_url=f"sqlite:///{tmp_path / 'web.db'}",
        supabase_url=None,
        supabase_key=None,
        supabase_service_key=None,
    )
    for module in (core.config, db_module, files_module):
        monkeypatch.setattr(module, "settings", fake, raising=False)

    monkeypatch.setenv("WEB_DATA_MODE", "live")
    monkeypatch.setenv("WEB_CACHE_SECONDS", "300")
    monkeypatch.chdir(tmp_path)  # local storage writes under data/uploads/ here

    database.reset_engine()
    resolved = str(database.get_engine().url)
    assert resolved.startswith("sqlite"), (
        f"refusing to run: this test would write to {resolved!r}, not a temporary file"
    )
    assert not files_module.is_cloud(), "refusing to run: uploads would go to real Storage"

    database.init_db()
    with database.session_scope() as session:
        create_run(session, "upload test run")

    from web.main import app

    yield TestClient(app)

    database.reset_engine()


def _documents():
    with database.session_scope() as session:
        return [
            (d.filename, d.category, d.extraction_status)
            for d in session.query(Document).all()
        ]


def _transaction_total():
    with database.session_scope() as session:
        return session.query(ActualTransaction).count(), sum(
            t.amount for t in session.query(ActualTransaction)
        )


# ---------------------------------------------------------------------------
# The happy paths
# ---------------------------------------------------------------------------


def test_a_contract_uploads_and_is_read_on_the_spot(client):
    response = client.post(
        "/upload?mode=live",
        files=[("contracts", ("msa.txt", CONTRACT, "text/plain"))],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "ok=1" in response.headers["location"]
    assert _documents() == [("msa.txt", "contract", "complete")]


def test_a_csv_is_held_for_its_column_mapping_and_then_imports(client):
    """The whole two-step flow, which is the only way money enters a run."""
    posted = client.post(
        "/upload?mode=live",
        files=[("actuals", ("statement.csv", CSV, "text/csv"))],
        follow_redirects=False,
    )
    location = posted.headers["location"]
    assert "/columns" in location, "a .csv must go to the mapper, never straight to done"
    assert _documents() == [("statement.csv", "statement", "pending")]
    assert _transaction_total() == (0, 0), "nothing may be parsed before confirmation"

    form = client.get(location)
    assert form.status_code == 200
    assert "Which column is the date" in form.text

    document_id = int(re.search(r"/upload/(\d+)/columns", location).group(1))
    confirmed = client.post(
        f"/upload/{document_id}/columns?mode=live",
        data={"date": "date", "amount": "amount", "description": "description"},
        follow_redirects=False,
    )
    assert confirmed.status_code == 303
    assert "imported=2" in confirmed.headers["location"]
    assert _transaction_total() == (2, 12000.0)
    assert _documents() == [("statement.csv", "statement", "complete")]


def test_both_zones_in_one_submission(client):
    client.post(
        "/upload?mode=live",
        files=[
            ("contracts", ("msa.txt", CONTRACT, "text/plain")),
            ("actuals", ("statement.csv", CSV, "text/csv")),
        ],
        follow_redirects=False,
    )
    assert sorted(_documents()) == [
        ("msa.txt", "contract", "complete"),
        ("statement.csv", "statement", "pending"),
    ]


# ---------------------------------------------------------------------------
# The three bugs found by running it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(
            [("contracts", EMPTY_PART), ("actuals", EMPTY_PART)], id="both zones empty"
        ),
        pytest.param(
            [("contracts", ("msa.txt", CONTRACT, "text/plain")), ("actuals", EMPTY_PART)],
            id="contracts only",
        ),
        pytest.param(
            [("contracts", EMPTY_PART), ("actuals", ("statement.csv", CSV, "text/csv"))],
            id="actuals only",
        ),
    ],
)
def test_an_untouched_file_input_is_not_an_error(client, files):
    """The 422. A zone the user left alone still posts a part, and it must read
    as "nothing here" rather than as a validation failure."""
    response = client.post("/upload?mode=live", files=files, follow_redirects=False)
    assert response.status_code == 303, response.text[:200]


def test_writing_clears_the_read_cache(client):
    from web import cache as web_cache

    client.get("/?mode=live&state=processing")  # populate
    assert web_cache.stats()["entries"] > 0
    client.post(
        "/upload?mode=live",
        files=[("contracts", ("msa.txt", CONTRACT, "text/plain"))],
        follow_redirects=False,
    )
    assert web_cache.stats()["entries"] == 0, "ADR-025: a write must bust the cache"


def test_the_same_file_twice_does_not_duplicate(client):
    for _ in range(2):
        response = client.post(
            "/upload?mode=live",
            files=[("contracts", ("msa.txt", CONTRACT, "text/plain"))],
            follow_redirects=False,
        )
    assert "ok=0" in response.headers["location"]
    assert len(_documents()) == 1


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_demo_mode_cannot_write(client):
    response = client.post(
        "/upload?mode=demo",
        files=[("contracts", ("msa.txt", CONTRACT, "text/plain"))],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "err=demo" in response.headers["location"]
    assert _documents() == []


def test_a_mapping_without_an_amount_is_refused(client):
    """ADR-010's floor. Date and amount are required; description is not."""
    posted = client.post(
        "/upload?mode=live",
        files=[("actuals", ("statement.csv", CSV, "text/csv"))],
        follow_redirects=False,
    )
    document_id = int(re.search(r"/upload/(\d+)/columns", posted.headers["location"]).group(1))
    response = client.post(
        f"/upload/{document_id}/columns?mode=live",
        data={"date": "date", "amount": "", "description": "description"},
        follow_redirects=False,
    )
    assert "err=fields" in response.headers["location"]
    assert _transaction_total() == (0, 0)


def test_an_oversize_file_is_skipped_not_stored(client):
    from web.routers.uploads import MAX_UPLOAD_BYTES

    response = client.post(
        "/upload?mode=live",
        files=[("contracts", ("huge.txt", b"x" * (MAX_UPLOAD_BYTES + 1), "text/plain"))],
        follow_redirects=False,
    )
    assert "err=size" in response.headers["location"]
    assert _documents() == []
