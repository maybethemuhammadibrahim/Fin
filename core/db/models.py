"""[A] SQLAlchemy ORM models for all 12 tables. Phase 1.

Schema notes that are load-bearing, not stylistic:

* **`run_id` on every run-scoped table** so a demo can be re-run without wiping
  the database, and so baseline and fine-tuned results sit side by side for
  Phase 11's comparison.
* **`clause_references.source_page` and `.source_bbox` are nullable** (ADR-005).
  Clause grounding can legitimately fail; the UI degrades to a page-level view
  rather than crashing. Any consumer that assumes a bbox is present is a bug.
* **No Postgres-only types.** `JSON` and `String` work identically on the SQLite
  fallback, which ADR-003 requires stay functional for offline work. No `ARRAY`,
  no `JSONB`, no native `ENUM` — the four leak types are enforced with a
  `CheckConstraint`, which both backends honour.
* **Cascades are declared on the relationships and on the FKs**, so deleting a
  `Run` removes everything scoped to it. `scripts/reset_run.py` depends on this,
  and so does SQLite — see the `PRAGMA foreign_keys` listener in `database.py`.
* No Alembic. Schema changes are drop-and-recreate until Phase 9.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------------------------------------------------------------------------
# Vocabularies. Kept as plain tuples rather than native DB enums so the SQLite
# fallback behaves identically and a drop-and-recreate never has to migrate a
# type. Mirrored in core/ai/schemas.py as Literals when Phase 5 lands.
# ---------------------------------------------------------------------------

#: The four mutually exclusive leak types. Enforced in the database.
ANOMALY_TYPES = ("ghost_invoice", "forgotten_raise", "zombie_discount", "short_change")

#: Anomaly lifecycle. The agent (Phase 8) moves rows out of "unverified".
ANOMALY_STATUSES = ("unverified", "confirmed", "false_positive", "needs_review")

#: How clause_locator found the bbox, or why it could not (ADR-005).
LOCATE_METHODS = ("exact", "fuzzy", "failed")

#: Timeline rows are either the recurring fee or a one-off milestone.
PAYMENT_TYPES = ("recurring", "milestone")

BILLING_FREQUENCIES = ("monthly", "quarterly", "annual", "one_time", "unknown")

#: Per-document extraction lifecycle, so failures are visible in the UI
#: instead of vanishing.
EXTRACTION_STATUSES = ("pending", "processing", "complete", "failed")


def _utcnow() -> datetime:
    """Timezone-aware UTC now. Python-side so SQLite and Postgres agree."""
    return datetime.now(timezone.utc)


def _one_of(column: str, allowed: tuple[str, ...]) -> CheckConstraint:
    values = ", ".join(f"'{v}'" for v in allowed)
    return CheckConstraint(f"{column} IN ({values})", name=f"ck_{column}")


class Base(DeclarativeBase):
    """Declarative base. `scripts/init_db.py` calls `Base.metadata.create_all`."""


# ---------------------------------------------------------------------------
# 1. runs — the scope every other table hangs off
# ---------------------------------------------------------------------------


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)

    #: Which endpoint and which weights produced this run. Phase 11 compares
    #: two rows of this table that differ only in `model_name`.
    llm_provider: Mapped[str | None] = mapped_column(String(50))
    model_name: Mapped[str | None] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    documents: Mapped[list[Document]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    clients: Mapped[list[Client]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    timeline_entries: Mapped[list[ExpectedTimeline]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    transactions: Mapped[list[ActualTransaction]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    anomalies: Mapped[list[Anomaly]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Run id={self.id} label={self.label!r}>"


# ---------------------------------------------------------------------------
# 2. documents — uploaded contracts, invoices, statements
# ---------------------------------------------------------------------------


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (_one_of("extraction_status", EXTRACTION_STATUSES),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(20))
    #: "contract" | "invoice" | "statement" — set by Phase 4's document_router.
    category: Mapped[str | None] = mapped_column(String(50))

    #: Signed Supabase Storage URL. Files do not live on a laptop.
    storage_url: Mapped[str | None] = mapped_column(String(1000))

    extraction_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(2000))

    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    run: Mapped[Run] = relationship(back_populates="documents")
    contract_rules: Mapped[list[ContractRule]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    clause_references: Mapped[list[ClauseReference]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    transactions: Mapped[list[ActualTransaction]] = relationship(
        back_populates="document", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Document id={self.id} filename={self.filename!r}>"


# ---------------------------------------------------------------------------
# 3. clients
# ---------------------------------------------------------------------------


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("run_id", "normalized_name", name="uq_client_run_normalized"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    #: Lowercased, punctuation- and suffix-stripped. Reconciliation fuzzy-matches
    #: bank descriptions against this, not against `name` (ADR-006).
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    run: Mapped[Run] = relationship(back_populates="clients")
    contract_rules: Mapped[list[ContractRule]] = relationship(
        back_populates="client", cascade="all, delete-orphan", passive_deletes=True
    )
    timeline_entries: Mapped[list[ExpectedTimeline]] = relationship(
        back_populates="client", cascade="all, delete-orphan", passive_deletes=True
    )
    transactions: Mapped[list[ActualTransaction]] = relationship(
        back_populates="client", passive_deletes=True
    )
    anomalies: Mapped[list[Anomaly]] = relationship(
        back_populates="client", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Client id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# 4. contract_rules — the structured form of one contract
# ---------------------------------------------------------------------------


class ContractRule(Base):
    __tablename__ = "contract_rules"
    __table_args__ = (_one_of("billing_frequency", BILLING_FREQUENCIES),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)

    base_amount: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    billing_frequency: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)

    contract_start: Mapped[date | None] = mapped_column(Date)
    contract_end: Mapped[date | None] = mapped_column(Date)
    payment_terms: Mapped[str | None] = mapped_column(String(200))

    #: The model's raw ContractRules JSON, kept verbatim so an extraction can be
    #: re-scored later without re-running inference.
    raw_extraction: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    client: Mapped[Client] = relationship(back_populates="contract_rules")
    document: Mapped[Document | None] = relationship(back_populates="contract_rules")
    clause_references: Mapped[list[ClauseReference]] = relationship(
        back_populates="contract_rule", cascade="all, delete-orphan", passive_deletes=True
    )
    escalations: Mapped[list[PriceEscalation]] = relationship(
        back_populates="contract_rule", cascade="all, delete-orphan", passive_deletes=True
    )
    discounts: Mapped[list[Discount]] = relationship(
        back_populates="contract_rule", cascade="all, delete-orphan", passive_deletes=True
    )
    milestones: Mapped[list[Milestone]] = relationship(
        back_populates="contract_rule", cascade="all, delete-orphan", passive_deletes=True
    )
    timeline_entries: Mapped[list[ExpectedTimeline]] = relationship(
        back_populates="contract_rule", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ContractRule id={self.id} base={self.base_amount} freq={self.billing_frequency}>"


# ---------------------------------------------------------------------------
# 5. clause_references — the proof behind every finding (ADR-005)
# ---------------------------------------------------------------------------


class ClauseReference(Base):
    __tablename__ = "clause_references"
    __table_args__ = (_one_of("locate_method", LOCATE_METHODS),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_rule_id: Mapped[int] = mapped_column(
        ForeignKey("contract_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)

    #: "escalation" | "discount" | "milestone" | "base_fee" | "payment_terms"
    clause_type: Mapped[str | None] = mapped_column(String(50))

    #: Copied VERBATIM from the document by the model. Never paraphrased — this
    #: string is what clause_locator.py searches the PDF for.
    clause_text: Mapped[str] = mapped_column(String, nullable=False)

    # ---- ADR-005: both nullable, on purpose. ----
    #: NULL when the quote could not be located. Consumers MUST degrade to a
    #: page-level view; a quote that cannot be found was probably hallucinated,
    #: and the owning rule is flagged low-confidence.
    source_page: Mapped[int | None] = mapped_column(Integer)
    #: [x0, y0, x1, y1] in PDF points, or NULL. Stored as JSON, not ARRAY, so
    #: the SQLite fallback works.
    source_bbox: Mapped[list[float] | None] = mapped_column(JSON)

    #: "exact" | "fuzzy" | "failed" — drives the clause-grounding-rate metric.
    locate_method: Mapped[str | None] = mapped_column(String(20))

    contract_rule: Mapped[ContractRule] = relationship(back_populates="clause_references")
    document: Mapped[Document | None] = relationship(back_populates="clause_references")
    anomalies: Mapped[list[Anomaly]] = relationship(back_populates="clause_reference", passive_deletes=True)

    @property
    def is_grounded(self) -> bool:
        """True when we have real coordinates to highlight."""
        return self.source_page is not None and bool(self.source_bbox)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ClauseReference id={self.id} type={self.clause_type!r} page={self.source_page}>"


# ---------------------------------------------------------------------------
# 6. price_escalations
# ---------------------------------------------------------------------------


class PriceEscalation(Base):
    __tablename__ = "price_escalations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_rule_id: Mapped[int] = mapped_column(
        ForeignKey("contract_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The clause that proves it. Nullable only because extraction can fail.
    clause_reference_id: Mapped[int | None] = mapped_column(
        ForeignKey("clause_references.id", ondelete="SET NULL")
    )

    percentage: Mapped[float] = mapped_column(Float, nullable=False)
    after_months: Mapped[int] = mapped_column(Integer, nullable=False)

    contract_rule: Mapped[ContractRule] = relationship(back_populates="escalations")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PriceEscalation +{self.percentage}% after {self.after_months}m>"


# ---------------------------------------------------------------------------
# 7. discounts
# ---------------------------------------------------------------------------


class Discount(Base):
    __tablename__ = "discounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_rule_id: Mapped[int] = mapped_column(
        ForeignKey("contract_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    clause_reference_id: Mapped[int | None] = mapped_column(
        ForeignKey("clause_references.id", ondelete="SET NULL")
    )

    percentage: Mapped[float] = mapped_column(Float, nullable=False)
    #: How long the discount was meant to last. A zombie_discount is one still
    #: being applied after this many months.
    duration_months: Mapped[int] = mapped_column(Integer, nullable=False)

    contract_rule: Mapped[ContractRule] = relationship(back_populates="discounts")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Discount -{self.percentage}% for {self.duration_months}m>"


# ---------------------------------------------------------------------------
# 8. milestones
#
# NOT in the plan's ER diagram, which draws 11 tables while the plan text and
# the models.py stub both say 12. This is the missing one, and it is required:
# ContractRules.milestones exists in interfaces.md, TimelineEntry.payment_type
# includes "milestone", and the worked example in project_context.md turns on a
# $15,000 launch milestone that was never billed. Without this table a Phase 5
# extraction has nowhere to put milestones and Phase 6 cannot emit milestone
# timeline rows. Mirrors price_escalations / discounts deliberately.
# ---------------------------------------------------------------------------


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_rule_id: Mapped[int] = mapped_column(
        ForeignKey("contract_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    clause_reference_id: Mapped[int | None] = mapped_column(
        ForeignKey("clause_references.id", ondelete="SET NULL")
    )

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    #: Free text: "on website launch". Phase 6 needs a date to bill against, so
    #: `due_date` is set when the condition can be resolved and left NULL when
    #: it cannot.
    due_condition: Mapped[str | None] = mapped_column(String(500))
    due_date: Mapped[date | None] = mapped_column(Date)

    contract_rule: Mapped[ContractRule] = relationship(back_populates="milestones")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Milestone {self.description!r} {self.amount}>"


# ---------------------------------------------------------------------------
# 9. expected_timeline — what the contract says SHOULD have been billed
# ---------------------------------------------------------------------------


class ExpectedTimeline(Base):
    __tablename__ = "expected_timeline"
    __table_args__ = (_one_of("payment_type", PAYMENT_TYPES),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_rule_id: Mapped[int] = mapped_column(
        ForeignKey("contract_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )

    billing_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    expected_amount: Mapped[float] = mapped_column(Float, nullable=False)
    payment_type: Mapped[str] = mapped_column(String(20), default="recurring", nullable=False)

    #: Set by timeline_generator so a forgotten_raise can be told apart from a
    #: contract that simply never had an escalation.
    applied_escalation: Mapped[bool] = mapped_column(default=False, nullable=False)
    applied_discount_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    #: The clause this row was derived from, so an anomaly can inherit it.
    source_clause_ref_id: Mapped[int | None] = mapped_column(
        ForeignKey("clause_references.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(String(1000))

    run: Mapped[Run] = relationship(back_populates="timeline_entries")
    client: Mapped[Client] = relationship(back_populates="timeline_entries")
    contract_rule: Mapped[ContractRule] = relationship(back_populates="timeline_entries")
    anomalies: Mapped[list[Anomaly]] = relationship(
        back_populates="expected_entry", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ExpectedTimeline {self.billing_date} {self.expected_amount}>"


# ---------------------------------------------------------------------------
# 10. actual_transactions — what really happened
# ---------------------------------------------------------------------------


class ActualTransaction(Base):
    __tablename__ = "actual_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    #: NULL until client_matcher resolves the bank description to a client.
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)

    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    #: "invoice" | "bank" — where the row came from.
    source_type: Mapped[str | None] = mapped_column(String(20))

    run: Mapped[Run] = relationship(back_populates="transactions")
    document: Mapped[Document | None] = relationship(back_populates="transactions")
    client: Mapped[Client | None] = relationship(back_populates="transactions")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ActualTransaction {self.transaction_date} {self.amount}>"


# ---------------------------------------------------------------------------
# 11. anomalies — the findings
# ---------------------------------------------------------------------------


class Anomaly(Base):
    __tablename__ = "anomalies"
    __table_args__ = (
        _one_of("anomaly_type", ANOMALY_TYPES),
        _one_of("status", ANOMALY_STATUSES),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    expected_timeline_id: Mapped[int | None] = mapped_column(
        ForeignKey("expected_timeline.id", ondelete="CASCADE"), index=True
    )
    actual_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("actual_transactions.id", ondelete="SET NULL")
    )
    #: Every anomaly shown to a user must trace to a clause. Nullable at the DB
    #: level only so a partially-extracted row can be stored and flagged; the UI
    #: must not present an anomaly without one.
    clause_reference_id: Mapped[int | None] = mapped_column(
        ForeignKey("clause_references.id", ondelete="SET NULL"), index=True
    )

    anomaly_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    expected_amount: Mapped[float] = mapped_column(Float, nullable=False)
    actual_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    #: expected - actual. Computed by the engine, never by a model.
    gap: Mapped[float] = mapped_column(Float, nullable=False)

    #: 0.0-1.0 from the rule engine, later adjusted by the agent.
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="unverified", nullable=False, index=True)

    # ---- Phase 8 verification agent output ----
    agent_reasoning: Mapped[str | None] = mapped_column(String)
    agent_tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[Run] = relationship(back_populates="anomalies")
    client: Mapped[Client] = relationship(back_populates="anomalies")
    expected_entry: Mapped[ExpectedTimeline | None] = relationship(back_populates="anomalies")
    clause_reference: Mapped[ClauseReference | None] = relationship(back_populates="anomalies")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Anomaly id={self.id} {self.anomaly_type} gap={self.gap}>"


# ---------------------------------------------------------------------------
# 12. column_mappings — ADR-010, remember a confirmed CSV header layout
# ---------------------------------------------------------------------------


class ColumnMapping(Base):
    __tablename__ = "column_mappings"
    __table_args__ = (UniqueConstraint("header_signature", name="uq_column_mapping_signature"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    #: sha256 of the normalised header row. Not run-scoped on purpose — a
    #: confirmed mapping is worth reusing across every future run.
    header_signature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: {"date": "Txn Date", "amount": "Amount (USD)", ...}
    mapping: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ColumnMapping {self.header_signature[:8]}...>"


#: Every model, in dependency order. `9_db_health.py` counts these and
#: `reset_run.py` deletes in reverse.
ALL_MODELS: tuple[type[Base], ...] = (
    Run,
    Document,
    Client,
    ContractRule,
    ClauseReference,
    PriceEscalation,
    Discount,
    Milestone,
    ExpectedTimeline,
    ActualTransaction,
    Anomaly,
    ColumnMapping,
)
