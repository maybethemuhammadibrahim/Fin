"""[B] Pure math: expected vs actual, aggregated per client-month (ADR-006). Phase 6.

ADR-006 in one line: **sum a client's month and compare the total**, rather than
trying to match each payment to each invoice. Full matching is a combinatorial
assignment problem; aggregation is a sum. What it costs is precision on split
payments, and Phase 8's `check_split_payments` tool buys that back on the handful
of rows this function flags instead of on the thousands it doesn't.

Two things happen here, and they are separate on purpose:

1. **Attribution** — whose payment is this? A bank line says
   ``REGAL ENT GROUP ACH INV-202502``; the client is called *Regal Entertainment
   Group*. `attribute_transactions()` does that matching, and **refuses** rather
   than guessing when nothing scores well enough. An unattributed row is dropped
   from reconciliation, never quietly assigned to the nearest name — a wrong
   merge reconciles one client's money against another's contract, which is the
   one failure mode that produces confidently wrong findings.
2. **Reconciliation** — for each expected billing, sum what arrived and hand the
   gap to the classifier.

Pure throughout: no database, no network, no model, no clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from core.ai.client_matcher import normalise, similarity
from core.ai.schemas import Anomaly, ContractRules, TimelineEntry, TransactionRow
from core.engine.anomaly_classifier import DEFAULT_TOLERANCE_PCT, Classification, classify_gap

#: How far either side of a billing date a payment can land and still count as
#: that month's. Covers the "invoice on the 30th, paid on the 3rd" boundary that
#: calendar-month grouping alone gets wrong.
DEFAULT_DATE_TOLERANCE_DAYS = 15

#: Minimum name-match score to attribute a transaction to a client.
DEFAULT_MATCH_THRESHOLD = 85

#: How far clear the winner must be before an attribution is trusted. Two clients
#: called "Northwind Design" and "Northwind Digital" both score high on the same
#: bank line; attributing to whichever scored a point more is a coin toss with a
#: confident face on it, so neither gets it.
DEFAULT_MATCH_MARGIN = 6

#: Payment-rail decoration. These words say how money moved, never who sent it,
#: and they drag a fuzzy score down hard: "REGAL ENT GROUP ACH" scores 62 against
#: "Regal Entertainment Group" and 100 once "ACH" is gone.
_RAIL_NOISE = re.compile(
    r"\b(?:ach|eft|wire|xfer|transfer|pmt|pmts|payment|paymt|dep|deposit|dda|"
    r"credit|debit|memo|ref|inv|invoice|chk|check|recur|remit|remittance|"
    r"online|bill|billpay|from|via)\b",
    re.I,
)

#: Reference numbers: INV-202501, #1042, 000123456. Identity is never in them.
_REFERENCE = re.compile(r"\b[a-z]*[-#]?\d[\w-]*\b", re.I)


@dataclass(frozen=True)
class ClientRef:
    """A client to attribute payments to. `aliases` carries anything already
    confirmed by a human in `app/components/client_confirm.py` — a confirmed
    alias is an exact match, not a fuzzy one."""

    client_id: int
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Attribution:
    """One transaction, and who we decided sent it."""

    transaction: TransactionRow
    client_id: int | None
    score: int
    runner_up: int = 0

    @property
    def matched(self) -> bool:
        return self.client_id is not None


@dataclass
class MonthBucket:
    """One expected billing and everything that arrived against it."""

    expected: TimelineEntry
    transactions: list[TransactionRow] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(sum(t.amount for t in self.transactions), 2)


@dataclass
class ReconciliationResult:
    """Everything reconciliation learned, not just the findings.

    `unattributed` and `unmatched` are the honest residue: money that arrived and
    could not be tied to a contract. They are not anomalies — nobody is owed
    anything because of them — but a run that quietly discards them is a run
    whose totals cannot be checked against a bank statement.
    """

    anomalies: list[Anomaly]
    #: expected billing -> what was found, including the clean months.
    buckets: list[MonthBucket]
    #: paired 1:1 with `anomalies`, in the same order.
    classifications: list[Classification]
    #: attributed to a client, but landing in no expected billing window.
    unmatched: list[TransactionRow]
    #: no client scored high enough (bank fees, interest, a client nobody uploaded).
    unattributed: list[TransactionRow]

    @property
    def total_gap(self) -> float:
        return round(sum(a.gap for a in self.anomalies), 2)


# ---------------------------------------------------------------------------
# 1. attribution
# ---------------------------------------------------------------------------


def clean_description(description: str | None) -> str:
    """A bank description reduced to the part that names somebody.

    ``"REGAL ENT GROUP ACH INV-202502"`` -> ``"REGAL ENT GROUP"``. Reference
    numbers go first (so ``INV-202502`` cannot survive as a token), then the
    payment-rail words.
    """
    text = _REFERENCE.sub(" ", description or "")
    text = _RAIL_NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def name_score(description: str, client_name: str) -> int:
    """0-100 that a bank description names this client.

    Two ways to score, and the better one wins:

    * `client_matcher.similarity` — punctuation- and suffix-blind, catches
      ``"Central Garden Pet Co"`` vs ``"Central Garden & Pet Co."``.
    * an **abbreviation** rule — every word in the description is the start of a
      word in the client's name, in order. That is what a bank statement does to
      a long name: ``"REGAL ENT GROUP"``, ``"CTRL GARDEN PET"``. Fuzzy ratios are
      bad at it because the truncation deletes most of the characters.
    """
    base = similarity(description, client_name)
    return max(base, _abbreviation_score(description, client_name))


def _abbreviation_score(description: str, client_name: str) -> int:
    desc_tokens = [t for t in re.split(r"[^a-z0-9]+", description.lower()) if len(t) > 1]
    name_tokens = [t for t in re.split(r"[^a-z0-9]+", client_name.lower()) if len(t) > 1]
    if not desc_tokens or not name_tokens:
        return 0

    cursor = 0
    consumed = 0
    for token in desc_tokens:
        for index in range(cursor, len(name_tokens)):
            candidate = name_tokens[index]
            if candidate.startswith(token) or token.startswith(candidate):
                cursor = index + 1
                consumed += 1
                break
        else:
            return 0  # a word that is nowhere in the name: not this client

    # Require the match to cover the distinctive front of the name, so a
    # one-word description ("garden") cannot claim a three-word client.
    coverage = consumed / len(name_tokens)
    if consumed < 2 and len(name_tokens) > 1:
        return 0
    return int(round(80 + 20 * coverage))


def attribute_transactions(
    actuals: list[TransactionRow],
    clients: list[ClientRef],
    *,
    threshold: int = DEFAULT_MATCH_THRESHOLD,
    margin: int = DEFAULT_MATCH_MARGIN,
) -> list[Attribution]:
    """Decide which client each transaction belongs to. PURE.

    A row that already carries a `client_id` (because `client_matcher` or a human
    resolved it upstream) is passed through untouched with a score of 100 — this
    function never overrules a decision somebody already made.
    """
    by_id = {c.client_id: c for c in clients}
    out: list[Attribution] = []

    for row in actuals:
        if row.client_id is not None and row.client_id in by_id:
            out.append(Attribution(transaction=row, client_id=row.client_id, score=100))
            continue

        cleaned = clean_description(row.description)
        if not cleaned:
            out.append(Attribution(transaction=row, client_id=None, score=0))
            continue

        scored: list[tuple[int, int]] = []
        for client in clients:
            best = name_score(cleaned, client.name)
            for alias in client.aliases:
                if normalise(alias) and normalise(alias) == normalise(cleaned):
                    best = 100
                else:
                    best = max(best, name_score(cleaned, alias))
            scored.append((best, client.client_id))

        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        top_score, top_id = scored[0] if scored else (0, None)
        runner_up = scored[1][0] if len(scored) > 1 else 0

        confident = top_score >= threshold and (top_score - runner_up) >= margin
        out.append(
            Attribution(
                transaction=row.model_copy(update={"client_id": top_id}) if confident else row,
                client_id=top_id if confident else None,
                score=top_score,
                runner_up=runner_up,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 2. reconciliation
# ---------------------------------------------------------------------------


def reconcile(
    expected: list[TimelineEntry],
    actuals: list[TransactionRow],
    date_tolerance_days: int = DEFAULT_DATE_TOLERANCE_DAYS,
    *,
    rules_by_contract: dict[int, ContractRules] | None = None,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> list[Anomaly]:
    """PURE FUNCTION. Aggregates actuals per client-month (see ADR-006).

    The declared interface. `rules_by_contract` maps
    `TimelineEntry.contract_rule_id` to the `ContractRules` behind it — the
    classifier needs the escalation and discount clauses to tell a
    forgotten_raise from a short_change. Without it every shortfall degrades to
    `short_change`, which is honest but uninformative.

    Use `reconcile_detail()` when you also want the clean months, the
    unattributed rows and the reasoning.
    """
    return reconcile_detail(
        expected,
        actuals,
        date_tolerance_days=date_tolerance_days,
        rules_by_contract=rules_by_contract,
        tolerance_pct=tolerance_pct,
    ).anomalies


def reconcile_detail(
    expected: list[TimelineEntry],
    actuals: list[TransactionRow],
    *,
    date_tolerance_days: int = DEFAULT_DATE_TOLERANCE_DAYS,
    rules_by_contract: dict[int, ContractRules] | None = None,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> ReconciliationResult:
    """`reconcile()` plus everything it had to work out along the way."""
    rules_by_contract = rules_by_contract or {}

    buckets = [MonthBucket(expected=e) for e in expected]
    unattributed: list[TransactionRow] = []
    unmatched: list[TransactionRow] = []

    #: Every transaction lands in **exactly one** bucket. Aggregating "the
    #: calendar month, plus 15 days either side" without this would let a payment
    #: on the 3rd count for both December and January, and a client who paid
    #: everything once would come out with a surplus in one month and a
    #: ghost_invoice in the next.
    for row in actuals:
        if row.client_id is None:
            unattributed.append(row)
            continue
        bucket = _best_bucket(buckets, row, date_tolerance_days)
        if bucket is None:
            unmatched.append(row)
        else:
            bucket.transactions.append(row)

    anomalies: list[Anomaly] = []
    classifications: list[Classification] = []

    for bucket in buckets:
        rules = rules_by_contract.get(bucket.expected.contract_rule_id)
        result = classify_gap(
            bucket.expected,
            bucket.total,
            rules or _bare_rules(bucket.expected),
            tolerance_pct=tolerance_pct,
        )
        if result is None:
            continue

        anomalies.append(
            Anomaly(
                anomaly_type=result.anomaly_type,
                client_id=bucket.expected.client_id,
                expected_timeline_id=bucket.expected.id,
                #: One id for a month that may hold several payments — the
                #: largest, so the UI's "jump to the transaction" lands on the
                #: one a user recognises. Phase 8 sees all of them.
                actual_transaction_id=_representative_id(bucket),
                clause_reference_id=bucket.expected.source_clause_ref_id,
                expected_amount=round(bucket.expected.expected_amount, 2),
                actual_amount=bucket.total,
                gap=round(bucket.expected.expected_amount - bucket.total, 2),
                billing_date=bucket.expected.billing_date,
                confidence_score=result.confidence,
                status="unverified",
            )
        )
        classifications.append(result)

    return ReconciliationResult(
        anomalies=anomalies,
        buckets=buckets,
        classifications=classifications,
        unmatched=unmatched,
        unattributed=unattributed,
    )


def _best_bucket(
    buckets: list[MonthBucket], row: TransactionRow, tolerance_days: int
) -> MonthBucket | None:
    """The expected billing this payment most plausibly answers.

    Candidates are the same client's billings in the same calendar month, or
    within `tolerance_days` either side of the billing date.

    Among them, **a payment answers a billing that has already happened**: the
    most recent billing on or before the payment date wins. Only when the payment
    precedes every candidate billing — a prepayment — does it attach to the
    nearest future one.

    Nearest-date alone gets this wrong in both directions. Billed on the 1st and
    paid on the 30th, nearest-date hands the money to *next* month's billing,
    leaving a ghost invoice behind it. Billed on the 30th and paid on the 3rd,
    same-calendar-month alone hands it to the billing four weeks ahead. Lag
    ordering is the rule that reads both correctly.
    """
    best: tuple[tuple[int, int, date], MonthBucket] | None = None
    for bucket in buckets:
        entry = bucket.expected
        if entry.client_id != row.client_id:
            continue
        lag = (row.transaction_date - entry.billing_date).days
        same_month = (
            row.transaction_date.year == entry.billing_date.year
            and row.transaction_date.month == entry.billing_date.month
        )
        if not same_month and abs(lag) > tolerance_days:
            continue
        # (0, lag) for a billing already issued, (1, wait) for one still to come;
        # then the earlier billing date, so an exact tie settles the older debt.
        key = (0, lag, entry.billing_date) if lag >= 0 else (1, -lag, entry.billing_date)
        if best is None or key < best[0]:
            best = (key, bucket)
    return best[1] if best else None


def _representative_id(bucket: MonthBucket) -> int | None:
    with_ids = [t for t in bucket.transactions if t.id is not None]
    if not with_ids:
        return None
    return max(with_ids, key=lambda t: t.amount).id


def _bare_rules(entry: TimelineEntry) -> ContractRules:
    """A rules object with no clauses, for when the caller passed none.

    Every shortfall then classifies as `short_change` — correct, since with no
    escalation or discount on record there is nothing else it could be.
    """
    return ContractRules(
        client_name="",
        contract_start_date=entry.billing_date,
        contract_end_date=None,
        base_amount=entry.expected_amount,
        billing_frequency="monthly",
        payment_terms=None,
        escalation=None,
    )


def window_for(entries: list[TimelineEntry]) -> tuple[date, date] | None:
    """The first and last billing date in a timeline. Convenience for callers
    that need to bound a query on `actual_transactions`."""
    if not entries:
        return None
    dates = [e.billing_date for e in entries]
    return min(dates), max(dates)


def date_window(entries: list[TimelineEntry], tolerance_days: int = DEFAULT_DATE_TOLERANCE_DAYS):
    """`window_for` widened by the matching tolerance, so a query returns the
    payments that land just outside the first and last billing."""
    window = window_for(entries)
    if window is None:
        return None
    first, last = window
    return first - timedelta(days=tolerance_days), last + timedelta(days=tolerance_days)
