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

#: The credential each provider needs. Only the active provider's is required.
PROVIDER_CREDENTIAL = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "finetuned_tunnel": "FINETUNED_TUNNEL_URL",
}

#: Used only when LLM_MODEL is unset, so switching provider stays a one-liner.
PROVIDER_DEFAULT_MODEL = {
    "gemini": "gemini-2.5-flash",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "google/gemini-2.0-flash-exp:free",
    "finetuned_tunnel": "finsight-qwen2.5-3b",
}


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
    if not value or any(p in value for p in _PLACEHOLDERS):
        return default
    return value


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
    llm_provider: str
    llm_model: str
    gemini_api_key: str | None
    groq_api_key: str | None
    openrouter_api_key: str | None
    finetuned_tunnel_url: str | None
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
    def active_credential_name(self) -> str:
        return PROVIDER_CREDENTIAL.get(self.llm_provider, "GEMINI_API_KEY")

    @property
    def active_credential(self) -> str | None:
        return {
            "GEMINI_API_KEY": self.gemini_api_key,
            "GROQ_API_KEY": self.groq_api_key,
            "OPENROUTER_API_KEY": self.openrouter_api_key,
            "FINETUNED_TUNNEL_URL": self.finetuned_tunnel_url,
        }.get(self.active_credential_name)

    # ---- inspection ----

    def checks(self) -> list[Setting]:
        """Every variable with its status. Drives the config page and validate()."""
        active = self.active_credential_name
        return [
            Setting("LLM_PROVIDER", self.llm_provider, True, False, "ADR-002: the one variable that swaps providers"),
            Setting("LLM_MODEL", self.llm_model, True, False, "Defaults per provider"),
            Setting(
                active,
                self.active_credential,
                True,
                active != "FINETUNED_TUNNEL_URL",
                f"Credential for the active provider ({self.llm_provider})",
            ),
            Setting("DATABASE_URL", self.database_url, False, True, f"Falls back to {SQLITE_FALLBACK}"),
            Setting("SUPABASE_URL", self.supabase_url, False, False, "Needed from Phase 1 (file storage)"),
            Setting("SUPABASE_KEY", self.supabase_key, False, True, "Needed from Phase 1 (file storage)"),
            Setting("HF_TOKEN", self.hf_token, False, True, "Needed from Phase 3 (dataset downloads)"),
            Setting("LLM_CACHE_ENABLED", str(self.llm_cache_enabled).lower(), False, False, "Cache LLM responses on disk"),
            Setting("LOG_LEVEL", self.log_level, False, False, "DEBUG | INFO | WARNING | ERROR"),
        ]

    def missing_required(self) -> list[Setting]:
        return [c for c in self.checks() if c.required and not c.present]

    def validate(self) -> None:
        """Raise ConfigError naming everything that is missing or invalid."""
        problems: list[str] = []

        if self.llm_provider not in PROVIDER_CREDENTIAL:
            problems.append(
                f"LLM_PROVIDER={self.llm_provider!r} is not one of "
                f"{' | '.join(PROVIDER_CREDENTIAL)}"
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
    provider = (_read("LLM_PROVIDER", "gemini") or "gemini").lower()
    return Settings(
        database_url=_read("DATABASE_URL"),
        supabase_url=_read("SUPABASE_URL"),
        supabase_key=_read("SUPABASE_KEY"),
        llm_provider=provider,
        llm_model=_read("LLM_MODEL", PROVIDER_DEFAULT_MODEL.get(provider)) or "",
        gemini_api_key=_read("GEMINI_API_KEY"),
        groq_api_key=_read("GROQ_API_KEY"),
        openrouter_api_key=_read("OPENROUTER_API_KEY"),
        finetuned_tunnel_url=_read("FINETUNED_TUNNEL_URL"),
        hf_token=_read("HF_TOKEN"),
        llm_cache_enabled=_read_bool("LLM_CACHE_ENABLED", True),
        log_level=(_read("LOG_LEVEL", "INFO") or "INFO").upper(),
    )


#: The one settings object. Import this, never os.environ.
settings = get_settings()
