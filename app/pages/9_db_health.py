"""[B] Dev-only diagnostics: connection status and per-table row counts. Phase 1.

The one page that is allowed to talk about infrastructure. Everything else in
`app/` renders business data and must not know what a table is.

It never raises: a dead database renders a red box explaining what to fix, which
is the whole point of a health page. This is also the page that proves ADR-008 —
the UI reads the database and nothing else, from Phase 1 onward.
"""

from __future__ import annotations

import streamlit as st

from core.config import settings
from core.db import database
from core.db.queries import GLOBAL_TABLES, list_runs, table_counts

st.set_page_config(page_title="FinSight · DB Health", page_icon="🩺", layout="wide")

st.title("🩺 Database Health")
st.caption("Developer diagnostics. Not part of the product surface.")

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

ok, message = database.check_connection()

col_status, col_backend = st.columns([1, 3])
with col_status:
    if ok:
        st.success("Connected")
    else:
        st.error("Unreachable")
with col_backend:
    st.code(database.describe_backend(), language=None)

if settings.using_sqlite_fallback:
    st.warning(
        "**Using the offline SQLite fallback.** `DATABASE_URL` is not set, so this "
        "is a local file — your teammate cannot see these rows and a deployed app "
        "will not either. Set `DATABASE_URL` in `.env` to your Supabase URI "
        "(ADR-003).",
        icon="⚠️",
    )

if not ok:
    st.error(f"**Connection failed.**\n\n```\n{message}\n```")
    st.markdown(
        """
**Things to check, in order:**

1. Is `DATABASE_URL` set in `.env`? Leave it blank to fall back to SQLite.
2. Did you replace `[PASSWORD]` with your real Supabase database password?
   Unedited placeholders are treated as unset on purpose.
3. Is the Supabase project awake? Free projects pause after inactivity —
   open the Supabase dashboard and resume it.
4. Have the tables been created yet? Run `python scripts/init_db.py`.
        """
    )
    st.stop()

# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Tables")

try:
    with database.session_scope() as session:
        runs = list_runs(session)

        run_labels = {0: "— all runs —"} | {r.id: f"[{r.id}] {r.label}" for r in runs}
        selected = st.selectbox(
            "Scope row counts to a run",
            options=list(run_labels),
            format_func=lambda rid: run_labels[rid],
            help=(
                "Tables that hang off contract_rules are scoped by joining back "
                "to clients.run_id. Only column_mappings is genuinely global."
            ),
        )
        scope = None if selected == 0 else selected

        counts = table_counts(session, run_id=scope)
except Exception as exc:
    st.error(
        f"**Connected, but querying failed.**\n\n```\n{type(exc).__name__}: {exc}\n```\n\n"
        "If this says a table does not exist, run `python scripts/init_db.py`."
    )
    st.stop()

expected_tables = 12
found = len(counts)
total_rows = sum(counts.values())

metric_cols = st.columns(3)
metric_cols[0].metric("Tables", f"{found}/{expected_tables}")
metric_cols[1].metric("Rows", f"{total_rows:,}")
metric_cols[2].metric("Runs", len(runs))

if found != expected_tables:
    st.error(f"Expected {expected_tables} tables, found {found}. Run `python scripts/init_db.py`.")

st.dataframe(
    [
        {
            "table": name,
            "rows": count,
            "scope": "all runs" if name in GLOBAL_TABLES else ("this run" if scope else "all runs"),
        }
        for name, count in counts.items()
    ],
    hide_index=True,
    use_container_width=True,
    column_config={
        "table": st.column_config.TextColumn("Table"),
        "rows": st.column_config.NumberColumn("Rows", format="%d"),
        "scope": st.column_config.TextColumn(
            "Counting", help="column_mappings is reused across runs by design (ADR-010)."
        ),
    },
)

if total_rows == 0:
    st.info(
        "Every table is empty. That is the correct state at the end of Phase 1 — "
        "`scripts/seed_demo.py` fills them in Phase 2.",
        icon="ℹ️",
    )

# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Runs")

if not runs:
    st.caption("No runs yet. Phase 2's seeder creates the first one.")
else:
    st.dataframe(
        [
            {
                "id": r.id,
                "label": r.label,
                "provider": r.llm_provider or "—",
                "model": r.model_name or "—",
                "created": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "—",
            }
            for r in runs
        ],
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        "Two runs differing only in `model` are what Phase 11's base-vs-tuned "
        "comparison reads (ADR-012). Delete one with "
        "`python scripts/reset_run.py --run-id N`."
    )
