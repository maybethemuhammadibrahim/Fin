"""[A] The Decision Engine's arithmetic. Phase 9.

Drives the pure functions directly — no database, no model, no clock — the same
way `test_timeline.py` and `test_reconciliation.py` test Phase 6's engine.
`compute_baseline`/`compute_recovery` are the only functions here that read rows
and they do nothing but shape a query result before delegating, so the maths is
covered without a session.

The assertions worth reading first are the honesty ones: that an unknown expense
figure yields `None` rather than `0.0`, that a four-month run is averaged over
four months rather than six, and that the recovered run-rate is divided by the
window the run actually covers rather than a hardcoded 12.

Run: `pytest tests/test_cashflow.py -v`
"""

from __future__ import annotations

from datetime import date

import pytest

from core.engine.cashflow import (
    DEFAULT_HORIZON_MONTHS,
    MIN_MONTHS_FOR_CONFIDENCE,
    apply_scenario,
    baseline_from_monthly,
    evaluate,
    months_spanned,
    recovery_from_anomalies,
)

YEAR_2025 = {f"2025-{m:02d}": 22500.0 for m in range(1, 13)}


# ---------------------------------------------------------------------------
# 1. The baseline
# ---------------------------------------------------------------------------


def test_mean_monthly_revenue_over_the_window():
    b = baseline_from_monthly({"2025-01": 10000.0, "2025-02": 20000.0}, months=6)
    assert b.monthly_revenue == 15000.0
    assert b.months_observed == 2


def test_the_window_takes_the_most_recent_months():
    """A 12-month history with months=3 must read the last three, not the first."""
    history = {f"2025-{m:02d}": float(m * 1000) for m in range(1, 13)}
    b = baseline_from_monthly(history, months=3)
    assert b.months_observed == 3
    assert b.monthly_revenue == pytest.approx((10000 + 11000 + 12000) / 3, abs=0.01)
    assert [k for k, _ in b.revenue_by_month] == ["2025-10", "2025-11", "2025-12"]


def test_a_short_history_is_averaged_over_what_exists_not_over_the_window():
    """The silent-understatement bug this guards against: four months of revenue
    divided by a six-month window reads 33% low, and always in the direction
    that rejects affordable decisions."""
    b = baseline_from_monthly({f"2025-{m:02d}": 12000.0 for m in range(1, 5)}, months=6)
    assert b.months_observed == 4
    assert b.monthly_revenue == 12000.0, "must be the 4-month mean, not total/6"


def test_fewer_than_three_months_is_flagged_low_confidence():
    b = baseline_from_monthly({"2025-01": 5000.0, "2025-02": 5000.0}, months=6)
    assert b.confidence == "low"
    assert str(MIN_MONTHS_FOR_CONFIDENCE) in b.reason
    assert b.monthly_revenue == 5000.0, "still computed — flagged, not withheld"


def test_three_months_is_enough_for_confidence():
    b = baseline_from_monthly({f"2025-{m:02d}": 5000.0 for m in range(1, 4)}, months=6)
    assert b.confidence == "ok"


def test_no_transactions_at_all_is_confidence_none():
    b = baseline_from_monthly({}, months=6)
    assert b.confidence == "none"
    assert b.months_observed == 0
    assert b.monthly_surplus is None


def test_an_interior_zero_month_counts_in_the_mean():
    """A month in which nothing was collected is real data, not a gap to skip."""
    b = baseline_from_monthly({"2025-01": 3000.0, "2025-02": 0.0, "2025-03": 3000.0}, months=6)
    assert b.months_observed == 3
    assert b.monthly_revenue == 2000.0


def test_months_must_be_at_least_one():
    with pytest.raises(ValueError):
        baseline_from_monthly(YEAR_2025, months=0)


# ---------------------------------------------------------------------------
# 2. Unknown expenses stay unknown (ADR-024)
# ---------------------------------------------------------------------------


def test_no_expense_figure_means_surplus_is_none_not_zero():
    """None is "we don't know"; 0.0 is "breaks exactly even". Reporting the second
    when we mean the first is a false statement about someone's business."""
    b = baseline_from_monthly(YEAR_2025)
    assert b.monthly_expenses is None
    assert b.monthly_surplus is None
    assert b.expenses_known is False
    assert b.basis == "revenue"


def test_a_supplied_expense_figure_produces_a_surplus():
    b = baseline_from_monthly(YEAR_2025, monthly_expenses=18000.0)
    assert b.monthly_expenses == 18000.0
    assert b.monthly_surplus == 4500.0
    assert b.expenses_known is True
    assert b.basis == "surplus"


def test_zero_expenses_is_a_real_answer_and_not_treated_as_unknown():
    b = baseline_from_monthly(YEAR_2025, monthly_expenses=0.0)
    assert b.expenses_known is True
    assert b.monthly_surplus == 22500.0


# ---------------------------------------------------------------------------
# 3. Recovery — confirmed only, over the real window
# ---------------------------------------------------------------------------


def test_only_confirmed_gaps_reach_the_monthly_rate():
    r = recovery_from_anomalies(
        confirmed_gaps=[6000.0, 6000.0],
        months_covered=12,
        unverified_gaps=[99999.0],
        false_positive_count=2,
    )
    assert r.confirmed_total == 12000.0
    assert r.monthly == 1000.0
    # reported, so the UI can explain the difference from the dashboard headline
    assert r.unverified_total == 99999.0
    assert r.unverified_count == 1
    assert r.false_positive_count == 2


def test_the_run_rate_uses_the_window_the_run_covers_not_a_hardcoded_twelve():
    """implementation_plan.md writes sum(gap)/12. For a six-month run that halves
    the true run-rate."""
    r = recovery_from_anomalies(confirmed_gaps=[600.0] * 6, months_covered=6)
    assert r.monthly == 600.0, "3600 over 6 months is 600/month, not 300"


def test_zero_months_covered_does_not_divide_by_zero():
    r = recovery_from_anomalies(confirmed_gaps=[500.0], months_covered=0)
    assert r.monthly == 0.0
    assert r.confirmed_total == 500.0


def test_no_confirmed_anomalies_is_zero_recovery():
    r = recovery_from_anomalies(confirmed_gaps=[], months_covered=12, unverified_gaps=[8000.0])
    assert r.confirmed_count == 0
    assert r.monthly == 0.0
    assert r.unverified_total == 8000.0


def test_negative_months_covered_is_rejected():
    with pytest.raises(ValueError):
        recovery_from_anomalies(confirmed_gaps=[1.0], months_covered=-1)


def test_months_spanned_counts_distinct_months_not_elapsed_time():
    """January and December of one year is 2 months of evidence, not 12."""
    assert months_spanned([date(2025, 1, 15), date(2025, 12, 3)]) == 2
    assert months_spanned([date(2025, 3, 1), date(2025, 3, 28)]) == 1
    assert months_spanned([]) == 0
    assert months_spanned([date(2025, 1, 1), date(2026, 1, 1)]) == 2, "same month, different year"


# ---------------------------------------------------------------------------
# 4. The verdict
# ---------------------------------------------------------------------------


def _surplus_baseline(revenue=22500.0, expenses=18000.0):
    return baseline_from_monthly({f"2025-{m:02d}": revenue for m in range(1, 13)}, monthly_expenses=expenses)


def test_the_plan_worked_example_reproduces():
    """The four lines from implementation_plan.md, on its own numbers."""
    b = _surplus_baseline()                     # surplus 4500
    r = recovery_from_anomalies([1875.0 * 12], months_covered=12)   # 1875/month
    res = evaluate(b, r, monthly_cost=5000.0)
    assert res.corrected_surplus == 6375.0      # 4500 + 1875
    assert res.after_decision == 1375.0         # 6375 - 5000
    assert res.verdict == "yes"


def test_affordable_without_recovery_says_so_in_the_rationale():
    b = _surplus_baseline(expenses=10000.0)     # surplus 12500
    r = recovery_from_anomalies([1200.0], months_covered=12)
    res = evaluate(b, r, monthly_cost=5000.0)
    assert res.verdict == "yes"
    assert "widens the margin" in res.rationale


def test_affordable_only_because_of_recovery_says_that_instead():
    b = _surplus_baseline(expenses=18000.0)     # surplus 4500
    r = recovery_from_anomalies([12000.0], months_covered=12)  # 1000/month
    res = evaluate(b, r, monthly_cost=5000.0)
    assert res.verdict == "yes"
    assert res.after_decision == 500.0
    assert "only once the confirmed leaks are recovered" in res.rationale


def test_unaffordable_even_with_recovery_is_a_no():
    b = _surplus_baseline(expenses=21000.0)     # surplus 1500
    r = recovery_from_anomalies([1200.0], months_covered=12)   # 100/month
    res = evaluate(b, r, monthly_cost=5000.0)
    assert res.verdict == "no"
    assert res.after_decision == -3400.0
    assert "does not cover the commitment" in res.rationale


def test_exactly_break_even_is_not_a_yes():
    """after_decision == 0 leaves nothing over; the plan's rule is `> 0`."""
    b = _surplus_baseline(expenses=18000.0)     # surplus 4500
    r = recovery_from_anomalies([6000.0], months_covered=12)   # 500/month
    res = evaluate(b, r, monthly_cost=5000.0)
    assert res.after_decision == 0.0
    assert res.verdict == "no"


def test_unknown_expenses_yields_unknown_verdict_and_a_revenue_share():
    """The whole point of ADR-024: no invented surplus, but still a useful answer."""
    b = baseline_from_monthly(YEAR_2025)        # no expenses
    r = recovery_from_anomalies([12000.0], months_covered=12)   # 1000/month
    res = evaluate(b, r, monthly_cost=5000.0)
    assert res.verdict == "unknown"
    assert res.corrected_surplus is None
    assert res.after_decision is None
    # 5000 / (22500 + 1000)
    assert res.cost_share_of_revenue == pytest.approx(0.2128, abs=0.0001)
    assert "no affordability verdict is possible" in res.rationale


def test_an_empty_run_is_unknown_with_no_projection():
    res = evaluate(baseline_from_monthly({}), recovery_from_anomalies([], 0), monthly_cost=5000.0)
    assert res.verdict == "unknown"
    assert res.projection == ()
    assert "no transactions" in res.rationale.lower()


def test_a_negative_cost_is_rejected():
    with pytest.raises(ValueError):
        evaluate(_surplus_baseline(), recovery_from_anomalies([], 12), monthly_cost=-1.0)


def test_a_zero_horizon_is_rejected():
    with pytest.raises(ValueError):
        evaluate(_surplus_baseline(), recovery_from_anomalies([], 12), monthly_cost=1.0, horizon=0)


# ---------------------------------------------------------------------------
# 5. The projection
# ---------------------------------------------------------------------------


def test_projection_is_cumulative_and_two_series():
    b = _surplus_baseline(expenses=18000.0)     # surplus 4500
    r = recovery_from_anomalies([12000.0], months_covered=12)   # 1000/month
    res = evaluate(b, r, monthly_cost=4000.0)
    assert len(res.projection) == DEFAULT_HORIZON_MONTHS
    label, without, with_ = res.projection[0]
    assert label == "M1"
    assert without == 500.0                      # 4500 - 4000
    assert with_ == 1500.0                       # 5500 - 4000
    # and it accumulates
    assert res.projection[1][1] == 1000.0
    assert res.projection[-1][2] == 1500.0 * DEFAULT_HORIZON_MONTHS


def test_projection_labels_carry_no_calendar_month():
    """The engine takes no clock (the Phase 6 rule). M1..Mn, never "September"."""
    res = evaluate(_surplus_baseline(), recovery_from_anomalies([], 12), monthly_cost=100.0)
    assert [lbl for lbl, _, _ in res.projection] == [f"M{i}" for i in range(1, 13)]


def test_horizon_is_respected():
    res = evaluate(_surplus_baseline(), recovery_from_anomalies([], 12), monthly_cost=100.0, horizon=6)
    assert len(res.projection) == 6


def test_same_inputs_same_output_every_time():
    b = _surplus_baseline()
    r = recovery_from_anomalies([12000.0], months_covered=12)
    assert evaluate(b, r, 5000.0) == evaluate(b, r, 5000.0)


# ---------------------------------------------------------------------------
# 6. apply_scenario keeps the interfaces.md signature working
# ---------------------------------------------------------------------------


def test_apply_scenario_matches_evaluate_for_the_same_monthly_rate():
    b = _surplus_baseline()
    viaapply = apply_scenario(b, monthly_cost=5000.0, recovered_monthly=1875.0)
    via_eval = evaluate(b, recovery_from_anomalies([1875.0 * 12], 12), monthly_cost=5000.0)
    assert viaapply.after_decision == via_eval.after_decision
    assert viaapply.verdict == via_eval.verdict


def test_apply_scenario_supports_a_counterfactual_recovery_rate():
    """"What if only half of these hold up?" without rebuilding a baseline."""
    b = _surplus_baseline(expenses=18000.0)
    full = apply_scenario(b, monthly_cost=5000.0, recovered_monthly=1000.0)
    half = apply_scenario(b, monthly_cost=5000.0, recovered_monthly=500.0)
    assert full.after_decision == 500.0
    assert half.after_decision == 0.0
    assert full.verdict == "yes" and half.verdict == "no"


# ---------------------------------------------------------------------------
# 7. allowed_figures — the contract the explanation is checked against
# ---------------------------------------------------------------------------


def test_allowed_figures_contains_every_figure_the_ui_shows():
    b = _surplus_baseline()
    r = recovery_from_anomalies([1875.0 * 12], months_covered=12)
    res = evaluate(b, r, monthly_cost=5000.0)
    allowed = res.allowed_figures()
    for value in (22500.0, 18000.0, 4500.0, 1875.0, 5000.0, 6375.0, 1375.0):
        assert value in allowed, f"{value} must be quotable in an explanation"


def test_allowed_figures_excludes_a_plausible_invention():
    res = evaluate(_surplus_baseline(), recovery_from_anomalies([1875.0 * 12], 12), monthly_cost=5000.0)
    # a number that looks like it belongs but is arithmetically wrong
    assert 1975.0 not in res.allowed_figures()


def test_allowed_figures_omits_none_valued_fields_on_a_revenue_basis():
    res = evaluate(baseline_from_monthly(YEAR_2025), recovery_from_anomalies([], 12), monthly_cost=5000.0)
    allowed = res.allowed_figures()
    assert 22500.0 in allowed
    assert None not in allowed  # type: ignore[comparison-overlap]
