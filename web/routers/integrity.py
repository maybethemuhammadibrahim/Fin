"""[B] The Integrity Engine page. Phase 6.

Both data modes end at the same template with the same view model; the branch
is four lines wide and lives here. Everything below that point — the templates,
the macros, the CSS — cannot tell which mode produced the page, which is what
makes "does live mode look right?" a question you can answer by eye.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from web import chrome as chrome_mod
from web.deps import carry, db_or_none, last_db_error, request_mode, select_url
from web.presenters import demo, live
from web.templating import render
from web.viewmodels import IntegrityView, RunOption

router = APIRouter()

#: The five buttons on the state bar. `offline` is not a fifth screen — it is
#: `review` plus the banner, exactly as in the mockup.
DEMO_STATES = ("empty", "processing", "review", "clean", "offline")


@router.get("/", response_class=HTMLResponse, name="integrity")
def integrity_page(request: Request) -> HTMLResponse:
    mode = request_mode(request)
    state_param = request.query_params.get("state")
    selected = request.query_params.get("sel")

    if mode == "demo":
        state = state_param if state_param in DEMO_STATES else "review"
        view = demo.integrity(
            "review" if state == "offline" else state,
            selected=int(selected) if (selected or "").isdigit() else demo.DEFAULT_SELECTION,
        )
        chrome = chrome_mod.build(
            data_mode="demo",
            page="integrity",
            demo_state=state,
            run_label=demo.RUN_LABEL,
            state_note=demo.STATE_NOTES[state],
            is_offline=state == "offline",
        )
        return render(request, "integrity/index.html", chrome=chrome, view=view,
                      select_url=select_url(request, "/"))

    # -- live -------------------------------------------------------------
    with db_or_none() as session:
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
            return render(request, "integrity/index.html", chrome=chrome, view=view,
                          select_url=select_url(request, "/"))

        from core.db.queries import list_runs

        runs = list_runs(session)
        requested = request.query_params.get("run")
        run = next((r for r in runs if str(r.id) == requested), None) or (runs[0] if runs else None)
        run_id = run.id if run else None

        view = live.integrity(session, run_id, selected_id=selected)
        chrome = chrome_mod.build(
            data_mode="live",
            page="integrity",
            demo_state=view.state,
            run_label=live.run_label(run),
            state_note=live.state_note(session, run_id, view.state),
            is_offline=False,
            runs=[
                RunOption(id=r.id, label=f"{r.label} · #{r.id}", selected=r.id == run_id)
                for r in runs
            ],
        )
        return render(request, "integrity/index.html", chrome=chrome, view=view,
                      select_url=select_url(request, "/"))
