"""[B] The same view models, built from the database. Phase 6.

The rule this file lives under: **it never borrows from `demo.py`.** Where the
database has no answer, the view model carries `None` or an empty list and the
template draws a skeleton with a line saying which phase fills it. A page of
dashes is a correct page — it is the build telling the truth about itself. A
page that quietly showed a demo figure instead would be the one bug this whole
architecture is arranged to prevent.

What is genuinely absent today, and where it lands:

* agent verdicts and tool traces — `core/agents/` is a stub, Phase 8;
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
from datetime import date, timedelta

from sqlalchemy.orm import Session

from web import cache as web_cache
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
NOTICE_AGENT = (
    "The verification agent lands in Phase 8. Until then a finding carries no "
    "tool trace and no agent verdict, so nothing is shown here rather than a "
    "confidence score nobody computed."
)
NOTICE_DECISION = (
    "The Decision Engine's analyser lands in Phase 9. The working below is real "
    "— it comes from your transactions and your confirmed findings — but no "
    "verdict is drawn from it yet."
)
NOTICE_EXPENSES = (
    "No expense figures exist in the database, so the surplus and the verdict "
    "cannot be computed. Only what arrived is shown."
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
#: why a read cache is safe in a frontend that writes nothing.
def _memo(session: Session, key: tuple, build):
    cache = getattr(session, "_finsight_memo", None)
    if cache is None:
        cache = {}
        try:
            session._finsight_memo = cache  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - Session always accepts this
            return build()
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
    """Every run, for the picker. Cached — new runs come from scripts, not
    from this frontend, which writes nothing."""
    return _memo(session, ("runs",), lambda: list_runs(session))


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


def integrity(
    session: Session,
    run_id: int | None,
    selected_id: str | None = None,
    sort: str = DEFAULT_SORT,
) -> IntegrityView:
    """Build the Integrity Engine view from whatever the run actually holds."""
    state = derive_state(session, run_id)

    if run_id is None or state == "empty":
        return IntegrityView(state="empty")

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
        return IntegrityView(
            state="processing",
            pipeline=[_pipeline_doc(d, reconciled=bool(stats.anomaly_count)) for d in docs],
            pipeline_headline=f"Reading {plural(len(docs), 'document')}",
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


def decision(session: Session, run_id: int | None, question: str | None = None) -> DecisionView:
    """The working the database can support, and an honest blank where it cannot.

    No verdict is produced. `core/ai/decision_analyzer.py` is a stub, and the
    surplus it would need cannot be computed without expenses, which no table
    holds. The revenue line and the findings line are real.
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

    stats = _stats(session, run_id)
    months = revenue_by_month(session, run_id)
    avg_revenue = round(sum(months.values()) / len(months), 2) if months else None
    confirmed = [a for a in _anomalies(session, run_id) if a.status == "confirmed"]
    confirmed_total = round(sum(a.gap for a in confirmed), 2) if confirmed else 0.0
    monthly_recovery = round(confirmed_total / 12, 2) if confirmed_total else None

    working = [
        WorkRow(
            "Average monthly revenue",
            f"{plural(len(months), 'month')} of matched payments" if months else "no payments on file",
            money(avg_revenue),
        ),
        WorkRow("Average monthly expenses", "not recorded anywhere", None, accent=True),
        WorkRow("Surplus today", "needs expenses", None, bold=True),
        WorkRow(
            "Confirmed findings",
            f"{len(confirmed)} of {stats.anomaly_count} · see Findings",
            money(confirmed_total),
        ),
        WorkRow("Spread across the year", "divided by 12", money(monthly_recovery)),
        WorkRow("Surplus once collected", "needs expenses", None, bold=True),
        WorkRow("Cost of the question", "nothing asked yet", None, accent=True),
        WorkRow("Left over each month", None, None, final=True),
    ]

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
        caveat=(
            "This page will answer questions about affording a recurring cost. It cannot "
            "answer questions about one client, a past period, or a change to your prices."
        ),
        notices={"decision": NOTICE_DECISION, "expenses": NOTICE_EXPENSES},
    )


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
    if state == "empty":
        return "Nothing uploaded to this run"
    if state == "processing":
        return f"{plural(stats.document_count, 'document')} on file · nothing reconciled yet"
    if state == "clean":
        return f"{plural(stats.document_count, 'document')} read · no shortfall found"
    unverified = stats.unverified_count
    return (
        f"{plural(stats.anomaly_count, 'finding')} · "
        f"{unverified} not yet checked by an agent"
    )
