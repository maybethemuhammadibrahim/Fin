"""[B] The data-mode toggle and the endpoint status page. Phase 6.

`/mode/{mode}` is a plain GET that sets a cookie and bounces you back where you
came from. A GET that mutates is normally a smell; here the mutation is one
browser preference with no side effects, and making it a link is what lets the
toggle live in the state bar without a form or a line of JavaScript.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web import chrome as chrome_mod
from web.settings import DATA_MODES, MODE_COOKIE, MODE_COOKIE_MAX_AGE, get_web_settings
from web.templating import templates

router = APIRouter()


def _safe_next(raw: str | None) -> str:
    """Only ever redirect within this app.

    `next` comes off the query string, so without this an open-redirect falls
    out of a two-line convenience feature.
    """
    if not raw:
        return "/"
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc or not raw.startswith("/"):
        return "/"
    return raw


@router.get("/mode/{mode}", name="set_mode")
def set_mode(mode: str, request: Request) -> RedirectResponse:
    """Switch between demo and live content, then return to the page you were on."""
    target = _safe_next(request.query_params.get("next"))
    response = RedirectResponse(target, status_code=303)
    if mode in DATA_MODES:
        response.set_cookie(
            MODE_COOKIE,
            mode,
            max_age=MODE_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
    return response


@router.get("/mode/reset", name="reset_mode")
def reset_mode(request: Request) -> RedirectResponse:
    """Forget the cookie and fall back to whatever WEB_DATA_MODE says."""
    response = RedirectResponse(_safe_next(request.query_params.get("next")), status_code=303)
    response.delete_cookie(MODE_COOKIE)
    return response


@router.get("/endpoint", response_class=HTMLResponse, name="endpoint_page")
def endpoint_page(request: Request) -> HTMLResponse:
    """Where the offline banner's "Change endpoint" button lands.

    Read-only on purpose. The endpoint URL rotates every time a notebook
    restarts, and writing it is the Streamlit Model endpoint page's job
    (`app/pages/8_model_endpoint.py`) — duplicating that here would give two
    places to set one value and no way to tell which won.
    """
    rows: list[tuple[str, str, str]] = []
    active_provider = ""
    try:
        from core.ai import endpoints

        active_provider = endpoints.active().provider
        for endpoint in endpoints.list_endpoints():
            rows.append(
                (
                    endpoint.label,
                    endpoint.base_url or "not set",
                    f"{endpoint.env_var} · {endpoint.source}",
                )
            )
    except Exception as exc:  # noqa: BLE001
        rows.append(("Configuration error", str(exc), ""))

    label, online = chrome_mod.endpoint_status()
    return templates.TemplateResponse(
        request,
        "endpoint.html",
        {
            "request": request,
            "rows": rows,
            "active_provider": active_provider,
            "endpoint_label": label,
            "endpoint_online": online,
            "fluid_width": get_web_settings().fluid_width,
        },
    )
