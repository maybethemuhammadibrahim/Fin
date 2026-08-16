"""[B] Known expected + actuals -> known anomalies, including the zero-anomaly case. Phase 6.

Two halves, matching `core/engine/reconciliation.py`:

* **attribution** — a bank line names a client, or it names nobody. The tests
  that matter most here are the *refusals*: a bank fee must not be attributed to
  the nearest-sounding client, and two similarly named clients must not have a
  payment assigned to whichever scored a point higher.
* **reconciliation** — the four leak types, the clean month, the split payment,
  and the ±15-day boundary.

The zero-anomaly test is the one to keep honest. A detector that never says
"clean" is worthless, and `edge` in `scripts/eval_engine.py` is the same claim
at scenario scale.

Run: `pytest tests/test_reconciliation.py -v`
"""

from __future__ import annotations

from datetime import date

import pytest

from core.ai.schemas import ContractRules, Discount, Escalation, TimelineEntry, TransactionRow
from core.engine.anomaly_classifier import classify, classify_gap
from core.engine.reconciliation import (
    ClientRef,
    attribute_transactions,
    clean_description,
    name_score,
    reconcile,
    reconcile_detail,
)
from core.engine.timeline_generator import generate_timeline

CLIENT_ID = 7
CONTRACT_ID = 3


def _rules(**overrides) -> ContractRules:
    base = dict(
        client_name="Northwind Studio",
        contract_start_date=date(2024, 1, 1),
        contract_end_date=None,
        base_amount=6000.0,
        currency="USD",
        billing_frequency="monthly",
        payment_terms="Net 30",
        escalation=Escalation(percentage=8.0, after_months=12, clause_text="8% on each anniversary"),
        discounts=[],
        milestones=[],
    )
    base.update(overrides)
    return ContractRules(**base)


def _timeline(rules: ContractRules, *, months: int = 12, start=date(2025, 1, 1)):
    entries = generate_timeline(
        rules,
        client_id=CLIENT_ID,
        contract_rule_id=CONTRACT_ID,
        window_start=start,
        window_end=date(start.year, start.month, start.day).replace(year=start.year + 1),
        horizon_months=months,
    )[:months]
    for index, entry in enumerate(entries, start=1):
        entry.id = index
    return entries


def _paid(when: date, amount: float, *, txn_id: int = 1, description: str = "NORTHWIND STUDIO") -> TransactionRow:
    return TransactionRow(
        id=txn_id,
        transaction_date=when,
        amount=amount,
        description=description,
        source_type="bank",
        client_id=CLIENT_ID,
    )


# ---------------------------------------------------------------------------
# attribution
# ---------------------------------------------------------------------------


def test_clean_description_strips_references_and_rails():
    assert clean_description("REGAL ENT GROUP ACH INV-202502") == "REGAL ENT GROUP"
    assert clean_description("CENTRAL GARDEN & PET INV-202503") == "CENTRAL GARDEN & PET"
    assert clean_description(None) == ""


@pytest.mark.parametrize(
    "description, client, floor",
    [
        ("VISION HYDROGEN CORP", "Vision Hydrogen Corp.", 100),
        ("VISIONHYDROGEN CORP WIRE", "Vision Hydrogen Corp.", 85),
        ("REGAL ENT GROUP", "Regal Entertainment Group", 85),  # abbreviation, not a typo
        ("CTRL GARDEN PET CO", "Central Garden & Pet Co.", 85),
        ("GameznFlix", "GameznFlix Inc.", 95),
    ],
)
def test_name_score_recognises_real_bank_variants(description, client, floor):
    assert name_score(description, client) >= floor


def test_bank_noise_is_attributed_to_nobody():
    clients = [ClientRef(1, "Northwind Studio"), ClientRef(2, "Cellteck Inc.")]
    rows = [
        TransactionRow(transaction_date=date(2025, 3, 2), amount=-35.0, description="BANK SVC FEE"),
        TransactionRow(transaction_date=date(2025, 4, 2), amount=4.12, description="INTEREST CREDIT"),
    ]
    assert [a.client_id for a in attribute_transactions(rows, clients)] == [None, None]


def test_two_similar_clients_leave_an_ambiguous_row_unattributed():
    """Guessing here would reconcile one client's money against another's
    contract — the failure that produces confidently wrong findings."""
    clients = [ClientRef(1, "Northwind Design"), ClientRef(2, "Northwind Digital")]
    row = TransactionRow(transaction_date=date(2025, 3, 2), amount=100.0, description="NORTHWIND")
    attribution = attribute_transactions([row], clients)[0]
    assert attribution.client_id is None


def test_an_existing_client_id_is_never_overruled():
    clients = [ClientRef(1, "Northwind Studio"), ClientRef(2, "Cellteck Inc.")]
    row = TransactionRow(
        transaction_date=date(2025, 3, 2), amount=100.0, description="CELLTECK", client_id=1
    )
    attribution = attribute_transactions([row], clients)[0]
    assert attribution.client_id == 1
    assert attribution.score == 100


def test_a_confirmed_alias_matches_exactly():
    clients = [ClientRef(1, "Northwind Studio", aliases=("NW STU HOLDINGS",))]
    row = TransactionRow(transaction_date=date(2025, 3, 2), amount=100.0, description="NW STU HOLDINGS")
    assert attribute_transactions([row], clients)[0].client_id == 1


# ---------------------------------------------------------------------------
# the clean case — the one that proves the engine discriminates
# ---------------------------------------------------------------------------


def test_a_client_who_paid_correctly_produces_zero_anomalies():
    rules = _rules()
    expected = _timeline(rules)
    actuals = [
        _paid(e.billing_date, e.expected_amount, txn_id=i) for i, e in enumerate(expected, start=1)
    ]
    assert reconcile(expected, actuals, rules_by_contract={CONTRACT_ID: rules}) == []


def test_payment_within_one_percent_is_not_an_anomaly():
    """Bank rounding and an FX cent must not become a finding."""
    rules = _rules(escalation=None)
    expected = _timeline(rules, months=1)
    actuals = [_paid(date(2025, 1, 1), 5980.0)]  # $20 light on $6,000
    assert reconcile(expected, actuals, rules_by_contract={CONTRACT_ID: rules}) == []


def test_overpayment_is_not_a_finding():
    rules = _rules()
    expected = _timeline(rules, months=1)
    actuals = [_paid(date(2025, 1, 1), 9000.0)]
    assert reconcile(expected, actuals, rules_by_contract={CONTRACT_ID: rules}) == []


# ---------------------------------------------------------------------------
# the four leak types
# ---------------------------------------------------------------------------


def test_ghost_invoice_when_nothing_arrived():
    rules = _rules(escalation=None)
    expected = _timeline(rules, months=2)
    actuals = [_paid(date(2025, 1, 1), 6000.0)]  # February never paid

    anomalies = reconcile(expected, actuals, rules_by_contract={CONTRACT_ID: rules})
    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "ghost_invoice"
    assert anomalies[0].billing_date == date(2025, 2, 1)
    assert anomalies[0].actual_amount == 0.0
    assert anomalies[0].gap == 6000.0
    assert anomalies[0].actual_transaction_id is None


def test_forgotten_raise_when_the_old_rate_kept_being_billed():
    """Contract started Jan 2024, so Jan 2025 is the anniversary: $6,480 due,
    $6,000 paid, and the $480 gap is the escalation nobody applied."""
    rules = _rules()
    expected = _timeline(rules, months=1)
    assert expected[0].expected_amount == 6480.0

    anomalies = reconcile(expected, [_paid(date(2025, 1, 1), 6000.0)], rules_by_contract={CONTRACT_ID: rules})
    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "forgotten_raise"
    assert anomalies[0].gap == 480.0
    assert anomalies[0].confidence_score >= 0.9


def test_zombie_discount_when_an_expired_discount_is_still_applied():
    rules = _rules(
        escalation=None,
        discounts=[Discount(percentage=30.0, duration_months=12, clause_text="30% for the first year")],
    )
    expected = _timeline(rules, months=1)  # Jan 2025: the discount expired in Dec 2024
    assert expected[0].expected_amount == 6000.0
    assert expected[0].applied_discount_pct == 0.0

    anomalies = reconcile(expected, [_paid(date(2025, 1, 1), 4200.0)], rules_by_contract={CONTRACT_ID: rules})
    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "zombie_discount"
    assert anomalies[0].gap == 1800.0


def test_short_change_when_no_clause_explains_the_gap():
    rules = _rules(escalation=None)
    expected = _timeline(rules, months=1)
    anomalies = reconcile(expected, [_paid(date(2025, 1, 1), 4800.0)], rules_by_contract={CONTRACT_ID: rules})
    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "short_change"
    assert anomalies[0].gap == 1200.0


def test_a_shortfall_is_short_change_when_the_contract_has_no_clauses_at_all():
    """No rules passed: nothing can be attributed to an escalation or a discount,
    so the honest answer is the residual type, not a guess."""
    entry = TimelineEntry(
        id=1,
        client_id=CLIENT_ID,
        contract_rule_id=CONTRACT_ID,
        billing_date=date(2025, 1, 1),
        expected_amount=6000.0,
        payment_type="recurring",
        applied_escalation=False,
        applied_discount_pct=0.0,
        source_clause_ref_id=None,
        notes="",
    )
    anomalies = reconcile([entry], [_paid(date(2025, 1, 1), 5000.0)])
    assert [a.anomaly_type for a in anomalies] == ["short_change"]


# ---------------------------------------------------------------------------
# ADR-006 — aggregation per client-month
# ---------------------------------------------------------------------------


def test_a_split_payment_is_one_finding_not_two():
    """Two partial payments in the same month sum to one shortfall. Matching
    transaction-to-invoice would report the month twice."""
    rules = _rules(escalation=None)
    expected = _timeline(rules, months=1)
    actuals = [
        _paid(date(2025, 1, 3), 3000.0, txn_id=1),
        _paid(date(2025, 1, 18), 1800.0, txn_id=2),
    ]
    anomalies = reconcile(expected, actuals, rules_by_contract={CONTRACT_ID: rules})
    assert len(anomalies) == 1
    assert anomalies[0].actual_amount == 4800.0
    assert anomalies[0].actual_transaction_id == 1  # the larger of the two


def test_a_payment_just_after_month_end_still_answers_that_billing():
    """Billed on 30 January, paid on 3 February: inside the ±15 day tolerance,
    so it is January's money — not a January ghost and a February surplus."""
    rules = _rules(escalation=None, contract_start_date=date(2024, 1, 30))
    expected = _timeline(rules, months=2, start=date(2025, 1, 30))
    actuals = [_paid(date(2025, 2, 3), 6000.0), _paid(date(2025, 3, 2), 6000.0, txn_id=2)]
    assert reconcile(expected, actuals, rules_by_contract={CONTRACT_ID: rules}) == []


def test_one_payment_cannot_settle_two_months():
    """The bug aggregation invites: a payment counted for both the month it
    landed in and the neighbouring billing inside the tolerance window."""
    rules = _rules(escalation=None)
    expected = _timeline(rules, months=2)
    anomalies = reconcile(expected, [_paid(date(2025, 1, 30), 6000.0)], rules_by_contract={CONTRACT_ID: rules})
    assert [a.anomaly_type for a in anomalies] == ["ghost_invoice"]
    # The money settled the billing it followed (1 January); February is the ghost.
    assert anomalies[0].billing_date == date(2025, 2, 1)


def test_transactions_for_an_unknown_client_are_reported_not_dropped():
    rules = _rules(escalation=None)
    expected = _timeline(rules, months=1)
    stray = TransactionRow(transaction_date=date(2025, 1, 5), amount=500.0, description="BANK SVC FEE")
    result = reconcile_detail(
        expected,
        [_paid(date(2025, 1, 1), 6000.0), stray],
        rules_by_contract={CONTRACT_ID: rules},
    )
    assert result.anomalies == []
    assert result.unattributed == [stray]


def test_a_payment_far_outside_every_billing_window_is_unmatched():
    rules = _rules(escalation=None)
    expected = _timeline(rules, months=1)
    stray = _paid(date(2026, 7, 4), 6000.0, txn_id=9)
    result = reconcile_detail(expected, [_paid(date(2025, 1, 1), 6000.0), stray], rules_by_contract={CONTRACT_ID: rules})
    assert result.unmatched == [stray]
    assert result.anomalies == []


# ---------------------------------------------------------------------------
# what every finding must carry
# ---------------------------------------------------------------------------


def test_every_anomaly_carries_confidence_and_inherits_its_clause():
    rules = _rules()
    expected = _timeline(rules, months=3)
    for entry in expected:
        entry.source_clause_ref_id = 42

    result = reconcile_detail(expected, [], rules_by_contract={CONTRACT_ID: rules})
    assert len(result.anomalies) == 3
    for anomaly in result.anomalies:
        assert 0.0 < anomaly.confidence_score <= 1.0
        assert anomaly.clause_reference_id == 42
        assert anomaly.status == "unverified"
        assert anomaly.expected_timeline_id is not None
        assert anomaly.gap == round(anomaly.expected_amount - anomaly.actual_amount, 2)


def test_every_anomaly_comes_with_a_reason_naming_the_figures():
    rules = _rules()
    expected = _timeline(rules, months=1)
    result = reconcile_detail(expected, [_paid(date(2025, 1, 1), 6000.0)], rules_by_contract={CONTRACT_ID: rules})
    reason = result.classifications[0].reason
    assert "8%" in reason and "6,480.00" in reason and "6,000.00" in reason


def test_classify_matches_the_declared_interface():
    rules = _rules()
    entry = _timeline(rules, months=1)[0]
    kind, confidence = classify(entry, _paid(date(2025, 1, 1), 6000.0), rules)
    assert (kind, confidence > 0.5) == ("forgotten_raise", True)
    assert classify(entry, _paid(date(2025, 1, 1), 6480.0), rules) == ("", 0.0)


def test_classify_gap_returns_none_for_a_clean_month():
    rules = _rules()
    entry = _timeline(rules, months=1)[0]
    assert classify_gap(entry, 6480.0, rules) is None
