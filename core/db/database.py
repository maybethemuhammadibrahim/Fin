"""[A] Engine and session factory; DATABASE_URL with a SQLite fallback. Phase 1.

Two rules worth knowing before you import this:

* **The engine is built lazily, on first use** — never at import. Importing this
  module must not open a socket, so `streamlit run` still starts (and the config
  page still renders its ❌) when Supabase is unreachable or unconfigured.
* **SQLite does not enforce foreign keys unless asked.** Without the
  `PRAGMA foreign_keys=ON` listener below, every `ondelete="CASCADE"` in
  models.py silently does nothing on the offline fallback, and `reset_run.py`
  would leave orphans on SQLite while working correctly on Postgres. That
  divergence is exactly what ADR-003 warns about.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from core.config import settings
from core.db.models import Base

log = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _prepare_sqlite_path(url: str) -> None:
    """Create the parent directory for a SQLite file, or the connect fails."""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return
    path = Path(url[len(prefix) :])
    path.parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> Engine:
    """The process-wide engine, created on first call.

    Reads `settings.resolved_database_url`, which is `DATABASE_URL` when set and
    `sqlite:///data/finsight.db` when it is not.
    """
    global _engine, _SessionFactory
    if _engine is not None:
        return _engine

    url = settings.resolved_database_url
    _prepare_sqlite_path(url)

    if url.startswith("sqlite"):
        _engine = create_engine(url, future=True, connect_args={"check_same_thread": False})

        @event.listens_for(_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    else:
        # pool_pre_ping: Supabase drops idle connections, and a Streamlit app
        # sits idle between clicks. Without this the first query after a pause
        # raises instead of transparently reconnecting.
        _engine = create_engine(url, future=True, pool_pre_ping=True, pool_recycle=1800)

    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    log.debug("database engine created for %s", describe_backend())
    return _engine


def get_session() -> Session:
    """A new Session. The caller closes it.

    Prefer `session_scope()` in scripts, which commits and closes for you.
    """
    if _SessionFactory is None:
        get_engine()
    assert _SessionFactory is not None  # narrowed by get_engine()
    return _SessionFactory()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session that commits on success, rolls back on error, always closes."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create every table that does not already exist. Idempotent.

    No Alembic until Phase 9 — a schema change means dropping and recreating.
    """
    Base.metadata.create_all(get_engine())


def drop_all() -> None:
    """Drop every table. Destructive; only `scripts/init_db.py --drop` calls it."""
    Base.metadata.drop_all(get_engine())


def check_connection() -> tuple[bool, str]:
    """Return (ok, message). Never raises — the health page renders either way."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, f"connected to {describe_backend()}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def describe_backend() -> str:
    """Human-readable backend, with credentials stripped. Safe to display."""
    url = settings.resolved_database_url
    if url.startswith("sqlite"):
        return f"SQLite ({url[len('sqlite:///'):]})"
    try:
        return f"PostgreSQL ({make_url_safe(url)})"
    except Exception:  # pragma: no cover - display only
        return "PostgreSQL"


def make_url_safe(url: str) -> str:
    """Strip the password out of a connection URL so it can be shown."""
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    host = parsed.host or "?"
    return f"{parsed.username or '?'}@{host}/{parsed.database or '?'}"


def reset_engine() -> None:
    """Forget the cached engine. Used by tests that swap DATABASE_URL."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
