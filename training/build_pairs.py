#!/usr/bin/env python3
"""[A] Turn contracts into instruction/response training pairs. Phase 10.

    python training/build_pairs.py --count 85          # generate, no network
    python training/build_pairs.py --count 85 --reword # + DeepSeek wording variety
    python training/build_pairs.py --dry-run           # show one pair, write nothing
    python training/build_pairs.py --check-leak        # prove the seal is enforced

Writes `training/data/train.jsonl` and `training/data/val.jsonl`.

**It does NOT write `eval_set.jsonl`.** That file is built from the 30 real
contracts sealed in `data/corpus/heldout/` *after* a human has checked them
(`scripts/seal_testset.py`, docs/phase10_plan.md step 5). Generated text never
becomes an exam question — see *The seal* below.

---

## Why the pairs are generated rather than extracted

`docs/implementation_plan.md` asks for 80–120 pairs drafted from real contracts
by "the best available model" and then human-verified. The corpus yields ~192
distinct contracts, but only a fraction carry a *clean, unambiguous* fee +
escalation pair, and verifying each drafted answer by hand is the evening of
work the plan itself calls "the highest-leverage hour in the project".

Generating instead inverts the problem. **We choose the figures, so the answer
is correct by construction and there is nothing to verify.** That is not a new
liberty: ADR-014 already established it for redacted values — *"the inserted
value IS ground truth by construction, so nothing needs verifying. If a model
chose it, you would have to read its output to learn what it picked — a step,
and a way to be silently wrong."* This applies the same reasoning to a whole
document instead of one blank.

What we give up is prose realism, and that is what `--reword` buys back:
DeepSeek rewrites each clause in different words while the **figures stay
ours**. Every reworded clause is then re-checked — if a number moved, the
rewrite is discarded and the original wording kept. A model never supplies a
value and never supplies an answer key.

## The seal — enforced here, not remembered

`data/corpus/heldout/` holds the exam. The sealed contracts are *copies*, so the
originals are still sitting in `data/corpus/contracts/`, which means the
training pool physically contains them (see `scripts/seal_testset.py` for why
copying beats moving). Nothing stops a careless reader from feeding one in
except this module.

So: **every source contract this file touches is checked against the sealed
manifest by sha256, and a match is a hard stop.** Not a warning — a refusal.
A leak does not announce itself; it just makes Phase 11's number look excellent
(known issues #26, #78).

The generated templates below are written from scratch and share no text with
any real filing, so they cannot leak. The check exists because `--from-corpus`
mixes real prose in, and because the next person to edit this file will not have
read this docstring.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ai.schemas import ContractRules, Discount, Escalation, Milestone  # noqa: E402

OUT_DIR = ROOT / "training" / "data"
SEALED_JSON = ROOT / "data" / "corpus" / "heldout" / "SEALED.json"
DEFAULT_SEED = 20260817

INSTRUCTION = "Extract all financial rules from this contract text as JSON."

# Baseten / DeepSeek — offline drafting only, never the runtime path (ADR-011).
# No vendor SDK: plain HTTP, so nothing lands in requirements.txt (hard rule 6).
BASETEN_URL = "https://inference.baseten.co/v1/chat/completions"
BASETEN_MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"
REWORD_BATCH = 6  # per known issue #80: reasoning cost is per REQUEST, so batch


# ---------------------------------------------------------------------------
# The seal — first, because everything below depends on it holding
# ---------------------------------------------------------------------------


class SealBreach(RuntimeError):
    """A held-out contract reached the training pool. Not recoverable in code."""


def _sealed_hashes() -> set[str]:
    if not SEALED_JSON.exists():
        raise SealBreach(
            f"{SEALED_JSON.relative_to(ROOT)} is missing.\n"
            "The test set must be sealed BEFORE any training pair exists, or there is\n"
            "no way to prove training never saw it. Run:\n"
            "    python scripts/seal_testset.py"
        )
    manifest = json.loads(SEALED_JSON.read_text(encoding="utf-8"))
    return {row["sha256"] for row in manifest["contracts"]}


def assert_not_sealed(path: Path, sealed: set[str]) -> None:
    """Hard stop if `path` is one of the held-out contracts."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest in sealed:
        raise SealBreach(
            f"REFUSING: {path.name} is part of the sealed test set.\n"
            "Training on it would make the Phase 11 comparison meaningless, and it\n"
            "would fail in the worst direction — the score would look excellent.\n"
            "Check any file with: python scripts/seal_testset.py --check <file>"
        )


# ---------------------------------------------------------------------------
# Vocabulary — fictional parties, so a generated contract cannot resemble a filing
# ---------------------------------------------------------------------------

_FIRST = [
    "Northgate", "Brightwater", "Cedarline", "Halcyon", "Ironwood", "Kestrel",
    "Lakeshore", "Meridian", "Oakfield", "Pinehurst", "Quarry", "Redstone",
    "Silverbrook", "Thornbury", "Umbrella", "Vantage", "Westmoor", "Yarrow",
    "Ashcroft", "Belmont", "Copperfield", "Draycott", "Elmgrove", "Fairhaven",
]
_SECOND = [
    "Analytics", "Systems", "Logistics", "Diagnostics", "Interactive", "Robotics",
    "Media", "Bioscience", "Networks", "Industries", "Partners", "Studios",
    "Laboratories", "Consulting", "Technologies", "Holdings", "Group", "Works",
]
_SUFFIX = ["Inc.", "LLC", "Ltd.", "Corp.", "PLC", "GmbH"]

_SERVICES = [
    "managed information technology services",
    "software development and maintenance services",
    "marketing and creative services",
    "payroll and benefits administration services",
    "facilities management services",
    "clinical data management services",
    "logistics coordination services",
    "cloud hosting and support services",
    "design and brand services",
    "security monitoring services",
]

_PROVIDERS = ["Provider", "Supplier", "Contractor", "Vendor", "Consultant"]
_CLIENTS = ["Client", "Customer", "Company", "Purchaser"]


def _company(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST)} {rng.choice(_SECOND)} {rng.choice(_SUFFIX)}"


def _money(value: float) -> str:
    return f"${value:,.0f}" if float(value).is_integer() else f"${value:,.2f}"


_WORDS = {
    3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
    9: "nine", 10: "ten", 12: "twelve", 15: "fifteen", 20: "twenty", 25: "twenty-five",
}


def _spell(n: float) -> str:
    """'8' -> 'eight'. Contracts write numbers both ways; the model should see both."""
    i = int(n)
    return _WORDS.get(i, str(i)) if float(n).is_integer() else str(n)


# ---------------------------------------------------------------------------
# Templates — one per shape the engine actually reasons about
# ---------------------------------------------------------------------------


@dataclass
class Pair:
    text: str
    rules: ContractRules
    template: str
    #: exact clause sentences, by field, so --reword can swap them and re-verify
    clauses: dict[str, str]


def _header(rng: random.Random, client: str, provider: str, service: str, start: date) -> str:
    return (
        f"SERVICES AGREEMENT\n\n"
        f"This Services Agreement (the \"Agreement\") is entered into as of "
        f"{start.strftime('%B %d, %Y')} by and between {provider} (\"{rng.choice(_PROVIDERS)}\") "
        f"and {client} (\"{rng.choice(_CLIENTS)}\").\n\n"
        f"1. SERVICES. Provider shall furnish {service} to Client in accordance with "
        f"the terms set out below.\n\n"
    )


def _tail(end: date | None, terms: str) -> str:
    body = f"\n\n{terms}\n\n"
    if end:
        body += (
            f"TERM. This Agreement shall commence on the Effective Date and continue "
            f"until {end.strftime('%B %d, %Y')} unless terminated earlier in accordance "
            f"with Section 9.\n\n"
        )
    body += (
        "GOVERNING LAW. This Agreement shall be governed by the laws of the State of "
        "Delaware, without regard to its conflict of laws principles.\n\n"
        "ENTIRE AGREEMENT. This Agreement constitutes the entire understanding between "
        "the parties and supersedes all prior negotiations.\n"
    )
    return body


_TERMS = [
    "PAYMENT TERMS. All invoices are due and payable within thirty (30) days of receipt.",
    "PAYMENT TERMS. Client shall remit payment within forty-five (45) days of the invoice date.",
    "PAYMENT TERMS. Invoices are payable in advance on the first day of each billing period.",
    "PAYMENT TERMS. Payment shall be made net sixty (60) days from receipt of a valid invoice.",
]

# Deliberate distractors. Known issue #34: an "18% per annum" late-payment clause
# scored as a fee escalation and was only caught by hand. Known issue #24: 68 of 81
# CUAD "escalation" matches meant escalating a DISPUTE. The model must learn to
# ignore both, so both appear in training documents with a null answer for them.
_DISTRACTORS = [
    "LATE PAYMENT. Any amount not paid when due shall bear interest at the rate of "
    "eighteen percent (18%) per annum, or the maximum rate permitted by law, whichever is less.",
    "LATE PAYMENT. Overdue balances accrue interest at one and one-half percent (1.5%) "
    "per month until paid in full.",
    "DISPUTE RESOLUTION. Any dispute shall first be escalated to the senior management "
    "of each party, who shall confer in good faith for fifteen (15) days before either "
    "party commences arbitration.",
    "DISPUTE RESOLUTION. If the parties' project managers cannot resolve a disagreement "
    "within ten (10) business days, the matter shall be escalated to the respective "
    "executive sponsors.",
    "EXPENSES. Client shall reimburse Provider for pre-approved travel expenses at cost, "
    "provided such expenses do not exceed five percent (5%) of the annual fees.",
]


def _t_recurring_escalation(rng: random.Random) -> Pair:
    """Monthly fee + anniversary escalation. The forgotten_raise shape."""
    client, provider = _company(rng), _company(rng)
    start = date(rng.randint(2021, 2024), rng.randint(1, 12), 1)
    amount = float(rng.choice([2500, 3000, 4500, 6000, 7500, 8000, 12000, 15000]))
    pct = float(rng.choice([3, 4, 5, 6, 8, 10]))

    fee = (
        f"2. FEES. In consideration of the Services, Client shall pay Provider a monthly "
        f"fee of {_money(amount)}, invoiced on the first day of each calendar month."
    )
    esc = (
        f"3. FEE ADJUSTMENT. On each anniversary of the Effective Date, the monthly fee "
        f"shall increase by {_spell(pct)} percent ({pct:g}%)."
    )
    text = (
        _header(rng, client, provider, rng.choice(_SERVICES), start)
        + fee + "\n\n" + esc + "\n\n" + rng.choice(_DISTRACTORS)
        + _tail(None, rng.choice(_TERMS))
    )
    rules = ContractRules(
        client_name=client, contract_start_date=start, contract_end_date=None,
        base_amount=amount, currency="USD", billing_frequency="monthly",
        payment_terms=None,
        escalation=Escalation(percentage=pct, after_months=12, clause_text=esc),
        discounts=[], milestones=[],
    )
    return Pair(text, rules, "recurring_escalation", {"escalation": esc})


def _t_intro_discount(rng: random.Random) -> Pair:
    """Monthly fee + a discount that expires. The zombie_discount shape."""
    client, provider = _company(rng), _company(rng)
    start = date(rng.randint(2021, 2024), rng.randint(1, 12), 1)
    amount = float(rng.choice([3500, 5000, 6000, 9000, 11000, 14000]))
    pct = float(rng.choice([5, 10, 15, 20, 25]))
    months = rng.choice([3, 4, 6])

    fee = (
        f"2. FEES. Client shall pay Provider a recurring monthly fee of {_money(amount)} "
        f"for the Services, invoiced monthly in arrears."
    )
    dis = (
        f"3. INTRODUCTORY DISCOUNT. A discount of {_spell(pct)} percent ({pct:g}%) shall "
        f"apply to the monthly fee for the first {_spell(months)} ({months}) months of "
        f"the Term, after which the full fee shall apply."
    )
    text = (
        _header(rng, client, provider, rng.choice(_SERVICES), start)
        + fee + "\n\n" + dis + "\n\n" + rng.choice(_DISTRACTORS)
        + _tail(None, rng.choice(_TERMS))
    )
    rules = ContractRules(
        client_name=client, contract_start_date=start, contract_end_date=None,
        base_amount=amount, currency="USD", billing_frequency="monthly",
        payment_terms=None, escalation=None,
        discounts=[Discount(percentage=pct, duration_months=months, clause_text=dis)],
        milestones=[],
    )
    return Pair(text, rules, "intro_discount", {"discount": dis})


def _t_milestone(rng: random.Random) -> Pair:
    """Monthly fee + a one-off milestone. The ghost_invoice shape (#55: no due date)."""
    client, provider = _company(rng), _company(rng)
    start = date(rng.randint(2021, 2024), rng.randint(1, 12), 1)
    amount = float(rng.choice([4000, 5500, 7000, 9500]))
    ms_amount = float(rng.choice([10000, 15000, 20000, 25000, 30000]))
    event = rng.choice([
        "completion of the website launch", "delivery of the final data migration",
        "acceptance of the pilot deployment", "go-live of the production environment",
        "completion of user acceptance testing",
    ])

    fee = (
        f"2. FEES. Client shall pay Provider {_money(amount)} per month for the Services "
        f"during the Term."
    )
    ms = (
        f"3. MILESTONE PAYMENT. In addition to the monthly fee, Client shall pay Provider "
        f"a one-time amount of {_money(ms_amount)} upon {event}."
    )
    text = (
        _header(rng, client, provider, rng.choice(_SERVICES), start)
        + fee + "\n\n" + ms + "\n\n" + rng.choice(_DISTRACTORS)
        + _tail(None, rng.choice(_TERMS))
    )
    rules = ContractRules(
        client_name=client, contract_start_date=start, contract_end_date=None,
        base_amount=amount, currency="USD", billing_frequency="monthly",
        payment_terms=None, escalation=None, discounts=[],
        milestones=[Milestone(description=f"Payment upon {event}", amount=ms_amount,
                              due_condition=f"upon {event}", clause_text=ms)],
    )
    return Pair(text, rules, "milestone", {"milestone": ms})


def _t_quarterly_cpi(rng: random.Random) -> Pair:
    """Quarterly billing + a CPI-linked rise with a floor — the wording that fooled
    Phase 3's keyword filter, and the shape a real MSA actually uses."""
    client, provider = _company(rng), _company(rng)
    start = date(rng.randint(2021, 2024), rng.choice([1, 4, 7, 10]), 1)
    amount = float(rng.choice([18000, 24000, 30000, 45000, 60000]))
    pct = float(rng.choice([2, 3, 4, 5]))
    end = date(start.year + rng.choice([2, 3]), start.month, start.day)

    fee = (
        f"2. FEES. Client shall pay Provider a fee of {_money(amount)} per quarter, "
        f"invoiced in advance on the first day of each calendar quarter."
    )
    esc = (
        f"3. ANNUAL ADJUSTMENT. On each anniversary of the Effective Date the quarterly "
        f"fee shall increase by the greater of (i) the change in the United States "
        f"Consumer Price Index for the preceding twelve months and (ii) {_spell(pct)} "
        f"percent ({pct:g}%)."
    )
    text = (
        _header(rng, client, provider, rng.choice(_SERVICES), start)
        + fee + "\n\n" + esc + "\n\n" + rng.choice(_DISTRACTORS)
        + _tail(end, rng.choice(_TERMS))
    )
    rules = ContractRules(
        client_name=client, contract_start_date=start, contract_end_date=end,
        base_amount=amount, currency="USD", billing_frequency="quarterly",
        payment_terms=None,
        escalation=Escalation(percentage=pct, after_months=12, clause_text=esc),
        discounts=[], milestones=[],
    )
    return Pair(text, rules, "quarterly_cpi", {"escalation": esc})


def _t_discount_and_escalation(rng: random.Random) -> Pair:
    """Both at once — the pitch's own contract, and the case a model most often
    half-reads (it finds one clause and stops)."""
    client, provider = _company(rng), _company(rng)
    start = date(rng.randint(2021, 2024), rng.randint(1, 12), 1)
    amount = float(rng.choice([6000, 8500, 10000, 12500]))
    d_pct = float(rng.choice([10, 15, 20]))
    d_months = rng.choice([3, 6])
    e_pct = float(rng.choice([5, 8, 10]))
    ms_amount = float(rng.choice([15000, 18000]))

    fee = (
        f"2. FEES. The Services shall be provided for a monthly fee of {_money(amount)}, "
        f"payable in advance on the first day of each month."
    )
    dis = (
        f"2.1 DISCOUNT. Notwithstanding Section 2, a {_spell(d_pct)} percent ({d_pct:g}%) "
        f"discount shall apply during the first {_spell(d_months)} ({d_months}) months "
        f"following the Effective Date."
    )
    esc = (
        f"2.2 ESCALATION. Beginning on the first anniversary of the Effective Date, and "
        f"on each anniversary thereafter, the monthly fee shall be increased by "
        f"{_spell(e_pct)} percent ({e_pct:g}%)."
    )
    ms = (
        f"2.3 LAUNCH FEE. Client shall additionally pay {_money(ms_amount)} upon launch "
        f"of the Client's new public website."
    )
    text = (
        _header(rng, client, provider, rng.choice(_SERVICES), start)
        + fee + "\n\n" + dis + "\n\n" + esc + "\n\n" + ms + "\n\n"
        + rng.choice(_DISTRACTORS) + _tail(None, rng.choice(_TERMS))
    )
    rules = ContractRules(
        client_name=client, contract_start_date=start, contract_end_date=None,
        base_amount=amount, currency="USD", billing_frequency="monthly",
        payment_terms=None,
        escalation=Escalation(percentage=e_pct, after_months=12, clause_text=esc),
        discounts=[Discount(percentage=d_pct, duration_months=d_months, clause_text=dis)],
        milestones=[Milestone(description="Website launch fee", amount=ms_amount,
                              due_condition="upon launch of the new public website",
                              clause_text=ms)],
    )
    return Pair(text, rules, "discount_and_escalation",
                {"discount": dis, "escalation": esc, "milestone": ms})


def _t_flat_no_escalation(rng: random.Random) -> Pair:
    """A flat fee and NOTHING else — except distractors that look like rules.

    The negative case, and the one the plan never asked for. Known issue #49: three
    of ten contracts extracted zero clauses and still scored as "valid", proving
    nothing. A model shown only contracts that contain escalations learns to find
    one whether or not it is there."""
    client, provider = _company(rng), _company(rng)
    start = date(rng.randint(2021, 2024), rng.randint(1, 12), 1)
    amount = float(rng.choice([1500, 2000, 3500, 5000, 22000]))
    freq = rng.choice(["monthly", "annual"])
    unit = "month" if freq == "monthly" else "year"

    fee = (
        f"2. FEES. Client shall pay Provider a fixed fee of {_money(amount)} per {unit} "
        f"for the Services. The fee is not subject to adjustment during the Term."
    )
    text = (
        _header(rng, client, provider, rng.choice(_SERVICES), start)
        + fee + "\n\n" + rng.choice(_DISTRACTORS) + "\n\n" + rng.choice(_DISTRACTORS)
        + _tail(None, rng.choice(_TERMS))
    )
    rules = ContractRules(
        client_name=client, contract_start_date=start, contract_end_date=None,
        base_amount=amount, currency="USD", billing_frequency=freq,
        payment_terms=None, escalation=None, discounts=[], milestones=[],
    )
    return Pair(text, rules, "flat_no_escalation", {})


TEMPLATES = [
    _t_recurring_escalation,
    _t_intro_discount,
    _t_milestone,
    _t_quarterly_cpi,
    _t_discount_and_escalation,
    _t_flat_no_escalation,
]


# ---------------------------------------------------------------------------
# Verification — a generated pair must still prove itself
# ---------------------------------------------------------------------------


def _numbers(text: str) -> set[str]:
    """Every figure in a string, normalised. Used to prove a rewrite changed no value."""
    out = set()
    for raw in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        cleaned = raw.replace(",", "")
        out.add(cleaned.rstrip("0").rstrip(".") if "." in cleaned else cleaned)
    return out


def verify(pair: Pair) -> list[str]:
    """Problems with a pair. Empty list means it is safe to train on.

    Generated data is correct by construction — but only if the construction is
    right. This catches a template edited into inconsistency, which is otherwise
    invisible and would teach the model a wrong answer with total confidence.
    """
    problems: list[str] = []
    r = pair.rules

    if r.base_amount is not None and str(int(r.base_amount)) not in _numbers(pair.text):
        problems.append(f"base_amount {r.base_amount} does not appear in the text")
    if r.client_name not in pair.text:
        problems.append("client_name does not appear in the text")

    for label, clause in (
        ("escalation", r.escalation.clause_text if r.escalation else None),
        *[(f"discount[{i}]", d.clause_text) for i, d in enumerate(r.discounts)],
        *[(f"milestone[{i}]", m.clause_text) for i, m in enumerate(r.milestones)],
    ):
        if clause is None:
            continue
        # The load-bearing property: clause_text is VERBATIM (architecture rule 2).
        # If this ever fails, clause_locator cannot place a box on the page.
        if clause not in pair.text:
            problems.append(f"{label} clause_text is not verbatim in the document")

    if r.escalation and f"{r.escalation.percentage:g}" not in pair.text:
        problems.append(f"escalation {r.escalation.percentage}% not in the text")
    for i, d in enumerate(r.discounts):
        if f"{d.percentage:g}" not in pair.text:
            problems.append(f"discount[{i}] {d.percentage}% not in the text")
    for i, m in enumerate(r.milestones):
        if str(int(m.amount)) not in _numbers(pair.text):
            problems.append(f"milestone[{i}] amount {m.amount} not in the text")
    return problems


# ---------------------------------------------------------------------------
# Wording variety — DeepSeek rewrites prose, never figures
# ---------------------------------------------------------------------------


@dataclass
class Spend:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    rejected: int = 0

    def line(self) -> str:
        return (
            f"{self.calls} call(s), {self.prompt_tokens + self.completion_tokens:,} tokens "
            f"({self.reasoning_tokens:,} spent thinking), {self.rejected} rewrite(s) rejected"
        )


def _api_key() -> str | None:
    for name in ("BASETEN_API_KEY", "DEEPSEEK_API", "DEEPSEEK_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() in ("BASETEN_API_KEY", "DEEPSEEK_API", "DEEPSEEK_API_KEY") and value.strip():
                return value.strip()
    return None


class BudgetExhausted(RuntimeError):
    """The API said no more. Reported loudly — the user set a hard $5 cap."""


def _reword_batch(sentences: list[str], key: str, spend: Spend, tries: int = 3) -> list[str] | None:
    """Rewrite each sentence, preserving every figure. None on failure — callers keep
    the original wording, which is always safe."""
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    prompt = (
        "Rewrite each numbered contract clause in different words, as a real commercial "
        "contract would phrase it. Keep EVERY number, percentage, currency amount and "
        "date exactly as written. Do not add or remove any figure. Keep the clause "
        "number prefix if there is one.\n"
        f"Return a JSON array of {len(sentences)} strings and nothing else.\n\n"
        f"{numbered}\n"
    )
    payload = {
        "model": BASETEN_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        # Generous, because a reasoning model that runs out mid-thought returns
        # content=null with NO error (known issue #80).
        "max_tokens": 2400,
        "temperature": 0.9,
        "reasoning_effort": "low",
    }
    request = urllib.request.Request(
        BASETEN_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(tries):
        try:
            body = json.loads(urllib.request.urlopen(request, timeout=180).read())
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode(errors="ignore")
            if exc.code in (402, 403) or "quota" in detail.lower() or "credit" in detail.lower():
                raise BudgetExhausted(f"HTTP {exc.code}: {detail}") from exc
            if exc.code == 429 and attempt < tries - 1:
                time.sleep(5 * (attempt + 1))  # throughput is low; back off properly
                continue
            return None
        except Exception:
            if attempt < tries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return None

        usage = body.get("usage") or {}
        spend.calls += 1
        spend.prompt_tokens += usage.get("prompt_tokens", 0)
        spend.completion_tokens += usage.get("completion_tokens", 0)
        spend.reasoning_tokens += (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)

        content = (body.get("choices") or [{}])[0].get("message", {}).get("content")
        if not content:  # ran out of room while thinking — retry with the same budget
            continue
        match = re.search(r"\[.*\]", content, re.S)
        if not match:
            continue
        try:
            items = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(items, list) and len(items) == len(sentences):
            return [str(x) for x in items]
    return None


def reword_pairs(pairs: list[Pair], key: str, spend: Spend) -> None:
    """Swap each clause for a reworded one, in place — but only where the figures
    survived unchanged AND the new sentence is still verbatim in the document.

    A rejected rewrite costs nothing: the original wording is already correct.
    """
    jobs: list[tuple[Pair, str, str]] = []
    for pair in pairs:
        for field, clause in pair.clauses.items():
            jobs.append((pair, field, clause))

    for start in range(0, len(jobs), REWORD_BATCH):
        chunk = jobs[start : start + REWORD_BATCH]
        rewritten = _reword_batch([c for _, _, c in chunk], key, spend)
        if rewritten is None:
            continue
        for (pair, field, original), new in zip(chunk, rewritten):
            new = new.strip()
            if not new or _numbers(new) != _numbers(original):
                spend.rejected += 1  # a figure moved — discard, keep ours
                continue
            pair.text = pair.text.replace(original, new)
            pair.clauses[field] = new
            if field == "escalation" and pair.rules.escalation:
                pair.rules.escalation.clause_text = new
            elif field == "discount" and pair.rules.discounts:
                pair.rules.discounts[0].clause_text = new
            elif field == "milestone" and pair.rules.milestones:
                pair.rules.milestones[0].clause_text = new
        time.sleep(1.0)  # low per-minute throughput; do not burst


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def generate(count: int, seed: int) -> list[Pair]:
    """Round-robin the templates so every shape is evenly represented."""
    rng = random.Random(seed)
    pairs: list[Pair] = []
    for i in range(count):
        pairs.append(TEMPLATES[i % len(TEMPLATES)](rng))
    return pairs


def as_record(pair: Pair) -> dict:
    return {
        "instruction": INSTRUCTION,
        "input": pair.text,
        "output": pair.rules.model_dump_json(),
        "template": pair.template,
    }


def write_split(pairs: list[Pair], seed: int) -> dict[str, int]:
    """train/val only. eval_set.jsonl comes from the sealed REAL contracts."""
    rng = random.Random(seed)
    shuffled = pairs[:]
    rng.shuffle(shuffled)
    cut = max(1, int(len(shuffled) * 0.15))
    val, train = shuffled[:cut], shuffled[cut:]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train", train), ("val", val)):
        path = OUT_DIR / f"{name}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for pair in rows:
                handle.write(json.dumps(as_record(pair), ensure_ascii=False) + "\n")
    return {"train": len(train), "val": len(val)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=85)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--reword", action="store_true", help="DeepSeek wording variety (costs money)")
    parser.add_argument("--dry-run", action="store_true", help="print one pair, write nothing")
    parser.add_argument("--check-leak", action="store_true", help="prove the seal is enforced, then exit")
    args = parser.parse_args()

    # The seal is loaded FIRST. No pair is generated before it is known to exist.
    try:
        sealed = _sealed_hashes()
    except SealBreach as exc:
        print(f"! {exc}")
        return 2
    print(f"seal loaded: {len(sealed)} held-out contract(s) are off limits")

    if args.check_leak:
        heldout = sorted(SEALED_JSON.parent.glob("*.txt"))
        if not heldout:
            print("! no sealed contracts on disk to test against")
            return 2
        try:
            assert_not_sealed(heldout[0], sealed)
        except SealBreach as exc:
            print(f"\nPASS — the guard refused a sealed contract:\n{exc}")
            return 0
        print("\nFAIL — a sealed contract was NOT refused. Do not generate training data.")
        return 1

    pairs = generate(args.count, args.seed)

    bad = 0
    for pair in pairs:
        problems = verify(pair)
        if problems:
            bad += 1
            print(f"! {pair.template}: {'; '.join(problems)}")
    if bad:
        print(f"\n{bad} pair(s) failed verification — refusing to write. Fix the template.")
        return 1
    print(f"generated {len(pairs)} pair(s), all verified: figures and clauses are verbatim")

    if args.reword:
        key = _api_key()
        if not key:
            print("! no API key found (BASETEN_API_KEY / DEEPSEEK_API) — skipping rewording")
        else:
            spend = Spend()
            try:
                reword_pairs(pairs, key, spend)
            except BudgetExhausted as exc:
                print(f"\n! THE API BUDGET IS EXHAUSTED — tell the user.\n  {exc}")
                print(f"  spend so far: {spend.line()}")
                print("  the pairs are still valid; they just keep the original wording.")
            print(f"rewording: {spend.line()}")
            bad = sum(1 for p in pairs if verify(p))
            if bad:
                print(f"\n{bad} pair(s) broke during rewording — refusing to write.")
                return 1
            print("re-verified after rewording: every figure and clause still intact")

    if args.dry_run:
        sample = pairs[0]
        print("\n--- sample input ---\n" + sample.text[:900])
        print("\n--- sample output ---\n" + json.dumps(json.loads(sample.rules.model_dump_json()), indent=2)[:900])
        print("\n(dry run — nothing written)")
        return 0

    counts = write_split(pairs, args.seed)
    print(f"\nwritten: train={counts['train']} val={counts['val']} -> {OUT_DIR.relative_to(ROOT)}")
    print("eval_set.jsonl NOT written here — it comes from the 30 sealed REAL")
    print("contracts once a human has checked them (docs/phase10_plan.md step 5).")
    by_template: dict[str, int] = {}
    for pair in pairs:
        by_template[pair.template] = by_template.get(pair.template, 0) + 1
    for name, n in sorted(by_template.items()):
        print(f"  {name:26} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
