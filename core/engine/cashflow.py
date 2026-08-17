"""[A] Pure math: cash-flow baseline and scenario projection. Phase 9.

Every number the Decision Engine shows a user is computed here. `core/ai/
decision_analyzer.py` reads the question and phrases the answer; it never does
arithmetic, and it is handed a `ScenarioResult` it may only describe. That split
is the load-bearing rule in `CLAUDE.md` and the reason this module exists apart
from the analyser at all.

**The database read is deliberately quarantined into one function.**
`compute_baseline(session, ...)` is the only thing here that touches I/O, and it
does nothing but turn rows into a `{month: revenue}` dict before handing off to
`baseline_from_monthly`, which is pure. Every assertion in
`tests/test_cashflow.py` drives the pure functions directly, so the maths is
tested without a database — the same shape Phase 6 used for `pipeline.py` versus
the engine proper.

**What this module refuses to do.**

*Invent an expense.* No table in the schema holds operating costs
(`actual_transactions` is client receipts: `source_type` is `invoice|bank` and
amounts are unsigned), so a true surplus is not derivable from the database.
ADR-024 records the decision: monthly costs are supplied by the caller, from a
number the user typed, and when nobody supplies one this module reports
`expenses_known=False` and refuses to name a surplus. A confident
`monthly_surplus` computed against an assumed expense figure would be the exact
class of plausible-but-wrong number the whole architecture is arranged to
prevent — and unlike a wrong clause box, nobody could see it was wrong.

*Divide by a window it did not measure.* `implementation_plan.md` writes
`recovered_monthly = sum(gap) / 12`. That is right only for a run whose findings
span a year. `recovery_from_anomalies` divides by the number of months the run's
own billings actually cover, so a six-month run reads as a six-month run. The
hardcoded 12 is recorded as a plan-vs-code difference in `docs/progress.md`
rather than silently reproduced.

*Project confidently from thin data.* Fewer than `MIN_MONTHS_FOR_CONFIDENCE`
months of revenue returns `confidence="low"` with a reason, and no months at all
returns `confidence="none"`. The caller must render that, not average it away.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

#: Below this many distinct months of revenue, a projection is a guess dressed
#: as a trend. Three is the plan's own threshold ("fewer than three months ->
#: return a low-confidence flag rather than a confident projection").
MIN_MONTHS_FOR_CONFIDENCE = 3

#: How far `project` runs by default. Twelve months is what the Page 2 mockup
#: draws and what makes an annual commitment legible.
DEFAULT_HORIZON_MONTHS = 12

Confidence = Literal["ok", "low", "none"]
Verdict = Literal["yes", "no", "unknown"]


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CashFlowBaseline:
    """What the business earns per month before any decision is applied.

    `monthly_surplus` is `None` — not 0.0 — when no expense figure was supplied.
    None means "unknown"; 0.0 would mean "breaks exactly even", which is a
    completely different statement to make about someone's business.
    """

    months_observed: int
    monthly_revenue: float
    monthly_expenses: float | None
    monthly_surplus: float | None
    confidence: Confidence
    reason: str
    #: Oldest first, for the chart and for anyone checking the mean by hand.
    revenue_by_month: tuple[tuple[str, float], ...] = ()

    @property
    def expenses_known(self) -> bool:
        return self.monthly_expenses is not None

    @property
    def basis(self) -> Literal["surplus", "revenue"]:
        """Which claim the caller is entitled to make from this baseline."""
        return "surplus" if self.expenses_known else "revenue"


@dataclass(frozen=True)
class Recovery:
    """Money the run proved is owed, expressed as a monthly run-rate.

    Only `confirmed` anomalies are counted. Phase 8's verification agent exists
    so that this number is trustworthy; counting `unverified` rows would make
    the Decision Engine's answer depend on findings nobody has checked, and
    counting `false_positive` rows would be simply wrong.
    """

    confirmed_count: int
    confirmed_total: float
    months_covered: int
    monthly: float
    #: Rows that exist but were not counted, so the UI can say why the number is
    #: smaller than the dashboard's headline total.
    unverified_count: int = 0
    unverified_total: float = 0.0
    false_positive_count: int = 0


@dataclass(frozen=True)
class ScenarioResult:
    """The finished arithmetic. `decision_analyzer.explain_verdict` may phrase
    only what is on this object, and `tests/test_decision_analyzer.py` asserts
    that every numeral in the explanation appears in `allowed_figures()`."""

    baseline: CashFlowBaseline
    recovery: Recovery
    monthly_cost: float

    #: baseline.monthly_surplus + recovery.monthly, or None when expenses are
    #: unknown (you cannot correct a surplus you never had).
    corrected_surplus: float | None
    #: corrected_surplus - monthly_cost. None when expenses are unknown.
    after_decision: float | None

    verdict: Verdict
    #: Why the verdict is what it is, in one clause, for the UI to show *and*
    #: for the model to be given as grounding.
    rationale: str

    #: Cumulative position over the horizon, oldest first: (label, without, with)
    projection: tuple[tuple[str, float, float], ...] = ()

    #: Only meaningful on a revenue basis: the commitment as a share of corrected
    #: monthly revenue. The honest thing to report when a surplus is unknowable.
    cost_share_of_revenue: float | None = None

    def allowed_figures(self) -> set[float]:
        """Every number the explanation is permitted to contain.

        The guard behind the plan's own warning: *"if it states a number not in
        its input, that is a bug"*. Rounded to 2dp because that is the boundary
        precision the conventions in `docs/interfaces.md` fix for money.
        """
        values: list[float | None] = [
            self.baseline.monthly_revenue,
            self.baseline.monthly_expenses,
            self.baseline.monthly_surplus,
            self.recovery.confirmed_total,
            self.recovery.monthly,
            float(self.recovery.confirmed_count),
            float(self.recovery.months_covered),
            float(self.baseline.months_observed),
            self.monthly_cost,
            self.corrected_surplus,
            self.after_decision,
        ]
        if self.cost_share_of_revenue is not None:
            # both the fraction and the percentage reading of it
            values.append(self.cost_share_of_revenue)
            values.append(round(self.cost_share_of_revenue * 100, 2))
        out = {round(float(v), 2) for v in values if v is not None}
        # A sentence may legitimately name the annualised commitment or recovery.
        out.add(round(self.monthly_cost * 12, 2))
        out.add(round(self.recovery.monthly * 12, 2))
        # English states a deficit as a positive quantity — "the shortfall is
        # $1,625" for an after_decision of -1625.00 — so the magnitude of every
        # signed figure is quotable too. Without this the honest fallback prose
        # failed its own guard.
        out |= {abs(v) for v in list(out)}
        return out


# ---------------------------------------------------------------------------
# Pure arithmetic — no session, no clock, no I/O
# ---------------------------------------------------------------------------


def baseline_from_monthly(
    revenue_by_month: dict[str, float],
    monthly_expenses: float | None = None,
    months: int = 6,
) -> CashFlowBaseline:
    """Mean monthly revenue over the most recent `months` observed months.

    Averages over the months that *exist*, never over `months` — a run holding
    four months of data reports a four-month mean flagged `low`, rather than
    dividing four months of revenue by six and reporting a number 33% too small.
    That failure mode is silent and always understates, which would make the
    Decision Engine reject affordable decisions.
    """
    if months < 1:
        raise ValueError("months must be at least 1")

    ordered = sorted(revenue_by_month.items())
    # Drop months with no money in them only at the ends: an interior zero is a
    # real month in which nothing was collected and belongs in the mean.
    window = ordered[-months:]

    if not window:
        return CashFlowBaseline(
            months_observed=0,
            monthly_revenue=0.0,
            monthly_expenses=_round_or_none(monthly_expenses),
            monthly_surplus=None,
            confidence="none",
            reason="No transactions in this run, so there is no revenue history to project from.",
            revenue_by_month=(),
        )

    observed = len(window)
    total = sum(float(v) for _, v in window)
    revenue = round(total / observed, 2)

    expenses = _round_or_none(monthly_expenses)
    surplus = round(revenue - expenses, 2) if expenses is not None else None

    if observed < MIN_MONTHS_FOR_CONFIDENCE:
        confidence: Confidence = "low"
        reason = (
            f"Only {observed} month(s) of transactions in this run — fewer than the "
            f"{MIN_MONTHS_FOR_CONFIDENCE} needed before an average reads as a trend. "
            f"Treat the projection as indicative."
        )
    else:
        confidence = "ok"
        reason = f"Averaged over {observed} month(s) of real transactions."

    return CashFlowBaseline(
        months_observed=observed,
        monthly_revenue=revenue,
        monthly_expenses=expenses,
        monthly_surplus=surplus,
        confidence=confidence,
        reason=reason,
        revenue_by_month=tuple((k, round(float(v), 2)) for k, v in window),
    )


def recovery_from_anomalies(
    confirmed_gaps: list[float],
    months_covered: int,
    unverified_gaps: list[float] | None = None,
    false_positive_count: int = 0,
) -> Recovery:
    """Confirmed leakage as a monthly run-rate.

    `months_covered` is the span the run's findings actually cover, **not** a
    hardcoded 12 — see this module's docstring. A `months_covered` of 0 yields a
    monthly rate of 0.0 rather than a division error; the caller shows the total
    and says the run-rate is unknown.
    """
    if months_covered < 0:
        raise ValueError("months_covered cannot be negative")

    unverified = unverified_gaps or []
    total = round(sum(float(g) for g in confirmed_gaps), 2)
    monthly = round(total / months_covered, 2) if months_covered else 0.0

    return Recovery(
        confirmed_count=len(confirmed_gaps),
        confirmed_total=total,
        months_covered=months_covered,
        monthly=monthly,
        unverified_count=len(unverified),
        unverified_total=round(sum(float(g) for g in unverified), 2),
        false_positive_count=false_positive_count,
    )


def apply_scenario(
    baseline: CashFlowBaseline,
    monthly_cost: float,
    recovered_monthly: float,
    horizon: int = DEFAULT_HORIZON_MONTHS,
) -> ScenarioResult:
    """The four lines from the plan, plus an honest answer when a surplus is unknown.

        corrected_surplus = current_surplus + recovered_monthly
        after_decision    = corrected_surplus - monthly_cost
        verdict           = YES if after_decision > 0 else NO

    Signature kept as `docs/interfaces.md` declares it (baseline, monthly_cost,
    recovered_monthly). `recovered_monthly` is passed in rather than read off the
    baseline so a caller can ask counterfactuals — "what if only half of these
    hold up?" — without rebuilding a baseline.
    """
    return _scenario(
        baseline,
        Recovery(
            confirmed_count=0,
            confirmed_total=round(recovered_monthly * max(baseline.months_observed, 1), 2),
            months_covered=max(baseline.months_observed, 1),
            monthly=round(float(recovered_monthly), 2),
        ),
        monthly_cost,
        horizon,
    )


def evaluate(
    baseline: CashFlowBaseline,
    recovery: Recovery,
    monthly_cost: float,
    horizon: int = DEFAULT_HORIZON_MONTHS,
) -> ScenarioResult:
    """`apply_scenario` with the real `Recovery` kept intact.

    The richer entry point the UI actually calls: it preserves the confirmed /
    unverified / false-positive counts so the page can explain *why* the
    recovered figure is what it is. `apply_scenario` remains as
    `interfaces.md` declares it.
    """
    return _scenario(baseline, recovery, monthly_cost, horizon)


def _scenario(
    baseline: CashFlowBaseline,
    recovery: Recovery,
    monthly_cost: float,
    horizon: int,
) -> ScenarioResult:
    if monthly_cost < 0:
        raise ValueError("monthly_cost cannot be negative")
    if horizon < 1:
        raise ValueError("horizon must be at least 1 month")

    cost = round(float(monthly_cost), 2)
    recovered = recovery.monthly

    if baseline.confidence == "none":
        return ScenarioResult(
            baseline=baseline,
            recovery=recovery,
            monthly_cost=cost,
            corrected_surplus=None,
            after_decision=None,
            verdict="unknown",
            rationale=(
                "There are no transactions in this run, so there is no cash-flow "
                "history to judge the decision against."
            ),
            projection=(),
            cost_share_of_revenue=None,
        )

    corrected_revenue = round(baseline.monthly_revenue + recovered, 2)

    if not baseline.expenses_known:
        # The honest answer: report the commitment against revenue, and refuse a
        # Yes/No that would pretend to know what the business spends (ADR-024).
        share = round(cost / corrected_revenue, 4) if corrected_revenue else None
        return ScenarioResult(
            baseline=baseline,
            recovery=recovery,
            monthly_cost=cost,
            corrected_surplus=None,
            after_decision=None,
            verdict="unknown",
            rationale=(
                "No monthly operating costs were supplied, so a surplus cannot be "
                "computed and no affordability verdict is possible. What can be said "
                "is what the commitment costs as a share of monthly revenue."
            ),
            projection=_project(corrected_revenue, baseline.monthly_revenue, cost, horizon, revenue_basis=True),
            cost_share_of_revenue=share,
        )

    assert baseline.monthly_surplus is not None  # implied by expenses_known
    corrected_surplus = round(baseline.monthly_surplus + recovered, 2)
    after = round(corrected_surplus - cost, 2)

    if after > 0:
        verdict: Verdict = "yes"
        without = round(baseline.monthly_surplus - cost, 2)
        if without > 0:
            rationale = (
                "The current surplus already covers the commitment; recovering the "
                "confirmed leaks widens the margin rather than creating it."
            )
        else:
            rationale = (
                "The commitment is affordable only once the confirmed leaks are "
                "recovered — the current surplus alone does not cover it."
            )
    else:
        verdict = "no"
        rationale = (
            "Even with every confirmed leak recovered, the monthly surplus does not "
            "cover the commitment."
        )

    return ScenarioResult(
        baseline=baseline,
        recovery=recovery,
        monthly_cost=cost,
        corrected_surplus=corrected_surplus,
        after_decision=after,
        verdict=verdict,
        rationale=rationale,
        projection=_project(corrected_surplus, baseline.monthly_surplus, cost, horizon, revenue_basis=False),
        cost_share_of_revenue=round(cost / corrected_revenue, 4) if corrected_revenue else None,
    )


def _project(
    with_recovery_monthly: float,
    without_recovery_monthly: float,
    monthly_cost: float,
    horizon: int,
    *,
    revenue_basis: bool,
) -> tuple[tuple[str, float, float], ...]:
    """Cumulative position month by month, two series.

    Labels are `M1..Mn`, not calendar months: this module takes **no clock**
    (the same rule Phase 6's engine follows), so it cannot know what month it is
    and will not pretend. The caller labels them if it wants real month names.
    """
    rows = []
    running_without = 0.0
    running_with = 0.0
    for i in range(1, horizon + 1):
        running_without += without_recovery_monthly - monthly_cost
        running_with += with_recovery_monthly - monthly_cost
        rows.append((f"M{i}", round(running_without, 2), round(running_with, 2)))
    return tuple(rows)


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def months_spanned(dates: list[date]) -> int:
    """How many distinct calendar months a set of dates touches.

    Distinct months rather than end-minus-start, because a run whose billings
    land in January and December of the same year covers 2 months of *evidence*,
    not 12 — dividing its leakage by 12 would understate the run-rate sixfold.
    """
    return len({(d.year, d.month) for d in dates if d is not None})


# ---------------------------------------------------------------------------
# The one function here that reads the database
# ---------------------------------------------------------------------------


def compute_baseline(
    session: "Session",
    run_id: int,
    months: int = 6,
    monthly_expenses: float | None = None,
) -> CashFlowBaseline:
    """Baseline for a run, straight from `actual_transactions`.

    Signature extends `docs/interfaces.md`'s declaration with `monthly_expenses`,
    which the interface could not have anticipated: the plan assumed an expense
    source existed in the schema and none does (ADR-024). Passing `None` — the
    default — yields a revenue-only baseline that refuses to name a surplus.
    """
    from core.db.queries import revenue_by_month

    return baseline_from_monthly(
        revenue_by_month(session, run_id),
        monthly_expenses=monthly_expenses,
        months=months,
    )


def compute_recovery(session: "Session", run_id: int) -> Recovery:
    """Confirmed leakage for a run, as a monthly run-rate.

    Reads `anomalies` and derives the window from `expected_timeline`'s own
    billing dates, so the run-rate is divided by the months the run actually
    covers rather than a hardcoded 12.
    """
    from sqlalchemy import select

    from core.db.models import Anomaly, ExpectedTimeline

    rows = list(
        session.execute(
            select(Anomaly.status, Anomaly.gap).where(Anomaly.run_id == run_id)
        )
    )
    confirmed = [float(g or 0.0) for status, g in rows if status == "confirmed"]
    unverified = [float(g or 0.0) for status, g in rows if status == "unverified"]
    false_positives = sum(1 for status, _ in rows if status == "false_positive")

    billing_dates = [
        d
        for (d,) in session.execute(
            select(ExpectedTimeline.billing_date).where(ExpectedTimeline.run_id == run_id)
        )
        if d is not None
    ]

    return recovery_from_anomalies(
        confirmed_gaps=confirmed,
        months_covered=months_spanned(billing_dates),
        unverified_gaps=unverified,
        false_positive_count=false_positives,
    )
