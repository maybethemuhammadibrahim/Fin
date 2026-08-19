"""Grounding: the checks that stand between a model's output and the database.

There was no test file for `contract_extractor` at all until 2026-08-19, which
meant the two rules the product's credibility rests on — a quote must be in the
document, a rate must be in its quote — had zero automated coverage. The second
rule did not exist; it was written after the base-vs-tuned exam found the tuned
adapter inventing percentages (docs/phase11_results.md).

Every fabrication case below is a real one from that exam, quoted from the real
contract, so the exact failure cannot come back silently.
"""

from __future__ import annotations

from core.ai.contract_extractor import (
    _ground,
    is_absent,
    is_verbatim,
    percentage_in_clause,
)
from core.ai.schemas import ContractRules, Discount, Escalation, Milestone

# --- real clauses from the 20 sealed contracts -------------------------------

AUREUS = (
    "The Monthly Fee shall increase every twelve (12) months (the “Anniversary Date”) "
    "by the greater of i) 3% or ii) a percentage equal to the percentage change in the "
    "Consumer Price Index statistics published by the United States Bureau of Labor."
)
POINDEXTER = (
    "The Management Fee shall be adjusted annually, on each anniversary date of this "
    "Agreement, in accordance with the percentage increase in the Consumer Price Index "
    "for All Urban Consumers, Houston-Galveston-Brazoria, not seasonally adjusted."
)
MARTIN = (
    "The Tank Lease Fee shall be adjusted annually as follows. The Tank Lease Fee shall "
    "be adjusted (both upward and downward as hereinafter provided) by a factor equal to "
    "the increase or decrease, as the case may be, in the Consumer Price Index."
)
PINNACLE = (
    "Effective on January 1, 2004 and on January 1 of each succeeding year, the rate for "
    "meteorology products and services provided hereunder shall be increased by an amount "
    "equal to the percent increase, if any, in the Producer Price Index for finished goods, "
    "but in no event in excess of five percent (5%) and in no event less than zero."
)


def _rules(**kw) -> ContractRules:
    base = dict(
        client_name="Acme Ltd",
        contract_start_date=None,
        contract_end_date=None,
        base_amount=6000.0,
        currency="USD",
        billing_frequency="monthly",
        payment_terms=None,
        escalation=None,
        discounts=[],
        milestones=[],
    )
    base.update(kw)
    return ContractRules(**base)


# --- the rate must be in the sentence it came from ---------------------------


def test_a_rate_written_in_its_clause_survives():
    assert percentage_in_clause(3.0, AUREUS) is True


def test_the_fabrications_the_exam_caught_are_all_refused():
    # Measured 2026-08-19: the tuned adapter claimed each of these, and none of
    # the figures appears anywhere in the contract it was reading.
    assert percentage_in_clause(1.0, POINDEXTER) is False
    assert percentage_in_clause(1.0, MARTIN) is False


def test_a_zero_percent_rise_is_not_a_rise():
    # 5 of the tuned model's 10 false positives were exactly this.
    assert percentage_in_clause(0.0, AUREUS) is False
    assert percentage_in_clause(-2.0, AUREUS) is False
    assert percentage_in_clause(None, AUREUS) is False


def test_a_cap_still_counts_as_written_because_it_is_in_the_text():
    # Pinnacle's 5% is a CEILING, not the rate -- reading that distinction is
    # beyond a verbatim check, and this test records the known limit rather
    # than pretending otherwise. It is in the sentence, so it survives.
    assert percentage_in_clause(5.0, PINNACLE) is True


def test_the_several_ways_a_contract_writes_the_same_figure():
    for text in (
        "Fees increase by 8% each year.",
        "Fees increase by 8 % each year.",
        "Fees increase by 8.0% each year.",
        "Fees increase by 8 percent each year.",
        "Fees increase by 8 per cent each year.",
        "Fees increase by eight percent each year.",
        "Fees increase by eight (8) percent each year.",
    ):
        assert percentage_in_clause(8.0, text) is True, text


def test_a_number_must_be_used_as_a_percentage_not_merely_present():
    # A $3,000 fee must not licence a 3% escalation off the same sentence.
    assert percentage_in_clause(3.0, "Client shall pay $3,000 per month.") is False


def test_a_decimal_rate_matches_itself():
    assert percentage_in_clause(2.5, "an uplift of 2.5% applies") is True
    assert percentage_in_clause(2.5, "an uplift of 3% applies") is False


# --- the quote must be in the document (pre-existing rule, now covered) ------

DOC = "Recitals. " + AUREUS + " Payment is due Net 30."


def test_a_real_quote_is_verbatim():
    assert is_verbatim(AUREUS, DOC) is True


def test_a_paraphrase_is_not_verbatim():
    assert is_verbatim("The fee goes up by three percent every year.", DOC) is False


def test_a_quote_too_short_to_prove_anything_is_refused():
    assert is_verbatim("3%", DOC) is False


def test_absent_is_not_the_same_as_fabricated():
    assert is_absent("null") is True
    assert is_absent("") is True
    assert is_absent(AUREUS) is False


# --- the two rules together, through _ground ---------------------------------


def test_ground_keeps_a_rule_whose_quote_and_rate_are_both_real():
    rules = _rules(escalation=Escalation(percentage=3.0, after_months=12, clause_text=AUREUS))
    out, dropped, grounded, blank, bad_figure = _ground(rules, DOC)
    assert out.escalation is not None
    assert (dropped, blank, bad_figure) == ([], [], [])
    assert grounded == 1


def test_ground_drops_a_real_sentence_carrying_an_invented_rate():
    doc = "Recitals. " + POINDEXTER + " Ends 2030."
    rules = _rules(escalation=Escalation(percentage=1.0, after_months=12, clause_text=POINDEXTER))
    out, dropped, grounded, blank, bad_figure = _ground(rules, doc)
    assert out.escalation is None, "an invented rate must not reach the database"
    assert dropped == [], "the SENTENCE was genuine; it is not a hallucinated quote"
    assert len(bad_figure) == 1
    assert grounded == 1, "grounding still counts the quote: it really is in the document"


def test_ground_applies_the_same_rule_to_discounts():
    doc = "Recitals. A 10% introductory discount applies for the first three months."
    good = Discount(percentage=10.0, duration_months=3,
                    clause_text="A 10% introductory discount applies for the first three months.")
    bad = Discount(percentage=25.0, duration_months=3,
                   clause_text="A 10% introductory discount applies for the first three months.")
    out, _, _, _, bad_figure = _ground(_rules(discounts=[good, bad]), doc)
    assert len(out.discounts) == 1
    assert out.discounts[0].percentage == 10.0
    assert len(bad_figure) == 1


def test_milestones_are_not_rate_checked():
    # A milestone carries an amount, not a rate. Checking a dollar figure
    # against its own sentence is a separate question and is not attempted.
    quote = "A milestone payment of $15,000 is due upon delivery of the final website."
    doc = "Recitals. " + quote
    out, _, _, _, bad_figure = _ground(
        _rules(milestones=[Milestone(description="Launch", amount=15000.0,
                                     due_condition=None, clause_text=quote)]),
        doc,
    )
    assert len(out.milestones) == 1
    assert bad_figure == []
