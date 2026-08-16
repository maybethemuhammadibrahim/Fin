"""[A] Known contract rules -> known timeline. The most important tests in the project. Phase 6.

Every expected amount in here was computed by hand before the code ran. That is
the whole point: when someone asks *"how do you know $6,480 is right?"*, the
answer is this file, not a model's output. The running example is the one from
`CLAUDE.md` — $6,000/month, 10% off for three months, 8% on the anniversary, and
a $15,000 launch milestone — because it is also the example the product pitch
uses, so a change that breaks the pitch breaks a test.

Run: `pytest tests/test_timeline.py -v`
"""

from __future__ import annotations

from datetime import date

import pytest

from core.ai.schemas import ContractRules, Discount, Escalation, Milestone
from core.engine.timeline_generator import (
    ClauseRefMap,
    add_months,
    generate_timeline,
    months_between,
    rate_for,
    unresolved_milestones,
)


def _rules(**overrides) -> ContractRules:
    """The worked example, unless a test says otherwise."""
    base = dict(
        client_name="Northwind Studio",
        contract_start_date=date(2025, 1, 1),
        contract_end_date=None,
        base_amount=6000.0,
        currency="USD",
        billing_frequency="monthly",
        payment_terms="Net 30",
        escalation=Escalation(percentage=8.0, after_months=12, clause_text="8% on each anniversary"),
        discounts=[Discount(percentage=10.0, duration_months=3, clause_text="10% for the first three months")],
        milestones=[],
    )
    base.update(overrides)
    return ContractRules(**base)


# ---------------------------------------------------------------------------
# month arithmetic — the edge cases the plan calls out by name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "anchor, months, expected",
    [
        (date(2025, 1, 31), 1, date(2025, 2, 28)),  # clamped to a short month
        (date(2024, 1, 31), 1, date(2024, 2, 29)),  # leap year
        (date(2025, 1, 31), 2, date(2025, 3, 31)),  # the clamp is NOT remembered
        (date(2025, 1, 31), 3, date(2025, 4, 30)),
        (date(2025, 12, 15), 1, date(2026, 1, 15)),  # year rollover
        (date(2025, 3, 15), -1, date(2025, 2, 15)),  # backwards, for counterfactuals
        (date(2025, 1, 15), 0, date(2025, 1, 15)),
        (date(2025, 3, 31), 12, date(2026, 3, 31)),
    ],
)
def test_add_months(anchor, months, expected):
    assert add_months(anchor, months) == expected


def test_months_between_counts_calendar_months_not_days():
    # 28 February to 1 March is one calendar month, whatever the day count says.
    assert months_between(date(2025, 2, 28), date(2025, 3, 1)) == 1
    assert months_between(date(2024, 3, 1), date(2025, 3, 1)) == 12
    assert months_between(date(2025, 3, 1), date(2024, 3, 1)) == -12


# ---------------------------------------------------------------------------
# the worked example, month by month
# ---------------------------------------------------------------------------


def test_worked_example_thirteen_months():
    entries = generate_timeline(_rules(), client_id=1, contract_rule_id=1, horizon_months=13)

    amounts = [e.expected_amount for e in entries]
    assert amounts == [
        5400.0,  # Jan — $6,000 less the 10% intro discount
        5400.0,  # Feb
        5400.0,  # Mar — third and final discounted month
        6000.0,  # Apr — discount expired, full rate
        6000.0,
        6000.0,
        6000.0,
        6000.0,
        6000.0,
        6000.0,
        6000.0,
        6000.0,  # Dec — month 12, still pre-anniversary
        6480.0,  # Jan 2026 — 8% escalation applied
    ]
    assert [e.billing_date for e in entries][:2] == [date(2025, 1, 1), date(2025, 2, 1)]
    assert entries[-1].billing_date == date(2026, 1, 1)


def test_discount_expires_on_its_duration_not_after_it():
    entries = generate_timeline(_rules(), 1, 1, horizon_months=4)
    assert [e.applied_discount_pct for e in entries] == [10.0, 10.0, 10.0, 0.0]


def test_escalation_applies_on_the_anniversary_not_before():
    entries = generate_timeline(_rules(), 1, 1, horizon_months=13)
    assert [e.applied_escalation for e in entries] == [False] * 12 + [True]


def test_escalation_compounds_each_anniversary():
    entries = generate_timeline(_rules(), 1, 1, horizon_months=25)
    # 6000 -> 6480.00 -> 6998.40. Rounded at each anniversary, because an
    # escalation resets the rate card and a rate card is in whole cents.
    assert entries[12].expected_amount == 6480.0
    assert entries[24].expected_amount == 6998.40


def test_single_rise_contract_does_not_compound():
    entries = generate_timeline(_rules(), 1, 1, horizon_months=25, compound_escalation=False)
    assert entries[24].expected_amount == 6480.0


def test_escalation_then_discount_order_matters():
    """A contract with a 12-month discount and a 12-month escalation: month 13
    is escalated AND still inside no discount window — but if the discount ran
    24 months, month 13 is 6480 less 10%, not 6000 less 10% then escalated."""
    rules = _rules(
        discounts=[Discount(percentage=10.0, duration_months=24, clause_text="10% for two years")]
    )
    entries = generate_timeline(rules, 1, 1, horizon_months=13)
    assert entries[0].expected_amount == 5400.0
    assert entries[12].expected_amount == 5832.0  # round(6000*1.08, 2) * 0.9


# ---------------------------------------------------------------------------
# windows, frequencies and the ways a contract can be unreadable
# ---------------------------------------------------------------------------


def test_window_selects_a_year_out_of_a_longer_contract():
    """The reconciliation case: a 2024 contract against a 2025 bank statement."""
    rules = _rules(contract_start_date=date(2024, 3, 1), discounts=[])
    entries = generate_timeline(
        rules, 1, 1, window_start=date(2025, 1, 1), window_end=date(2025, 12, 1)
    )
    assert len(entries) == 12
    assert entries[0].billing_date == date(2025, 1, 1)
    # The anniversary falls inside the window: Jan/Feb at the old rate, Mar on.
    assert [e.expected_amount for e in entries[:4]] == [6000.0, 6000.0, 6480.0, 6480.0]


def test_contract_end_date_truncates_the_horizon():
    rules = _rules(contract_end_date=date(2025, 6, 1), discounts=[])
    entries = generate_timeline(rules, 1, 1, horizon_months=24)
    assert len(entries) == 6
    assert entries[-1].billing_date == date(2025, 6, 1)


def test_mid_month_start_bills_on_the_same_day_each_month():
    rules = _rules(contract_start_date=date(2025, 3, 15), discounts=[])
    entries = generate_timeline(rules, 1, 1, horizon_months=3)
    assert [e.billing_date for e in entries] == [
        date(2025, 3, 15),
        date(2025, 4, 15),
        date(2025, 5, 15),
    ]


def test_month_end_start_never_drifts_earlier_permanently():
    """Jan 31 clamps to Feb 28, and March must go back to the 31st. Stepping from
    the previous result instead of the anchor is what gets this wrong."""
    rules = _rules(contract_start_date=date(2025, 1, 31), discounts=[])
    entries = generate_timeline(rules, 1, 1, horizon_months=3)
    assert [e.billing_date for e in entries] == [
        date(2025, 1, 31),
        date(2025, 2, 28),
        date(2025, 3, 31),
    ]


@pytest.mark.parametrize(
    "frequency, expected_count, step_months",
    [("monthly", 12, 1), ("quarterly", 4, 3), ("annual", 1, 12)],
)
def test_billing_frequency(frequency, expected_count, step_months):
    rules = _rules(billing_frequency=frequency, discounts=[])
    entries = generate_timeline(
        rules, 1, 1, window_start=date(2025, 1, 1), window_end=date(2025, 12, 31)
    )
    assert len(entries) == expected_count
    if expected_count > 1:
        assert months_between(entries[0].billing_date, entries[1].billing_date) == step_months


def test_one_time_contract_bills_once():
    rules = _rules(billing_frequency="one_time", discounts=[])
    entries = generate_timeline(rules, 1, 1, horizon_months=12)
    assert len(entries) == 1
    assert entries[0].expected_amount == 6000.0


def test_unknown_frequency_bills_once_rather_than_guessing_monthly():
    """An unreadable extraction must not manufacture eleven ghost invoices."""
    rules = _rules(billing_frequency="unknown", discounts=[])
    entries = generate_timeline(rules, 1, 1, horizon_months=12)
    assert len(entries) == 1


def test_no_start_date_produces_no_timeline():
    assert generate_timeline(_rules(contract_start_date=None), 1, 1) == []


def test_no_base_amount_produces_no_timeline():
    assert generate_timeline(_rules(base_amount=None), 1, 1) == []


# ---------------------------------------------------------------------------
# milestones
# ---------------------------------------------------------------------------


def _with_milestone() -> ContractRules:
    return _rules(
        milestones=[
            Milestone(
                description="Website launch",
                amount=15000.0,
                due_condition="on website launch",
                clause_text="$15,000 payable on launch",
            )
        ]
    )


def test_dated_milestone_joins_the_timeline_in_date_order():
    entries = generate_timeline(
        _with_milestone(), 1, 1, horizon_months=6, milestone_dates={0: date(2025, 4, 10)}
    )
    milestones = [e for e in entries if e.payment_type == "milestone"]
    assert len(milestones) == 1
    assert milestones[0].expected_amount == 15000.0
    assert [e.billing_date for e in entries] == sorted(e.billing_date for e in entries)


def test_undated_milestone_is_left_out_and_reported():
    rules = _with_milestone()
    entries = generate_timeline(rules, 1, 1, horizon_months=6)
    assert all(e.payment_type == "recurring" for e in entries)

    unresolved = unresolved_milestones(rules)
    assert len(unresolved) == 1
    assert unresolved[0][1].description == "Website launch"


def test_milestone_outside_the_window_is_not_billed():
    entries = generate_timeline(
        _with_milestone(), 1, 1, horizon_months=3, milestone_dates={0: date(2026, 9, 1)}
    )
    assert all(e.payment_type == "recurring" for e in entries)


# ---------------------------------------------------------------------------
# clause references — every row must be able to prove itself (ADR-005)
# ---------------------------------------------------------------------------


def test_each_row_cites_the_clause_that_explains_its_amount():
    refs = ClauseRefMap(base_fee=10, escalation=20, discounts={0: 30})
    entries = generate_timeline(_rules(), 1, 1, horizon_months=13, clause_refs=refs)

    assert entries[0].source_clause_ref_id == 30  # discounted month -> discount clause
    assert entries[5].source_clause_ref_id == 10  # plain month -> base fee clause
    assert entries[12].source_clause_ref_id == 20  # escalated month -> escalation clause


def test_missing_clause_refs_degrade_to_none_not_a_crash():
    entries = generate_timeline(_rules(), 1, 1, horizon_months=13)
    assert all(e.source_clause_ref_id is None for e in entries)


def test_notes_state_the_arithmetic_in_words():
    entries = generate_timeline(_rules(), 1, 1, horizon_months=13)
    assert "10% discount active" in entries[0].notes
    assert "5,400.00" in entries[0].notes
    assert "8% escalation applied" in entries[12].notes


# ---------------------------------------------------------------------------
# purity
# ---------------------------------------------------------------------------


def test_rate_for_is_a_pure_counterfactual():
    rules = _rules()
    assert rate_for(rules, date(2025, 1, 1)) == (5400.0, False, 10.0)
    assert rate_for(rules, date(2025, 6, 1)) == (6000.0, False, 0.0)
    assert rate_for(rules, date(2026, 1, 1)) == (6480.0, True, 0.0)


def test_same_inputs_same_output_every_time():
    """No clock, no randomness, no shared state: the timeline generated today
    must equal the one generated a hundred calls later."""
    first = generate_timeline(_rules(), 1, 1, horizon_months=13)
    for _ in range(100):
        assert generate_timeline(_rules(), 1, 1, horizon_months=13) == first
