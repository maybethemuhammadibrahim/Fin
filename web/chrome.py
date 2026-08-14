"""[B] The header, state bar and offline banner, for either data mode. Phase 6.

Split out of the routers because both pages need the same chrome and neither
should have to know how the endpoint status is discovered.

**The endpoint is never probed here.** `endpoints.probe()` opens a socket with
a ten-second timeout, and a dead Colab session would make every page load hang
for ten seconds — the exact failure the offline banner exists to explain
gracefully. Instead the chrome reports what can be known for free: whether a
URL is configured at all, and whether anything has answered recently. Actually
testing the connection is the Model endpoint page's job, on a button press.
"""

from __future__ import annotations

import time

from web.viewmodels import Chrome, RunOption

#: How long after a successful call we still call the endpoint "live" without
#: re-checking. Half an hour: a notebook session that answered within the last
#: half hour is very likely still up, and one that has not is worth doubting.
FRESH_SECONDS = 30 * 60


def endpoint_status() -> tuple[str, bool]:
    """(label, online) for the dot in the header. Never raises, never blocks."""
    try:
        from core.ai import endpoints

        active = endpoints.active()
        if not active.configured:
            return f"{active.label} · no URL set", False

        answered = endpoints.last_answered()
        if answered and (time.time() - float(answered.get("at", 0))) < FRESH_SECONDS:
            provider = answered.get("provider", active.provider)
            label = endpoints.get(provider).label if provider else active.label
            return f"{label} answered", True

        # Configured but nothing recent. Not a failure — most likely nothing
        # has been asked yet — so it is stated as unknown, not as down.
        return f"{active.label} · not called yet", True
    except Exception:
        # A misconfigured .env raises out of core.config. The web shell has to
        # render anyway, or you cannot use it to see what is misconfigured.
        return "Endpoint unavailable", False


def build(
    *,
    data_mode: str,
    page: str,
    demo_state: str,
    run_label: str | None,
    state_note: str,
    is_offline: bool,
    runs: list[RunOption] | None = None,
) -> Chrome:
    """Assemble the chrome. Demo mode fakes the endpoint; live mode reads it."""
    if data_mode == "demo":
        # The mockup's "Model offline" state is a demonstration, so the label
        # follows the chosen state rather than the real endpoint.
        label = "Endpoint unreachable" if is_offline else "Endpoint live"
        online = not is_offline
    else:
        label, online = endpoint_status()
        is_offline = not online

    return Chrome(
        data_mode=data_mode,
        page=page,
        demo_state=demo_state,
        run_label=run_label,
        endpoint_label=label,
        endpoint_online=online,
        state_note=state_note,
        is_offline=is_offline,
        runs=runs or [],
    )
