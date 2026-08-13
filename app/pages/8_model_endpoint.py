"""[B] Pick the live model endpoint and paste a fresh tunnel URL. Phase 5.

The tunnel URL rotates on every notebook restart, and the whole point of ADR-002
is that switching hosts costs one variable. Making that variable editable in the
app closes the last gap: a URL pasted here takes effect on the next call, with
no Streamlit restart and no text editor.

Colab and Kaggle are peers. Both can be configured at once, and switching
between them mid-demo is a radio button. What this page writes goes to
`data/endpoint_override.json` (via `core/ai/endpoints.py`) and takes precedence
over `.env`; the Reset button hands control back.

The bearer secret is deliberately **not** editable here. A secret typed into a
text box ends up in a screenshot.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st  # noqa: E402

from core.ai import cache, endpoints  # noqa: E402
from core.config import settings  # noqa: E402

st.set_page_config(page_title="FinSight · Model endpoint", page_icon="🧠", layout="wide")

st.title("🧠 Model endpoint")
st.caption(
    "FinSight runs its own open-source model on a free Colab or Kaggle GPU "
    "(ADR-011). No frontier model API is called anywhere in this project."
)

active = endpoints.active()

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

if "endpoint_health" not in st.session_state:
    st.session_state.endpoint_health = endpoints.probe(timeout=6)

health = st.session_state.endpoint_health

status, detail, refresh = st.columns([1, 4, 1])
with status:
    if health.ok:
        st.success("Live")
    else:
        st.error("Down")
with detail:
    st.markdown(f"**{active.label}** — {health.detail}")
    if active.base_url:
        st.caption(f"`{active.base_url}/v1/chat/completions` · model `{endpoints.model()}`")
with refresh:
    if st.button("Test now", use_container_width=True):
        st.session_state.endpoint_health = endpoints.probe(timeout=15)
        st.rerun()

if not health.ok:
    st.info(
        "Start a session and paste its URL below. The notebook prints the exact "
        "line to copy. Full walkthrough: `docs/serving_setup.md`.",
        icon="🚀",
    )
    st.code(
        "!git clone -q https://github.com/maybethemuhammadibrahim/Fin.git "
        "2>/dev/null || git -C Fin pull -q\n"
        "!python Fin/training/serve_model.py --self-test",
        language="python",
    )
    st.caption(
        "Same cell on both hosts. Colab: Runtime → Change runtime type → T4 GPU. "
        "Kaggle: Accelerator → GPU T4 x2, and Internet → On."
    )

answered = endpoints.last_answered()
if answered:
    age = int(time.time() - float(answered.get("at", 0)))
    who = endpoints.PROVIDER_LABELS.get(str(answered.get("provider")), answered.get("provider"))
    if answered.get("failover"):
        st.warning(
            f"The last call was served by **{who}** as a failover, {age}s ago — "
            "the endpoint selected below was not the one that answered.",
            icon="🔀",
        )
    else:
        st.caption(f"Last call served by {who}, {age}s ago.")

st.divider()

# ---------------------------------------------------------------------------
# Switcher
# ---------------------------------------------------------------------------

st.subheader("Which host is live right now")

providers = list(endpoints.PROVIDER_LABELS)
chosen = st.radio(
    "Active endpoint",
    providers,
    index=providers.index(active.provider),
    format_func=lambda p: (
        f"{endpoints.PROVIDER_LABELS[p]}"
        + ("" if endpoints.get(p).configured else "  ·  no URL yet")
    ),
    horizontal=True,
    label_visibility="collapsed",
)
if chosen != active.provider:
    endpoints.set_active(chosen)
    st.session_state.pop("endpoint_health", None)
    st.rerun()

tabs = st.tabs([endpoints.PROVIDER_LABELS[p] for p in providers])
for tab, provider in zip(tabs, providers):
    endpoint = endpoints.get(provider)
    with tab:
        url_column, button_column = st.columns([4, 1])
        with url_column:
            typed = st.text_input(
                f"{endpoint.env_var}",
                value=endpoint.base_url or "",
                placeholder="https://something-random.trycloudflare.com",
                key=f"url_{provider}",
                help="Paste whatever the notebook printed — a trailing /v1 or "
                     "/v1/chat/completions is stripped automatically.",
            )
        with button_column:
            st.write("")
            st.write("")
            if st.button("Save", key=f"save_{provider}", use_container_width=True):
                endpoints.set_url(provider, typed)
                st.session_state.pop("endpoint_health", None)
                st.rerun()

        left, right = st.columns(2)
        with left:
            source = "set in this app" if endpoint.source == "override" else "from .env"
            st.caption(f"Currently {source}." if endpoint.configured else "Not configured.")
        with right:
            if endpoint.configured and st.button(
                "Test this endpoint", key=f"test_{provider}", use_container_width=True
            ):
                result = endpoints.probe(endpoint, timeout=15)
                (st.success if result.ok else st.error)(result.detail)

st.divider()

# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------

left, right = st.columns(2)

with left:
    st.subheader("Failover")
    spare = endpoints.fallback()
    if not settings.llm_failover:
        st.caption("Off (`LLM_FAILOVER=false`). A dead session fails the request.")
    elif spare:
        st.caption(
            f"On. If **{active.label}** is unreachable, one retry goes to "
            f"**{spare.label}** and the app says so rather than hiding it."
        )
    else:
        st.caption(
            "On, but there is nowhere to fail over to — only one endpoint has a "
            "URL. Start the other host and paste its URL above."
        )

with right:
    st.subheader("Response cache")
    stats = cache.stats()
    st.caption(
        f"{stats.entries} cached response(s), {stats.bytes / 1024:.0f} KB. "
        "Keyed on prompt and model, **not** on which host answered — so a "
        "response cached from Colab still hits after you switch to Kaggle, and "
        "keeps working after a session dies."
    )
    if stats.entries and st.button("Clear cache"):
        st.warning(f"Deleted {cache.clear()} entries.")

if endpoints.has_overrides():
    st.divider()
    st.caption(
        "This page is currently overriding `.env`. Reset to go back to whatever "
        "`.env` (or Streamlit Secrets) declares."
    )
    if st.button("Reset to .env"):
        endpoints.clear_overrides()
        st.session_state.pop("endpoint_health", None)
        st.rerun()
