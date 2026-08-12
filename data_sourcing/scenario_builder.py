"""[B] Derive actuals from true contract rules and plant known anomalies. Phase 3.

The heart of Phase 3 (ADR-007): contracts are SOURCED (real filings, hand-picked from
data/corpus/contracts/ — see filter_contracts.py), actuals are DERIVED by arithmetic
over hand-verified `ContractRules` — never invented, never scored by a model. That is
what gives Phase 11 a real precision/recall number instead of an eyeballed one.

`expected_row()` is a deliberately small, PRIVATE duplicate of what Phase 6's
core/engine/timeline_generator.py will formalize. Phase 3 runs before Phase 6 exists
(ADR-008's top-down build order) and this file does not own core/engine/ — the same
pattern scripts/seed_demo.py used for Phase 2's demo run (`_expected_amount`).

**What is real vs. what is scenario-assigned.** For every client below, the recurring
fee, the escalation percentage, the escalation trigger ("after 12 months" / "on each
anniversary"), the discount percentage and its duration, and the clause text are all
copied verbatim from a real EDGAR filing in data/corpus/contracts/ (hand-read once, by
a person, not a model — see TrueRule below; two clients' figures were inserted by
filter_contracts.fill_document under ADR-014 and are marked `filled_by_adr014=True`).
What is scenario-assigned is the CALENDAR: which real month a contract's genuinely
annual escalation or discount-expiry lands on, chosen so the twelve-month observation
window (2025) contains a demoable before/after cutover, exactly as scripts/seed_demo.py
did for Phase 2. This is arithmetic construction of a timeline, not invention of a
contract term (ADR-007's actual distinction).
"""

from __future__ import annotations

import csv
import json
import random
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from core.ai.schemas import ContractRules, Discount, Escalation

SCENARIOS_DIR = Path("data/scenarios")
CORPUS_DIR = Path("data/corpus/contracts")
OBSERVATION_YEAR = 2025


# ---------------------------------------------------------------------------
# Hand-verified facts about one real, sourced contract.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrueRule:
    client_name: str
    source_contract: Path  # under data/corpus/contracts/{ready,filled}/
    filled_by_adr014: bool  # True when the number was inserted by fill_document, not read
    base_amount: float
    base_fee_clause: str
    contract_start: date  # scenario-assigned calendar anchor; see module docstring
    payment_terms: str | None
    escalation_pct: float | None = None
    escalation_after_months: int | None = None
    escalation_clause: str | None = None
    discount_pct: float | None = None
    discount_duration_months: int | None = None
    discount_clause: str | None = None


def to_contract_rules(rule: TrueRule) -> ContractRules:
    return ContractRules(
        client_name=rule.client_name,
        contract_start_date=rule.contract_start,
        contract_end_date=None,
        base_amount=rule.base_amount,
        currency="USD",
        billing_frequency="monthly",
        payment_terms=rule.payment_terms,
        escalation=(
            Escalation(
                percentage=rule.escalation_pct,
                after_months=rule.escalation_after_months,
                clause_text=rule.escalation_clause,
            )
            if rule.escalation_pct is not None
            else None
        ),
        discounts=(
            [
                Discount(
                    percentage=rule.discount_pct,
                    duration_months=rule.discount_duration_months,
                    clause_text=rule.discount_clause,
                )
            ]
            if rule.discount_pct is not None
            else []
        ),
        milestones=[],
    )


def _months_between(start: date, when: date) -> int:
    return (when.year - start.year) * 12 + (when.month - start.month)


def expected_row(rules: ContractRules, month_date: date) -> tuple[float, bool, float]:
    """(amount, applied_escalation, applied_discount_pct) for one billing month. PURE.

    Escalation applies once contract_start_date + escalation.after_months has elapsed.
    A discount applies only within its duration_months window from contract_start —
    which is exactly what makes a discount still being paid after that window a
    zombie_discount leak: `expected_row` will already say the discount should be gone.
    """
    amount = rules.base_amount or 0.0
    escalated = False
    if rules.escalation and rules.contract_start_date:
        if _months_between(rules.contract_start_date, month_date) >= rules.escalation.after_months:
            amount = round(amount * (1 + rules.escalation.percentage / 100), 2)
            escalated = True
    discount_pct = 0.0
    for d in rules.discounts:
        if rules.contract_start_date and _months_between(rules.contract_start_date, month_date) < d.duration_months:
            amount = round(amount * (1 - d.percentage / 100), 2)
            discount_pct = d.percentage
    return amount, escalated, discount_pct


# ---------------------------------------------------------------------------
# Planting: which months get broken, and how.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Plant:
    months: tuple[int, ...]  # 1-12
    anomaly_type: str  # one of core.db.models.ANOMALY_TYPES
    split_payment: bool = False  # short_change delivered as two partial transactions


@dataclass
class ClientScenario:
    rule: TrueRule
    plant: Plant | None  # None = clean control client
    name_variants: list[str] = field(default_factory=list)  # noisy scenarios only


@dataclass
class ScenarioManifest:
    name: str
    out_dir: str
    n_clients: int
    n_leaking_clients: int
    n_anomalies: int
    total_gap: float
    anomaly_types: dict[str, int]
    contracts: list[str]


# ---------------------------------------------------------------------------
# Noise generators (realistic scenario only).
# ---------------------------------------------------------------------------

_UNRELATED_NOISE = [
    ("BANK SVC FEE", -35.0),
    ("WIRE TRANSFER FEE", -25.0),
    ("INTEREST CREDIT", 4.12),
    ("MISC CREDIT ADJ", 150.0),
    ("CHECK #1042 DEPOSIT", 900.0),
]


def _jittered_date(billing_date: date, rng: random.Random) -> date:
    """A few days after billing_date -- real payments never land exactly on it."""
    return billing_date + timedelta(days=rng.randint(1, 6))


def _name_variant(name: str, month: int, variants: list[str]) -> str:
    if not variants:
        return name.upper()
    return variants[month % len(variants)]


# ---------------------------------------------------------------------------
# The builder.
# ---------------------------------------------------------------------------


def build_scenario(
    contract_paths: list[Path],
    rules: list[ContractRules],
    plant: list[str | None],
    out_dir: str,
    *,
    clients: list[ClientScenario] | None = None,
    noisy: bool = False,
    seed: int = 20260810,
) -> ScenarioManifest:
    """Derives actuals from TRUE rules, then plants the named anomaly types.
    Writes contracts/ (copies of the sourced files) + actuals.csv + ground_truth.json +
    manifest.json into `out_dir`.

    `contract_paths`, `rules`, `plant` are the plan's documented positional signature
    (docs/interfaces.md); `clients` carries the richer per-client detail (which months,
    split payments, name variants) this module's callers actually need — when given, it
    takes precedence and the first three positional lists are used only for the
    manifest's contract listing.
    """
    rng = random.Random(seed)
    out = SCENARIOS_DIR / out_dir
    contracts_out = out / "contracts"
    if out.exists():
        shutil.rmtree(out)
    contracts_out.mkdir(parents=True)

    ground_truth: dict = {"scenario": out_dir, "observation_year": OBSERVATION_YEAR, "clients": []}
    actual_rows: list[tuple[date, str, float]] = []
    n_anomalies = 0
    total_gap = 0.0
    by_type: dict[str, int] = {}
    n_leaking = 0

    if clients is None:
        raise ValueError("build_scenario requires `clients` (see _easy/_realistic/_edge below)")
    cs_list = clients

    for cs in cs_list:
        rule = cs.rule
        cr = to_contract_rules(rule)
        shutil.copy2(rule.source_contract, contracts_out / rule.source_contract.name)

        planted_months = set(cs.plant.months) if cs.plant else set()
        client_timeline = []
        client_gap = 0.0
        client_anomalies = 0

        for month in range(1, 13):
            billing_date = date(OBSERVATION_YEAR, month, 1)
            expected_amount, escalated, discount_pct = expected_row(cr, billing_date)

            is_planted = month in planted_months
            anomaly_type = cs.plant.anomaly_type if is_planted else None
            actual_amount = expected_amount
            actual_txns: list[tuple[date, float]] = []

            if not is_planted:
                actual_txns = [(_jittered_date(billing_date, rng) if noisy else billing_date, expected_amount)]
            elif anomaly_type == "ghost_invoice":
                actual_amount = 0.0
                actual_txns = []
            elif anomaly_type == "forgotten_raise":
                # Billed at the pre-escalation rate, as if nobody applied the increase.
                pre_escalation = round((rule.base_amount or 0.0), 2)
                actual_amount = pre_escalation
                actual_txns = [(_jittered_date(billing_date, rng) if noisy else billing_date, pre_escalation)]
            elif anomaly_type == "zombie_discount":
                discounted = round(expected_amount * (1 - (rule.discount_pct or 0.0) / 100), 2)
                actual_amount = discounted
                actual_txns = [(_jittered_date(billing_date, rng) if noisy else billing_date, discounted)]
            elif anomaly_type == "short_change":
                actual_amount = round(expected_amount * 0.8, 2)
                if cs.plant.split_payment:
                    first = round(expected_amount * 0.5, 2)
                    second = round(actual_amount - first, 2)
                    d1 = _jittered_date(billing_date, rng)
                    d2 = _jittered_date(billing_date + timedelta(days=10), rng)
                    actual_txns = [(d1, first), (d2, second)]
                else:
                    actual_txns = [(_jittered_date(billing_date, rng) if noisy else billing_date, actual_amount)]
            else:  # pragma: no cover - defensive
                raise ValueError(f"unknown anomaly_type {anomaly_type!r}")

            desc = _name_variant(rule.client_name, month, cs.name_variants) if noisy else rule.client_name.upper()
            for txn_date, amount in actual_txns:
                actual_rows.append((txn_date, f"{desc} INV-{OBSERVATION_YEAR}{month:02d}", amount))

            gap = round(expected_amount - actual_amount, 2)
            client_timeline.append(
                {
                    "month": month,
                    "billing_date": billing_date.isoformat(),
                    "expected_amount": expected_amount,
                    "actual_amount": actual_amount,
                    "gap": gap,
                    "applied_escalation": escalated,
                    "applied_discount_pct": discount_pct,
                    "is_anomaly": is_planted,
                    "anomaly_type": anomaly_type,
                }
            )
            if is_planted:
                n_anomalies += 1
                client_anomalies += 1
                total_gap += gap
                client_gap += gap
                by_type[anomaly_type] = by_type.get(anomaly_type, 0) + 1

        if client_anomalies:
            n_leaking += 1

        proving_clause = {
            "forgotten_raise": rule.escalation_clause,
            "zombie_discount": rule.discount_clause,
            "ghost_invoice": rule.base_fee_clause,
            "short_change": rule.base_fee_clause,
        }.get(cs.plant.anomaly_type if cs.plant else "", rule.base_fee_clause)

        ground_truth["clients"].append(
            {
                "name": rule.client_name,
                "source_contract": rule.source_contract.name,
                "filled_by_adr014": rule.filled_by_adr014,
                "rules": json.loads(cr.model_dump_json()),
                "proving_clause": proving_clause,
                "timeline": client_timeline,
                "client_gap": round(client_gap, 2),
                "client_anomaly_count": client_anomalies,
            }
        )

    if noisy:
        for desc, amount in rng.sample(_UNRELATED_NOISE, k=min(3, len(_UNRELATED_NOISE))):
            noise_date = date(OBSERVATION_YEAR, rng.randint(1, 12), rng.randint(1, 28))
            actual_rows.append((noise_date, desc, amount))

    actual_rows.sort(key=lambda r: r[0])
    with (out / "actuals.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "description", "amount"])
        for txn_date, desc, amount in actual_rows:
            writer.writerow([txn_date.isoformat(), desc, f"{amount:.2f}"])

    ground_truth["total_gap"] = round(total_gap, 2)
    ground_truth["anomaly_count"] = n_anomalies
    ground_truth["by_type"] = by_type
    (out / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2), encoding="utf-8")

    manifest = ScenarioManifest(
        name=out_dir,
        out_dir=str(out),
        n_clients=len(cs_list),
        n_leaking_clients=n_leaking,
        n_anomalies=n_anomalies,
        total_gap=round(total_gap, 2),
        anomaly_types=by_type,
        contracts=[cs.rule.source_contract.name for cs in cs_list],
    )
    (out / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# Seven real, hand-verified contracts (data/corpus/contracts/), one hand-read pass
# each. Recurring amount, escalation/discount percentage and duration, and clause
# text are all verbatim from the filing. `contract_start` is scenario-assigned (see
# module docstring) to place each contract's genuinely annual escalation/discount
# cutover at a demoable month inside OBSERVATION_YEAR.
# ---------------------------------------------------------------------------

_READY = CORPUS_DIR / "ready"
_FILLED = CORPUS_DIR / "filled"

GAMEZNFLIX = TrueRule(
    client_name="GameznFlix Inc.",
    source_contract=_READY / "GAMEZNFLIX_INC_EX-10.10_0001094328-08-000017.txt",
    filled_by_adr014=False,
    base_amount=5000.0,
    base_fee_clause=(
        "The cash monthly fee of $5,000 shall be due and payable not later than the "
        "fifteenth (15th) of each month, beginning with the first payment due on "
        "August 15, 2007."
    ),
    contract_start=date(2024, 3, 1),
    payment_terms="Due the 15th of each month; late if unpaid within 15 days of the due date",
    escalation_pct=10.0,
    escalation_after_months=12,
    escalation_clause=(
        "Such monthly fees shall increase by ten percent (10%) beginning on each "
        "anniversary date of the Agreement."
    ),
)

RMD = TrueRule(
    client_name="RMD Technologies Inc.",
    source_contract=_READY / "RMD_Technologies_Inc_EX-10.14_0001094328-06-000080.txt",
    filled_by_adr014=False,
    base_amount=2000.0,
    base_fee_clause=(
        "Monthly fee of $2,000 shall be due and payable not later than the fifteenth "
        "(15th) of each month, beginning with the first payment due on September 15, 2005."
    ),
    contract_start=date(2024, 5, 1),
    payment_terms="Due the 15th of each month; late if unpaid within 15 days of the due date",
    escalation_pct=10.0,
    escalation_after_months=12,
    escalation_clause=(
        "Such monthly fees shall increase by ten percent (10%) beginning on each "
        "anniversary date of the Agreement."
    ),
)

CBS_OUTDOOR = TrueRule(
    client_name="CBS Outdoor Americas Inc.",
    source_contract=_READY / "CBS_OUTDOOR_AMERICAS_INC_EX-10.1_0001193125-14-270475.txt",
    filled_by_adr014=False,
    base_amount=12500.0,
    base_fee_clause="$12,500 per month in which service is provided, as a Service Charge.",
    contract_start=date(2024, 2, 1),
    payment_terms="Net 60 from receipt of invoice",
    escalation_pct=3.0,
    escalation_after_months=12,
    escalation_clause=(
        "The amount of the Service Charge for each Service shall increase three percent "
        "(3%) annually on each anniversary of this Agreement (including during the term "
        "of any Service Extension)."
    ),
)

CENTRAL_GARDEN = TrueRule(
    client_name="Central Garden & Pet Co.",
    source_contract=_READY / "CENTRAL_GARDEN__PET_CO_EX-10.1_0001193125-07-130797.txt",
    filled_by_adr014=False,
    base_amount=5000.0,
    base_fee_clause='Executive shall be paid five thousand dollars ($5,000) per month ("Consulting Fee") during the Term of Agreement.',
    contract_start=date(2024, 4, 1),
    payment_terms=None,
    escalation_pct=2.0,
    escalation_after_months=12,
    escalation_clause=(
        "This Consulting Fee shall increase two percent (2%) each year following "
        "signature of this Agreement. Such 2% annual increase shall continue during "
        "the Term of Agreement."
    ),
)

VISION_HYDROGEN = TrueRule(
    client_name="Vision Hydrogen Corp.",
    source_contract=_READY / "VISION_HYDROGEN_Corp_EX-10.1_0001493152-22-017495.txt",
    filled_by_adr014=False,
    base_amount=100000.0,
    base_fee_clause=(
        'Recipient shall pay to Service Provider the sum of USD $100,000 (ONE HUNDRED '
        'THOUSAND UNITED STATES DOLLARS) per month beginning May 1, 2022 (the "Service Fee").'
    ),
    contract_start=date(2024, 6, 1),
    payment_terms="Payable in advance, in monthly installments, on the first day of each calendar month",
    escalation_pct=5.0,  # contractual floor of "the greater of CPI+2% or 5%" -- see clause
    escalation_after_months=12,
    escalation_clause=(
        "On each anniversary of this Agreement the Service Fee shall increase by the "
        "greater of (i) an amount equal to the previous year's change in the United "
        "States Consumer Price Index plus two per cent (CPI+2%) and (ii) five per cent (5%)."
    ),
)

REGAL = TrueRule(
    client_name="Regal Entertainment Group",
    source_contract=_FILLED / "REGAL_ENTERTAINMENT_GROUP_EX-10.1_0001104659-11-000106.txt",
    filled_by_adr014=True,  # $6,000 and 8% were [***] in the real filing; inserted per ADR-014
    base_amount=6000.0,
    base_fee_clause=(
        "...a monthly payment in addition to the Theatre Access Fee per Digital Screen "
        "shall be made from LLC to FM in the amount of $6,000 per month through the end "
        "of LLC's 2011 fiscal year..."
    ),
    contract_start=date(2024, 8, 1),
    payment_terms=None,
    escalation_pct=8.0,
    escalation_after_months=12,
    escalation_clause=(
        "...which additional amount shall increase 8% annually thereafter, with payment "
        "for (y) the first month to be pro rata based upon the number of days in such "
        "month in which the converted screen is operational..."
    ),
)

CELLTECK = TrueRule(
    client_name="Cellteck Inc.",
    source_contract=_READY / "Cellteck_Inc_EX-99.1_0001144204-13-014190.txt",
    filled_by_adr014=False,
    base_amount=5000.0,
    base_fee_clause=(
        'The Company agreed to pay Quantum a monthly fee of $5,000 per month, payable '
        'on the 15th day of each month (the "Monthly Retainer").'
    ),
    contract_start=date(2024, 1, 1),  # discount window (12mo) has fully elapsed by 2025
    payment_terms="Due the 15th of each month",
    discount_pct=30.0,
    discount_duration_months=12,
    discount_clause=(
        "if Cellteck engages Clouding to perform any services, such services will be "
        "rendered at a 30% discount for the first year of any such contract."
    ),
)


# ---------------------------------------------------------------------------
# Three scenarios (implementation_plan.md Phase 3): easy, realistic, edge.
# ---------------------------------------------------------------------------


def _easy() -> ScenarioManifest:
    clients = [
        ClientScenario(GAMEZNFLIX, Plant(months=(3, 4, 5), anomaly_type="forgotten_raise")),
        ClientScenario(CBS_OUTDOOR, Plant(months=(7,), anomaly_type="ghost_invoice")),
        ClientScenario(RMD, Plant(months=(9,), anomaly_type="short_change")),
        ClientScenario(CELLTECK, Plant(months=(5, 6), anomaly_type="zombie_discount")),
    ]
    return build_scenario([], [], [], "easy", clients=clients, noisy=False)


def _realistic() -> ScenarioManifest:
    clients = [
        ClientScenario(
            VISION_HYDROGEN,
            Plant(months=(6, 7, 8), anomaly_type="forgotten_raise"),
            name_variants=["VISION HYDROGEN CORP", "Vision Hydrogen", "VISIONHYDROGEN CORP WIRE"],
        ),
        ClientScenario(
            REGAL,
            Plant(months=(10,), anomaly_type="ghost_invoice"),
            name_variants=["REGAL ENTERTAINMENT GRP", "Regal Entertainment", "REGAL ENT GROUP ACH"],
        ),
        ClientScenario(
            CENTRAL_GARDEN,
            Plant(months=(8,), anomaly_type="short_change", split_payment=True),
            name_variants=["CENTRAL GARDEN & PET", "Central Garden Pet Co", "CTRL GARDEN PET CO"],
        ),
        ClientScenario(
            GAMEZNFLIX,
            None,  # clean control -- paid correctly, including its own escalation
            name_variants=["GAMEZNFLIX INC", "GameznFlix", "GAMEZNFLIX INC ACH PMT"],
        ),
    ]
    return build_scenario([], [], [], "realistic", clients=clients, noisy=True)


def _edge() -> ScenarioManifest:
    """Zero anomalies. The scenario examiners ask about: a detector that never says
    'clean' is worthless, so this proves the arithmetic discriminates rather than
    flagging everything."""
    clients = [
        ClientScenario(RMD, None),
        ClientScenario(CELLTECK, None),
    ]
    return build_scenario([], [], [], "edge", clients=clients, noisy=False)


def main() -> int:
    for label, fn in (("easy", _easy), ("realistic", _realistic), ("edge", _edge)):
        m = fn()
        print(
            f"{label:<10} clients={m.n_clients} leaking={m.n_leaking_clients} "
            f"anomalies={m.n_anomalies} gap=${m.total_gap:,.2f} types={m.anomaly_types}"
        )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
