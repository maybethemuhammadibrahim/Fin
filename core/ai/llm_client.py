"""[B] Client for our self-hosted OpenAI-compatible endpoint (ADR-011). Phase 5.

Endpoint chosen by LLM_PROVIDER; no frontier model API is ever called. Needs a
generous timeout and one cold-start retry, and must fail visibly when the
notebook session is down.

Three obligations this client has that a vendor SDK never did:

1. **Read the base URL at call time.** The tunnel URL rotates on every notebook
   restart, so it comes from `core/ai/endpoints.py`, never from a value captured
   at import.
2. **Survive a cold start.** The first request after a session begins waits for
   3B of weights to load. One retry, generous timeout.
3. **Fail honestly.** `complete_json` returns `None` and never raises (ADR-004),
   but `last_error()` records *why*, so the UI can say "the model endpoint is
   down" instead of rendering an empty result that looks like "no findings".

Colab and Kaggle are interchangeable here: a call goes to whichever endpoint is
active, and — when `LLM_FAILOVER` is on — falls through to the other configured
one rather than failing mid-demo. Whichever answered is recorded, so the UI can
tell you it happened.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

import requests
from pydantic import BaseModel, ValidationError

from core.ai import cache, endpoints

log = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

#: Pause before the cold-start retry. Long enough that a loading server has
#: made progress, short enough not to feel hung.
COLD_START_PAUSE_SECONDS = 8

#: Per-base-URL memo of what the server accepts, negotiated downwards on the
#: first 400. vLLM takes a full JSON schema (grammar-constrained decoding — the
#: upgrade ADR-011 bought us); the transformers fallback backend takes neither
#: and relies entirely on the repair-retry below.
_JSON_MODE: dict[str, str] = {}
_JSON_MODE_ORDER = ("json_schema", "json_object", "none")

_LAST_ERROR: str | None = None

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


@dataclass
class Completion:
    """One round trip's outcome, including which host served it."""

    text: str | None = None
    error: str | None = None
    provider: str | None = None
    from_cache: bool = False
    was_failover: bool = False
    attempts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.text is not None


def last_error() -> str | None:
    """Why the most recent call failed, for the UI. None after a success."""
    return _LAST_ERROR


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _response_format(mode: str, schema: type[BaseModel] | None) -> dict | None:
    if mode == "none" or schema is None:
        return {"type": "json_object"} if mode == "json_object" else None
    if mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "schema": schema.model_json_schema(),
            "strict": True,
        },
    }


def _post(endpoint: endpoints.Endpoint, payload: dict, timeout: int) -> tuple[str | None, str | None]:
    """(content, error). One HTTP call, no retries, no exceptions escaping."""
    key = endpoints.api_key()
    if not key:
        return None, "LLM_API_KEY is not set"
    if not endpoint.chat_url:
        return None, f"{endpoint.env_var} is not set"

    try:
        response = requests.post(
            endpoint.chat_url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except requests.Timeout:
        return None, f"timed out after {timeout}s — the session may still be loading weights"
    except requests.RequestException as exc:
        return None, f"unreachable ({type(exc).__name__}) — the notebook session is probably dead"

    if response.status_code == 401:
        return None, "401 — LLM_API_KEY does not match the notebook's secret"
    if response.status_code == 400:
        return None, f"400 — {response.text[:300]}"
    if response.status_code != 200:
        return None, f"HTTP {response.status_code} — {response.text[:300]}"

    try:
        body = response.json()
        return body["choices"][0]["message"]["content"], None
    except Exception as exc:
        return None, f"unparseable response ({type(exc).__name__}): {response.text[:300]}"


def _call_endpoint(
    endpoint: endpoints.Endpoint,
    messages: list[dict],
    *,
    schema: type[BaseModel] | None,
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> tuple[str | None, str | None]:
    """One endpoint, with JSON-mode negotiation and the cold-start retry."""
    base = endpoint.base_url or ""
    mode = _JSON_MODE.get(base, "json_schema" if schema else "none")
    if schema is None:
        mode = "none"

    # Negotiate downwards: a server that rejects a JSON schema gets asked for a
    # JSON object, and one that rejects that gets asked in the prompt only.
    start = _JSON_MODE_ORDER.index(mode)
    for candidate in _JSON_MODE_ORDER[start:]:
        payload: dict[str, Any] = {
            "model": endpoints.model(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response_format = _response_format(candidate, schema)
        if response_format:
            payload["response_format"] = response_format

        text, error = _post(endpoint, payload, timeout)

        if text is not None:
            if _JSON_MODE.get(base) != candidate:
                _JSON_MODE[base] = candidate
                log.info("%s accepts response_format=%s", endpoint.provider, candidate)
            return text, None

        if error and error.startswith("400") and candidate != _JSON_MODE_ORDER[-1] and schema:
            log.info("%s rejected response_format=%s; falling back", endpoint.provider, candidate)
            continue

        # Not a schema-support problem. Cold starts look like a timeout or a
        # refused connection, and are worth exactly one retry.
        if error and ("timed out" in error or "unreachable" in error):
            log.warning("%s: %s — retrying once for a cold start", endpoint.provider, error)
            time.sleep(COLD_START_PAUSE_SECONDS)
            text, error = _post(endpoint, payload, timeout)
            if text is not None:
                return text, None
        return None, error

    return None, "no response_format the server accepts"


def call(
    prompt: str,
    *,
    system: str = "",
    schema: type[BaseModel] | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1536,
    use_cache: bool = True,
) -> Completion:
    """The one code path every LLM call in FinSight goes through.

    Cache -> active endpoint -> (optional) the other configured endpoint.
    Never raises.
    """
    global _LAST_ERROR

    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    model_name = endpoints.model()
    cache_key = cache.key(
        prompt,
        model_name,
        system,
        temperature=temperature,
        max_tokens=max_tokens,
        schema=schema.__name__ if schema else None,
    )

    if use_cache:
        hit = cache.get(cache_key)
        if hit is not None:
            log.debug("cache hit %s", cache_key[:12])
            _LAST_ERROR = None
            return Completion(text=hit, from_cache=True, provider="cache")

    timeout = endpoints.timeout_seconds()
    result = Completion()

    targets: list[tuple[endpoints.Endpoint, bool]] = [(endpoints.active(), False)]
    spare = endpoints.fallback()
    if spare:
        targets.append((spare, True))

    for endpoint, is_failover in targets:
        if not endpoint.configured:
            result.attempts.append(f"{endpoint.provider}: {endpoint.env_var} not set")
            continue
        if is_failover:
            log.warning(
                "active endpoint failed; failing over to %s (LLM_FAILOVER=true)",
                endpoint.provider,
            )
        text, error = _call_endpoint(
            endpoint,
            messages,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        if text is not None:
            if use_cache:
                cache.put(cache_key, text, model=model_name, preview=prompt)
            endpoints.record_answered(endpoint.provider, was_failover=is_failover)
            _LAST_ERROR = None
            return Completion(
                text=text,
                provider=endpoint.provider,
                was_failover=is_failover,
                attempts=result.attempts,
            )
        result.attempts.append(f"{endpoint.provider}: {error}")

    _LAST_ERROR = "; ".join(result.attempts) or "no endpoint configured"
    log.error("LLM call failed — %s", _LAST_ERROR)
    return Completion(error=_LAST_ERROR, attempts=result.attempts)


# ---------------------------------------------------------------------------
# The two functions everyone else imports
# ---------------------------------------------------------------------------


def complete(prompt: str, system: str = "", **kw: Any) -> str | None:
    """Free-text completion. `None` when the endpoint could not answer.

    interfaces.md declared this `-> str`; it is `str | None` in practice,
    because the project's own convention is that a function which can
    legitimately fail returns None rather than a plausible-looking empty string.
    """
    return call(prompt, system=system, **kw).text


def _strip_to_json(text: str) -> str:
    """Small models wrap JSON in prose or code fences even when told not to."""
    cleaned = _FENCE.sub("", text.strip())
    start = cleaned.find("{")
    if start == -1:
        return cleaned
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : index + 1]
    return cleaned[start:]


def complete_json(
    prompt: str,
    schema: type[ModelT],
    system: str = "",
    max_repairs: int = 1,
    **kw: Any,
) -> ModelT | None:
    """JSON mode -> Pydantic validate -> one repair retry -> None on failure.

    NEVER raises to the caller (ADR-004). A `None` here means "we could not get
    valid structured output", and every caller must handle it.
    """
    global _LAST_ERROR

    result = call(prompt, system=system, schema=schema, **kw)
    if not result.ok:
        return None

    text = result.text or ""
    for attempt in range(max_repairs + 1):
        candidate = _strip_to_json(text)
        try:
            return schema.model_validate_json(candidate)
        except ValidationError as exc:
            problem = str(exc)[:1200]
        except Exception as exc:
            problem = f"{type(exc).__name__}: {exc}"

        if attempt == max_repairs:
            _LAST_ERROR = f"invalid JSON after {max_repairs} repair(s): {problem[:300]}"
            log.warning("%s", _LAST_ERROR)
            return None

        log.info("repairing invalid JSON (attempt %d)", attempt + 1)
        repair = call(
            "The JSON below is invalid. Return ONLY corrected JSON — no prose, no "
            "code fences, no explanation.\n\n"
            f"Invalid JSON:\n{candidate[:4000]}\n\n"
            f"Validation errors:\n{problem}",
            system="You fix malformed JSON. You output JSON and nothing else.",
            schema=schema,
            **kw,
        )
        if not repair.ok:
            return None
        text = repair.text or ""

    return None


def health() -> bool:
    """Is the endpoint answering? Used by the UI to distinguish 'no anomalies'
    from 'the notebook died'."""
    return endpoints.probe().ok
