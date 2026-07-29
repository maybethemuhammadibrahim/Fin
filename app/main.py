"""[B] Streamlit entry point. Phase 0: renders the resolved config, secrets masked.

Phase 2 replaces this body with the run selector and the real landing page.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit runs this file as a script, so the repo root is not importable yet.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from core.config import ConfigError, PROVIDER_CREDENTIAL, settings  # noqa: E402

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
mid.metric("LLM provider", settings.llm_provider)
right.metric("Model", settings.llm_model or "—")

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

with st.expander("Swapping LLM provider (ADR-002)"):
    st.markdown(
        "Change one variable. No code changes anywhere, including in Phase 11's "
        "baseline-vs-fine-tuned comparison."
    )
    st.table(
        [
            {
                "LLM_PROVIDER": provider,
                "Credential it needs": credential,
                "Set?": "✅" if getattr(settings, credential.lower(), None) else "—",
            }
            for provider, credential in PROVIDER_CREDENTIAL.items()
        ]
    )
