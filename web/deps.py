"""[B] Per-request plumbing: the data mode, the session, the query carry-over. Phase 6.

The one non-obvious piece here is `db_or_none`. Live mode has to survive a
database that is unreachable — a bad `DATABASE_URL`, Supabase asleep, no
`data/finsight.db` yet — because the page that would tell you so is this page.
So the session is opened defensively and a failure downgrades the request to an
empty view with a stated reason, rather than a 500 with a stack trace.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from html import escape
from urllib.parse import urlencode

from fastapi import Request

from web.settings import MODE_COOKIE, resolve_mode

#: Query parameters that identify *what you are looking at* and should survive
#: a tab switch. `sel` and `q` belong to one page each and are not carried.
CARRIED = ("state", "run", "mode", "sort")


def request_mode(request: Request) -> str:
    """Data mode for this request: ?mode= wins, then the cookie, then the env."""
    return resolve_mode(
        request.cookies.get(MODE_COOKIE),
        request.query_params.get("mode"),
    )


def carry(request: Request, **overrides: str | None) -> str:
    """The carried query string, with overrides applied. Includes the '?'.

    Returns "" when there is nothing to carry, so it can be concatenated onto
    a URL unconditionally.
    """
    params = {k: v for k, v in request.query_params.items() if k in CARRIED}
    for key, value in overrides.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    return f"?{urlencode(params)}" if params else ""


def carry_hidden_fields(request: Request, exclude: tuple[str, ...] = ()) -> str:
    """The same carried parameters as hidden <input>s, for a GET form.

    A form submit replaces the whole query string, so anything not restated as
    a field is silently dropped — which is how asking a question would knock
    you back to the default run. `exclude` drops a parameter the form supplies
    itself, so the run picker does not emit two `run` values.
    """
    params = {
        k: v for k, v in request.query_params.items() if k in CARRIED and k not in exclude
    }
    return "".join(
        f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">'
        for k, v in params.items()
    )


def select_url(request: Request, path: str) -> str:
    """A URL ending in ``sel=`` so a row id can be appended to it."""
    params = {k: v for k, v in request.query_params.items() if k in CARRIED}
    query = urlencode(params)
    return f"{path}?{query}&sel=" if query else f"{path}?sel="


def sort_url(request: Request, path: str) -> str:
    """A URL ending in ``sort=``. Keeps the selected finding across a re-sort —
    re-ordering the list should not throw away what you were reading."""
    params = {
        k: v for k, v in request.query_params.items() if k in CARRIED and k != "sort"
    }
    if "sel" in request.query_params:
        params["sel"] = request.query_params["sel"]
    query = urlencode(params)
    return f"{path}?{query}&sort=" if query else f"{path}?sort="


def ask_url(request: Request, path: str) -> str:
    """A URL ending in ``q=`` so a suggested question can be appended."""
    params = {k: v for k, v in request.query_params.items() if k in CARRIED}
    query = urlencode(params)
    return f"{path}?{query}&q=" if query else f"{path}?q="


@contextmanager
def db_or_none(request: Request | None = None) -> Iterator[object | None]:
    """A read session, or None when the database cannot be reached.

    Yields None rather than raising so the caller can render an honest empty
    page. The reason is available from `last_db_error()`.

    Passing the request lets ``?fresh=1`` bypass the read cache for that one
    render — the flag is stamped on the session because the presenters have no
    request of their own.
    """
    global _LAST_DB_ERROR
    fresh = bool(request and request.query_params.get("fresh"))
    try:
        from core.db import database

        with database.session_scope() as session:
            _LAST_DB_ERROR = None
            if fresh:
                session._finsight_fresh = True  # type: ignore[attr-defined]
            yield session
    except Exception as exc:  # noqa: BLE001 - the whole point is not to raise
        _LAST_DB_ERROR = f"{type(exc).__name__}: {exc}"
        yield None


_LAST_DB_ERROR: str | None = None


def last_db_error() -> str | None:
    """Why the last `db_or_none` yielded None, if it did."""
    return _LAST_DB_ERROR
