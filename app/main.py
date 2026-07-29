"""[B] Streamlit entry point. Phase 0: renders the resolved config, secrets masked.

Phase 2 replaces this body with the run selector and the real landing page.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit runs this file as a script, so the repo root is not importable yet.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from core.config import ConfigError, PROVIDER_ENDPOINT, settings  # noqa: E402

st.set_page_config(page_title="FinSight — Config", page_icon="💸", layout="wide")

st.title("💸 FinSight")
st.caption(
    "Revenue you were contractually owed but never collected — with the clause that proves it."
)

st.info(
    "**Phase 0 — Foundations.** No features yet. This page exists to prove that "
    "configuration resolves correctly for both of us, locally and deployed.",
    icon="🚧",
)

# ---- Startup validation: loud, named, and actionable -----------------------

try:
    settings.validate()
except ConfigError as exc:
    st.error(str(exc), icon="🛑")

# ---- Where the values came from -------------------------------------------

left, mid, right = st.columns(3)
left.metric("Config source", settings.source)
mid.metric("Inference endpoint", settings.llm_provider)
right.metric("Model", settings.llm_model or "—")

if settings.api_base:
    st.caption(f"Model endpoint: `{settings.api_base}/v1/chat/completions`")

# ---- Every variable, one row each ------------------------------------------

st.subheader("Resolved configuration")

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
)

st.caption("✅ set · ❌ required and missing · ⚪ optional, needed in a later phase")

# ---- Things worth seeing at a glance ---------------------------------------

if settings.using_sqlite_fallback:
    st.warning(
        f"`DATABASE_URL` is not set — falling back to `{settings.resolved_database_url}`. "
        "Fine for offline work; set the Supabase URL before Phase 1.",
        icon="🗄️",
    )
else:
    st.success(f"Database: `{settings.resolved_database_url.split('@')[-1]}`", icon="🗄️")

with st.expander("Inference endpoints (ADR-002 + ADR-011)"):
    st.markdown(
        "**No frontier model API is called anywhere in this project.** Every model "
        "call goes to an open-source model we host ourselves on a free Colab or "
        "Kaggle GPU, behind an OpenAI-compatible tunnel.\n\n"
        "Swapping between them is one variable, and so is Phase 11's "
        "base-vs-tuned comparison — that one is `LLM_MODEL`."
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
    st.warning(
        "Tunnel URLs change **every time the notebook restarts**. Expect to "
        "update this daily, and in Streamlit Secrets on the morning of a demo — "
        "no redeploy required.",
        icon="🔄",
    )
