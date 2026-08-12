"""[A] Pydantic schemas shared across every layer.

Data shapes only, pulled forward from Phase 5 because data_sourcing/scenario_builder.py
(Phase 3) needs a typed `ContractRules` to hand-verify real contracts against — the
plan's own signature is `build_scenario(contract_paths, rules: list[ContractRules], ...)`.
`core/ai/contract_extractor.py` (the LLM call that PRODUCES a ContractRules from a real
extraction) is still a Phase 5 stub; nothing here calls a model.

Mirrors the vocabularies in core/db/models.py (ANOMALY_TYPES, PAYMENT_TYPES,
BILLING_FREQUENCIES, ANOMALY_STATUSES, LOCATE_METHODS) as Literals.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class Escalation(BaseModel):
    percentage: float
    after_months: int
    clause_text: str  # VERBATIM from the document. Never paraphrased.


class Discount(BaseModel):
    percentage: float
    duration_months: int
    clause_text: str


class Milestone(BaseModel):
    description: str
    amount: float
    due_condition: str | None
    clause_text: str


class ContractRules(BaseModel):
    client_name: str
    contract_start_date: date | None
    contract_end_date: date | None
    base_amount: float | None
    currency: str = "USD"
    billing_frequency: Literal["monthly", "quarterly", "annual", "one_time", "unknown"]
    payment_terms: str | None
    escalation: Escalation | None
    discounts: list[Discount] = []
    milestones: list[Milestone] = []


class TimelineEntry(BaseModel):
    client_id: int
    contract_rule_id: int
    billing_date: date
    expected_amount: float
    payment_type: Literal["recurring", "milestone"]
    applied_escalation: bool
    applied_discount_pct: float
    source_clause_ref_id: int | None
    notes: str


class Anomaly(BaseModel):
    anomaly_type: Literal["ghost_invoice", "forgotten_raise", "zombie_discount", "short_change"]
    client_id: int
    expected_timeline_id: int
    actual_transaction_id: int | None
    clause_reference_id: int | None
    expected_amount: float
    actual_amount: float
    gap: float
    billing_date: date
    confidence_score: float  # 0.0 - 1.0, from the rule engine
    status: Literal["unverified", "confirmed", "false_positive", "needs_review"]


class ClauseLocation(BaseModel):
    page: int
    bbox: list[float]  # [x0, y0, x1, y1] in PDF points
    method: Literal["exact", "fuzzy"]


# ---------------------------------------------------------------------------
# Phase 4 — extraction. Not pre-declared as "shared data shapes" the way the
# AI-boundary types above were (docs/interfaces.md's Phase 3/5 entries), because
# Phase 4 is what first needs them. Defined here anyway, not split into a second
# module, because they cross the same A/B boundary this file exists to serve:
# document_router/pdf_extractor (A) produce ExtractedDoc, csv_parser (B) produces
# TransactionRow/ColumnProposal, and Phase 5's contract_extractor (A) consumes
# ExtractedDoc.blocks.
# ---------------------------------------------------------------------------


class DocBlock(BaseModel):
    page_number: int
    text: str
    is_table: bool = False


class ExtractedDoc(BaseModel):
    doc_type: Literal["text_pdf", "scanned", "image", "csv"]
    blocks: list[DocBlock]
    full_text: str
    page_count: int
    #: Non-fatal notes ("no extractable text on any page") that still let the
    #: caller decide complete vs. failed — this module never raises.
    warnings: list[str] = []


class TransactionRow(BaseModel):
    transaction_date: date
    amount: float
    description: str | None = None
    source_type: Literal["invoice", "bank"] | None = None


class ColumnProposal(BaseModel):
    #: {"date": "Txn Date", "amount": "Amount (USD)", "description": "Memo"}
    mapping: dict[str, str]
    #: sha256 of the normalised header row — how a confirmed mapping is cached
    #: (ADR-010) and looked up again for the same CSV shape.
    header_signature: str
    #: First few rows, for the confirmation UI to show next to the dropdowns.
    sample_rows: list[dict[str, str]] = []
