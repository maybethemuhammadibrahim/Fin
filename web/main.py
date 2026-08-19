"""[B] The FastAPI frontend. Phase 6.

Runs alongside the Streamlit app rather than replacing it — both read the same
database through the same `core.db.queries` helpers, so you can keep one open
to cross-check the other. Nothing under `app/` was changed to make this work.

    uvicorn web.main:app --reload        # or: python run_web.py
    streamlit run app/main.py            # still works, unchanged

**The demo/live toggle.** `WEB_DATA_MODE=demo|live` in `.env` sets what the app
boots into; the Demo / Live buttons at the top left override it per browser via
a cookie. Demo renders the mockup's own content. Live renders the database, and
where the database has nothing, a skeleton and a line saying which phase fills
it — never a borrowed demo figure.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from web.routers import decision, integrity, system, uploads
from web.settings import get_web_settings
from web.templating import STATIC_DIR, templates

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Open one database connection in the background as the server boots.

    Measured on 2026-08-19: the *first* connection to the Supabase pooler costs
    **9.4 s** — TLS, authentication and SQLAlchemy building the engine — against
    ~0.2 s for every one after it. Whoever loads the first live page pays that,
    and on a host that sleeps when idle it is paid again after every quiet spell.

    So it is paid here instead, by nobody, while the server is starting.

    In a thread, and swallowing everything: the web shell must start with an
    unreachable or unconfigured database, because the pages that tell you so are
    served by this app. A failure here costs one slow first page, which is
    exactly where we started.
    """

    def _warm() -> None:
        try:
            from core.db.database import check_connection

            ok, message = check_connection()
            log.info("database pool warm: %s", message if ok else f"not warmed — {message}")
        except Exception as exc:  # noqa: BLE001
            log.info("database pool not warmed: %s", exc)

    threading.Thread(target=_warm, name="finsight-db-warm", daemon=True).start()
    yield


app = FastAPI(
    title="FinSight",
    description="Revenue integrity for small B2B service businesses.",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(integrity.router)
app.include_router(decision.router)
app.include_router(uploads.router)
app.include_router(system.router)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    """Liveness only. It deliberately does not touch the database or the model
    endpoint — those have their own pages, and a health check that depends on
    a Colab session is a health check that reports the wrong thing."""
    return {"status": "ok", "default_mode": get_web_settings().default_data_mode}


@app.exception_handler(500)
def server_error(request: Request, exc: Exception) -> HTMLResponse:  # pragma: no cover
    log.exception("unhandled error rendering %s", request.url.path)
    return templates.TemplateResponse(
        request, "error.html", {"request": request, "detail": str(exc)}, status_code=500
    )
