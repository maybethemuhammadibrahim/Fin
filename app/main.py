"""[B] Streamlit entry point and landing page. Phase 2.

Phase 0 made this the config page. Phase 2 makes it the front door — what the
product is, which run you are looking at, and whether the two things it depends
on (database, model endpoint) are actually up. The full Phase 0 configuration
table is preserved verbatim, one expander down, because it is still the fastest
way to diagnose a bad `.env`.

Reads: `queries.get_summary_stats`, `queries.list_runs`. Computes nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit runs this file as a script, so the repo root is not importable yet.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from app import state  # noqa: E402
from app.components.summary_cards import money  # noqa: E402
from core.ai import endpoints  # noqa: E402
from core.config import ConfigError, PROVIDER_ENDPOINT, settings  # noqa: E402
from core.db import database  # noqa: E402
from core.db.queries import get_summary_stats  # noqa: E402
from core.storage import files  # noqa: E402

st.set_page_config(page_title="FinSight", page_icon="💸", layout="wide")

st.title("💸 FinSight")
st.caption(
    "Revenue you were contractually owed but never collected — with the clause that proves it."
)

# ---------------------------------------------------------------------------
# System status: the two things that can take the app down
# ---------------------------------------------------------------------------

db_ok, db_message = database.check_connection()

# Phase 5: the endpoint is a notebook session, so "configured" and "answering"
# are different questions and only the second one matters. Probed once per
# session — a live call on every rerun would cost seconds of page load.
if "endpoint_health" not in st.session_state:
    st.session_state.endpoint_health = endpoints.probe(timeout=6)
model_health = st.session_state.endpoint_health

status_db, status_model, status_storage = st.columns(3)
with status_db:
    if db_ok:
        st.success(f"**Database** · {database.describe_backend()}", icon="🗄️")
    else:
        st.error("**Database** · unreachable", icon="🗄️")
with status_model:
    if model_health.ok:
        st.success(f"**Model endpoint** · {endpoints.describe()}", icon="🧠")
    elif endpoints.active().configured:
        st.error(f"**Model endpoint** · {endpoints.active().label} not answering", icon="🧠")
    else:
        st.warning("**Model endpoint** · no session running", icon="🧠")
with status_storage:
    st.info(f"**Uploads** · {files.backend()}", icon="📦")

if not model_health.ok:
    st.caption(f"🧠 {model_health.detail}")
    st.page_link(
        "pages/8_model_endpoint.py",
        label="Start a session or paste a new tunnel URL",
        icon="🔌",
    )

if not db_ok:
    st.error(
        f"```\n{db_message}\n```\n\nOpen **DB Health** in the sidebar for what to check."
    )

# ---------------------------------------------------------------------------
# Current run
# ---------------------------------------------------------------------------

run_id = state.render_run_selector() if db_ok else None

if db_ok and run_id is None:
    st.divider()
    st.info(
        "**No runs in the database.** The app reads only from the database, "
        "never from a hardcoded fixture — so seed a run to see it working.",
        icon="🌱",
    )
    st.code("python scripts/seed_demo.py", language="bash")

elif db_ok and run_id is not None:
    st.divider()
    with state.db() as session:
        stats = get_summary_stats(session, run_id)

    left, mid, right = st.columns(3)
    left.metric("💰 Total leaked", money(stats.total_leaked))
    mid.metric("🔍 Findings", stats.anomaly_count)
    right.metric(
        "📄 Backed by a clause",
        f"{stats.grounded_count}/{stats.anomaly_count}" if stats.anomaly_count else "—",
        help="ADR-005: a quote that cannot be located in the PDF still counts as "
             "a finding, but it cannot be highlighted on a page.",
    )

    st.page_link(
        "pages/1_integrity_engine.py",
        label="Open the Revenue Integrity Dashboard",
        icon="📊",
    )
    st.page_link("pages/2_decision_engine.py", label="Open the Decision Engine", icon="🧭")

# ---------------------------------------------------------------------------
# What this is
# ---------------------------------------------------------------------------

st.divider()

what, how = st.columns(2)
with what:
    st.markdown(
        """
### What it finds

Four kinds of leak, mutually exclusive, each traced to a clause:

- 🔴 **Ghost Invoice** — billing that never happened
- 🟡 **Forgotten Raise** — an escalation clause never applied
- 🟠 **Zombie Discount** — a temporary discount never switched off
- 🟣 **Short-Change** — a partial payment with no follow-up
        """
    )
with how:
    st.markdown(
        """
### How the numbers stay defensible

- **The model never does arithmetic.** It turns contract prose into structured
  data; all money maths is deterministic Python.
- **The model never produces coordinates.** It quotes a clause verbatim; code
  finds it in the PDF. A quote that cannot be found is flagged, not faked.
- **The interface reads only the database.** Every figure on every page is a
  row you can go and look at.
        """
    )

# ---------------------------------------------------------------------------
# Configuration (Phase 0's page, preserved)
# ---------------------------------------------------------------------------

st.divider()

try:
    settings.validate()
    config_ok = True
except ConfigError as exc:
    config_ok = False
    config_error = str(exc)

with st.expander(
    "⚙️ Resolved configuration" + ("" if config_ok else "  —  ❌ something is missing"),
    expanded=not config_ok,
):
    if not config_ok:
        st.error(config_error, icon="🛑")
        st.caption(
            "From Phase 5 the tunnel URL is real, but it rotates on every notebook "
            "restart — a ❌ here usually means the last session ended, not that "
            "anything is broken. Paste the new URL on the **Model endpoint** page."
        )

    left, mid, right = st.columns(3)
    left.metric("Config source", settings.source)
    mid.metric("Inference endpoint", settings.llm_provider)
    right.metric("Model", settings.llm_model or "—")

    if settings.api_base:
        st.caption(f"Model endpoint: `{settings.api_base}/v1/chat/completions`")

    st.dataframe(
        [
            {
                "": check.status,
                "Variable": check.name,
                "Value": check.display,
                "Required now": "yes" if check.required else "no",
                "Note": check.note,
            }
            for check in settings.checks()
        ],
        hide_index=True,
        use_container_width=True,
    )
    st.caption("✅ set · ❌ required and missing · ⚪ optional, needed in a later phase")

    if settings.using_sqlite_fallback:
        st.warning(
            f"`DATABASE_URL` is not set — falling back to "
            f"`{settings.resolved_database_url}`. Fine offline, but your teammate "
            "and the deployed app cannot see those rows.",
            icon="🗄️",
        )

    st.markdown("**Inference endpoints (ADR-002 + ADR-011)**")
    st.caption(
        "No frontier model API is called anywhere in this project. Every model "
        "call goes to an open-source model we host ourselves on a free Colab or "
        "Kaggle GPU, behind an OpenAI-compatible tunnel. Swapping between them is "
        "one variable — and so is Phase 11's base-vs-tuned comparison, which is "
        "`LLM_MODEL`."
    )
    st.table(
        [
            {
                "LLM_PROVIDER": provider,
                "URL variable": endpoint,
                "Set?": "✅" if getattr(settings, endpoint.lower(), None) else "—",
                "Active": "◀" if provider == settings.llm_provider else "",
            }
            for provider, endpoint in PROVIDER_ENDPOINT.items()
        ]
    )
    st.caption(
        "🔄 Tunnel URLs change every time the notebook restarts. Expect to update "
        "this daily, and in Streamlit Secrets on the morning of a demo — no "
        "redeploy required."
    )
