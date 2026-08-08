"""[B] Resolved configuration: .env locally, st.secrets when deployed. Phase 0.

One `settings` object for the whole project. Nothing else reads os.environ.

Resolution order for every variable:
    1. a real environment variable
    2. .env  (local development, loaded into the environment by python-dotenv)
    3. st.secrets  (Streamlit Community Cloud, where there is no .env)
    4. the default declared below

Call `settings.validate()` at startup. It raises ConfigError naming every
missing required variable, because a beginner debugging a silent `None` API
key loses an hour and a startup error that names the variable costs thirty
seconds.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
SQLITE_FALLBACK = f"sqlite:///{PROJECT_ROOT / 'data' / 'finsight.db'}"

#: Where each provider's OpenAI-compatible endpoint lives. Only the active
#: provider's URL is required. These are OUR notebook sessions, not vendors
#: (ADR-011) — and the URL changes every time a session restarts.
PROVIDER_ENDPOINT = {
    "colab_tunnel": "COLAB_TUNNEL_URL",
    "kaggle_tunnel": "KAGGLE_TUNNEL_URL",
    "custom": "CUSTOM_BASE_URL",
}

#: Base weights we serve from Phase 5. Phase 10 swaps this for the tuned
#: adapter's served name; that single value is the whole comparison (ADR-012).
DEFAULT_MODEL = "Qwen/Qwen2.5-3B-Instruct"

#: A cold start loads 3B of weights before answering the first request.
DEFAULT_TIMEOUT_SECONDS = 120


class ConfigError(RuntimeError):
    """Raised at startup when a required variable is missing or invalid."""


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------


def _load_dotenv() -> bool:
    """Load .env into the environment. Returns whether a file was found.

    python-dotenv is optional at import time: on Streamlit Cloud there is no
    .env and the package may not have been installed yet during setup.
    """
    if not ENV_PATH.is_file():
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - depends on install state
        return False
    load_dotenv(ENV_PATH, override=False)
    return True


def _streamlit_secrets() -> dict[str, str]:
    """Return st.secrets as a flat dict, or {} outside Streamlit.

    Accessing st.secrets with no secrets file configured raises, so every
    failure mode here means "no secrets available", not an error.
    """
    try:
        import streamlit as st

        return {str(k): str(v) for k, v in st.secrets.items()}
    except Exception:
        return {}


#: Unedited placeholders from .env.example. Treated as "not set" so a
#: half-filled .env fails at startup rather than at the first connection.
_PLACEHOLDERS = ("[PASSWORD]", "[REF]")


def _read(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        value = _SECRETS.get(name)
    if value is None:
        return default
    value = value.strip()
    # python-dotenv strips an inline "# comment" only when the variable has a
    # value; on a BLANK one the comment text is handed back as the value. That
    # turned an unset tunnel URL into a ✅ on the config page — the exact
    # opposite of failing loudly. A value that starts with '#' is never real.
    if value.startswith("#"):
        return default
    if not value or any(p in value for p in _PLACEHOLDERS):
        return default
    return value


def _read_int(name: str, default: int) -> int:
    raw = _read(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _read_bool(name: str, default: bool) -> bool:
    raw = _read(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


_DOTENV_FOUND = _load_dotenv()
_SECRETS = _streamlit_secrets()


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Setting:
    """One configuration variable, for display and for validation."""

    name: str
    value: str | None
    required: bool
    secret: bool
    note: str

    @property
    def present(self) -> bool:
        return bool(self.value)

    @property
    def display(self) -> str:
        if not self.value:
            return "—"
        return mask(self.value) if self.secret else self.value

    @property
    def status(self) -> str:
        if self.present:
            return "✅"
        return "❌" if self.required else "⚪"


@dataclass(frozen=True)
class Settings:
    """Every variable the project reads, resolved once."""

    database_url: str | None
    supabase_url: str | None
    supabase_key: str | None
    #: service_role key. Bypasses RLS, so Storage works against a fully private
    #: bucket with no policies. Streamlit renders server-side and never ships
    #: this to a browser — that is the condition that makes it safe here.
    #: NEVER log it, never render it unmasked, never commit it.
    supabase_service_key: str | None
    llm_provider: str
    llm_model: str
    colab_tunnel_url: str | None
    kaggle_tunnel_url: str | None
    custom_base_url: str | None
    llm_api_key: str | None
    llm_timeout_seconds: int
    hf_token: str | None
    llm_cache_enabled: bool
    log_level: str

    # ---- derived ----

    @property
    def dotenv_found(self) -> bool:
        return _DOTENV_FOUND

    @property
    def secrets_found(self) -> bool:
        return bool(_SECRETS)

    @property
    def source(self) -> str:
        if self.secrets_found:
            return "st.secrets (deployed)"
        if self.dotenv_found:
            return f"{ENV_PATH.name} (local)"
        return "environment only"

    @property
    def resolved_database_url(self) -> str:
        """What Phase 1's `database.py` will actually connect to."""
        return self.database_url or SQLITE_FALLBACK

    @property
    def using_sqlite_fallback(self) -> bool:
        return not self.database_url

    @property
    def active_endpoint_name(self) -> str:
        """The env var holding the active provider's base URL."""
        return PROVIDER_ENDPOINT.get(self.llm_provider, "COLAB_TUNNEL_URL")

    @property
    def active_base_url(self) -> str | None:
        """Raw value of the active endpoint variable."""
        return {
            "COLAB_TUNNEL_URL": self.colab_tunnel_url,
            "KAGGLE_TUNNEL_URL": self.kaggle_tunnel_url,
            "CUSTOM_BASE_URL": self.custom_base_url,
        }.get(self.active_endpoint_name)

    @property
    def api_base(self) -> str | None:
        """Normalised base URL for llm_client: no trailing slash, no /v1.

        The tunnel URL is pasted in by hand after every notebook restart, so
        tolerate the shapes people actually paste.
        """
        url = self.active_base_url
        if not url:
            return None
        url = url.rstrip("/")
        for suffix in ("/v1/chat/completions", "/v1"):
            if url.endswith(suffix):
                url = url[: -len(suffix)]
        return url

    # ---- inspection ----

    def checks(self) -> list[Setting]:
        """Every variable with its status. Drives the config page and validate()."""
        endpoint = self.active_endpoint_name
        return [
            Setting("LLM_PROVIDER", self.llm_provider, True, False,
                    "ADR-002: the one variable that swaps endpoint"),
            Setting("LLM_MODEL", self.llm_model, True, False,
                    "ADR-012: base weights now, tuned adapter from Phase 10"),
            Setting(endpoint, self.active_base_url, True, False,
                    f"Our {self.llm_provider} endpoint — CHANGES ON EVERY NOTEBOOK RESTART"),
            Setting("LLM_API_KEY", self.llm_api_key, True, True,
                    "Shared secret. The tunnel is a PUBLIC URL — never run it open"),
            Setting("LLM_TIMEOUT_SECONDS", str(self.llm_timeout_seconds), False, False,
                    "Cold starts load 3B of weights before the first answer"),
            Setting("DATABASE_URL", self.database_url, False, True, f"Falls back to {SQLITE_FALLBACK}"),
            Setting("SUPABASE_URL", self.supabase_url, False, False, "Needed from Phase 2 (file storage)"),
            Setting("SUPABASE_KEY", self.supabase_key, False, True, "anon key — safe to publish"),
            Setting("SUPABASE_SERVICE_KEY", self.supabase_service_key, False, True,
                    "service_role — SERVER ONLY. Writes to the private Storage bucket"),
            Setting("HF_TOKEN", self.hf_token, False, True, "Needed from Phase 3 (datasets) and Phase 5 (weights)"),
            Setting("LLM_CACHE_ENABLED", str(self.llm_cache_enabled).lower(), False, False,
                    "Also what keeps a demo alive when the tunnel dies"),
            Setting("LOG_LEVEL", self.log_level, False, False, "DEBUG | INFO | WARNING | ERROR"),
        ]

    def missing_required(self) -> list[Setting]:
        return [c for c in self.checks() if c.required and not c.present]

    def validate(self) -> None:
        """Raise ConfigError naming everything that is missing or invalid."""
        problems: list[str] = []

        if self.llm_provider not in PROVIDER_ENDPOINT:
            problems.append(
                f"LLM_PROVIDER={self.llm_provider!r} is not one of "
                f"{' | '.join(PROVIDER_ENDPOINT)}"
            )

        url = self.active_base_url
        if url and not url.startswith(("http://", "https://")):
            problems.append(
                f"{self.active_endpoint_name}={url!r} is not a URL — paste the "
                "full https://... the notebook printed"
            )

        for setting in self.missing_required():
            problems.append(f"{setting.name} is not set — {setting.note}")

        if problems:
            raise ConfigError(
                "FinSight cannot start. Fix these in "
                f"{ENV_PATH if not self.secrets_found else 'Streamlit Secrets'}:\n  - "
                + "\n  - ".join(problems)
                + "\n\nCopy .env.example to .env and fill it in."
            )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def mask(value: str, head: int = 4, tail: int = 4) -> str:
    """Mask a secret for display: 'AIzaSyD...4f2a'."""
    if not value:
        return "—"
    if len(value) <= head + tail:
        return "•" * len(value)
    return f"{value[:head]}...{value[-tail:]}"


def configure_logging(level: str | None = None) -> None:
    """Apply LOG_LEVEL once, at process start."""
    logging.basicConfig(
        level=(level or settings.log_level).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Resolve every variable once per process."""
    provider = (_read("LLM_PROVIDER", "colab_tunnel") or "colab_tunnel").lower()
    return Settings(
        database_url=_read("DATABASE_URL"),
        supabase_url=_read("SUPABASE_URL"),
        supabase_key=_read("SUPABASE_KEY"),
        supabase_service_key=_read("SUPABASE_SERVICE_KEY"),
        llm_provider=provider,
        llm_model=_read("LLM_MODEL", DEFAULT_MODEL) or "",
        colab_tunnel_url=_read("COLAB_TUNNEL_URL"),
        kaggle_tunnel_url=_read("KAGGLE_TUNNEL_URL"),
        custom_base_url=_read("CUSTOM_BASE_URL"),
        llm_api_key=_read("LLM_API_KEY"),
        llm_timeout_seconds=_read_int("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        hf_token=_read("HF_TOKEN"),
        llm_cache_enabled=_read_bool("LLM_CACHE_ENABLED", True),
        log_level=(_read("LOG_LEVEL", "INFO") or "INFO").upper(),
    )


#: The one settings object. Import this, never os.environ.
settings = get_settings()
