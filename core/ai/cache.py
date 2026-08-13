"""[B] Disk cache keyed by sha256(prompt + model). Phase 5.

Not an optimisation. Three separate things depend on it:

* the same ten contracts get re-extracted fifty times while a prompt is being
  tuned, and each miss is a real GPU round trip;
* a cold start is minutes, so the first call of a session is expensive;
* **anything already cached still answers after the notebook session dies.**
  Pre-warming every demo document is the difference between a dead tunnel
  ruining a demo and nobody noticing.

The key deliberately does **not** include the endpoint. Colab and Kaggle serve
the same weights under the same name, so a response cached from one must hit
from the other — that is what makes the two hosts interchangeable rather than
merely both available.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from core.config import PROJECT_ROOT, settings

log = logging.getLogger(__name__)

CACHE_DIR = PROJECT_ROOT / "data" / "cache"


@dataclass(frozen=True)
class CacheStats:
    entries: int
    bytes: int
    oldest: float | None
    newest: float | None


def enabled() -> bool:
    return settings.llm_cache_enabled


def key(prompt: str, model: str, system: str = "", **extra: object) -> str:
    """sha256 over everything that changes the answer.

    The plan says `sha256(prompt + model)`. System prompt, temperature and the
    requested response format are folded in too: `prompts.py` versions its
    templates, and a cache that returned a free-text answer to a JSON-mode
    request would be a very confusing bug to find.
    """
    payload = json.dumps(
        {"model": model, "system": system, "prompt": prompt, **extra},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _path(cache_key: str) -> Path:
    # Two-character shard: a flat directory of a few thousand files is slow to
    # list on every platform we deploy to.
    return CACHE_DIR / cache_key[:2] / f"{cache_key}.json"


def get(cache_key: str) -> str | None:
    """The cached completion text, or None. Never raises."""
    if not enabled():
        return None
    try:
        record = json.loads(_path(cache_key).read_text(encoding="utf-8"))
        return record.get("response")
    except FileNotFoundError:
        return None
    except Exception as exc:
        log.warning("unreadable cache entry %s: %s", cache_key[:12], exc)
        return None


def put(cache_key: str, response: str, *, model: str = "", preview: str = "") -> None:
    """Write atomically. A half-written entry read by the next process is worse
    than a miss."""
    if not enabled():
        return
    target = _path(cache_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "response": response,
        "model": model,
        # First line of the prompt, so `ls`-ing the cache tells you something.
        "preview": preview[:200],
        "created": time.time(),
    }
    try:
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, delete=False
        )
        try:
            json.dump(record, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, target)
    except Exception as exc:  # a full disk must not break extraction
        log.warning("could not write cache entry %s: %s", cache_key[:12], exc)


def stats() -> CacheStats:
    entries = list(CACHE_DIR.glob("*/*.json")) if CACHE_DIR.is_dir() else []
    if not entries:
        return CacheStats(0, 0, None, None)
    times = [entry.stat().st_mtime for entry in entries]
    return CacheStats(
        entries=len(entries),
        bytes=sum(entry.stat().st_size for entry in entries),
        oldest=min(times),
        newest=max(times),
    )


def clear() -> int:
    """Delete every entry. Returns how many. Used when a prompt version changes
    and the old answers are actively misleading."""
    removed = 0
    for entry in CACHE_DIR.glob("*/*.json"):
        entry.unlink(missing_ok=True)
        removed += 1
    return removed
