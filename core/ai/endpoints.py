"""[B] Which self-hosted endpoint is live right now, resolved at call time. Phase 5.

`core/config.py` reads `.env` **once per process** into a frozen `settings`
object. That is right for a database URL and wrong for a tunnel URL: the tunnel
rotates on every notebook restart, and ADR-002's promise that one variable swaps
the endpoint is worthless if honouring it costs a Streamlit restart.

So this module owns the *mutable* half of the LLM configuration. It layers a
small override file on top of `settings`:

    override file (data/endpoint_override.json)   <- the in-app switcher writes here
    .env / st.secrets via settings                <- the durable default

Precedence is override, then `.env`. Nothing here reads `os.environ` — that
remains `config.py`'s job alone.

Why a file rather than `st.session_state`: `scripts/` and the eval harness need
to see the same choice the UI made, and session state is per-browser-session.
The file is inside gitignored `data/`, holds no secret (only a public tunnel URL
and a provider name), and is rewritten atomically.

Colab and Kaggle are peers here, not primary and backup. Both URLs can be set at
once; `set_active()` is the whole swap.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from core.config import PROJECT_ROOT, PROVIDER_ENDPOINT, normalise_base_url, settings

log = logging.getLogger(__name__)

OVERRIDE_PATH = PROJECT_ROOT / "data" / "endpoint_override.json"

#: Display names, in the order the switcher should offer them.
PROVIDER_LABELS = {
    "colab_tunnel": "Google Colab",
    "kaggle_tunnel": "Kaggle",
    "custom": "Custom endpoint",
}


@dataclass(frozen=True)
class Endpoint:
    """One place the model might be served from, right now."""

    provider: str
    label: str
    env_var: str
    base_url: str | None
    #: "override" when the in-app switcher set this URL, ".env" otherwise.
    source: str

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    @property
    def chat_url(self) -> str | None:
        return f"{self.base_url}/v1/chat/completions" if self.base_url else None

    @property
    def models_url(self) -> str | None:
        return f"{self.base_url}/v1/models" if self.base_url else None


@dataclass(frozen=True)
class Health:
    """The answer to 'is the notebook still alive?'"""

    ok: bool
    detail: str
    latency_ms: int | None = None
    models: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# The override file
# ---------------------------------------------------------------------------


def _read_override() -> dict:
    """Never raises: a corrupt override must not take the app down."""
    try:
        return json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("ignoring unreadable %s: %s", OVERRIDE_PATH, exc)
        return {}


def _write_override(data: dict) -> None:
    """Atomic, so a Streamlit rerun mid-write cannot read half a file."""
    OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=OVERRIDE_PATH.parent, delete=False
    )
    try:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, OVERRIDE_PATH)


def clear_overrides() -> None:
    """Fall back to whatever `.env` says. The switcher's Reset button."""
    OVERRIDE_PATH.unlink(missing_ok=True)


def has_overrides() -> bool:
    return bool(_read_override())


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _env_url(provider: str) -> str | None:
    """The `.env` value for one provider, whether or not it is the active one."""
    return {
        "colab_tunnel": settings.colab_tunnel_url,
        "kaggle_tunnel": settings.kaggle_tunnel_url,
        "custom": settings.custom_base_url,
    }.get(provider)


def active_provider() -> str:
    override = _read_override().get("provider")
    if override in PROVIDER_ENDPOINT:
        return override
    return settings.llm_provider if settings.llm_provider in PROVIDER_ENDPOINT else "colab_tunnel"


def get(provider: str) -> Endpoint:
    """One endpoint by name, with the override applied."""
    urls = _read_override().get("urls", {})
    override_url = normalise_base_url(urls.get(provider))
    return Endpoint(
        provider=provider,
        label=PROVIDER_LABELS.get(provider, provider),
        env_var=PROVIDER_ENDPOINT.get(provider, "CUSTOM_BASE_URL"),
        base_url=override_url or normalise_base_url(_env_url(provider)),
        source="override" if override_url else ".env",
    )


def list_endpoints() -> list[Endpoint]:
    return [get(provider) for provider in PROVIDER_LABELS]


def active() -> Endpoint:
    """The endpoint `llm_client` should call on THIS request."""
    return get(active_provider())


def fallback() -> Endpoint | None:
    """The other configured endpoint, if failover is on and one exists.

    Deliberately never returns `custom` unless it is what you switched away
    from: falling through to a URL nobody has looked at in a week is worse than
    a clean failure.
    """
    if not settings.llm_failover:
        return None
    current = active_provider()
    for candidate in ("colab_tunnel", "kaggle_tunnel", "custom"):
        if candidate == current:
            continue
        endpoint = get(candidate)
        if endpoint.configured:
            return endpoint
    return None


def api_key() -> str | None:
    """The shared bearer secret. Always from `.env`/Secrets, never overridable
    from the UI — a secret typed into a text box gets pasted into a screenshot."""
    return settings.llm_api_key


def model() -> str:
    """Served model name. Overridable because Phase 11's base-vs-tuned
    comparison is exactly this one value (ADR-012)."""
    return _read_override().get("model") or settings.llm_model


def timeout_seconds() -> int:
    return settings.llm_timeout_seconds


# ---------------------------------------------------------------------------
# Mutation — what the switcher calls
# ---------------------------------------------------------------------------


def set_active(provider: str) -> None:
    if provider not in PROVIDER_ENDPOINT:
        raise ValueError(f"unknown provider {provider!r}")
    data = _read_override()
    data["provider"] = provider
    _write_override(data)
    log.info("active LLM endpoint switched to %s", provider)


def set_url(provider: str, url: str | None) -> None:
    """Paste a fresh tunnel URL. Empty clears back to the `.env` value."""
    if provider not in PROVIDER_ENDPOINT:
        raise ValueError(f"unknown provider {provider!r}")
    data = _read_override()
    urls = dict(data.get("urls", {}))
    normalised = normalise_base_url(url)
    if normalised:
        urls[provider] = normalised
    else:
        urls.pop(provider, None)
    data["urls"] = urls
    _write_override(data)


def set_model(name: str | None) -> None:
    data = _read_override()
    if name:
        data["model"] = name
    else:
        data.pop("model", None)
    _write_override(data)


def record_answered(provider: str, *, was_failover: bool = False) -> None:
    """Remember which host actually served the last call, so the UI can say
    'Kaggle answered that' instead of quietly contradicting the switcher."""
    data = _read_override()
    data["last_answered"] = {
        "provider": provider,
        "at": time.time(),
        "failover": was_failover,
    }
    _write_override(data)


def last_answered() -> dict | None:
    return _read_override().get("last_answered")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def probe(endpoint: Endpoint | None = None, timeout: int = 10) -> Health:
    """GET /v1/models with the bearer token. Never raises.

    Distinguishes the four failures that actually happen, because "it doesn't
    work" costs an hour and "your key is wrong" costs ten seconds:
    unconfigured, unreachable (dead session), 401 (key mismatch), and reachable
    but serving a different model than LLM_MODEL names.
    """
    endpoint = endpoint or active()
    if not endpoint.configured:
        return Health(False, f"{endpoint.env_var} is not set — no URL to call")

    key = api_key()
    if not key:
        return Health(False, "LLM_API_KEY is not set; the server would reject us")

    request = urllib.request.Request(
        endpoint.models_url or "",
        headers={"Authorization": f"Bearer {key}"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return Health(False, "401 — LLM_API_KEY does not match the notebook's secret")
        return Health(False, f"HTTP {exc.code} from {endpoint.base_url}")
    except Exception as exc:
        return Health(
            False,
            f"unreachable — {type(exc).__name__}. The session is probably dead; "
            "re-run the notebook cell and paste the new URL.",
        )

    latency = int((time.monotonic() - started) * 1000)
    served = tuple(str(entry.get("id")) for entry in payload.get("data", []) if entry.get("id"))
    wanted = model()
    if served and wanted not in served:
        return Health(
            False,
            f"reachable, but it serves {', '.join(served)} — LLM_MODEL is {wanted}",
            latency,
            served,
        )
    return Health(True, f"{endpoint.label} answering in {latency} ms", latency, served)


def describe() -> str:
    """One line for a status widget."""
    endpoint = active()
    if not endpoint.configured:
        return f"{endpoint.label} · no URL set"
    suffix = " (overridden in-app)" if endpoint.source == "override" else ""
    return f"{endpoint.label}{suffix}"
