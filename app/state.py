"""[B] st.session_state helpers. Phase 2.

Streamlit reruns the entire script on every interaction, so anything that must
survive a click lives in `st.session_state`. This module is the only place that
touches it by key — everywhere else calls these functions, so a typo'd key is a
missing attribute rather than a silently empty widget.

**It holds ids, never rows.** The selected run is an `int`; the selected anomaly
is an `int`. Data is re-read from the database on every rerun. Caching row
objects here would reintroduce exactly the stale-data problem ADR-008 exists to
avoid, and would let the UI drift from the database it is supposed to mirror.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import streamlit as st

from core.db import database
from core.db.queries import RunRow, get_latest_run, list_runs

_RUN_ID = "selected_run_id"
_ANOMALY_ID = "selected_anomaly_id"
_UPLOADS = "pending_uploads"


@contextmanager
def db() -> Iterator:
    """A session for the duration of one render. Read-only by convention."""
    with database.session_scope() as session:
        yield session


# ---------------------------------------------------------------------------
# Selected run
# ---------------------------------------------------------------------------


def get_run_id() -> int | None:
    """The run every page renders, defaulting to the newest one.

    Returns None only when the database has no runs at all, which the pages
    handle by telling the user to seed.
    """
    if st.session_state.get(_RUN_ID) is None:
        with db() as session:
            latest = get_latest_run(session)
            st.session_state[_RUN_ID] = latest.id if latest else None
    return st.session_state.get(_RUN_ID)


def set_run_id(run_id: int | None) -> None:
    """Switch runs. Clears the drill-down, which belonged to the old run."""
    if st.session_state.get(_RUN_ID) != run_id:
        clear_selected_anomaly()
    st.session_state[_RUN_ID] = run_id


def render_run_selector(label: str = "Run") -> int | None:
    """Sidebar run picker. Returns the selected run_id, or None if there are none."""
    with db() as session:
        runs: list[RunRow] = list_runs(session)

    if not runs:
        st.sidebar.warning("No runs yet.")
        st.sidebar.code("python scripts/seed_demo.py", language="bash")
        return None

    current = get_run_id()
    ids = [r.id for r in runs]
    labels = {r.id: f"{r.label}  ·  #{r.id}" for r in runs}
    index = ids.index(current) if current in ids else 0

    chosen = st.sidebar.selectbox(
        label, options=ids, index=index, format_func=lambda rid: labels[rid]
    )
    set_run_id(chosen)

    picked = next(r for r in runs if r.id == chosen)
    st.sidebar.caption(
        f"model: `{picked.model_name or '—'}`  \n"
        f"created: {picked.created_at:%Y-%m-%d %H:%M}" if picked.created_at else "—"
    )
    return chosen


# ---------------------------------------------------------------------------
# Drill-down selection
# ---------------------------------------------------------------------------


def get_selected_anomaly() -> int | None:
    return st.session_state.get(_ANOMALY_ID)


def set_selected_anomaly(anomaly_id: int | None) -> None:
    st.session_state[_ANOMALY_ID] = anomaly_id


def clear_selected_anomaly() -> None:
    st.session_state[_ANOMALY_ID] = None


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


def record_upload(filename: str) -> None:
    """Remember a filename saved this session, so the UI can confirm it."""
    st.session_state.setdefault(_UPLOADS, [])
    if filename not in st.session_state[_UPLOADS]:
        st.session_state[_UPLOADS].append(filename)


def pending_uploads() -> list[str]:
    return list(st.session_state.get(_UPLOADS, []))
