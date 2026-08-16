"""[A] Pure math: ContractRules -> the expected billing timeline. Phase 6.

This is the most load-bearing function in the project. Every figure a user is
shown descends from it, and it is the answer to *"how do you know $6,480 is
right?"* — a hundred lines of arithmetic and a test file, not a model's opinion.

So, deliberately:

* **No database, no network, no LLM.** Everything it needs arrives as arguments.
* **No `datetime.today()`.** A function that reads the clock produces a different
  answer tomorrow and cannot be unit-tested. The billing window is passed in.
* **Nothing is invented.** A contract with no start date produces no timeline; a
  milestone whose date cannot be resolved is *reported* (`unresolved_milestones`)
  rather than parked on a guessed date, because a fabricated billing date turns
  into a fabricated ghost_invoice two functions later.

The order of operations is the part worth reading twice::

    rate  = base
    rate  = round(rate * (1 + escalation%) ** anniversaries, 2)   # the new rate card
    owed  = round(rate * (1 - discount%), 2)                      # applied to the new rate

Escalation first, then discount, and **each stage rounds to cents**. That is not
a floating-point convenience: an escalation clause resets the rate card, and the
studio's invoice for the discounted months is computed from the rate on that
card, not from an unrounded intermediate. Rounding once at the end instead can
land a cent away, which is enough to fail an exact ground-truth comparison.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date

from core.ai.schemas import ContractRules, Milestone, TimelineEntry

#: How many recurring billings to emit when a contract has a start date but no
#: end date and the caller names no window. Twelve months is the demo horizon and
#: the scenario observation year; it is a default, never an assumption baked in.
DEFAULT_HORIZON_MONTHS = 12

#: months per billing period, by ContractRules.billing_frequency.
_PERIOD_MONTHS: dict[str, int] = {
    "monthly": 1,
    "quarterly": 3,
    "annual": 12,
    "one_time": 0,  # one entry, on the start date
}


@dataclass(frozen=True)
class ClauseRefMap:
    """Which `clause_references.id` proves which part of the contract.

    Every timeline row cites the clause that explains **its own amount** — the
    escalation clause on an escalated row, the discount clause on a discounted
    one, the base-fee clause otherwise. Phase 6's `pipeline.py` may later swap in
    a different clause when the *anomaly* type calls for one (a zombie_discount
    is proven by the discount's expiry clause, not by the rate card), and it can,
    because the map is kept whole rather than collapsed into one id.

    All fields are optional: extraction fails, and a timeline with no clause
    reference is still arithmetically correct — it is just not yet *provable*,
    which the UI shows honestly (ADR-005).
    """

    base_fee: int | None = None
    escalation: int | None = None
    #: index into `ContractRules.discounts` -> clause_references.id
    discounts: dict[int, int] = field(default_factory=dict)
    #: index into `ContractRules.milestones` -> clause_references.id
    milestones: dict[int, int] = field(default_factory=dict)


def add_months(anchor: date, months: int) -> date:
    """`anchor` shifted by whole months, clamped to the target month's last day.

    Jan 31 + 1 month is Feb 28 (or Feb 29 in a leap year), and Jan 31 + 1 + 1 is
    Mar 28, **not** Mar 31 — the clamp is not remembered. That is the honest
    reading of a monthly billing schedule anchored on the 31st, and it is why the
    generator always steps from the original anchor (`add_months(start, n)`)
    rather than repeatedly adding one month to the previous result.
    """
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def months_between(start: date, when: date) -> int:
    """Whole calendar months from `start` to `when`, ignoring the day of month.

    Calendar months, not elapsed days: a contract signed on 15 March escalates on
    15 March, and *"after 12 months"* means the thirteenth billing, whatever the
    day count in between. Negative when `when` precedes `start`.
    """
    return (when.year - start.year) * 12 + (when.month - start.month)


def rate_for(rules: ContractRules, billing_date: date, *, compound: bool = True) -> tuple[float, bool, float]:
    """`(expected_amount, applied_escalation, applied_discount_pct)` for one billing.

    Pure and independently testable — the reconciliation classifier calls it to
    ask counterfactual questions ("what would this month have cost at the
    *pre*-escalation rate?") without rebuilding a timeline.
    """
    base = rules.base_amount or 0.0
    start = rules.contract_start_date
    if start is None:
        return round(base, 2), False, 0.0

    elapsed = months_between(start, billing_date)

    rate = base
    escalated = False
    esc = rules.escalation
    if esc and esc.after_months > 0 and elapsed >= esc.after_months:
        # How many anniversaries have passed. `compound=False` applies the rise
        # exactly once, which is what a "one increase, then flat" contract says.
        anniversaries = elapsed // esc.after_months if compound else 1
        for _ in range(anniversaries):
            rate = round(rate * (1 + esc.percentage / 100), 2)
        escalated = True

    owed = rate
    discount_pct = 0.0
    for discount in rules.discounts:
        if 0 <= elapsed < discount.duration_months:
            owed = round(owed * (1 - discount.percentage / 100), 2)
            discount_pct = discount.percentage

    return round(owed, 2), escalated, discount_pct


def generate_timeline(
    rules: ContractRules,
    client_id: int,
    contract_rule_id: int,
    *,
    window_start: date | None = None,
    window_end: date | None = None,
    horizon_months: int | None = None,
    clause_refs: ClauseRefMap | None = None,
    milestone_dates: dict[int, date] | None = None,
    compound_escalation: bool = True,
) -> list[TimelineEntry]:
    """PURE FUNCTION. No DB, no network, no LLM. Fully unit-testable.

    The three positional arguments are the contract of `docs/interfaces.md`. The
    keyword-only arguments are Phase 6 additions, and every one of them exists to
    keep a decision *out* of this function:

    * `window_start` / `window_end` — which billings to emit. A contract that
      started in 2024 and is being reconciled against a 2025 bank statement wants
      the twelve billings of 2025, not everything since signature. Defaults to
      the contract's own start, running for `horizon_months`.
    * `horizon_months` — how far to run when the contract has no end date.
    * `clause_refs` — the proof map; see `ClauseRefMap`.
    * `milestone_dates` — `{index into rules.milestones: date}`. A milestone whose
      condition ("on website launch") nobody has resolved to a calendar date is
      **left out**; ask `unresolved_milestones()` for the list rather than
      inventing a date for it.
    * `compound_escalation` — an annual clause that says *"on each anniversary"*
      compounds. Set False for a contract with a single, one-off rise.

    Returns rows in billing-date order, recurring and milestone interleaved.
    Returns `[]` — never raises — when the contract has no start date or no
    amount to bill, because "we could not read this contract" is a legitimate
    outcome and the caller has to render it either way.
    """
    start = rules.contract_start_date
    if start is None or rules.base_amount is None:
        return []

    refs = clause_refs or ClauseRefMap()
    period = _PERIOD_MONTHS.get(rules.billing_frequency, 0)

    first = window_start or start
    if window_end is not None:
        last = window_end
    elif rules.contract_end_date is not None:
        last = rules.contract_end_date
    else:
        span = horizon_months if horizon_months is not None else DEFAULT_HORIZON_MONTHS
        last = add_months(first, max(span - 1, 0))
    if rules.contract_end_date is not None:
        last = min(last, rules.contract_end_date)

    entries: list[TimelineEntry] = []

    if period == 0:
        # one_time (or an unknown frequency, which is treated as one_time rather
        # than guessed at — billing an unreadable contract monthly for a year
        # would manufacture eleven ghost invoices out of a bad extraction).
        if first <= start <= last:
            amount, escalated, discount_pct = rate_for(rules, start, compound=compound_escalation)
            entries.append(
                _entry(rules, refs, client_id, contract_rule_id, start, amount, escalated, discount_pct)
            )
    else:
        # Step from the contract's own anchor so the day-of-month clamp never
        # compounds, then keep the billings that land inside the window.
        offset = 0
        while True:
            billing_date = add_months(start, offset * period)
            if billing_date > last:
                break
            if billing_date >= first:
                amount, escalated, discount_pct = rate_for(
                    rules, billing_date, compound=compound_escalation
                )
                entries.append(
                    _entry(
                        rules, refs, client_id, contract_rule_id, billing_date, amount, escalated, discount_pct
                    )
                )
            offset += 1
            if offset > 1200:  # 100 years of monthly billing: a bad date, not a contract
                break

    for index, milestone in enumerate(rules.milestones):
        due = (milestone_dates or {}).get(index)
        if due is None or not (first <= due <= last):
            continue
        entries.append(
            TimelineEntry(
                client_id=client_id,
                contract_rule_id=contract_rule_id,
                billing_date=due,
                expected_amount=round(milestone.amount, 2),
                payment_type="milestone",
                applied_escalation=False,
                applied_discount_pct=0.0,
                source_clause_ref_id=refs.milestones.get(index, refs.base_fee),
                notes=_milestone_note(milestone),
            )
        )

    entries.sort(key=lambda e: (e.billing_date, e.payment_type))
    return entries


def unresolved_milestones(
    rules: ContractRules, milestone_dates: dict[int, date] | None = None
) -> list[tuple[int, Milestone]]:
    """The milestones `generate_timeline` had to leave out, and why they matter.

    A milestone with no date is money the contract says is owed on a condition
    nobody has tied to the calendar — *"$15,000 on website launch"*. It is not a
    finding and it is not nothing. Surfacing it as "we cannot check this one"
    beats both silently dropping it and inventing a due date to bill against.
    """
    dated = milestone_dates or {}
    return [(i, m) for i, m in enumerate(rules.milestones) if dated.get(i) is None]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _entry(
    rules: ContractRules,
    refs: ClauseRefMap,
    client_id: int,
    contract_rule_id: int,
    billing_date: date,
    amount: float,
    escalated: bool,
    discount_pct: float,
) -> TimelineEntry:
    if escalated:
        clause_ref = refs.escalation or refs.base_fee
    elif discount_pct:
        clause_ref = _discount_ref(rules, refs, discount_pct) or refs.base_fee
    else:
        clause_ref = refs.base_fee
    return TimelineEntry(
        client_id=client_id,
        contract_rule_id=contract_rule_id,
        billing_date=billing_date,
        expected_amount=amount,
        payment_type="recurring",
        applied_escalation=escalated,
        applied_discount_pct=discount_pct,
        source_clause_ref_id=clause_ref,
        notes=_note(rules, amount, escalated, discount_pct),
    )


def _discount_ref(rules: ContractRules, refs: ClauseRefMap, pct: float) -> int | None:
    for index, discount in enumerate(rules.discounts):
        if discount.percentage == pct:
            return refs.discounts.get(index)
    return None


def _note(rules: ContractRules, amount: float, escalated: bool, discount_pct: float) -> str:
    """The line a user reads in the timeline. Every number in it is one this
    function computed — nothing here is phrased by a model."""
    base = rules.base_amount or 0.0
    parts = [f"Base {_money(base)}"]
    if escalated and rules.escalation:
        parts.append(f"+{_fmt_pct(rules.escalation.percentage)}% escalation applied")
    if discount_pct:
        parts.append(f"-{_fmt_pct(discount_pct)}% discount active")
    if not escalated and not discount_pct:
        parts.append("contract rate, no adjustment")
    parts.append(f"= {_money(amount)}")
    return " · ".join(parts)


def _milestone_note(milestone: Milestone) -> str:
    condition = milestone.due_condition or "no stated condition"
    return f"Milestone: {milestone.description} ({condition}) = {_money(milestone.amount)}"


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _fmt_pct(value: float) -> str:
    return f"{value:g}"
