"""[B] The Decision Engine page. Phase 6.

Demo mode renders the mockup's worked example. Live mode renders the working
the database can support and no verdict at all — `core/ai/decision_analyzer.py`
is a stub and no table holds expenses, so any verdict here would be invented.
The page says which of those two is missing rather than showing a plausible
"Yes", because a wrong answer to "can I afford this hire" is the most expensive
thing this product could get wrong.
"""

from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from web import chrome as chrome_mod
from web.deps import ask_url, db_or_none, last_db_error, request_mode
from web.presenters import demo, live
from web.templating import render
from web.viewmodels import DecisionView, RunOption

router = APIRouter()


@router.get("/decision", response_class=HTMLResponse, name="decision")
def decision_page(request: Request) -> HTMLResponse:
    mode = request_mode(request)
    question = request.query_params.get("q") or ""

    if mode == "demo":
        view = demo.decision()
        state = request.query_params.get("state")
        state = state if state in demo.STATE_NOTES else "review"
        chrome = chrome_mod.build(
            data_mode="demo",
            page="decision",
            demo_state=state,
            run_label=demo.RUN_LABEL,
            state_note=demo.STATE_NOTES[state],
            is_offline=state == "offline",
        )
        return render(request, "decision/index.html", chrome=chrome, view=view,
                      ask_url=ask_url(request, "/decision"))

    # -- live -------------------------------------------------------------
    with db_or_none(request) as session:
        if session is None:
            view = DecisionView(
                question=question,
                suggestions=[],
                answered=False,
                verdict_word=None,
                verdict_qual=None,
                lead_html=None,
                after=None,
                notices={"decision": last_db_error() or "The database could not be reached."},
            )
            chrome = chrome_mod.build(
                data_mode="live",
                page="decision",
                demo_state="empty",
                run_label=None,
                state_note="Database unreachable",
                is_offline=False,
            )
            return render(request, "decision/index.html", chrome=chrome, view=view,
                          ask_url=ask_url(request, "/decision"))

        runs = live.runs(session)
        requested = request.query_params.get("run")
        run = next((r for r in runs if str(r.id) == requested), None) or (runs[0] if runs else None)
        run_id = run.id if run else None

        # No table holds expenses (ADR-024), so the figure arrives in the URL.
        # Bad input is ignored rather than raised on: a stray character in a
        # query string must not 500 the page, it must fall back to "can't say".
        raw_expenses = request.query_params.get("exp")
        try:
            monthly_expenses = float(raw_expenses) if raw_expenses not in (None, "") else None
        except ValueError:
            monthly_expenses = None
        if monthly_expenses is not None and monthly_expenses < 0:
            monthly_expenses = None

        view = live.decision(
            session, run_id, question=question, monthly_expenses=monthly_expenses
        )
        # DecisionView is frozen, so echo the figure back with `replace` rather
        # than assigning — the view models are immutable on purpose.
        view = dataclasses.replace(view, expenses_value=monthly_expenses)
        state = live.derive_state(session, run_id)
        chrome = chrome_mod.build(
            data_mode="live",
            page="decision",
            demo_state=state,
            run_label=live.run_label(run),
            state_note=live.state_note(session, run_id, state),
            is_offline=False,
            runs=[
                RunOption(id=r.id, label=f"{r.label} · #{r.id}", selected=r.id == run_id)
                for r in runs
            ],
        )
        return render(request, "decision/index.html", chrome=chrome, view=view,
                      ask_url=ask_url(request, "/decision"))
