"""[B] The only place engine output becomes database rows. Phase 6.

`timeline_generator`, `reconciliation` and `anomaly_classifier` are pure by rule
— no session, no network, no clock. Something still has to read `contract_rules`
out of Postgres, hand those pure functions their arguments and write
`expected_timeline` and `anomalies` back. This is that something, and keeping it
in one file is what stops a `session` argument leaking into the maths.

Not in the plan's directory tree: the plan assumed persistence would happen
inside `scripts/seed_demo.py`, which was true while every row was seeded. Now
that the rows are computed, both the Streamlit upload flow and a scenario loader
need the same twelve steps, and neither of them is a seed script.

**Idempotent.** `compute_run` deletes the run's previous `expected_timeline` and
`anomalies` rows before writing new ones, so re-running it after fixing an
extraction leaves one answer in the database instead of two overlapping ones.
Nothing else is touched: documents, clients, contract rules and transactions are
inputs, not output.

> If this is ever called from `web/`, the caller **must** invoke
> `web.cache.clear()` afterwards (known issue #52). `web/cache.py` holds reads for
> `WEB_CACHE_SECONDS`, which is only safe while nothing writes.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from core.ai import client_matcher
from core.ai.schemas import ContractRules, Discount, Escalation, Milestone, TimelineEntry, TransactionRow
from core.db import models
from core.engine.anomaly_classifier import Classification
from core.engine.reconciliation import ClientRef, attribute_transactions, reconcile_detail
from core.engine.timeline_generator import ClauseRefMap, generate_timeline, unresolved_milestones

log = logging.getLogger(__name__)


@dataclass
class ContractPlan:
    """One contract, ready for the pure functions: its rules, whose it is, and
    which clause row proves which part of it."""

    contract_rule_id: int
    client_id: int
    rules: ContractRules
    clause_refs: ClauseRefMap
    milestone_dates: dict[int, date]


@dataclass
class RunSummary:
    """What `compute_run` did, in numbers a caller can print or assert on."""

    run_id: int
    contracts: int = 0
    timeline_rows: int = 0
    anomalies: int = 0
    total_gap: float = 0.0
    by_type: dict[str, int] = field(default_factory=dict)
    #: transactions newly tied to a client by name matching.
    attributed: int = 0
    #: transactions no client claimed — bank fees, or a client nobody uploaded.
    unattributed: int = 0
    #: attributed, but landing outside every billing window.
    unmatched: int = 0
    #: contracts that produced no timeline at all (no start date, no amount).
    skipped_contracts: list[str] = field(default_factory=list)
    #: milestones with no resolvable due date — money we deliberately did not check.
    unresolved_milestones: list[str] = field(default_factory=list)

    def as_line(self) -> str:
        return (
            f"run {self.run_id}: {self.contracts} contracts -> {self.timeline_rows} expected billings, "
            f"{self.anomalies} findings, ${self.total_gap:,.2f} recoverable"
        )


# ---------------------------------------------------------------------------
# reading the contract back out of the database
# ---------------------------------------------------------------------------


def load_contract_plans(session: Session, run_id: int) -> list[ContractPlan]:
    """Every contract in the run, rebuilt as the pure `ContractRules` shape.

    Reads the normalised tables (`price_escalations`, `discounts`, `milestones`)
    rather than `contract_rules.raw_extraction`, because those rows are what a
    human may have corrected. The raw JSON is kept for re-scoring an extraction,
    not for driving the maths.
    """
    stmt = (
        select(models.ContractRule)
        .join(models.Client)
        .where(models.Client.run_id == run_id)
        .options(
            selectinload(models.ContractRule.escalations),
            selectinload(models.ContractRule.discounts),
            selectinload(models.ContractRule.milestones),
            selectinload(models.ContractRule.client),
        )
        .order_by(models.ContractRule.id)
    )

    plans: list[ContractPlan] = []
    for row in session.scalars(stmt).all():
        # One escalation per contract: the schema allows several, the four leak
        # types assume one rate card. If a contract really carries two, the
        # earliest wins and the rest are logged rather than silently averaged.
        escalations = sorted(row.escalations, key=lambda e: e.after_months)
        if len(escalations) > 1:
            log.warning(
                "contract_rule %s has %d escalations; using the first (after %s months)",
                row.id,
                len(escalations),
                escalations[0].after_months,
            )

        rules = ContractRules(
            client_name=row.client.name,
            contract_start_date=row.contract_start,
            contract_end_date=row.contract_end,
            base_amount=row.base_amount,
            currency=row.currency or "USD",
            billing_frequency=row.billing_frequency or "unknown",
            payment_terms=row.payment_terms,
            escalation=(
                Escalation(
                    percentage=escalations[0].percentage,
                    after_months=escalations[0].after_months,
                    clause_text="",
                )
                if escalations
                else None
            ),
            discounts=[
                Discount(percentage=d.percentage, duration_months=d.duration_months, clause_text="")
                for d in row.discounts
            ],
            milestones=[
                Milestone(
                    description=m.description,
                    amount=m.amount,
                    due_condition=m.due_condition,
                    clause_text="",
                )
                for m in row.milestones
            ],
        )

        clause_refs = ClauseRefMap(
            base_fee=_base_fee_clause_id(session, row.id),
            escalation=escalations[0].clause_reference_id if escalations else None,
            discounts={i: d.clause_reference_id for i, d in enumerate(row.discounts) if d.clause_reference_id},
            milestones={
                i: m.clause_reference_id for i, m in enumerate(row.milestones) if m.clause_reference_id
            },
        )
        milestone_dates = {i: m.due_date for i, m in enumerate(row.milestones) if m.due_date is not None}

        plans.append(
            ContractPlan(
                contract_rule_id=row.id,
                client_id=row.client_id,
                rules=rules,
                clause_refs=clause_refs,
                milestone_dates=milestone_dates,
            )
        )
    return plans


def _base_fee_clause_id(session: Session, contract_rule_id: int) -> int | None:
    return session.scalar(
        select(models.ClauseReference.id)
        .where(
            models.ClauseReference.contract_rule_id == contract_rule_id,
            models.ClauseReference.clause_type == "base_fee",
        )
        .order_by(models.ClauseReference.id)
        .limit(1)
    )


# ---------------------------------------------------------------------------
# writing an extraction into the database
# ---------------------------------------------------------------------------


def persist_rules(
    session: Session,
    run_id: int,
    document_id: int | None,
    rules: ContractRules,
    *,
    document_text: str = "",
    client_id: int | None = None,
    replace: bool = True,
) -> int:
    """Write one `ContractRules` into `contract_rules` and its child tables.

    The step Phase 5 deliberately stopped short of (known issue #41): extraction
    produced a validated `ContractRules` and nothing wrote it down, because the
    timeline is the first thing that needs those rows. Returns the new
    `contract_rules.id`.

    Clause references are created for every clause the extraction quoted, and
    `locate_method` is set to `"failed"` when the quote cannot be found in the
    document's own text. Page and box stay NULL — putting a quote on a page is
    `clause_locator`'s job and needs a PDF (ADR-005, known issue #28).

    `client_id` is resolved by normalised name when not given, so re-uploading a
    second contract for the same client attaches to the client already there
    rather than tripping the `(run_id, normalized_name)` unique constraint.
    """
    client = _client_for(session, run_id, rules.client_name, client_id)

    if replace and document_id is not None:
        session.execute(
            delete(models.ContractRule).where(
                models.ContractRule.document_id == document_id,
                models.ContractRule.client_id == client.id,
            )
        )
        session.flush()

    rule = models.ContractRule(
        client_id=client.id,
        document_id=document_id,
        base_amount=rules.base_amount,
        currency=rules.currency or "USD",
        billing_frequency=rules.billing_frequency or "unknown",
        contract_start=rules.contract_start_date,
        contract_end=rules.contract_end_date,
        payment_terms=rules.payment_terms,
        #: Kept verbatim so an extraction can be re-scored later without paying
        #: for inference again. The maths reads the normalised rows, never this.
        raw_extraction=json.loads(rules.model_dump_json()),
    )
    session.add(rule)
    session.flush()

    def clause(clause_type: str, text: str | None) -> models.ClauseReference | None:
        if not text or not text.strip():
            return None
        ref = models.ClauseReference(
            contract_rule_id=rule.id,
            document_id=document_id,
            clause_type=clause_type,
            clause_text=text,
            source_page=None,
            source_bbox=None,
            locate_method=None if _quote_is_present(text, document_text) else "failed",
        )
        session.add(ref)
        return ref

    base_ref = clause("base_fee", _base_fee_quote(rules))
    esc_ref = clause("escalation", rules.escalation.clause_text if rules.escalation else None)
    discount_refs = [clause("discount", d.clause_text) for d in rules.discounts]
    milestone_refs = [clause("milestone", m.clause_text) for m in rules.milestones]
    session.flush()

    if rules.escalation:
        session.add(
            models.PriceEscalation(
                contract_rule_id=rule.id,
                clause_reference_id=(esc_ref or base_ref).id if (esc_ref or base_ref) else None,
                percentage=rules.escalation.percentage,
                after_months=rules.escalation.after_months,
            )
        )
    for index, discount in enumerate(rules.discounts):
        ref = discount_refs[index] or base_ref
        session.add(
            models.Discount(
                contract_rule_id=rule.id,
                clause_reference_id=ref.id if ref else None,
                percentage=discount.percentage,
                duration_months=discount.duration_months,
            )
        )
    for index, milestone in enumerate(rules.milestones):
        ref = milestone_refs[index] or base_ref
        session.add(
            models.Milestone(
                contract_rule_id=rule.id,
                clause_reference_id=ref.id if ref else None,
                description=milestone.description,
                amount=milestone.amount,
                due_condition=milestone.due_condition,
                #: NULL: no model is asked to turn "on website launch" into a
                #: date. `compute_run` reports the milestone as unchecked instead
                #: of billing it against a guess.
                due_date=None,
            )
        )
    session.flush()
    return rule.id


def _client_for(session: Session, run_id: int, name: str, client_id: int | None) -> models.Client:
    if client_id is not None:
        existing = session.get(models.Client, client_id)
        if existing is not None:
            return existing

    normalized = client_matcher.normalise(name or "")
    found = session.scalar(
        select(models.Client).where(
            models.Client.run_id == run_id, models.Client.normalized_name == normalized
        )
    )
    if found is not None:
        return found

    client = models.Client(run_id=run_id, name=name or "Unnamed client", normalized_name=normalized)
    session.add(client)
    session.flush()
    return client


def _base_fee_quote(rules: ContractRules) -> str | None:
    """`ContractRules` has no `base_fee` clause field of its own — the model is
    asked for the escalation, discount and milestone quotes. Reuse whichever
    quote mentions the base amount, so a ghost_invoice still has something real
    to point at rather than nothing at all."""
    amount = rules.base_amount
    if amount is None:
        return None
    needles = {f"{amount:,.0f}", f"{amount:,.2f}", f"{amount:.0f}"}
    for candidate in [
        *(d.clause_text for d in rules.discounts),
        rules.escalation.clause_text if rules.escalation else None,
        *(m.clause_text for m in rules.milestones),
    ]:
        if candidate and any(n in candidate for n in needles):
            return candidate
    return None


def _quote_is_present(quote: str, document_text: str) -> bool:
    if not document_text:
        return False
    squash = lambda s: " ".join(s.split()).lower()  # noqa: E731
    return squash(quote) in squash(document_text)


# ---------------------------------------------------------------------------
# placing every quote on a page (Phase 7)
# ---------------------------------------------------------------------------


@dataclass
class LocateSummary:
    """What `locate_run_clauses` managed to place, and on what."""

    run_id: int
    clauses: int = 0
    exact: int = 0
    fuzzy: int = 0
    failed: int = 0
    #: documents whose page image is typeset by us because the source is not a
    #: PDF — EDGAR HTML saved as .txt (ADR-021, known issue #28).
    typeset_documents: int = 0
    #: documents with neither a PDF nor extracted text to typeset.
    unrenderable: list[str] = field(default_factory=list)

    @property
    def grounded(self) -> int:
        return self.exact + self.fuzzy

    def as_line(self) -> str:
        return (
            f"run {self.run_id}: {self.grounded}/{self.clauses} clauses placed on a page "
            f"({self.exact} exact, {self.fuzzy} fuzzy, {self.failed} not found)"
        )


def locate_run_clauses(session: Session, run_id: int, *, commit: bool = True) -> LocateSummary:
    """Give every clause in the run a page and a box, where one can be found.

    Runs `clause_locator` over each document once — a contract with five clauses
    is one `pymupdf.open`, not five — and writes `source_page`, `source_bbox` and
    `locate_method` back.

    A document that is not a PDF is **typeset into one** first
    (`pdf_renderer.ensure_pdf`, ADR-021), which is what makes highlighting work
    at all on the EDGAR corpus. A quote that still cannot be found is recorded as
    `locate_method="failed"` with NULL coordinates: ADR-005's third state, which
    the viewer shows as the quote with no highlight and says why.
    """
    from core.extraction import pdf_renderer
    from core.extraction.clause_locator import locate_all

    summary = LocateSummary(run_id=run_id)

    documents = session.scalars(
        select(models.Document).where(models.Document.run_id == run_id)
    ).all()

    for document in documents:
        clauses = session.scalars(
            select(models.ClauseReference)
            .where(models.ClauseReference.document_id == document.id)
            .order_by(models.ClauseReference.id)
        ).all()
        if not clauses:
            continue

        summary.clauses += len(clauses)

        source = pdf_renderer.ensure_pdf(
            storage_url=document.storage_url,
            extracted_text=document.extracted_text,
            filename=document.filename,
            file_type=document.file_type,
        )
        if source is None:
            summary.unrenderable.append(document.filename)
            summary.failed += len(clauses)
            for clause in clauses:
                clause.source_page = None
                clause.source_bbox = None
                clause.locate_method = "failed"
            continue

        path, is_typeset = source
        if is_typeset:
            summary.typeset_documents += 1

        for clause, location in zip(clauses, locate_all(path, [c.clause_text for c in clauses])):
            if location is None:
                clause.source_page = None
                clause.source_bbox = None
                clause.locate_method = "failed"
                summary.failed += 1
                continue
            clause.source_page = location.page
            clause.source_bbox = [round(v, 2) for v in location.bbox]
            clause.locate_method = location.method
            if location.method == "exact":
                summary.exact += 1
            else:
                summary.fuzzy += 1

    if commit:
        session.commit()
    return summary


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------


def compute_run(
    session: Session,
    run_id: int,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
    horizon_months: int | None = None,
    commit: bool = True,
) -> RunSummary:
    """Rebuild this run's expected timeline and findings from its contracts.

    The billing window defaults to **the span the run's own transactions cover**,
    not to today's date — a run reconciling a 2025 bank statement must produce the
    same answer in 2027 as it did the day it was uploaded. With no transactions at
    all, the window falls back to each contract's own start.
    """
    summary = RunSummary(run_id=run_id)

    plans = load_contract_plans(session, run_id)
    summary.contracts = len(plans)
    if not plans:
        log.info("run %s has no contract rules; nothing to compute", run_id)
        _clear_computed(session, run_id)
        if commit:
            session.commit()
        return summary

    if window_start is None or window_end is None:
        derived = _transaction_window(session, run_id)
        window_start = window_start or (derived[0] if derived else None)
        window_end = window_end or (derived[1] if derived else None)

    _clear_computed(session, run_id)

    # ---- 1. expected timeline ------------------------------------------------
    entries_by_plan: list[tuple[ContractPlan, list[TimelineEntry]]] = []
    for plan in plans:
        entries = generate_timeline(
            plan.rules,
            client_id=plan.client_id,
            contract_rule_id=plan.contract_rule_id,
            window_start=window_start,
            window_end=window_end,
            horizon_months=horizon_months,
            clause_refs=plan.clause_refs,
            milestone_dates=plan.milestone_dates,
        )
        if not entries:
            summary.skipped_contracts.append(
                f"{plan.rules.client_name}: no start date or no amount to bill"
            )
        entries_by_plan.append((plan, entries))
        summary.unresolved_milestones.extend(
            f"{plan.rules.client_name}: {m.description} ({m.due_condition or 'no stated condition'})"
            for _i, m in unresolved_milestones(plan.rules, plan.milestone_dates)
        )

    persisted: list[TimelineEntry] = []
    for plan, entries in entries_by_plan:
        for entry in entries:
            row = models.ExpectedTimeline(
                run_id=run_id,
                client_id=entry.client_id,
                contract_rule_id=entry.contract_rule_id,
                billing_date=entry.billing_date,
                expected_amount=entry.expected_amount,
                payment_type=entry.payment_type,
                applied_escalation=entry.applied_escalation,
                applied_discount_pct=entry.applied_discount_pct,
                source_clause_ref_id=entry.source_clause_ref_id,
                notes=entry.notes,
            )
            session.add(row)
            session.flush()  # we need the id before reconciliation can cite it
            persisted.append(entry.model_copy(update={"id": row.id}))
    summary.timeline_rows = len(persisted)

    # ---- 2. attribution ------------------------------------------------------
    clients = [
        ClientRef(client_id=c.id, name=c.name, aliases=(c.normalized_name,))
        for c in session.scalars(select(models.Client).where(models.Client.run_id == run_id)).all()
    ]
    txn_rows = session.scalars(
        select(models.ActualTransaction).where(models.ActualTransaction.run_id == run_id)
    ).all()
    actuals = [
        TransactionRow(
            id=t.id,
            transaction_date=t.transaction_date,
            amount=t.amount,
            description=t.description,
            source_type=t.source_type,
            client_id=t.client_id,
        )
        for t in txn_rows
    ]

    attributions = attribute_transactions(actuals, clients)
    by_txn_id = {t.id: t for t in txn_rows}
    attributed: list[TransactionRow] = []
    for attribution in attributions:
        if not attribution.matched:
            continue
        attributed.append(attribution.transaction)
        row = by_txn_id.get(attribution.transaction.id)
        # Write the decision back, so the UI and Phase 8's agent see the same
        # attribution this reconciliation used rather than re-deriving it.
        if row is not None and row.client_id != attribution.client_id:
            row.client_id = attribution.client_id
            summary.attributed += 1

    # ---- 3. reconciliation ---------------------------------------------------
    result = reconcile_detail(
        persisted,
        attributed,
        rules_by_contract={p.contract_rule_id: p.rules for p, _ in entries_by_plan},
    )
    # Counted from the attributions, not from `result.unattributed`: rows nobody
    # claimed are filtered out before reconciliation ever sees them, so asking
    # the result would always report zero.
    summary.unattributed = sum(1 for a in attributions if not a.matched)
    summary.unmatched = len(result.unmatched)

    clause_by_contract = {p.contract_rule_id: p.clause_refs for p, _ in entries_by_plan}
    timeline_by_id = {e.id: e for e in persisted}

    for anomaly, classification in zip(result.anomalies, result.classifications):
        entry = timeline_by_id.get(anomaly.expected_timeline_id)
        refs = clause_by_contract.get(entry.contract_rule_id) if entry else None
        session.add(
            models.Anomaly(
                run_id=run_id,
                client_id=anomaly.client_id,
                expected_timeline_id=anomaly.expected_timeline_id,
                actual_transaction_id=anomaly.actual_transaction_id,
                clause_reference_id=_proving_clause(classification, refs, anomaly.clause_reference_id),
                anomaly_type=anomaly.anomaly_type,
                expected_amount=anomaly.expected_amount,
                actual_amount=anomaly.actual_amount,
                gap=anomaly.gap,
                confidence_score=anomaly.confidence_score,
                status="unverified",
                # Phase 8 overwrites this with the agent's own reasoning. Until
                # then the field holds the engine's arithmetic, which is a better
                # answer than an empty panel and is not a model's words.
                agent_reasoning=classification.reason,
            )
        )
        summary.by_type[anomaly.anomaly_type] = summary.by_type.get(anomaly.anomaly_type, 0) + 1

    summary.anomalies = len(result.anomalies)
    summary.total_gap = result.total_gap

    if commit:
        session.commit()
    return summary


def _proving_clause(
    classification: Classification, refs: ClauseRefMap | None, inherited: int | None
) -> int | None:
    """Which clause proves this finding.

    The timeline row cites the clause that explains its *amount*; a finding needs
    the clause that explains its *type*. A zombie_discount is proven by the
    discount's expiry, not by the rate card the row was billed at — the same map
    `data_sourcing/scenario_builder.py` uses when it records a `proving_clause` in
    ground truth. Falls back to whatever the row carried (ADR-005: nullable).
    """
    if refs is None:
        return inherited
    if classification.clause_role == "escalation":
        return refs.escalation or inherited or refs.base_fee
    if classification.clause_role == "discount":
        first_discount = next(iter(refs.discounts.values()), None)
        return first_discount or inherited or refs.base_fee
    return refs.base_fee or inherited


def _clear_computed(session: Session, run_id: int) -> None:
    """Delete only what this module writes. Anomalies first: they reference
    `expected_timeline` rows."""
    session.execute(delete(models.Anomaly).where(models.Anomaly.run_id == run_id))
    session.execute(delete(models.ExpectedTimeline).where(models.ExpectedTimeline.run_id == run_id))
    session.flush()


def _transaction_window(session: Session, run_id: int) -> tuple[date, date] | None:
    dates = session.scalars(
        select(models.ActualTransaction.transaction_date).where(
            models.ActualTransaction.run_id == run_id
        )
    ).all()
    if not dates:
        return None
    #: Billings are anchored to the contract's own day of month, so widening to
    #: whole months keeps the first and last billing inside the window even when
    #: the first payment landed a few days after it.
    first, last = min(dates), max(dates)
    return first.replace(day=1), last


def normalized(name: str) -> str:
    """The `clients.normalized_name` form. Re-exported so a caller writing client
    rows uses the same normalisation reconciliation matches against."""
    return client_matcher.normalise(name)
