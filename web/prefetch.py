"""[B] Run independent database reads at the same time. Phase 6.

**Why this exists, and where it is worth using — which is narrower than it
looks.** `web/cache.py` explains that a live page costs `queries × round-trip`
and nothing else: the SQL is trivial, the distance to `ap-southeast-1` is not.
That module attacks the *second* render by caching. This one attacks the
*first*, by overlapping round trips that were sequential only because Python is.

The catch, measured on 2026-08-19 rather than assumed: **a concurrent read is
not free.** Each job needs a Session of its own, and each Session pays a pooled
checkout (`pool_pre_ping` is one full round trip) and a rollback on close
(another). That is roughly 350 ms of tax per job on this link. So the gather
wins only when there is more than that much to overlap.

A/B over eight renders each, run twice:

    Decision page    3 independent reads   2.10s -> 1.74s   keep
    Integrity page   2 reads, one of them
                     a helper issuing 3
                     statements in a row   2.15s -> 2.85s   reverted
    Finding detail   3 reads, 5 statements 1.74s -> 1.74s   reverted

So there is exactly one call site today, in `live.decision`. **Do not spread
this without measuring**; on this link the variance between renders is close to
a second, so a single sample proves nothing.

**A Session is not thread-safe**, so every job gets its own — which is the whole
cost above. That is safe here because every `core.db.queries` helper returns
plain dataclasses built from the rows, never live ORM objects, so a result can
outlive the session that fetched it. If a helper is ever changed to return a
`Base` subclass, it must not be gathered here: it would raise
`DetachedInstanceError` on the first attribute a template touched.

**It is strictly best-effort.** A job that fails is dropped from the results and
the caller falls back to reading it sequentially on its own session. So this
module can make a page faster and it can make a page no faster, but it cannot
change what a page says or raise an error the sequential path would not have.
That property is worth more than the milliseconds.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from sqlalchemy.orm import Session

from web import cache as web_cache

log = logging.getLogger(__name__)

#: Ceiling on connections one render may hold at once. The engine's pool is
#: SQLAlchemy's default 5 with 10 overflow, so four concurrent readers leaves
#: room for other requests rather than starving them. No caller asks for more
#: than three today; the ceiling is here so a future one cannot quietly turn a
#: page into a connection storm.
MAX_WORKERS = 4

#: A job is `(cache_key, fn)` where `fn` takes a Session of its own.
Job = tuple[Any, Callable[[Session], Any]]


def gather(jobs: list[Job], *, enabled: bool = True) -> dict[Any, Any]:
    """Run `jobs` concurrently and return `{key: value}` for those that worked.

    A key missing from the result is not an error — it means "read this one the
    ordinary way". Callers must handle that, which is why every call site here
    is written as a lookup with a sequential fallback rather than an index.

    `enabled` is passed through to `web.cache`: True lets the results serve the
    next request too, False runs the read without touching the TTL cache — for
    a caller whose *assembled* result is already cached, where caching the parts
    as well would only fill the store with entries nothing reads.

    Fewer than two jobs is not worth a thread or a second connection, so it
    returns `{}` and lets the caller's own session do the work.
    """
    if len(jobs) < 2:
        return {}

    results: dict[Any, Any] = {}
    with ThreadPoolExecutor(
        max_workers=min(len(jobs), MAX_WORKERS), thread_name_prefix="finsight-read"
    ) as pool:
        for future in [pool.submit(_run, key, fn, enabled) for key, fn in jobs]:
            results.update(future.result())  # _run never raises
    return results


def _run(key: Any, fn: Callable[[Session], Any], enabled: bool) -> dict[Any, Any]:
    """One read, on a Session of its own. Returns `{}` instead of raising."""
    from core.db import database

    try:
        session = database.get_session()
    except Exception as exc:  # noqa: BLE001 - a prefetch may never break a page
        log.debug("prefetch %r could not open a session: %s", key, exc)
        return {}

    try:
        return {key: web_cache.get_or_set(key, lambda: fn(session), enabled=enabled)}
    except Exception as exc:  # noqa: BLE001
        log.warning("prefetch %r failed; falling back to a sequential read: %s", key, exc)
        return {}
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover - closing a dead session
            pass
