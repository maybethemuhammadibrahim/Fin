"""[B] Pure math: classify a gap into one of the four leak types. Phase 6.

The four types are mutually exclusive by construction, and each is a *hypothesis
about what the bookkeeper did*, tested by arithmetic:

====================  =========================================================
🔴 ghost_invoice      nothing arrived at all
🟡 forgotten_raise    what arrived is the rate **before** the escalation clause
🟠 zombie_discount    what arrived is the expected rate minus an **expired** discount
🟣 short_change       less than expected, and no other clause explains the shortfall
====================  =========================================================

`short_change` is the residual on purpose. A gap that matches a specific clause
is attributed to that clause; a gap that matches nothing is reported as what it
is — an unexplained shortfall — rather than being forced into a category that
would put a confident wrong story in front of the user.

Nothing here calls a model, and nothing here reads the clock or the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.ai.schemas import ContractRules, TimelineEntry, TransactionRow
from core.engine.timeline_generator import add_months, rate_for

#: A month is "paid" when the total is within this much of expected. One percent
#: absorbs rounding, an FX cent and a bank's own rounding of a wire; anything
#: wider starts hiding real short-changes on large contracts.
DEFAULT_TOLERANCE_PCT = 1.0

#: How close a total has to sit to a hypothesised rate before that hypothesis is
#: accepted. Tighter than the payment tolerance: this is pattern matching, not
#: "close enough to be paid".
_MATCH_TOLERANCE_PCT = 1.0

ClauseRole = Literal["base_fee", "escalation", "discount"]


@dataclass(frozen=True)
class Classification:
    """One classified gap, with the reasoning kept next to the verdict."""

    anomaly_type: Literal["ghost_invoice", "forgotten_raise", "zombie_discount", "short_change"]
    confidence: float
    #: Which clause proves this finding — `pipeline.py` resolves it to a
    #: `clause_references.id`. A forgotten_raise is proven by the escalation
    #: clause, not by the row's own rate-card clause, which is why the role
    #: travels with the classification instead of being inferred later.
    clause_role: ClauseRole
    #: Plain English, every number in it computed here. The LLM never writes this.
    reason: str

    def as_tuple(self) -> tuple[str, float]:
        return self.anomaly_type, self.confidence


def classify(
    expected: TimelineEntry, actual: TransactionRow | None, rules: ContractRules
) -> tuple[str, float]:
    """Returns (anomaly_type, confidence_score).

    The signature `docs/interfaces.md` declared. `actual` is the client-month
    **aggregate** (ADR-006), not necessarily a single payment — `reconcile()`
    sums the month first. Returns `("", 0.0)` when the month is not an anomaly,
    so a caller that only has this signature can still tell clean from leaking;
    `classify_gap()` returns `None` for the same case and is the better call.
    """
    result = classify_gap(expected, 0.0 if actual is None else actual.amount, rules)
    return result.as_tuple() if result else ("", 0.0)


def classify_gap(
    expected: TimelineEntry,
    actual_total: float,
    rules: ContractRules,
    *,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> Classification | None:
    """The real entry point. `None` means "this month is fine".

    `None` is also returned when the client **overpaid**. Over-collection is not
    one of the four leak types and this product does not tell a studio it owes
    money back on the strength of a fuzzy name match — Phase 8's agent is where
    an unexplained surplus gets looked at.
    """
    owed = round(expected.expected_amount, 2)
    paid = round(actual_total, 2)
    gap = round(owed - paid, 2)

    if owed <= 0:
        return None

    tolerance = max(owed * tolerance_pct / 100, 0.01)

    if paid <= 0:
        return Classification(
            anomaly_type="ghost_invoice",
            confidence=0.90,
            clause_role="base_fee",
            reason=(
                f"{_money(owed)} was due on {expected.billing_date:%d %b %Y} and no payment "
                f"was recorded for this client in that month."
            ),
        )

    if gap <= tolerance:
        return None  # paid in full, or overpaid — see the docstring

    candidates: list[tuple[float, Classification]] = []

    forgotten = _forgotten_raise(expected, paid, gap, rules)
    if forgotten:
        candidates.append(forgotten)

    zombie = _zombie_discount(expected, owed, paid, gap, rules)
    if zombie:
        candidates.append(zombie)

    if candidates:
        # Smallest residual wins: whichever hypothesised rate the payment sits
        # closest to is the one that explains it. Ties keep list order, which
        # puts forgotten_raise first — the escalation is the stronger claim
        # because the timeline row already knows an escalation was due.
        candidates.sort(key=lambda pair: pair[0])
        return candidates[0][1]

    ratio = min(gap / owed, 1.0)
    return Classification(
        anomaly_type="short_change",
        confidence=round(0.50 + 0.40 * ratio, 2),
        clause_role="base_fee",
        reason=(
            f"{_money(owed)} was due on {expected.billing_date:%d %b %Y}, {_money(paid)} was "
            f"received, leaving {_money(gap)} unpaid. No escalation or discount clause "
            f"accounts for the difference."
        ),
    )


# ---------------------------------------------------------------------------
# the two clause-backed hypotheses
# ---------------------------------------------------------------------------


def _forgotten_raise(
    expected: TimelineEntry, paid: float, gap: float, rules: ContractRules
) -> tuple[float, Classification] | None:
    """Did they keep billing the pre-escalation rate?

    Only asked when the timeline row says an escalation was due — which is
    exactly why `applied_escalation` is stored on `expected_timeline`. Without it
    this would be indistinguishable from a contract that never had a raise.
    """
    if not expected.applied_escalation or rules.escalation is None:
        return None

    previous = _previous_rate(expected, rules)
    if previous is None:
        return None

    residual = abs(paid - previous)
    if residual > max(previous * _MATCH_TOLERANCE_PCT / 100, 0.01):
        return None

    exact = residual <= 0.01
    return (
        residual,
        Classification(
            anomaly_type="forgotten_raise",
            confidence=0.95 if exact else 0.85,
            clause_role="escalation",
            reason=(
                f"The {_pct(rules.escalation.percentage)} escalation due after "
                f"{rules.escalation.after_months} months makes this billing {_money(expected.expected_amount)}, "
                f"but {_money(paid)} was received — the rate from before the increase. "
                f"{_money(gap)} was never billed."
            ),
        ),
    )


def _zombie_discount(
    expected: TimelineEntry, owed: float, paid: float, gap: float, rules: ContractRules
) -> tuple[float, Classification] | None:
    """Is the shortfall exactly an expired discount, still being applied?

    Requires `applied_discount_pct == 0` on the timeline row: if the discount is
    still contractually alive, the expected amount already has it and a shortfall
    is a different problem.
    """
    if expected.applied_discount_pct:
        return None

    best: tuple[float, Classification] | None = None
    for discount in rules.discounts:
        if discount.percentage <= 0:
            continue
        discounted = round(owed * (1 - discount.percentage / 100), 2)
        residual = abs(paid - discounted)
        if residual > max(discounted * _MATCH_TOLERANCE_PCT / 100, 0.01):
            continue
        exact = residual <= 0.01
        candidate = (
            residual,
            Classification(
                anomaly_type="zombie_discount",
                confidence=0.95 if exact else 0.85,
                clause_role="discount",
                reason=(
                    f"The {_pct(discount.percentage)} discount ran for "
                    f"{discount.duration_months} months and had expired by "
                    f"{expected.billing_date:%d %b %Y}, but {_money(paid)} was received — "
                    f"{_money(owed)} less {_pct(discount.percentage)}. "
                    f"{_money(gap)} was discounted away after the discount ended."
                ),
            ),
        )
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best


def _previous_rate(expected: TimelineEntry, rules: ContractRules) -> float | None:
    """What this billing would have cost one escalation step ago.

    Computed by re-running `rate_for` at a billing date one escalation period
    earlier, rather than by dividing the escalated amount out — division would
    not reproduce the per-step rounding the generator does, and a one-cent drift
    is enough to miss the match.

    The comparison then has to be like-for-like on discount: a year ago the
    contract may still have been inside an intro-discount window this billing has
    long left behind. Strip the discount that applied *then*, apply the one that
    applies *now*, and what is left is purely the effect of the escalation.
    """
    esc = rules.escalation
    if esc is None or rules.contract_start_date is None or esc.after_months <= 0:
        return None

    earlier = add_months(expected.billing_date, -esc.after_months)
    previous, _escalated, then_discount_pct = rate_for(rules, earlier)

    if then_discount_pct:
        previous = round(previous / (1 - then_discount_pct / 100), 2)
    if expected.applied_discount_pct:
        previous = round(previous * (1 - expected.applied_discount_pct / 100), 2)
    return round(previous, 2)


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _pct(value: float) -> str:
    return f"{value:g}%"
