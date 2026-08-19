"""[B] The write path. Uploading, and confirming a statement's columns. ADR-025.

**This is the first router in `web/` that writes**, which makes three things
load-bearing rather than stylistic:

* **Every write clears the read cache.** `web/cache.py` holds reads for
  `WEB_CACHE_SECONDS` (300 here), and its docstring says plainly that this is
  safe *only* while nothing writes — "the first write path must call
  `web.cache.clear()`". This is that path. Miss the call and an upload appears
  to do nothing for five minutes, which reads as a broken button.
* **Every POST answers with a redirect** (303, POST/redirect/GET). Otherwise a
  refresh re-posts the file. The duplicate-name check in `core.ingest` catches
  that anyway, but a user should not have to rely on it.
* **Demo mode cannot write.** There is no database behind it, and a demo that
  half-accepted an upload would be the borrowed-figure failure ADR-018 was
  written to prevent. Upload posted in demo mode is refused with a message
  telling you to switch, not silently ignored.

The two-step CSV flow (ADR-010) is why there are three routes and not one. A
contract or a PDF invoice is finished when `POST /upload` returns. A `.csv` is
not: it lands at `pending` and the user is sent to `/upload/{id}/columns` to say
which column is the date and which is the amount, because parsing money out of a
column nobody looked at is exactly what that ADR forbids. Both frontends run the
same two steps through `core.ingest`; only the widgets differ.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from starlette.datastructures import UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from core import ingest
from core.db.models import Document
from core.db.queries import list_runs
from web import cache as web_cache
from web import chrome as chrome_mod
from web.deps import carry, db_or_none, last_db_error, request_mode
from web.presenters import live
from web.templating import render, templates

router = APIRouter()

#: Anything larger is refused before it is read into memory. A contract is a few
#: hundred kilobytes and a year of bank statement is smaller; 25 MB is generous
#: for both and still small enough that a mistaken drop of a video file cannot
#: exhaust the process.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: What the two zones accept, as an `accept=` attribute for the file inputs.
CONTRACT_ACCEPT = ",".join(f".{e}" for e in ingest.CONTRACT_TYPES)
ACTUALS_ACCEPT = ",".join(f".{e}" for e in ingest.ACTUALS_TYPES)


def _back(request: Request, **overrides: str | None) -> str:
    """The Upload screen, keeping the run and the mode."""
    return f"/{carry(request, state='empty', **overrides)}"


@router.post("/upload", name="upload")
async def upload(request: Request) -> RedirectResponse:
    """Take both zones' files, record them, and come back to the Upload screen.

    Contracts and PDF/image invoices are finished here. A `.csv` is recorded at
    `pending` and the redirect carries you to its column mapper — the one step
    that turns a bank export into money, and the one that needs a human.

    **The form is read by hand rather than through `list[UploadFile]`
    parameters**, and that is not a style preference. A browser submitting a
    file input the user left empty still sends a part for it, with
    `filename=""` — Starlette parses that as a *string* field, and the typed
    parameter then fails validation with a raw 422 JSON page. Which means the
    ordinary case of "I have contracts to add but no statement this time" would
    have shown the user a stack-trace-shaped error instead of an upload. Reading
    the form and keeping only the parts that are genuinely files makes an empty
    zone mean what it looks like it means.
    """
    if request_mode(request) != "live":
        return RedirectResponse(_back(request, err="demo"), status_code=303)

    incoming: list[tuple[str, list[tuple[str, bytes]]]] = []
    oversize: list[str] = []

    async with request.form() as form:
        for zone, field_name in (("contract", "contracts"), ("actuals", "actuals")):
            collected: list[tuple[str, bytes]] = []
            for item in form.getlist(field_name):
                if not isinstance(item, UploadFile) or not item.filename:
                    continue
                data = await item.read()
                if len(data) > MAX_UPLOAD_BYTES:
                    oversize.append(item.filename)
                    continue
                collected.append((item.filename, data))
            incoming.append((zone, collected))

    with db_or_none(request) as session:
        if session is None:
            return RedirectResponse(_back(request, err="db"), status_code=303)

        runs = list_runs(session)
        requested = request.query_params.get("run")
        run = next((r for r in runs if str(r.id) == requested), None) or (
            runs[0] if runs else None
        )
        if run is None:
            return RedirectResponse(_back(request, err="norun"), status_code=303)

        recorded = 0
        pending: list[int] = []
        for zone, collected in incoming:
            if zone == "contract":
                batches = [(collected, "contract")]
            else:
                statements, invoices = ingest.split_actuals(collected)
                batches = [(statements, "statement"), (invoices, "invoice")]
            for batch, category in batches:
                result = ingest.ingest_files(session, run.id, batch, category=category)
                recorded += result.recorded
                pending += [f.document_id for f in result.pending if f.document_id]

    # After the session has committed, never before: a cleared cache that then
    # rolls back would leave the next reader rebuilding the same old rows.
    web_cache.clear()

    if pending:
        # Straight to the thing that still needs a person. Finishing the upload
        # and leaving the statement sitting at `pending` on a list somewhere is
        # how a run ends up with contracts and no payments.
        return RedirectResponse(
            f"/upload/{pending[0]}/columns{carry(request)}", status_code=303
        )
    if oversize:
        return RedirectResponse(_back(request, err="size"), status_code=303)
    return RedirectResponse(_back(request, ok=str(recorded)), status_code=303)


@router.get("/upload/{document_id}/columns", response_class=HTMLResponse, name="columns")
def columns_form(document_id: int, request: Request) -> HTMLResponse:
    """Ask which column is the date and which is the amount (ADR-010).

    A header layout confirmed before is applied without asking again — the
    proposal carries the remembered answer and the form says so.
    """
    if request_mode(request) != "live":
        return RedirectResponse(_back(request, err="demo"), status_code=303)

    with db_or_none(request) as session:
        if session is None:
            return _error_page(request, last_db_error() or "The database could not be reached.")

        document = session.get(Document, document_id)
        if document is None or document.category != "statement":
            return _error_page(request, "That upload is not a statement awaiting a mapping.")

        proposal = ingest.propose_mapping(session, document)
        if proposal is None:
            document.extraction_status = "failed"
            document.error_message = "could not read the uploaded file back from storage"
            web_cache.clear()
            return _error_page(request, document.error_message)

        runs = list_runs(session)
        chrome = chrome_mod.build(
            data_mode="live",
            page="integrity",
            demo_state="empty",
            run_label=live.run_label(next((r for r in runs if r.id == document.run_id), None)),
            state_note=f"Confirm the columns in {document.filename}",
            is_offline=False,
            runs=[],
        )
        return render(
            request,
            "upload/columns.html",
            chrome=chrome,
            view=None,
            document=document,
            proposal=proposal,
            fields=ingest.REQUIRED_FIELDS,
            post_url=f"/upload/{document_id}/columns{carry(request)}",
        )


@router.post("/upload/{document_id}/columns", name="columns_confirm")
async def columns_confirm(
    document_id: int,
    request: Request,
    date: str = Form(default=""),
    amount: str = Form(default=""),
    description: str = Form(default=""),
) -> RedirectResponse:
    """Parse the statement with the confirmed mapping. This writes money rows."""
    if request_mode(request) != "live":
        return RedirectResponse(_back(request, err="demo"), status_code=303)

    # "" is the form's "(none)" option. `missing_fields` decides what is
    # required — description is genuinely optional, date and amount are not.
    mapping = {
        field: value
        for field, value in (("date", date), ("amount", amount), ("description", description))
        if value
    }

    with db_or_none(request) as session:
        if session is None:
            return RedirectResponse(_back(request, err="db"), status_code=303)

        document = session.get(Document, document_id)
        if document is None:
            return RedirectResponse(_back(request, err="gone"), status_code=303)

        if ingest.missing_fields(mapping):
            return RedirectResponse(
                f"/upload/{document_id}/columns{carry(request, err='fields')}", status_code=303
            )

        outcome = ingest.apply_mapping(session, document, mapping)

    web_cache.clear()

    if outcome.status != "complete":
        return RedirectResponse(
            f"/upload/{document_id}/columns{carry(request, err='parse')}", status_code=303
        )
    return RedirectResponse(_back(request, imported=str(outcome.transactions)), status_code=303)


def _error_page(request: Request, detail: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "error.html", {"request": request, "detail": detail}, status_code=400
    )
