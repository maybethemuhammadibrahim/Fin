"""[B] A short-lived read cache for the live presenter. Phase 6.

**Why this exists, with the measurement.** The app renders a page in ~4 ms. The
Supabase instance this project uses sits in `ap-southeast-1`, and a single
`SELECT 1` from here has a **409 ms median round trip** — a fresh connection
costs 1.1 s. So the response time of a live page is, to within noise, `queries ×
400 ms` and nothing else. Reducing the count from 35 to 9 took a page from 8.7 s
to about 4 s. Getting below that is not an application problem; it is the speed
of light and a region choice.

So the reads are cached. Three things make that safe here rather than the usual
source of stale-data bugs:

* **The one write path clears this cache.** `web/routers/uploads.py` calls
  `clear()` after every successful upload and every confirmed column mapping
  (ADR-025). This used to read "web/ writes nothing", which was the whole
  safety argument until uploading landed — so if you add a second write path,
  **it must call `clear()` too**, immediately after its session commits. Miss it
  and the write appears not to have happened for the length of the TTL, which
  reads to a user as a broken button rather than a stale cache.
* **Everything else that changes the data changes it from outside this process**
  — `seed_demo.py`, `run_scenario.py`, the Streamlit app — and shows up on the
  next read after the TTL expires.
* **It is off by one flag.** `WEB_CACHE_SECONDS=0` disables it entirely, and
  `?fresh=1` on any URL bypasses it for that request.

Deliberately *not* used for demo mode, which touches no database and is already
4 ms, and *not* used as a fallback when a query fails — a failed read renders
the error, never the last good value under a fresh timestamp.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

#: Cheap enough to keep everything: entries are dataclass lists a few KB each,
#: and a run is scoped to one demo. Evicted by age, and by this ceiling so a
#: long-running process with many runs cannot grow without bound.
MAX_ENTRIES = 256


def ttl_seconds() -> float:
    """Read fresh each call so it can be changed without a restart in dev."""
    raw = os.environ.get("WEB_CACHE_SECONDS", "15").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 15.0


_lock = threading.Lock()
_store: dict[Any, tuple[float, Any]] = {}


def get_or_set(key: Any, build: Callable[[], Any], *, enabled: bool = True) -> Any:
    """Return the cached value for `key`, or build, store and return it.

    `build` runs **outside** the lock. Holding a lock across a 400 ms network
    query would serialise every request in the process behind the slowest one,
    which would cost more than the cache saves. Two requests racing for a cold
    key both do the work and the second overwrites the first — harmless, since
    they are reads of the same rows.
    """
    ttl = ttl_seconds()
    if not enabled or ttl <= 0:
        return build()

    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]

    value = build()

    with _lock:
        if len(_store) >= MAX_ENTRIES:
            # Drop the oldest quarter rather than one entry, so this scan runs
            # rarely instead of on every insert once full.
            for stale in sorted(_store, key=lambda k: _store[k][0])[: MAX_ENTRIES // 4]:
                _store.pop(stale, None)
        _store[key] = (time.monotonic(), value)
    return value


def clear() -> None:
    """Drop everything. For tests, and for a future write path to call."""
    with _lock:
        _store.clear()


def stats() -> dict[str, Any]:
    """What is cached right now, for the health page."""
    with _lock:
        return {"entries": len(_store), "ttl_seconds": ttl_seconds()}
