"""[B] The model's two ends of Phase 9: reading the question, phrasing the answer.

No network and no GPU — `llm_client.complete_json` / `.complete` are
monkeypatched to canned replies, the same shape `test_verification_agent.py`
uses for Phase 8.

**The assertions that matter most are in section 4.** `implementation_plan.md`
says of the explanation: *"if it states a number not in its input, that is a bug
— and it's worth writing an assertion that checks exactly this, because it's the
most likely place in the whole project for a plausible-sounding wrong number to
reach a user."* Those tests are that assertion, and they also prove the runtime
guard rejects such an explanation rather than merely failing CI later.

Run: `pytest tests/test_decision_analyzer.py -v`
"""

from __future__ import annotations

import pytest

from core.ai import decision_analyzer as da
from core.ai import llm_client
from core.engine.cashflow import baseline_from_monthly, evaluate, recovery_from_anomalies

YEAR = {f"2025-{m:02d}": 22500.0 for m in range(1, 13)}


def _result(expenses: float | None = 18000.0, cost: float = 5000.0, confirmed=(1875.0 * 12,)):
    return evaluate(
        baseline_from_monthly(YEAR, monthly_expenses=expenses),
        recovery_from_anomalies(list(confirmed), months_covered=12),
        monthly_cost=cost,
    )


@pytest.fixture()
def no_model(monkeypatch):
    """Every model call fails, as it does whenever no notebook is running."""
    monkeypatch.setattr(llm_client, "complete_json", lambda *a, **k: None)
    monkeypatch.setattr(llm_client, "complete", lambda *a, **k: None)
    monkeypatch.setattr(llm_client, "last_error", lambda: "no endpoint configured")
    monkeypatch.setattr(da.llm_client, "complete_json", lambda *a, **k: None)
    monkeypatch.setattr(da.llm_client, "complete", lambda *a, **k: None)
    monkeypatch.setattr(da.llm_client, "last_error", lambda: "no endpoint configured")


# ---------------------------------------------------------------------------
# 1. The amount is read deterministically, not by the model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Can I afford a $5,000/month senior designer?", 5000.0),
        ("Can I afford a $5,000 per month designer?", 5000.0),
        ("What about 5000 dollars a month?", 5000.0),
        ("Could we spend $12,500 monthly on ads?", 12500.0),
        ("Is £4,200 a month for an office sensible?", 4200.0),
        ("Thinking about $5.5k per month.", 5500.0),
        ("Can we do 8k a month?", 8000.0),
        ("A $1,234,567.89 per month rocket, obviously.", 1234567.89),
    ],
)
def test_extract_cost_reads_the_shapes_people_write(question, expected):
    amount, matched = da.extract_cost(question)
    assert amount == expected
    assert matched, "the matched substring must be quotable back to the user"


def test_a_currency_marked_figure_beats_a_bare_one():
    """"a $5,000 designer starting in 2026" has two numbers; one is money."""
    amount, _ = da.extract_cost("Hire a $5,000/month designer starting in 2026?")
    assert amount == 5000.0


def test_a_bare_year_is_not_read_as_a_price():
    amount, _ = da.extract_cost("Should we hire someone in 2026?")
    assert amount is None, "2026 is a date, not $2,026/month"


def test_a_lone_two_thousand_is_still_money():
    """The year guard must not swallow a genuine amount that happens to look like
    a year when it is the only figure present."""
    amount, _ = da.extract_cost("Can we afford 2000 a month?")
    assert amount == 2000.0


def test_no_amount_at_all_returns_none():
    assert da.extract_cost("Could we take on another developer?") == (None, None)


# ---------------------------------------------------------------------------
# 2. Cadence, and the one division allowed on a user-typed number
# ---------------------------------------------------------------------------


def test_annual_is_detected_and_converted_to_monthly():
    p = da.parse_locally("We're considering $72,000 a year on a bigger office.")
    assert p.cadence == "annual"
    assert p.raw_amount == 72000.0
    assert p.monthly_cost == 6000.0
    assert any("divided by 12" in w for w in p.warnings)


def test_monthly_is_detected_and_left_alone():
    p = da.parse_locally("Can I afford $5,000 per month?")
    assert p.cadence == "monthly"
    assert p.monthly_cost == 5000.0


def test_an_unstated_cadence_is_assumed_monthly_and_said_so():
    p = da.parse_locally("Can I afford a $5,000 designer?")
    assert p.cadence == "monthly"
    assert any("does not say how often" in w for w in p.warnings)


def test_cadence_words_are_not_matched_inside_ordinary_words():
    """"shipment" contains "pm"; that must not read as a monthly cadence."""
    assert da.detect_cadence("What about a $900 shipment?") is None


def test_annual_wins_over_monthly_when_both_words_appear():
    assert da.detect_cadence("$60,000 a year, billed monthly") == "annual"


def test_start_month_is_picked_up_when_stated():
    assert da.parse_locally("Hire in September?").start_month == "September"
    assert da.parse_locally("Hire in 2026-03?").start_month == "2026-03"
    assert da.parse_locally("Hire soon?").start_month is None


# ---------------------------------------------------------------------------
# 3. parse_question — the model enriches, the pattern owns the money
# ---------------------------------------------------------------------------


def test_the_pattern_owns_the_money_even_when_the_model_disagrees(monkeypatch):
    """The failure this prevents: a 3B model reading $5,000 as 50000 flips the
    verdict with nothing on screen looking wrong."""
    monkeypatch.setattr(
        da.llm_client,
        "complete_json",
        lambda *a, **k: da._ParsedFromModel(
            what="a senior designer", monthly_cost=50000.0, cadence="monthly", start_month="September"
        ),
    )
    p = da.parse_question("Can I afford a $5,000/month senior designer starting in September?")
    assert p.monthly_cost == 5000.0, "the user's own figure, not the model's"
    assert p.source == "pattern"
    assert p.needs_confirmation is False
    # but the model's prose IS used
    assert p.what == "a senior designer"
    assert p.start_month == "September"


def test_the_model_supplies_the_amount_only_when_the_pattern_found_none(monkeypatch):
    monkeypatch.setattr(
        da.llm_client,
        "complete_json",
        lambda *a, **k: da._ParsedFromModel(
            what="another developer", monthly_cost=6000.0, cadence="monthly", start_month=None
        ),
    )
    p = da.parse_question("Could we take on another developer?")
    assert p.monthly_cost == 6000.0
    assert p.source == "model"
    assert p.needs_confirmation is True, "a model-supplied figure must be confirmed"
    assert any("read by the model" in w for w in p.warnings)


def test_a_dead_model_still_yields_a_usable_parse(no_model):
    """The page must work with no GPU: the regex reads the amount, cashflow
    computes the verdict, the fallback writes the prose."""
    p = da.parse_question("Can I afford a $5,000/month designer?")
    assert p.monthly_cost == 5000.0
    assert p.source == "pattern"
    assert p.what == "", "no model, so no noun phrase — blank, not invented"
    assert any("pattern matching only" in w for w in p.warnings)


def test_no_amount_and_no_model_reports_that_nothing_can_be_tested(no_model):
    p = da.parse_question("Should we grow the team?")
    assert p.has_cost is False
    assert p.source == "none"


def test_the_model_naming_no_amount_is_respected_not_overridden(monkeypatch):
    """A null from the model is correct and useful; it must not become a guess."""
    monkeypatch.setattr(
        da.llm_client,
        "complete_json",
        lambda *a, **k: da._ParsedFromModel(what="another developer", monthly_cost=None),
    )
    p = da.parse_question("Could we take on another developer?")
    assert p.monthly_cost is None
    assert p.source == "none"


def test_an_empty_question_does_not_call_the_model(monkeypatch):
    called = {"n": 0}

    def spy(*a, **k):
        called["n"] += 1
        return None

    monkeypatch.setattr(da.llm_client, "complete_json", spy)
    da.parse_question("   ")
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# 4. THE GUARD — an explanation may not contain a number it was not given
# ---------------------------------------------------------------------------


def test_a_clean_explanation_is_accepted(monkeypatch):
    res = _result()  # surplus 4500, recovered 1875, corrected 6375, after 1375
    good = (
        "Yes, but the recovered money is what makes it work. Your surplus today is "
        "$4,500.00 a month, and collecting the confirmed findings adds $1,875.00, "
        "lifting you to $6,375.00 and leaving $1,375.00 after the $5,000.00 commitment."
    )
    monkeypatch.setattr(da.llm_client, "complete", lambda *a, **k: good)
    out = da.explain_verdict(res)
    assert out.source == "model"
    assert out.rejected_numbers == []
    assert out.text == good


def test_an_invented_number_is_detected():
    """The plan's own warning, as an assertion. $7,200 is arithmetically plausible
    here and completely wrong."""
    res = _result()
    bad = "Yes — after the hire you would still clear $7,200.00 a month."
    offenders = da.offending_numbers(bad, res)
    assert 7200.0 in offenders


def test_an_invented_number_is_rejected_at_runtime_not_just_in_ci(monkeypatch):
    """The guard is in `explain_verdict`, so a wrong figure never reaches a user —
    it does not merely fail a test somebody runs later."""
    res = _result()
    monkeypatch.setattr(
        da.llm_client, "complete", lambda *a, **k: "You would clear $7,200.00 a month."
    )
    out = da.explain_verdict(res)
    assert out.source == "fallback", "the bad explanation must not be shown"
    assert 7200.0 in out.rejected_numbers
    assert "7,200" not in out.text


def test_a_rejected_explanation_is_retried_once_before_falling_back(monkeypatch):
    res = _result()
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return "You would clear $9,999.00 a month."          # invented
        return f"Yes. After the {da.money(res.monthly_cost)} commitment, {da.money(res.after_decision)} is left."

    monkeypatch.setattr(da.llm_client, "complete", flaky)
    out = da.explain_verdict(res)
    assert calls["n"] == 2
    assert out.source == "model"
    assert 9999.0 in out.rejected_numbers, "the rejected attempt is still reported"


def test_every_figure_the_ui_shows_is_quotable():
    res = _result()
    for value in (22500.0, 18000.0, 4500.0, 1875.0, 5000.0, 6375.0, 1375.0):
        text = f"the figure is {da.money(value)}"
        assert da.offending_numbers(text, res) == [], f"{value} should be allowed"


def test_small_integers_are_allowed_as_english():
    """"the 7 confirmed findings", "over 12 months" — not money, cannot be a wrong
    figure."""
    res = _result()
    assert da.offending_numbers("There are 7 findings over 12 months, in 2 places.", res) == []


def test_a_rounded_percentage_is_allowed_on_a_revenue_basis():
    """A model writing 20.5% or 21% for 20.51% is rounding English, not inventing
    a figure. The percentage is derived from the result rather than hardcoded so
    this test cannot drift out of step with the arithmetic."""
    res = _result(expenses=None)
    assert res.cost_share_of_revenue is not None
    pct = res.cost_share_of_revenue * 100
    for text in (f"that is {pct:.2f}% of revenue", f"that is {pct:.1f}% of revenue", f"that is {pct:.0f}% of revenue"):
        assert da.offending_numbers(text, res) == [], text


def test_a_wrong_percentage_is_still_caught():
    res = _result(expenses=None)
    assert da.offending_numbers("that is 45.90% of revenue", res) == [45.9]


def test_figures_for_omits_what_is_unknown():
    revenue_only = da.figures_for(_result(expenses=None))
    joined = " ".join(revenue_only)
    assert "monthly surplus" not in joined, "cannot quote a surplus that does not exist"
    assert "share of revenue" in joined
    assert "monthly revenue" in joined


# ---------------------------------------------------------------------------
# 5. The fallback prose is always correct, and always available
# ---------------------------------------------------------------------------


def test_fallback_is_used_when_there_is_no_model(no_model):
    out = da.explain_verdict(_result())
    assert out.source == "fallback"
    assert out.text
    assert da.offending_numbers(out.text, _result()) == [], "the fallback must satisfy its own guard"


@pytest.mark.parametrize("expenses,cost", [(18000.0, 5000.0), (21000.0, 5000.0), (None, 5000.0), (10000.0, 1000.0)])
def test_the_fallback_never_quotes_a_figure_it_was_not_given(expenses, cost):
    res = _result(expenses=expenses, cost=cost)
    text = da.fallback_explanation(res)
    assert da.offending_numbers(text, res) == [], text


def test_fallback_says_yes_for_a_yes():
    text = da.fallback_explanation(_result(expenses=18000.0))
    assert text.startswith("Yes")


def test_fallback_says_no_and_names_the_shortfall():
    res = _result(expenses=21000.0)       # surplus 1500, recovered 1875 -> 3375 < 5000
    text = da.fallback_explanation(res)
    assert text.startswith("No")
    assert da.money(abs(res.after_decision)) in text


def test_fallback_on_a_revenue_basis_refuses_a_yes_or_no():
    res = _result(expenses=None)
    text = da.fallback_explanation(res)
    assert "cannot be answered yes or no" in text
    assert "running costs" in text


def test_fallback_uses_the_parsed_noun_phrase_when_there_is_one():
    res = _result()
    parsed = da.ParsedQuestion(
        question="q", what="a senior designer", monthly_cost=5000.0,
        cadence="monthly", start_month=None, source="pattern",
    )
    assert "a senior designer" in da.fallback_explanation(res, parsed)


def test_fallback_on_an_empty_run_explains_the_absence():
    res = evaluate(baseline_from_monthly({}), recovery_from_anomalies([], 0), monthly_cost=5000.0)
    text = da.fallback_explanation(res)
    assert "not enough transaction history" in text
