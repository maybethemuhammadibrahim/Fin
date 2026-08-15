"""[B] The Integrity Engine page, and the detail fragment behind it. Phase 6.

Two routes, and the second is what makes the screen feel instant:

* ``/`` renders the whole page.
* ``/finding/{id}`` renders **only** the detail pane, as an HTML fragment.

`app.js` fetches the fragment on hover and swaps it on click, so selecting a
finding costs one small request instead of a full page render — and usually
zero, because the hover already fetched it. The same URL renders a whole page
when you arrive at it directly, so the fragment is an optimisation, never a
requirement: with JavaScript off, every row is still an ordinary link.

Both data modes end at the same templates with the same view models; the branch
is a few lines wide and lives here.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from web import chrome as chrome_mod
from web.deps import carry, db_or_none, last_db_error, request_mode, select_url, sort_url
from web.presenters import demo, live
from web.presenters.grouping import DEFAULT_SORT
from web.templating import render, templates
from web.viewmodels import IntegrityView, RunOption

router = APIRouter()

#: The five buttons on the state bar. `offline` is not a fifth screen — it is
#: `review` plus the banner, exactly as in the mockup.
DEMO_STATES = ("empty", "processing", "review", "clean", "offline")


def _run_options(runs, run_id):
    return [
        RunOption(id=r.id, label=f"{r.label} · #{r.id}", selected=r.id == run_id) for r in runs
    ]


def _pick_run(session, requested: str | None):
    """The run to show, and the list for the picker. Cached like every other
    read — the run list changes only when a script creates one."""
    runs = live.runs(session)
    run = next((r for r in runs if str(r.id) == requested), None) or (runs[0] if runs else None)
    return runs, run


@router.get("/", response_class=HTMLResponse, name="integrity")
def integrity_page(request: Request) -> HTMLResponse:
    mode = request_mode(request)
    state_param = request.query_params.get("state")
    selected = request.query_params.get("sel")
    sort = request.query_params.get("sort") or DEFAULT_SORT

    extra = {
        "select_url": select_url(request, "/"),
        "sort_url": sort_url(request, "/"),
    }

    if mode == "demo":
        state = state_param if state_param in DEMO_STATES else "review"
        view = demo.integrity(
            "review" if state == "offline" else state,
            selected=int(selected) if (selected or "").isdigit() else demo.DEFAULT_SELECTION,
            sort=sort,
        )
        chrome = chrome_mod.build(
            data_mode="demo",
            page="integrity",
            demo_state=state,
            run_label=demo.RUN_LABEL,
            state_note=demo.STATE_NOTES[state],
            is_offline=state == "offline",
        )
        return render(request, "integrity/index.html", chrome=chrome, view=view, **extra)

    # -- live -------------------------------------------------------------
    with db_or_none(request) as session:
        if session is None:
            view = IntegrityView(
                state="empty",
                notices={"db": last_db_error() or "The database could not be reached."},
            )
            chrome = chrome_mod.build(
                data_mode="live",
                page="integrity",
                demo_state="empty",
                run_label=None,
                state_note="Database unreachable",
                is_offline=False,
            )
            return render(request, "integrity/index.html", chrome=chrome, view=view, **extra)

        runs, run = _pick_run(session, request.query_params.get("run"))
        run_id = run.id if run else None

        view = live.integrity(session, run_id, selected_id=selected, sort=sort)
        chrome = chrome_mod.build(
            data_mode="live",
            page="integrity",
            demo_state=view.state,
            run_label=live.run_label(run),
            state_note=live.state_note(session, run_id, view.state),
            is_offline=False,
            runs=_run_options(runs, run_id),
        )
        return render(request, "integrity/index.html", chrome=chrome, view=view, **extra)


@router.get("/finding/{finding_id}", response_class=HTMLResponse, name="finding_detail")
def finding_detail(finding_id: str, request: Request) -> HTMLResponse:
    """Just the detail pane, for `app.js` to swap in.

    Returns 404 with a rendered "not found" pane rather than a JSON error, so a
    stale id from a bookmarked URL degrades into something readable instead of
    wiping the pane.
    """
    mode = request_mode(request)

    if mode == "demo":
        sel = demo.detail(int(finding_id)) if finding_id.isdigit() else None
        notice = None
    else:
        with db_or_none(request) as session:
            if session is None:
                sel, notice = None, last_db_error()
            else:
                _runs, run = _pick_run(session, request.query_params.get("run"))
                sel = live.detail(session, run.id, finding_id) if run else None
                notice = live.NOTICE_AGENT

    return templates.TemplateResponse(
        request,
        "integrity/_finding_detail.html",
        {"request": request, "sel": sel, "agent_notice": notice},
        status_code=200 if sel else 404,
        # The fragment is per-run and per-mode state; caching it in a shared
        # proxy would serve one user's run to another. app.js keeps its own
        # in-memory cache for the session instead.
        headers={"Cache-Control": "no-store"},
    )
