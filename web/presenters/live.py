"""[B] The same view models, built from the database. Phase 6.

The rule this file lives under: **it never borrows from `demo.py`.** Where the
database has no answer, the view model carries `None` or an empty list and the
template draws a skeleton with a line saying which phase fills it. A page of
dashes is a correct page — it is the build telling the truth about itself. A
page that quietly showed a demo figure instead would be the one bug this whole
architecture is arranged to prevent.

What is genuinely absent today, and where it lands:

* agent verdicts and tool traces — **built** (Phase 8), but `web/` cannot start a
  verification run: `web/` can upload but has no reconcile or verify action yet
  (ADR-025 opened the write path; those two buttons are still Streamlit's). A finding shows its
  verdict and tool trace as soon as something has written one; until then the
  pane says so and names where the run is started (`app/`), not a phase;
* headline prose and the Decision Engine's answer — `core/ai/decision_analyzer.py`
  is a stub, Phase 9;
* clause page coordinates — Phase 7, and nullable forever after (ADR-005), so
  the viewer degrades rather than crashes. Phase 6 writes the clause *quote* for
  every finding it computes; only the page and box are still missing, and for a
  contract sourced from EDGAR as HTML there is no page to point at at all
  (known issue #28);
* expenses — no table holds them, so no surplus can be computed. The working
  ledger shows revenue and findings and dashes the rest.

Every figure that *is* shown comes out of a `core.db.queries` helper and was
computed by deterministic Python upstream. Nothing here does arithmetic beyond
averaging what the query returned.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from web import cache as web_cache
from web import prefetch
from core.ai import decision_analyzer
from core.engine import cashflow
from core.db.queries import (
    AnomalyRow,
    RunRow,
    get_clause_reference,
    get_client_totals,
    get_summary_stats,
    list_anomalies,
    list_documents,
    list_runs,
    list_transaction_rows,
    revenue_by_month,
)
from web.format import DASH, day_month, gap as fmt_gap, money, month_name, pct, plural
from web.presenters.grouping import (
    DEFAULT_SORT,
    build_groups,
    haystack,
    sort_key,
    sort_options,
)
from web.viewmodels import (
    Bar,
    Card,
    CleanRun,
    CleanStat,
    DecisionView,
    FindingDetail,
    FindingRow,
    IntegrityView,
    PipelineDoc,
    STATUS_LABELS,
    TYPE_LABELS,
    ToolCall,
    Txn,
    WorkRow,
)

#: ADR-006 matches a payment to a calendar month with 15 days of slack at each
#: boundary. The drill-down widens its ledger window by the same amount so the
#: user sees the payments the classifier saw, not a narrower set.
TOLERANCE_DAYS = 15

#: Which of the four Integrity screens is warranted by what the run holds.
#: Order matters — a run with findings is `review` even while documents are
#: still processing, because the findings are the thing worth looking at.
#: Shown only while a finding has no verdict *and* no tool trace. The agent
#: itself exists (Phase 8) — what is missing is a run over this finding, and
#: `web/` can upload (ADR-025) but cannot yet *run* anything — no reconcile and no
#: verify button exists here (known issue #56).
#: So this names where the run is started rather than naming a phase.
NOTICE_AGENT = (
    "This finding has not been through the verification agent yet, so no tool "
    "trace and no agent verdict are shown here — better than a confidence score "
    "nobody computed. Run \"Verify findings\" in the Streamlit app to fill it in; "
    "this frontend is read-only."
)
#: The analyser exists (Phase 9). What this frontend cannot do is *ask* it: it has
#: no POST route for it, and a verdict needs both a
#: question and a monthly running-cost figure that only a form can collect. So
#: this names the surface that can answer, rather than a phase — the lesson from
#: the 2026-08-17 audit, which found four strings still promising Phase 8.
NOTICE_DECISION = (
    "The working below is real — computed by the same engine the Streamlit app uses. "
    "A verdict needs two things this read-only frontend cannot collect: your question "
    'and your monthly running costs. Ask it on the Decision Engine page of the '
    "Streamlit app."
)
NOTICE_EXPENSES = (
    "No table holds expenses (ADR-024), so a surplus cannot be computed from the "
    "database. Add your monthly running costs to the box above and the verdict "
    "becomes a real yes or no; without them, only a share of revenue can be stated."
)
#: Nothing asked yet. Not an error — the page is waiting, and the working below is
#: already real, so it says that rather than dressing the space as a failure.
NOTICE_ASK = (
    "Ask a question above and this becomes a verdict. The working below is already "
    "computed from your own records."
)
NOTICE_NO_AMOUNT = (
    "No amount was found in that question, so there is nothing to test against. "
    "Name a figure — for example “a $5,000 a month designer”."
)


# ---------------------------------------------------------------------------
# Request-scoped memo
# ---------------------------------------------------------------------------

#: Supabase is a network hop away — measured at roughly a quarter-second per
#: round trip from here — so the query *count* per render is the whole
#: performance story, not the SQL. The first version of this module asked for
#: `get_summary_stats` three times per page (once to derive the state, once for
#: the cards, once for the state-bar note), and that one function is seven
#: queries: 21 round trips for one figure, before anything else ran. Measured:
#: 35 queries and 8.7s for a single page.
#:
#: The cache hangs off the Session, which `deps.db_or_none` opens and closes per
#: request. That makes its lifetime exactly one request by construction — it
#: cannot go stale between them and it cannot leak across users, which a
#: module-level dict would do on both counts.
#: Layered on top of that is `web.cache`, a few-second TTL shared across
#: requests. The per-session memo below is what makes one render cheap; the TTL
#: cache is what makes the *next* render free. Read that module's docstring for
#: why a read cache is safe here, and what the upload path owes it.
def _memo(session: Session, key: tuple, build):
    cache = _memo_store(session)
    if key not in cache:
        cache[key] = web_cache.get_or_set(key, build, enabled=cache_enabled(session))
    return cache[key]


def cache_enabled(session: Session) -> bool:
    """False when the request asked for fresh data with ``?fresh=1``.

    Set by the router on the session, because the presenter has no request.
    """
    return not getattr(session, "_finsight_fresh", False)


def _stats(session: Session, run_id: int):
    return _memo(session, ("stats", run_id), lambda: get_summary_stats(session, run_id))


def _anomalies(session: Session, run_id: int):
    return _memo(session, ("anomalies", run_id), lambda: list_anomalies(session, run_id))


def _documents(session: Session, run_id: int):
    return _memo(session, ("documents", run_id), lambda: list_documents(session, run_id))


def runs(session: Session):
    """Every run, for the picker. Cached — this frontend uploads into a run but
    never creates one, so the list only changes when a script makes it change."""
    return _memo(session, ("runs",), lambda: list_runs(session))


def _memo_store(session: Session) -> dict:
    cache = getattr(session, "_finsight_memo", None)
    if cache is None:
        cache = {}
        try:
            session._finsight_memo = cache  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - Session always accepts this
            pass
    return cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _month_window(day: date | None) -> tuple[date | None, date | None]:
    """The calendar month around `day`, widened by the ADR-006 tolerance."""
    if day is None:
        return None, None
    first = day.replace(day=1)
    last = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    return first - timedelta(days=TOLERANCE_DAYS), last + timedelta(days=TOLERANCE_DAYS)


def _verdict(status: str) -> tuple[str, str]:
    """anomaly.status -> (word, tag kind). Unknown statuses show as themselves."""
    return STATUS_LABELS.get(status, (status.replace("_", " ").title(), "out"))


def _type_label(anomaly_type: str) -> str:
    return TYPE_LABELS.get(anomaly_type, anomaly_type.replace("_", " ").capitalize())


def _title(row: AnomalyRow) -> str:
    """A one-line description built from stored figures — never from a model.

    Each of the four leak types has one sentence, filled with amounts the
    engine computed. It says only what the row already claims.
    """
    when = month_name(row.billing_date) or "an unrecorded period"
    if row.anomaly_type == "ghost_invoice":
        return f"Nothing arrived against a billing due in {when}"
    if row.anomaly_type == "forgotten_raise":
        return f"Billed at the pre-rise rate in {when}"
    if row.anomaly_type == "zombie_discount":
        return f"Still billed at a discounted rate in {when}"
    if row.anomaly_type == "short_change":
        return f"Part-paid in {when}, and the balance was never chased"
    return f"Shortfall in {when}"


def _headline(row: AnomalyRow) -> str:
    """The drill-down's heading. Two stored numbers and a verb, nothing more."""
    due = money(row.expected_amount)
    got = money(row.actual_amount)
    if row.anomaly_type == "ghost_invoice":
        return f"{due} was due. Nothing arrived."
    return f"{due} was due. {got} arrived."


def _calc(row: AnomalyRow) -> str:
    return (
        f"due {money(row.expected_amount)} · received {money(row.actual_amount)} "
        f"· not collected {money(row.gap)}"
    )


_STAGE_BY_STATUS = {
    # uploaded · text read · rules extracted · reconciled
    "pending": (1, 0, 0, 0),
    "processing": (1, 2, 0, 0),
    "failed": (1, 3, 0, 0),
    "complete": (1, 1, 1, 0),
}


def _pipeline_doc(doc, reconciled: bool) -> PipelineDoc:
    stages = list(_STAGE_BY_STATUS.get(doc.extraction_status, (1, 0, 0, 0)))
    if doc.extraction_status == "complete" and reconciled:
        stages[3] = 1

    status = {
        "pending": "Queued",
        "processing": "Reading",
        "failed": "Failed",
        "complete": "Reconciled" if reconciled else "Read",
    }.get(doc.extraction_status, doc.extraction_status.title())

    action = {"failed": "Replace file", "processing": "Check status", "pending": "Check status"}.get(
        doc.extraction_status, "Open"
    )

    if doc.error_message:
        note = doc.error_message
    elif doc.extraction_status == "complete":
        pages = doc.extracted_page_count
        note = f"Text read from {plural(pages, 'page')}." if pages else "Text read."
        if not reconciled:
            note += " Waiting on the rest of the run before it can be compared."
    elif doc.extraction_status == "processing":
        note = "Reading the text out of this file."
    elif doc.extraction_status == "pending":
        note = "Uploaded and queued. Nothing has been read from it yet."
    else:
        note = None

    return PipelineDoc(
        name=doc.filename,
        note=note,
        status=status,
        action=action,
        stages=tuple(stages),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Integrity Engine
# ---------------------------------------------------------------------------


def derive_state(session: Session, run_id: int | None) -> str:
    """Which screen this run has earned.

    * no run, or a run with nothing in it -> ``empty``
    * findings on file -> ``review``
    * every document read and nothing found -> ``clean``
    * anything else still in flight -> ``processing``
    """
    if run_id is None:
        return "empty"

    stats = _stats(session, run_id)
    if stats.document_count == 0:
        return "empty"
    if stats.anomaly_count:
        return "review"

    docs = _documents(session, run_id)
    if all(d.extraction_status == "complete" for d in docs):
        # Read everything, found nothing. That is a result, not a blank page —
        # but only if there was something to reconcile against in the first place.
        return "clean" if stats.client_count else "processing"
    return "processing"


def _cards(stats) -> list[Card]:
    # Two different ADR-005 failures, kept apart: `quoted` is how many findings
    # carry a clause at all, `grounded_count` is how many of those the locator
    # could place on a page. Collapsing them would hide the one that matters.
    quoted = stats.anomaly_count - stats.unlinked_count
    counts = " · ".join(
        p
        for p in (
            f"{stats.anomaly_count - stats.unverified_count} checked" if stats.anomaly_count else None,
            f"{stats.unverified_count} not yet checked" if stats.unverified_count else None,
        )
        if p
    )
    return [
        Card("Not collected", money(stats.total_leaked), "Every finding on file", accent=True),
        Card("Findings", str(stats.anomaly_count), counts or None),
        Card(
            "Clients affected",
            f"{stats.affected_client_count} of {stats.client_count}" if stats.client_count else DASH,
            f"Across {plural(stats.document_count, 'document')} on file",
        ),
        Card(
            "Clauses located",
            f"{stats.grounded_count} of {stats.anomaly_count}" if stats.anomaly_count else DASH,
            f"{quoted} carry a quote · {stats.unlocatable_count} not placed on a page"
            if stats.anomaly_count
            else None,
        ),
    ]


def _detail(session: Session, run_id: int, row: AnomalyRow) -> FindingDetail:
    """Cached whole, not per-query. The three reads below (clause, ledger,
    client totals) always travel together, so caching the assembled result is
    three fewer round trips than caching each one."""
    return _memo(session, ("detail", run_id, row.id), lambda: _build_detail(session, run_id, row))


def _build_detail(session: Session, run_id: int, row: AnomalyRow) -> FindingDetail:
    verdict, kind = _verdict(row.status)

    # These three reads were tried as a concurrent gather (see web/prefetch.py)
    # and measured *no faster*, twice — the per-connection cost cancels the
    # overlap on so few statements. Left sequential on the evidence.

    # -- the contract side ------------------------------------------------
    clause = get_clause_reference(session, row.clause_reference_id) if row.clause_reference_id else None
    if clause is None:
        # Hard rule 5: a finding with no clause is not proven. Say so rather
        # than showing an empty quote box that reads as "nothing to see".
        clause_text = None
        clause_ref = None
        doc_meta = None
        ground = "none"
        page_image_url = None
        page_is_typeset = False
    else:
        clause_text = clause.clause_text
        clause_ref = clause.clause_type.replace("_", " ") if clause.clause_type else None
        parts = [clause.document_filename or "unknown document"]
        if clause.source_page is not None:
            parts.append(f"page {clause.source_page}")
        doc_meta = " — ".join(parts)
        ground = clause.locate_method if clause.locate_method in {"exact", "fuzzy"} else "none"
        # Phase 7: the page itself, rendered by `/clause/{id}/page.png`. Offered
        # whenever there is a document behind the clause — an ungrounded quote
        # still gets its page, just without a box (ADR-005).
        page_image_url = f"/clause/{clause.id}/page.png" if clause.document_id else None
        # Read off the filename rather than fetching the document row: this is
        # exactly how `pdf_renderer.ensure_pdf` decides, and over a 400 ms link
        # an extra query for a caption is a query too many (known issue #53).
        page_is_typeset = not (clause.document_filename or "").lower().endswith(".pdf")

    # -- the ledger side --------------------------------------------------
    start, end = _month_window(row.billing_date)
    txn_rows = (
        list_transaction_rows(session, run_id, client_id=row.client_id, start=start, end=end)
        if row.billing_date
        else []
    )
    txns = [
        Txn(
            label=t.description or f"Payment — {t.client_name or 'unassigned'}",
            meta=" · ".join(
                p for p in (day_month(t.transaction_date), t.document_filename) if p
            )
            or None,
            amount=money(t.amount),
        )
        for t in txn_rows
    ]
    if not txns:
        txns = [
            Txn(
                label=f"No payment matched to this client in {month_name(row.billing_date) or 'this period'}",
                meta=None,
                amount=money(0),
                muted=True,
            )
        ]

    # A client can have several billings falling in one month — a retainer and
    # a milestone, say — so the payments visible in the window are not
    # necessarily the payments reconciliation matched to *this* one. Where the
    # two differ, both are shown and labelled. Where they agree, the extra row
    # is suppressed rather than printing the same figure twice.
    window_sum = round(sum(t.amount for t in txn_rows), 2)
    window_total = (
        money(window_sum) if abs(window_sum - row.actual_amount) >= 0.005 else None
    )

    # -- the client strip -------------------------------------------------
    totals = get_client_totals(session, run_id, row.client_id)

    # -- the verification side --------------------------------------------
    tools = _tool_calls(row)

    return FindingDetail(
        client=row.client_name,
        type_label=_type_label(row.anomaly_type),
        period=month_name(row.billing_date),
        headline=_headline(row),
        provenance=(
            f"Reconciled against {plural(len(txn_rows), 'matched payment')} in the "
            f"{month_name(row.billing_date)} window"
            if row.billing_date
            else None
        ),
        calc=_calc(row),
        clause=clause_text,
        clause_ref=clause_ref,
        doc_meta=doc_meta,
        ground=ground,
        txns=txns,
        window_total=window_total,
        received_total=money(row.actual_amount),
        due_total=money(row.expected_amount),
        gap_total=fmt_gap(row.gap),
        verdict=verdict,
        kind=kind,
        tools=tools,
        agent_prose=row.agent_reasoning,
        needs_review=row.status in {"unverified", "needs_review"},
        c_contracts=str(totals.contract_count) if totals else None,
        c_received=money(totals.received_total) if totals else None,
        c_share=pct(totals.revenue_share) if totals else None,
        c_gap=fmt_gap(totals.gap_total) if totals else None,
        page_image_url=page_image_url,
        page_is_typeset=page_is_typeset,
    )


def _tool_calls(row: AnomalyRow) -> list[ToolCall]:
    """The agent's trace, if Phase 8 has written one.

    `agent_tool_calls` is free-form JSON, so read it defensively — a run from an
    older schema should degrade to no trace, not to a 500.
    """
    raw = row.agent_tool_calls or []
    calls: list[ToolCall] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        call = item.get("call") or item.get("tool") or item.get("name")
        result = item.get("result") or item.get("output") or item.get("response")
        if call:
            calls.append(ToolCall(str(call), str(result) if result is not None else DASH))
    return calls


def detail(session: Session, run_id: int, anomaly_id: str) -> FindingDetail | None:
    """One finding's detail, for the fragment route. None when unknown.

    Looks the row up in the run's own list rather than by primary key alone, so
    an id from a different run cannot be rendered under this run's chrome.
    """
    rows = _anomalies(session, run_id)
    row = next((r for r in rows if str(r.id) == str(anomaly_id)), None)
    return _detail(session, run_id, row) if row else None


#: The two screens a user may navigate to in live mode, overriding
#: `derive_state`. Both are honest to ask for at any time: Upload is standing
#: copy about getting data in, and the document list is worth reading whether or
#: not anything is still in flight. The other three stay derived — a button
#: promising "Findings" on a run with none would be inventing a screen.
FORCEABLE_STATES = frozenset({"empty", "processing"})


def integrity(
    session: Session,
    run_id: int | None,
    selected_id: str | None = None,
    sort: str = DEFAULT_SORT,
    force_state: str | None = None,
) -> IntegrityView:
    """Build the Integrity Engine view from whatever the run actually holds.

    `force_state` is the header's Upload / Processing tabs asking for a specific
    screen. Anything outside `FORCEABLE_STATES` is ignored rather than honoured,
    so a hand-typed `?state=clean` cannot dress a run with findings as a clean
    one — the URL may choose between screens, never contradict the data.
    """
    derived = derive_state(session, run_id)
    state = derived
    if run_id is not None and force_state in FORCEABLE_STATES:
        state = force_state

    if run_id is None or state == "empty":
        # The "load a run" hint belongs on a run that genuinely has nothing, not
        # on the Upload screen someone navigated to on purpose — there it would
        # read as a complaint about a run that is fine. The template owns the
        # wording (it carries markup); this owns whether it is true.
        return IntegrityView(
            state="empty",
            notices={"empty_run": "yes"} if derived == "empty" else {},
        )

    stats = _stats(session, run_id)

    if state == "processing":
        # Fetched only here. The review and clean screens never render the
        # document list, and over a 400 ms link an unused query is 400 ms.
        docs = _documents(session, run_id)
        done = sum(1 for d in docs if d.extraction_status == "complete")
        failed = sum(1 for d in docs if d.extraction_status == "failed")
        in_flight = len(docs) - done - failed
        sub = " · ".join(
            p
            for p in (
                f"{done} read" if done else None,
                f"{in_flight} in progress" if in_flight else None,
                f"{failed} failed" if failed else None,
            )
            if p
        )
        # Reachable from the header now, not only when something is mid-flight,
        # so the headline has to state what is actually true of these documents.
        # "Reading 5 documents" over five finished ones is the kind of small lie
        # this codebase spends its comments avoiding.
        if in_flight:
            headline = f"Reading {plural(len(docs), 'document')}"
        elif not docs:
            headline = "Nothing uploaded against this run"
        elif failed:
            headline = f"{plural(len(docs), 'document')} on file · {failed} failed"
        else:
            headline = f"{plural(len(docs), 'document')} on file · all read"

        return IntegrityView(
            state="processing",
            pipeline=[_pipeline_doc(d, reconciled=bool(stats.anomaly_count)) for d in docs],
            pipeline_headline=headline,
            pipeline_sub=sub or None,
            column_map_file=None,
            column_map=[],
            column_map_note=None,
            clients_headline=None,
            clients=[],
            notices={
                "column_map": (
                    "The confirmed CSV column mapping is stored per header signature "
                    "(ADR-010) and is only shown while a statement is being imported. "
                    "Nothing is awaiting confirmation in this run."
                ),
                "clients": (
                    "Client matching runs during import. This run has no names waiting "
                    "on a decision."
                ),
            },
        )

    if state == "clean":
        months = revenue_by_month(session, run_id)
        return IntegrityView(
            state="clean",
            cards=_cards(stats),
            clean=CleanRun(
                run_label=f"Clean run · {plural(stats.client_count, 'client')}",
                headline="Every billing matched. Nothing to collect.",
                body=[
                    "Every document in this run was read and every expected billing was "
                    "matched against a payment. No shortfall survived classification.",
                    "A run that finds nothing is a result, not a failure. If this tool "
                    "flagged something here, you would have no reason to trust it when it "
                    "flags something real.",
                ],
                stats=[
                    CleanStat("Months checked", str(len(months)) if months else DASH),
                    CleanStat("Documents read", str(stats.document_count)),
                    CleanStat("Clients reconciled", str(stats.client_count)),
                ],
            ),
        )

    # -- review -----------------------------------------------------------
    rows = _anomalies(session, run_id)
    chosen = None
    if selected_id is not None:
        chosen = next((r for r in rows if str(r.id) == str(selected_id)), None)
    if chosen is None and rows:
        chosen = rows[0]

    items = []
    for r in rows:
        verdict, kind = _verdict(r.status)
        period = month_name(r.billing_date)
        type_label = _type_label(r.anomaly_type)
        title = _title(r)
        row = FindingRow(
            id=str(r.id),
            client=r.client_name,
            title=title,
            sub=type_label
            + (f" · confidence {r.confidence_score:.2f}" if r.confidence_score else ""),
            due=money(r.expected_amount),
            received=money(r.actual_amount),
            gap=fmt_gap(r.gap),
            verdict=verdict,
            kind=kind,
            selected=chosen is not None and r.id == chosen.id,
            type_key=r.anomaly_type,
            haystack=haystack(r.client_name, title, type_label, period, verdict),
        )
        items.append((row, float(r.gap or 0.0), r.client_name, r.billing_date))

    items.sort(key=sort_key(sort))
    findings = [item[0] for item in items]
    gaps = {item[0].id: item[1] for item in items}

    notices = {}
    selected_detail = _detail(session, run_id, chosen) if chosen else None
    if selected_detail is not None and not selected_detail.tools and not selected_detail.agent_prose:
        notices["agent"] = NOTICE_AGENT

    return IntegrityView(
        state="review",
        cards=_cards(stats),
        findings=findings,
        groups=build_groups(findings, gaps),
        sorts=sort_options(sort),
        selected=selected_detail,
        notices=notices,
    )


# ---------------------------------------------------------------------------
# Decision Engine
# ---------------------------------------------------------------------------


def decision(
    session: Session,
    run_id: int | None,
    question: str | None = None,
    monthly_expenses: float | None = None,
) -> DecisionView:
    """The Decision Engine, answered. Phase 9.

    **This is the one action `web/` performs, and it is still a read** — the
    reason it does not breach ADR-018. Asking a question computes a verdict from
    rows and from two numbers the user typed into the URL; it writes nothing, so
    there is nothing for `web.cache.clear()` to invalidate (known issue #56 is
    about *write* paths and remains true).

    Two inputs arrive as query parameters rather than from the database: the
    question, and `monthly_expenses` — because no table holds expenses (ADR-024).
    With no expense figure the verdict is deliberately `unknown` and the page
    reports the commitment as a share of revenue instead of inventing a surplus.

    Every figure here is computed by `core/engine/cashflow.py`. The model, if one
    is answering, only phrases them — and `decision_analyzer.explain_verdict`
    rejects its prose outright if it quotes a number it was not given.
    """
    suggestions = [
        "Can I afford 3,000 a month more rent from July?",
        "Two contractors at 4,200 each?",
        "A 1,800 a month tool subscription?",
    ]

    if run_id is None:
        return DecisionView(
            question=question or "",
            suggestions=suggestions,
            answered=False,
            verdict_word=None,
            verdict_qual=None,
            lead_html=None,
            after=None,
            notices={"decision": NOTICE_DECISION, "working": "No run selected."},
        )

    # Phase 9: the arithmetic is the engine's, not this presenter's. It used to
    # average revenue and divide the confirmed total by a hardcoded 12 right here
    # — money math in a view layer, and wrong for any run not spanning a year.
    # `compute_recovery` divides by the months the run actually covers.
    # Three independent reads, fetched at once rather than one after another.
    # `compute_recovery` is the engine's rather than a query helper's, but it
    # takes a session and does its own reads, so it gathers exactly like one.
    #
    # This is the *only* page where the gather pays. Measured twice on
    # 2026-08-19: this page 2.10s -> 1.74s, while the Integrity page got
    # **slower** the same way (2.15s -> 2.85s) and the detail pane did not move.
    # The difference is how much there is to overlap — three separate reads here
    # against two on Integrity, one of which is a single helper issuing three
    # statements in a row that no caller can split. Below that threshold, the
    # cost of a second pooled connection exceeds the overlap it buys.
    # If `core/db/queries.py` ever gets cheaper per call, re-measure before
    # spreading this further; do not assume it generalises.
    warmed = prefetch.gather(
        [
            (("stats", run_id), lambda s: get_summary_stats(s, run_id)),
            (("months", run_id), lambda s: revenue_by_month(s, run_id)),
            (("recovery", run_id), lambda s: cashflow.compute_recovery(s, run_id)),
        ],
        enabled=cache_enabled(session),
    )
    _memo_store(session).update({k: v for k, v in warmed.items() if k[0] == "stats"})

    stats = _stats(session, run_id)
    months = (
        warmed[("months", run_id)]
        if ("months", run_id) in warmed
        else revenue_by_month(session, run_id)
    )
    baseline = cashflow.baseline_from_monthly(
        months, monthly_expenses=monthly_expenses, months=max(len(months), 1)
    )
    recovery = (
        warmed[("recovery", run_id)]
        if ("recovery", run_id) in warmed
        else cashflow.compute_recovery(session, run_id)
    )

    working = [
        WorkRow(
            "Average monthly revenue",
            f"{plural(baseline.months_observed, 'month')} of matched payments"
            if months
            else "no payments on file",
            money(baseline.monthly_revenue) if months else None,
        ),
        WorkRow("Average monthly expenses", "not recorded anywhere", None, accent=True),
        WorkRow("Surplus today", "needs expenses", None, bold=True),
        WorkRow(
            "Confirmed findings",
            f"{recovery.confirmed_count} of {stats.anomaly_count} · see Findings",
            money(recovery.confirmed_total),
        ),
        WorkRow(
            "As a monthly run-rate",
            f"over {plural(recovery.months_covered, 'month')} of billings"
            if recovery.months_covered
            else "no billing window",
            money(recovery.monthly) if recovery.monthly else None,
        ),
        WorkRow("Surplus once collected", "needs expenses", None, bold=True),
        WorkRow("Cost of the question", "ask in the Streamlit app", None, accent=True),
        WorkRow("Left over each month", None, None, final=True),
    ]

    caveat = (
        "This answers questions about affording a recurring cost. It cannot answer "
        "questions about one client, a past period, or a change to your prices."
    )

    # Nothing asked yet: show the working, and no verdict. Not a failure state —
    # the page is waiting, and says so rather than filling the space.
    if not (question or "").strip():
        return DecisionView(
            question="",
            suggestions=suggestions,
            answered=False,
            verdict_word=None,
            verdict_qual=None,
            lead_html=None,
            after=None,
            bars=[],
            axis=[],
            working=working,
            caveat=caveat,
            notices={"decision": NOTICE_ASK, "expenses": NOTICE_EXPENSES},
        )

    parsed = decision_analyzer.parse_question(question)

    if not parsed.has_cost:
        return DecisionView(
            question=question or "",
            suggestions=suggestions,
            answered=False,
            verdict_word=None,
            verdict_qual=None,
            lead_html=None,
            after=None,
            bars=[],
            axis=[],
            working=working,
            caveat=caveat,
            notices={"decision": NOTICE_NO_AMOUNT, "expenses": NOTICE_EXPENSES},
        )

    result = cashflow.evaluate(baseline, recovery, monthly_cost=parsed.monthly_cost or 0.0)
    explanation = decision_analyzer.explain_verdict(result, parsed)

    # The working table gains the three lines a question makes computable.
    working = _decision_working(stats, baseline, recovery, result, months)

    if result.verdict == "unknown":
        # Honest per ADR-024: a share of revenue is a fact; a Yes/No would not be.
        share = (
            f"{result.cost_share_of_revenue * 100:.1f}% of monthly revenue"
            if result.cost_share_of_revenue is not None
            else "no revenue on file to compare against"
        )
        return DecisionView(
            question=question or "",
            suggestions=suggestions,
            answered=True,
            verdict_word="Can't say",
            verdict_qual=share,
            lead_html=_emphasise(explanation.text),
            after=_provenance(explanation, parsed),
            bars=_bars(result),
            axis=_axis(result),
            working=working,
            caveat=caveat,
            notices={"expenses": NOTICE_EXPENSES},
        )

    left = money(result.after_decision)
    without = money(round((baseline.monthly_surplus or 0.0) - result.monthly_cost, 2))

    return DecisionView(
        question=question or "",
        suggestions=suggestions,
        answered=True,
        verdict_word="Yes" if result.verdict == "yes" else "No",
        verdict_qual=f"{left} a month left over — {without} if you recover nothing",
        lead_html=_emphasise(explanation.text),
        after=_provenance(explanation, parsed),
        bars=_bars(result),
        axis=_axis(result),
        working=working,
        caveat=caveat,
        notices={},
    )


def _decision_working(stats, baseline, recovery, result, months) -> list[WorkRow]:
    """The working table once a question has been asked."""
    rows = [
        WorkRow(
            "Average monthly revenue",
            f"{plural(baseline.months_observed, 'month')} of matched payments"
            if months
            else "no payments on file",
            money(baseline.monthly_revenue) if months else None,
        ),
    ]
    if baseline.monthly_expenses is not None:
        rows.append(
            WorkRow("Average monthly expenses", "the figure you gave", f"({money(baseline.monthly_expenses)})", accent=True)
        )
        rows.append(WorkRow("Surplus today", None, money(baseline.monthly_surplus), bold=True))
    else:
        rows.append(WorkRow("Average monthly expenses", "not recorded anywhere", None, accent=True))
        rows.append(WorkRow("Surplus today", "needs expenses", None, bold=True))

    rows.append(
        WorkRow(
            "Confirmed findings",
            f"{recovery.confirmed_count} of {stats.anomaly_count} · see Findings",
            money(recovery.confirmed_total),
        )
    )
    rows.append(
        WorkRow(
            "As a monthly run-rate",
            f"over {plural(recovery.months_covered, 'month')} of billings"
            if recovery.months_covered
            else "no billing window",
            money(recovery.monthly) if recovery.monthly else None,
        )
    )
    if result.corrected_surplus is not None:
        rows.append(WorkRow("Surplus once collected", None, money(result.corrected_surplus), bold=True))
    else:
        rows.append(WorkRow("Surplus once collected", "needs expenses", None, bold=True))

    rows.append(
        WorkRow("Cost of the commitment", "taken from your question", f"({money(result.monthly_cost)})", accent=True)
    )
    rows.append(
        WorkRow(
            "Left over each month",
            None,
            money(result.after_decision) if result.after_decision is not None else None,
            final=True,
        )
    )
    return rows


def _emphasise(text: str) -> str:
    """Wrap every money figure in the prose in <b>, as the design does.

    The template takes `lead_html` as safe HTML, so the text is escaped here
    first — the prose can come from a language model, and an unescaped `<` from
    one would be an injection straight into the page.
    """
    from html import escape

    return re.sub(r"(\$[\d,]+(?:\.\d{2})?|\d+(?:\.\d+)?%)", r"<b>\1</b>", escape(text))


def _provenance(explanation, parsed) -> str:
    """The line under the answer: who wrote the sentence, and what was excluded.

    Says outright when the model's prose was thrown away for quoting a figure it
    was not given — that rejection is a feature and hiding it would waste it.
    """
    bits = []
    if explanation.source == "model":
        bits.append("The sentences above were written by the model around figures it was given; it produced none of them.")
    elif explanation.rejected_numbers:
        bits.append(
            f"The model's answer was discarded — it quoted "
            f"{plural(len(explanation.rejected_numbers), 'figure')} it was not given — so "
            f"FinSight wrote this itself."
        )
    else:
        bits.append("No model endpoint answered, so FinSight wrote this itself.")

    if parsed.matched_text:
        bits.append(f"The amount was read from your own words (“{parsed.matched_text}”), not guessed.")
    if parsed.needs_confirmation and parsed.has_cost:
        bits.append("The amount was inferred rather than found verbatim — check it.")
    return " ".join(bits)


def _bars(result) -> list[Bar]:
    """Twelve months of monthly surplus, two series, as CSS heights.

    Monthly rather than cumulative, matching the chart's own heading. The surplus
    is flat in this model, so the bars are flat too — and the *gap* between the
    pairs is the recovered money, which is the thing the chart exists to show.
    Negative months are floored at a visible sliver rather than drawn upside
    down; the working table carries the sign.
    """
    if not result.projection:
        return []

    per_month_with = (result.corrected_surplus if result.corrected_surplus is not None else result.baseline.monthly_revenue + result.recovery.monthly) - result.monthly_cost
    per_month_without = (
        result.baseline.monthly_surplus if result.baseline.monthly_surplus is not None else result.baseline.monthly_revenue
    ) - result.monthly_cost

    ceiling = max(per_month_with, per_month_without, 1.0)

    def height(value: float) -> str:
        return f"{max(round(value / ceiling * 100), 2) if value > 0 else 2}%"

    return [Bar(height(per_month_without), height(per_month_with)) for _ in result.projection]


def _axis(result) -> list[str]:
    """Five labels across the twelve bars.

    `M1..Mn`, never calendar months: `cashflow` takes no clock, so it does not
    know what month it is, and inventing "Sep" here would put a date on the page
    that nothing computed.
    """
    labels = [label for label, _, _ in result.projection]
    if len(labels) < 5:
        return labels
    picks = [0, len(labels) // 4, len(labels) // 2, (3 * len(labels)) // 4, len(labels) - 1]
    return [labels[i] for i in picks]


# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------


def run_label(run: RunRow | None) -> str | None:
    """``"demo_v1 · qwen2.5-3b"`` — or None, which the header dashes."""
    if run is None:
        return None
    model = run.model_name or "model not recorded"
    return f"{run.label} · {model}"


def state_note(session: Session, run_id: int | None, state: str) -> str:
    """The line on the right of the state bar, describing this run honestly."""
    if run_id is None:
        return "No runs in the database yet"

    stats = _stats(session, run_id)
    # `state` is now the screen you are *looking at*, which since the header
    # gained Upload and Processing tabs is not the same as what the run holds.
    # So the note reads the run, not the screen — otherwise clicking Upload on a
    # finished run would print "Nothing uploaded to this run" underneath its
    # documents.
    if state == "empty":
        if stats.document_count == 0:
            return "Nothing uploaded to this run"
        return f"{plural(stats.document_count, 'document')} already on file"
    if state == "processing":
        if stats.anomaly_count:
            return (
                f"{plural(stats.document_count, 'document')} on file · "
                f"{plural(stats.anomaly_count, 'finding')} reconciled"
            )
        return f"{plural(stats.document_count, 'document')} on file · nothing reconciled yet"
    if state == "clean":
        return f"{plural(stats.document_count, 'document')} read · no shortfall found"
    unverified = stats.unverified_count
    return (
        f"{plural(stats.anomaly_count, 'finding')} · "
        f"{unverified} not yet checked by an agent"
    )
