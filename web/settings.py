"""[B] Settings for the FastAPI frontend. Phase 6.

Deliberately thin, and deliberately *not* part of `core/config.py`. That module
is the single reader of `os.environ` for everything the pipeline needs, and it
raises when a required LLM variable is missing. The web shell must start even
then — a config page that cannot render because the config is wrong is not much
of a config page — so the three variables here are read straight from the
environment with defaults that always work.

Resolution for the data mode, most specific first:

1. the ``mode`` cookie, set by clicking Demo / Live in the state bar;
2. ``WEB_DATA_MODE`` in the environment or ``.env``;
3. ``demo``.

So the environment sets the default the app boots into, and the on-page toggle
overrides it for that browser. Both halves of "in the env or on the website"
are there, and neither can strand you: clearing the cookie returns you to the
env's answer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

#: The only two data modes. `demo` renders the values baked into the mockup;
#: `live` renders whatever the database holds, dashes and skeletons included.
DATA_MODES = ("demo", "live")

#: Name of the cookie the on-page toggle writes.
MODE_COOKIE = "finsight_data_mode"

#: One year. The toggle is a workbench preference, not a session thing.
MODE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WebSettings:
    #: Mode the app boots into when the browser has no cookie yet.
    default_data_mode: str
    host: str
    port: int
    reload: bool
    #: The delivered mockup is a fixed 1440px art board centred on a grey
    #: ground. That framing is an artefact of how it was drawn, not part of the
    #: design, so the app fills the window by default. Set WEB_FLUID_WIDTH=false
    #: to restore the exact art board when comparing against the original file.
    fluid_width: bool

    @property
    def demo_by_default(self) -> bool:
        return self.default_data_mode == "demo"


@lru_cache(maxsize=1)
def get_web_settings() -> WebSettings:
    """Read once per process. The cookie, not this, is what varies per request."""
    # core.config loads the .env; importing it here means WEB_* variables can
    # live in the same file as everything else. It must never be allowed to
    # take the web server down, hence the bare except.
    try:
        from core.config import settings as _core_settings  # noqa: F401
    except Exception:  # pragma: no cover - config errors are the config page's job
        pass

    mode = _env("WEB_DATA_MODE", "demo").lower()
    if mode not in DATA_MODES:
        mode = "demo"

    return WebSettings(
        default_data_mode=mode,
        host=_env("WEB_HOST", "127.0.0.1"),
        port=int(_env("WEB_PORT", "8000")),
        reload=_env_bool("WEB_RELOAD", False),
        fluid_width=_env_bool("WEB_FLUID_WIDTH", True),
    )


def resolve_mode(cookie_value: str | None, query_value: str | None = None) -> str:
    """Pick the data mode for one request.

    `query_value` wins when present so a link like ``?mode=live`` works without
    touching the cookie — useful for a screenshot or a bug report that has to
    pin the mode. Otherwise the cookie, otherwise the environment's default.
    """
    for candidate in (query_value, cookie_value):
        if candidate and candidate.lower() in DATA_MODES:
            return candidate.lower()
    return get_web_settings().default_data_mode
