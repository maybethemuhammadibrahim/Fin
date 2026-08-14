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

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from web.routers import decision, integrity, system
from web.settings import get_web_settings
from web.templating import STATIC_DIR, templates

log = logging.getLogger(__name__)

app = FastAPI(
    title="FinSight",
    description="Revenue integrity for small B2B service businesses.",
    docs_url=None,
    redoc_url=None,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(integrity.router)
app.include_router(decision.router)
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
