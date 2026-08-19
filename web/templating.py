"""[B] The Jinja environment and the one function that renders a page. Phase 6.

Every route ends in `render(...)`. Going through one function is what
guarantees the chrome, the carried query string and the macros are present on
every page — a template that quietly lost `keep_query` would break the tab
links on exactly one screen, which is the kind of bug you find in a demo.

`macros` is registered as a Jinja *global* rather than imported at the top of
`base.html`. A `{% import %}` in a parent template is not reliably visible
inside a block that a child template overrides, and the includes below live
inside such a block. As a global it is simply always there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core import ingest
from web import format as fmt
from web.deps import ask_url, carry, carry_hidden_fields, select_url
from web.settings import get_web_settings

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Filters, so a template can format a raw value in the rare case the presenter
# did not. Presenters should still do the formatting — these are a safety net,
# not an invitation to move money-formatting into the templates.
templates.env.filters["money"] = fmt.money
templates.env.filters["gap"] = fmt.gap
templates.env.filters["dash"] = fmt.dash
templates.env.filters["pct"] = fmt.pct

# Trim whitespace so the fixed-width layout is not pushed around by newlines
# left behind by block tags.
templates.env.trim_blocks = True
templates.env.lstrip_blocks = True

templates.env.globals["macros"] = templates.env.get_template("macros.html").module


def render(
    request: Request,
    template: str,
    *,
    chrome: Any,
    view: Any,
    **extra: Any,
) -> HTMLResponse:
    """Render one page with the context every template assumes exists."""
    path = request.url.path
    context: dict[str, Any] = {
        "request": request,
        "chrome": chrome,
        "view": view,
        # Where we are, for the mode links to come back to.
        "current_path": f"{path}{carry(request)}",
        # Appended to the tab links so switching page keeps the run and state.
        "keep_query": carry(request),
        # The same carried query with `state` swapped — how the header's Upload
        # and Processing tabs link to a screen without losing the run or the
        # data mode. `with_state(None)` drops the parameter instead, which is
        # what the Integrity Engine tab wants: no `state` means live mode goes
        # back to deriving the screen from the run.
        "with_state": lambda state: carry(request, state=state),
        # Hidden inputs for GET forms; the run picker supplies its own `run`.
        "carry_fields": carry_hidden_fields(request, exclude=("run",)),
        "fluid_width": get_web_settings().fluid_width,
        # What the two upload zones accept, as `accept=` attributes. Sourced from
        # `core.ingest` rather than retyped, so the list the browser filters on
        # and the list the server can actually route are the same list — the
        # `.docx`/`.xlsx` trap was exactly this drifting apart.
        "contract_accept": ",".join(f".{e}" for e in ingest.CONTRACT_TYPES),
        "actuals_accept": ",".join(f".{e}" for e in ingest.ACTUALS_TYPES),
        # Sensible defaults so a template that uses them cannot blow up if a
        # route forgot to pass one.
        "select_url": select_url(request, path),
        "ask_url": ask_url(request, path),
    }
    context.update(extra)
    return templates.TemplateResponse(request, template, context)
