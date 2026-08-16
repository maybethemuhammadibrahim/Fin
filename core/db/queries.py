"""[B] Read helpers the UI calls; the UI never writes SQL itself. Phase 1.

Every function takes `session` first and returns a frozen dataclass, never an
ORM object and never a bare dict. Three reasons that matters here:

* Streamlit reruns the whole script on every interaction. Detached ORM instances
  raise `DetachedInstanceError` the moment a lazy relationship is touched after
  its session closed. These row objects are plain data and cannot.
* The UI gets autocomplete and type errors instead of `KeyError` at runtime.
* Money is rounded to 2dp exactly once — here, at the boundary — so the same
  figure cannot render two different ways on two different pages.

A lookup that legitimately finds nothing returns `None`. Callers handle it.

**Signature note:** `interfaces.md` originally declared
`list_anomalies(...) -> list[Anomaly]`. It returns `list[AnomalyRow]`. `Anomaly`
is both the ORM model and the Phase-5 Pydantic schema, and the DB row carries
fields the schema does not (`id`, `status`, agent output, the joined client
name) while the schema carries `billing_date`, which lives on
`expected_timeline`. A distinct row type avoids three things sharing one name.
`interfaces.md` has been updated to match.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from core.db.models import (
    ActualTransaction,
    Anomaly,
    ClauseReference,
    Client,
    ContractRule,
    Document,
    ExpectedTimeline,
    Run,
)


def _money(value: float | None) -> float:
    """Round to 2dp at the boundary, per the money convention."""
    return round(float(value or 0.0), 2)


# ---------------------------------------------------------------------------
# Row shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SummaryStats:
    """What the dashboard's summary cards render."""

    run_id: int
    total_leaked: float
    anomaly_count: int
    client_count: int
    #: Distinct clients with at least one finding. The dashboard shows
    #: "3 of 5"; both halves are aggregates, neither is inferred in the UI.
    affected_client_count: int
    document_count: int
    #: {"ghost_invoice": 3, "forgotten_raise": 1, ...} — only non-zero types.
    by_type: dict[str, int]
    #: Findings the agent has not yet looked at.
    unverified_count: int

    # ---- Two different ADR-005 failure modes. Do not conflate them. ----
    #: Anomalies with NO clause_reference at all. Hard rule 5 says these must
    #: never be shown to a user as proven findings.
    unlinked_count: int
    #: Anomalies that DO have a clause, but whose clause has no page/bbox —
    #: the quote is real, the locator just could not place it in the PDF. The
    #: finding is still valid; only the highlight degrades to text-only.
    #: Together these give the clause-grounding rate ADR-005 asks for.
    unlocatable_count: int

    @property
    def grounded_count(self) -> int:
        """Findings with a clause we can point at on a page."""
        return self.anomaly_count - self.unlinked_count - self.unlocatable_count

    @property
    def grounding_rate(self) -> float:
        """0.0-1.0. The headline honesty metric: how much of this is provable."""
        if not self.anomaly_count:
            return 0.0
        return round(self.grounded_count / self.anomaly_count, 3)


@dataclass(frozen=True)
class AnomalyRow:
    """One finding, flattened with the joined names the table needs."""

    id: int
    run_id: int
    client_id: int
    client_name: str
    anomaly_type: str
    expected_amount: float
    actual_amount: float
    gap: float
    confidence_score: float
    status: str
    billing_date: date | None
    clause_reference_id: int | None
    expected_timeline_id: int | None
    actual_transaction_id: int | None
    agent_reasoning: str | None
    #: The agent's tool trace, as Phase 8 wrote it. Carried on the row rather
    #: than re-fetched, so rendering a finding does not cost an extra round
    #: trip per drill-down — free here, because the ORM object is already open.
    agent_tool_calls: list[dict] | None
    verified_at: datetime | None

    @property
    def has_clause(self) -> bool:
        """False means the UI must not offer a drill-down for this row."""
        return self.clause_reference_id is not None


@dataclass(frozen=True)
class ClauseRefRow:
    """A clause quote plus wherever we managed to locate it (ADR-005)."""

    id: int
    contract_rule_id: int
    document_id: int | None
    clause_type: str | None
    clause_text: str
    source_page: int | None
    source_bbox: list[float] | None
    locate_method: str | None
    #: Convenience for the viewer's title bar.
    document_filename: str | None

    @property
    def is_grounded(self) -> bool:
        """True when there are real coordinates to highlight.

        False is normal, not an error. The viewer degrades to a page-level or
        text-only view. It must never crash.
        """
        return self.source_page is not None and bool(self.source_bbox)


@dataclass(frozen=True)
class ClientRow:
    id: int
    run_id: int
    name: str
    normalized_name: str
    contract_count: int


@dataclass(frozen=True)
class DocumentRow:
    id: int
    run_id: int
    filename: str
    file_type: str | None
    category: str | None
    storage_url: str | None
    extraction_status: str
    error_message: str | None
    uploaded_at: datetime | None
    extracted_text: str | None
    extracted_page_count: int | None


@dataclass(frozen=True)
class RunRow:
    id: int
    label: str
    llm_provider: str | None
    model_name: str | None
    created_at: datetime | None


@dataclass(frozen=True)
class TransactionRow:
    """One bank line, flattened for display.

    Distinct from `list_transactions` below, which hands back live ORM objects
    for the Phase-8 agent to work with inside its own session. This is the
    UI-safe shape: plain data, money already rounded, the joined filename
    resolved while the session is still open.
    """

    id: int
    client_id: int | None
    client_name: str | None
    transaction_date: date
    amount: float
    description: str | None
    source_type: str | None
    document_filename: str | None


@dataclass(frozen=True)
class ClientTotals:
    """What one client is worth, and what is outstanding against them."""

    client_id: int
    name: str
    contract_count: int
    #: Every matched payment for this client in the run.
    received_total: float
    #: Sum of this client's anomaly gaps.
    gap_total: float
    #: 0.0-1.0 share of the run's total receipts. None when the run received
    #: nothing at all — a share of zero is undefined, not 0%.
    revenue_share: float | None


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def create_run(session: Session, label: str) -> int:
    """Create a run and return its id. Stamps the active endpoint and model.

    Recording the model on the run is what makes Phase 11's base-vs-tuned
    comparison possible after the fact (ADR-012).
    """
    from core.config import settings

    run = Run(label=label, llm_provider=settings.llm_provider, model_name=settings.llm_model)
    session.add(run)
    session.flush()
    return run.id


def list_runs(session: Session) -> list[RunRow]:
    """Every run, newest first. Drives the run selector."""
    runs = session.scalars(select(Run).order_by(Run.created_at.desc(), Run.id.desc())).all()
    return [
        RunRow(
            id=r.id,
            label=r.label,
            llm_provider=r.llm_provider,
            model_name=r.model_name,
            created_at=r.created_at,
        )
        for r in runs
    ]


def get_latest_run(session: Session) -> RunRow | None:
    """The most recent run, or None when the database is empty."""
    runs = list_runs(session)
    return runs[0] if runs else None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def _count_if(condition) -> object:
    """SUM(CASE WHEN cond THEN 1 ELSE 0 END) — a conditional count.

    Written the long way rather than with `count(...) FILTER (WHERE ...)`
    because FILTER is Postgres-only and ADR-003 requires the SQLite fallback to
    behave identically. This form runs the same on both.
    """
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def get_summary_stats(session: Session, run_id: int) -> SummaryStats:
    """Aggregate figures for one run.

    Returns a zero-filled SummaryStats for an unknown or empty run rather than
    None — the dashboard should render "nothing found" cards, not blow up.

    **Three round trips, not eight.** This used to issue one query per figure,
    which reads nicely and cost 3.2 seconds a page against a Supabase instance
    two continents away (measured: 409 ms median per round trip). Every count
    that comes off `anomalies` is now one scan with conditional sums, because
    over a link like that the number of queries *is* the response time.
    """
    row = session.execute(
        select(
            func.coalesce(func.sum(Anomaly.gap), 0.0),
            func.count(Anomaly.id),
            _count_if(Anomaly.status == "unverified"),
            _count_if(Anomaly.clause_reference_id.is_(None)),
            func.count(func.distinct(Anomaly.client_id)),
        ).where(Anomaly.run_id == run_id)
    ).one()
    total_gap, anomaly_count, unverified, unlinked, affected = row

    by_type = {
        r.anomaly_type: r.n
        for r in session.execute(
            select(Anomaly.anomaly_type, func.count(Anomaly.id).label("n"))
            .where(Anomaly.run_id == run_id)
            .group_by(Anomaly.anomaly_type)
        )
    }

    # Has a clause, but the clause has no coordinates (ADR-005). Needs the join,
    # so it cannot fold into the scan above; the two remaining table counts ride
    # along with it as scalar subqueries rather than as their own round trips.
    counts = session.execute(
        select(
            select(func.count(Anomaly.id))
            .join(ClauseReference, Anomaly.clause_reference_id == ClauseReference.id)
            .where(Anomaly.run_id == run_id, ClauseReference.source_page.is_(None))
            .scalar_subquery(),
            select(func.count(Client.id)).where(Client.run_id == run_id).scalar_subquery(),
            select(func.count(Document.id)).where(Document.run_id == run_id).scalar_subquery(),
        )
    ).one()
    unlocatable, clients, documents = counts

    return SummaryStats(
        run_id=run_id,
        total_leaked=_money(total_gap),
        anomaly_count=anomaly_count or 0,
        client_count=clients or 0,
        affected_client_count=affected or 0,
        document_count=documents or 0,
        by_type=by_type,
        unverified_count=unverified or 0,
        unlinked_count=unlinked or 0,
        unlocatable_count=unlocatable or 0,
    )


def list_anomalies(
    session: Session,
    run_id: int,
    status: str | None = None,
    anomaly_type: str | None = None,
) -> list[AnomalyRow]:
    """Findings for a run, biggest gap first.

    `status` and `anomaly_type` are optional filters; None means "all".
    """
    stmt = (
        select(Anomaly, Client.name, ExpectedTimeline.billing_date)
        .join(Client, Anomaly.client_id == Client.id)
        .outerjoin(ExpectedTimeline, Anomaly.expected_timeline_id == ExpectedTimeline.id)
        .where(Anomaly.run_id == run_id)
        .order_by(Anomaly.gap.desc())
    )
    if status is not None:
        stmt = stmt.where(Anomaly.status == status)
    if anomaly_type is not None:
        stmt = stmt.where(Anomaly.anomaly_type == anomaly_type)

    return [
        AnomalyRow(
            id=a.id,
            run_id=a.run_id,
            client_id=a.client_id,
            client_name=client_name,
            anomaly_type=a.anomaly_type,
            expected_amount=_money(a.expected_amount),
            actual_amount=_money(a.actual_amount),
            gap=_money(a.gap),
            confidence_score=round(float(a.confidence_score or 0.0), 3),
            status=a.status,
            billing_date=billing_date,
            clause_reference_id=a.clause_reference_id,
            expected_timeline_id=a.expected_timeline_id,
            actual_transaction_id=a.actual_transaction_id,
            agent_reasoning=a.agent_reasoning,
            agent_tool_calls=a.agent_tool_calls,
            verified_at=a.verified_at,
        )
        for a, client_name, billing_date in session.execute(stmt)
    ]


def get_anomaly(session: Session, anomaly_id: int) -> AnomalyRow | None:
    """One finding by id, or None."""
    anomaly = session.get(Anomaly, anomaly_id)
    if anomaly is None:
        return None
    rows = list_anomalies(session, anomaly.run_id)
    return next((r for r in rows if r.id == anomaly_id), None)


# ---------------------------------------------------------------------------
# Drill-down
# ---------------------------------------------------------------------------


def get_clause_reference(session: Session, clause_ref_id: int) -> ClauseRefRow | None:
    """The clause behind a finding, or None if it has none.

    A returned row with `is_grounded == False` is a normal outcome, not a
    failure: the quote exists but could not be located in the PDF (ADR-005).
    """
    row = session.execute(
        select(ClauseReference, Document.filename)
        .outerjoin(Document, ClauseReference.document_id == Document.id)
        .where(ClauseReference.id == clause_ref_id)
    ).one_or_none()
    if row is None:
        return None

    ref, filename = row
    return ClauseRefRow(
        id=ref.id,
        contract_rule_id=ref.contract_rule_id,
        document_id=ref.document_id,
        clause_type=ref.clause_type,
        clause_text=ref.clause_text,
        source_page=ref.source_page,
        source_bbox=ref.source_bbox,
        locate_method=ref.locate_method,
        document_filename=filename,
    )


def get_document(session: Session, document_id: int) -> DocumentRow | None:
    """One document by id, or None."""
    doc = session.get(Document, document_id)
    if doc is None:
        return None
    return DocumentRow(
        id=doc.id,
        run_id=doc.run_id,
        filename=doc.filename,
        file_type=doc.file_type,
        category=doc.category,
        storage_url=doc.storage_url,
        extraction_status=doc.extraction_status,
        error_message=doc.error_message,
        uploaded_at=doc.uploaded_at,
        extracted_text=doc.extracted_text,
        extracted_page_count=doc.extracted_page_count,
    )


def list_clients(session: Session, run_id: int) -> list[ClientRow]:
    """Clients in a run, alphabetical, each with its contract count."""
    stmt = (
        select(Client, func.count(ContractRule.id))
        .outerjoin(ContractRule, ContractRule.client_id == Client.id)
        .where(Client.run_id == run_id)
        .group_by(Client.id)
        .order_by(Client.name)
    )
    return [
        ClientRow(
            id=c.id,
            run_id=c.run_id,
            name=c.name,
            normalized_name=c.normalized_name,
            contract_count=count or 0,
        )
        for c, count in session.execute(stmt)
    ]


def list_documents(session: Session, run_id: int) -> list[DocumentRow]:
    """Documents in a run, newest first. Drives the upload status list."""
    docs = session.scalars(
        select(Document).where(Document.run_id == run_id).order_by(Document.uploaded_at.desc(), Document.id.desc())
    ).all()
    return [
        DocumentRow(
            id=d.id,
            run_id=d.run_id,
            filename=d.filename,
            file_type=d.file_type,
            category=d.category,
            storage_url=d.storage_url,
            extraction_status=d.extraction_status,
            error_message=d.error_message,
            uploaded_at=d.uploaded_at,
            extracted_text=d.extracted_text,
            extracted_page_count=d.extracted_page_count,
        )
        for d in docs
    ]


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def table_counts(session: Session, run_id: int | None = None) -> dict[str, int]:
    """Row count per table; scoped to one run when `run_id` is given.

    Drives the DB Health page.

    Five tables carry no `run_id` of their own — `contract_rules` hangs off
    `clients`, and `clause_references` / `price_escalations` / `discounts` /
    `milestones` hang off `contract_rules`. Scoping them means joining back to
    `clients.run_id`. Counting them globally instead (the obvious shortcut)
    makes the health page quietly wrong the moment a second run exists: you ask
    for run 4 and get run 3's contract rules added in.

    `column_mappings` genuinely has no run scope — a confirmed CSV header
    mapping is reused across runs by design (ADR-010) — so it is always global,
    and the caller is told so by the `scoped` flag below.
    """
    from core.db.models import ALL_MODELS

    counts: dict[str, int] = {}
    for model in ALL_MODELS:
        stmt = select(func.count()).select_from(model)

        if run_id is not None:
            if model is Run:
                stmt = stmt.where(Run.id == run_id)
            elif hasattr(model, "run_id"):
                stmt = stmt.where(model.run_id == run_id)
            elif model is ContractRule:
                stmt = stmt.join(Client, ContractRule.client_id == Client.id).where(
                    Client.run_id == run_id
                )
            elif hasattr(model, "contract_rule_id"):
                stmt = (
                    stmt.join(ContractRule, model.contract_rule_id == ContractRule.id)
                    .join(Client, ContractRule.client_id == Client.id)
                    .where(Client.run_id == run_id)
                )
            # else: genuinely global (column_mappings). Left unfiltered.

        counts[model.__tablename__] = session.scalar(stmt) or 0
    return counts


#: Tables that cannot be scoped to a run, for the health page to label honestly.
GLOBAL_TABLES = frozenset({"column_mappings"})


def list_transaction_rows(
    session: Session,
    run_id: int,
    client_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[TransactionRow]:
    """Transactions for a run as display rows, oldest first.

    `start` / `end` are inclusive and optional. The drill-down passes the
    billing month widened by the ADR-006 tolerance, so a payment that landed on
    2 February still shows under January — the same window reconciliation used,
    which is the point: the ledger the user reads must be the ledger the
    classifier read.
    """
    stmt = (
        select(ActualTransaction, Client.name, Document.filename)
        .outerjoin(Client, ActualTransaction.client_id == Client.id)
        .outerjoin(Document, ActualTransaction.document_id == Document.id)
        .where(ActualTransaction.run_id == run_id)
        .order_by(ActualTransaction.transaction_date, ActualTransaction.id)
    )
    if client_id is not None:
        stmt = stmt.where(ActualTransaction.client_id == client_id)
    if start is not None:
        stmt = stmt.where(ActualTransaction.transaction_date >= start)
    if end is not None:
        stmt = stmt.where(ActualTransaction.transaction_date <= end)

    return [
        TransactionRow(
            id=t.id,
            client_id=t.client_id,
            client_name=client_name,
            transaction_date=t.transaction_date,
            amount=_money(t.amount),
            description=t.description,
            source_type=t.source_type,
            document_filename=filename,
        )
        for t, client_name, filename in session.execute(stmt)
    ]


def get_client_totals(session: Session, run_id: int, client_id: int) -> ClientTotals | None:
    """Receipts, contracts and outstanding gap for one client. None if unknown."""
    client = session.get(Client, client_id)
    if client is None or client.run_id != run_id:
        return None

    # One round trip, four scalar subqueries. Same reason as get_summary_stats:
    # against a remote Postgres the query count is the latency.
    contracts, received, gap_total, run_total = session.execute(
        select(
            select(func.count(ContractRule.id))
            .where(ContractRule.client_id == client_id)
            .scalar_subquery(),
            select(func.coalesce(func.sum(ActualTransaction.amount), 0.0))
            .where(
                ActualTransaction.run_id == run_id, ActualTransaction.client_id == client_id
            )
            .scalar_subquery(),
            select(func.coalesce(func.sum(Anomaly.gap), 0.0))
            .where(Anomaly.run_id == run_id, Anomaly.client_id == client_id)
            .scalar_subquery(),
            select(func.coalesce(func.sum(ActualTransaction.amount), 0.0))
            .where(ActualTransaction.run_id == run_id)
            .scalar_subquery(),
        )
    ).one()

    return ClientTotals(
        client_id=client_id,
        name=client.name,
        contract_count=contracts or 0,
        received_total=_money(received),
        gap_total=_money(gap_total),
        # A share of nothing is undefined. Reporting 0% would read as "this
        # client brings in nothing", which is a different claim.
        revenue_share=round((received or 0.0) / run_total, 4) if run_total else None,
    )


def revenue_by_month(session: Session, run_id: int) -> dict[str, float]:
    """{"2026-01": 41300.0, ...} — every matched receipt, summed per month.

    Ordered oldest first. Unassigned payments (no client) are included: they
    are money that arrived, whatever we failed to attribute it to.
    """
    rows = session.execute(
        select(ActualTransaction.transaction_date, ActualTransaction.amount).where(
            ActualTransaction.run_id == run_id
        )
    )
    totals: dict[str, float] = {}
    for txn_date, amount in rows:
        key = f"{txn_date:%Y-%m}"
        totals[key] = totals.get(key, 0.0) + float(amount or 0.0)
    return {k: _money(v) for k, v in sorted(totals.items())}


def list_transactions(session: Session, run_id: int, client_id: int | None = None) -> list[ActualTransaction]:
    """Raw transactions for a run. Returns ORM objects deliberately.

    The only consumer is Phase 8's `check_split_payments` tool, which runs
    inside a live session and needs the full row. The UI must not call this.
    """
    stmt = select(ActualTransaction).where(ActualTransaction.run_id == run_id)
    if client_id is not None:
        stmt = stmt.where(ActualTransaction.client_id == client_id)
    return list(session.scalars(stmt.order_by(ActualTransaction.transaction_date)))


def count_contract_rules(session: Session, run_id: int) -> int:
    """How many contracts in this run have structured rules on file. Phase 6.

    The question the Reconcile panel asks before offering its button: without a
    `contract_rules` row there is no expected timeline to generate, and the
    honest answer is "upload a contract and extract it", not an empty findings
    table.
    """
    return int(
        session.scalar(
            select(func.count())
            .select_from(ContractRule)
            .join(Client)
            .where(Client.run_id == run_id)
        )
        or 0
    )
