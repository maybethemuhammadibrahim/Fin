"""[B] Parse a strategic question, phrase the already-computed verdict. Phase 9.

The model appears at both ends of this phase and never in the middle. It reads
the user's sentence (`parse_question`) and it phrases the finished figures
(`explain_verdict`). Everything between is `core/engine/cashflow.py`. Nothing
here does arithmetic on money.

**Three deliberate departures from the plan's Phase 9 sketch**, each because
following it literally would put a number the user sees at the mercy of a 3B
model:

1. **The amount is extracted by regex first, and the model is the fallback.**
   The plan has the LLM parse `{what, monthly_cost, start_month}`. But
   `monthly_cost` *is* a number the user sees, and it drives the verdict — a
   model reading "$5,000" as 50000 flips a YES to a NO with nothing on screen
   looking wrong. `extract_cost` is deterministic, quotes the substring it
   matched so the UI can show its work, and handles the money shapes people
   actually write. The model still supplies `what` and `start_month`, which are
   prose and harmless to get slightly wrong, and it fills in `monthly_cost` only
   when the pattern found nothing.

2. **The parsed cost is proposed, never assumed.** `ParsedQuestion.needs_confirmation`
   is set whenever the figure came from the model rather than the pattern, so the
   UI confirms it before it drives a verdict — the same LLM-proposed /
   human-confirmed shape ADR-010 uses for CSV column mapping.

3. **`explain_verdict` refuses its own bad output.** The plan says a number in
   the explanation that is not in its input "is a bug ... worth writing an
   assertion". An assertion catches it in CI; `_offending_numbers` catches it in
   production. The explanation is checked against `ScenarioResult.allowed_figures()`,
   retried once, and then abandoned in favour of the deterministic sentence in
   `fallback_explanation`. A missing paragraph of prose is a far smaller failure
   than a confident wrong figure.

Everything here returns `None` rather than raising when the model is unreachable
(the project convention), and the page stays fully usable without a GPU: the
regex reads the amount, `cashflow` computes the verdict, and
`fallback_explanation` writes the prose.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from core.ai import llm_client, prompts
from core.engine.cashflow import ScenarioResult

log = logging.getLogger(__name__)

Cadence = Literal["monthly", "annual", "one_off"]

#: Words that mean "per month" next to an amount, and the same for a year. Ordered
#: longest-first so "per annum" wins before "per a".
#: "pm" is deliberately absent: it appears inside ordinary words ("shipment"),
#: and a substring check would read a monthly cadence out of one.
_MONTHLY_HINTS = ("per month", "a month", "/month", "/mo", "monthly", "each month")
_ANNUAL_HINTS = ("per annum", "per year", "a year", "/year", "/yr", "annually", "yearly", "each year")

_MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)

#: $5,000 / 5,000 dollars / 5k / £5.5k — the shapes people actually type.
_AMOUNT_RE = re.compile(
    r"""
    (?P<currency>[$£€])?\s*
    (?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?   # 5,000 or 1,234,567.89
              |\d+(?:\.\d+)?)                  # 5000 or 5000.50
    # (?![a-z]) or the "m" would match the start of "monthly" and turn
    # "$12,500 monthly" into twelve and a half billion. Found by
    # tests/test_decision_analyzer.py, not by reading the regex.
    \s*(?:(?P<suffix>k|m|thousand|million)(?![a-z]))?
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: A year-like number preceded by one of these is a date, not a price.
_DATE_PREPOSITIONS = ("in", "by", "from", "during", "starting", "after", "before", "until", "since")

_SUFFIX_MULTIPLIER = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "million": 1_000_000}

#: Every numeral in a sentence, for checking an explanation against its input.
_NUMBER_IN_TEXT_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class _ParsedFromModel(BaseModel):
    """What the model is asked for. Kept separate from `ParsedQuestion` so the
    model's output is validated before any of it is trusted."""

    what: str = Field(default="")
    monthly_cost: float | None = None
    cadence: str | None = None
    start_month: str | None = None


@dataclass(frozen=True)
class ParsedQuestion:
    """What the question asked for.

    `monthly_cost` is always **per month**, whatever cadence the question used —
    the conversion happens in `_to_monthly`, in Python. `raw_amount` and
    `matched_text` keep the original so the UI can show the user the substring it
    read the figure out of, rather than asking them to trust it.
    """

    question: str
    what: str
    monthly_cost: float | None
    cadence: Cadence | None
    start_month: str | None
    #: Where `monthly_cost` came from. "pattern" is deterministic and quotable.
    source: Literal["pattern", "model", "none"]
    raw_amount: float | None = None
    matched_text: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def needs_confirmation(self) -> bool:
        """True when the figure is not provably the user's own written number."""
        return self.source != "pattern"

    @property
    def has_cost(self) -> bool:
        return self.monthly_cost is not None and self.monthly_cost > 0


@dataclass
class ExplanationResult:
    """The prose, and an honest account of where it came from."""

    text: str
    source: Literal["model", "fallback"]
    #: Numbers the model tried to use that were not in its input. Non-empty means
    #: an attempt was rejected — surfaced so the UI and the eval can report it.
    rejected_numbers: list[float] = field(default_factory=list)
    attempts: int = 0


# ---------------------------------------------------------------------------
# Deterministic parsing — no model
# ---------------------------------------------------------------------------


def _to_monthly(amount: float, cadence: Cadence | None) -> float:
    """Normalise a stated amount to a monthly figure. The only division here, and
    it is on a number the user typed, not on a result."""
    if cadence == "annual":
        return round(amount / 12, 2)
    return round(amount, 2)


def detect_cadence(question: str) -> Cadence | None:
    """How often the amount is paid, from the words around it.

    Returns None when the question names no cadence — the caller decides what to
    assume and says so, rather than this function quietly picking "monthly".
    """
    q = question.lower()
    for hint in _ANNUAL_HINTS:
        if hint in q:
            return "annual"
    for hint in _MONTHLY_HINTS:
        if hint in q:
            return "monthly"
    return None


def extract_cost(question: str) -> tuple[float | None, str | None]:
    """The amount the question names, and the exact substring it came from.

    Deterministic on purpose (see this module's docstring). Prefers a
    currency-marked figure, because "a $5,000 designer starting in 2026" contains
    two numbers and only one of them is money.
    """
    def looks_like_a_year(m: re.Match[str]) -> bool:
        """"starting in 2026" is not a price. Reading it as $2,026/month would be
        a confident wrong verdict with nothing on screen looking amiss.

        Requires a **date preposition** in front, not merely a plausible year:
        "Can we afford 2000 a month?" is money, and an earlier version that
        keyed on the number's range alone rejected it.
        """
        raw = m.group("number")
        if m.group("currency") or m.group("suffix") or "," in raw or "." in raw:
            return False
        if not 1900 <= float(raw) <= 2100:
            return False
        before = question[max(0, m.start() - 12) : m.start()].lower()
        return any(re.search(rf"\b{word}\s*$", before) for word in _DATE_PREPOSITIONS)

    candidates = [m for m in _AMOUNT_RE.finditer(question) if m.group("number")]
    if not candidates:
        return None, None

    # Drop dates, but never the last remaining figure.
    priced = [m for m in candidates if not looks_like_a_year(m)]
    if priced:
        candidates = priced
    else:
        return None, None

    def score(m: re.Match[str]) -> tuple[int, int, int]:
        # currency symbol wins, then a magnitude suffix, then an earlier position
        return (
            1 if m.group("currency") else 0,
            1 if m.group("suffix") else 0,
            -m.start(),
        )

    best = max(candidates, key=score)

    raw = best.group("number").replace(",", "")
    try:
        value = float(raw)
    except ValueError:  # pragma: no cover - the regex cannot produce this
        return None, None

    suffix = (best.group("suffix") or "").lower()
    if suffix:
        value *= _SUFFIX_MULTIPLIER[suffix]

    return round(value, 2), best.group(0).strip()


def parse_locally(question: str) -> ParsedQuestion:
    """A complete parse with no model at all.

    What the page falls back to when there is no endpoint, and the source of
    `monthly_cost` even when the model *is* available. `what` is left empty
    because guessing a noun phrase from a regex would be worse than saying
    nothing; the model fills it in when it can.
    """
    amount, matched = extract_cost(question)
    cadence = detect_cadence(question)
    warnings: list[str] = []

    if amount is not None and cadence is None:
        cadence = "monthly"
        warnings.append(
            "The question does not say how often this is paid, so it is being read "
            "as a monthly cost."
        )

    monthly = _to_monthly(amount, cadence) if amount is not None else None
    if amount is not None and cadence == "annual":
        warnings.append("Read as an annual figure and divided by 12.")

    return ParsedQuestion(
        question=question,
        what="",
        monthly_cost=monthly,
        cadence=cadence,
        start_month=_find_start_month(question),
        source="pattern" if monthly is not None else "none",
        raw_amount=amount,
        matched_text=matched,
        warnings=tuple(warnings),
    )


def _find_start_month(question: str) -> str | None:
    q = question.lower()
    for name in _MONTHS:
        if name in q:
            return name.capitalize()
    iso = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", question)
    return iso.group(0) if iso else None


# ---------------------------------------------------------------------------
# The model's half of the parse
# ---------------------------------------------------------------------------


def parse_question(question: str) -> ParsedQuestion:
    """What the question is asking for. Never returns None, never raises.

    Deliberately unlike the rest of the codebase's "returns None on failure"
    convention, and for a reason worth stating: this function always has a
    deterministic answer available (`parse_locally`), so returning None would
    make the page unusable to protect against a failure that does not need to
    stop anything. The model is an enrichment here, not a dependency.
    """
    local = parse_locally(question)

    if not question.strip():
        return local

    raw = llm_client.complete_json(
        prompts.parse_user(question),
        _ParsedFromModel,
        system=prompts.PARSE_SYSTEM,
        temperature=0.0,
    )

    if raw is None:
        reason = llm_client.last_error() or "model endpoint unavailable"
        log.info("question parse fell back to pattern only: %s", reason)
        return _with_warning(
            local,
            "The question was read by pattern matching only — the model endpoint "
            "did not answer, so the description of the commitment is blank.",
        )

    what = (raw.what or "").strip()
    start_month = (raw.start_month or "").strip() or local.start_month
    model_cadence = _clean_cadence(raw.cadence)

    # The pattern owns the money whenever it found any.
    if local.monthly_cost is not None:
        cadence = local.cadence or model_cadence
        monthly = _to_monthly(local.raw_amount, cadence) if local.raw_amount is not None else local.monthly_cost
        return ParsedQuestion(
            question=question,
            what=what,
            monthly_cost=monthly,
            cadence=cadence,
            start_month=start_month,
            source="pattern",
            raw_amount=local.raw_amount,
            matched_text=local.matched_text,
            warnings=local.warnings,
        )

    # The pattern found nothing. Take the model's figure, but flag it for
    # confirmation — it is not provably a number the user wrote.
    if raw.monthly_cost is not None and raw.monthly_cost > 0:
        cadence = model_cadence or "monthly"
        return ParsedQuestion(
            question=question,
            what=what,
            monthly_cost=_to_monthly(float(raw.monthly_cost), cadence),
            cadence=cadence,
            start_month=start_month,
            source="model",
            raw_amount=round(float(raw.monthly_cost), 2),
            matched_text=None,
            warnings=local.warnings
            + (
                "This amount was read by the model, not found verbatim in your "
                "question — check it before relying on the verdict.",
            ),
        )

    return ParsedQuestion(
        question=question,
        what=what,
        monthly_cost=None,
        cadence=model_cadence,
        start_month=start_month,
        source="none",
        warnings=local.warnings
        + ("No amount was found in the question, so there is nothing to test against.",),
    )


def _clean_cadence(value: str | None) -> Cadence | None:
    v = (value or "").strip().lower()
    return v if v in ("monthly", "annual", "one_off") else None  # type: ignore[return-value]


def _with_warning(parsed: ParsedQuestion, message: str) -> ParsedQuestion:
    from dataclasses import replace

    return replace(parsed, warnings=parsed.warnings + (message,))


# ---------------------------------------------------------------------------
# The model's other half: phrasing figures it is forbidden to change
# ---------------------------------------------------------------------------


def money(value: float) -> str:
    """One money format, used both in the figure list handed to the model and in
    the fallback prose, so a number cannot change shape between them."""
    return f"${value:,.2f}"


def figures_for(result: ScenarioResult) -> list[str]:
    """The quotable figures, pre-formatted. The model's entire numeric universe."""
    b, r = result.baseline, result.recovery
    out = [f"monthly revenue {money(b.monthly_revenue)}"]
    if b.monthly_expenses is not None:
        out.append(f"monthly running costs {money(b.monthly_expenses)}")
    if b.monthly_surplus is not None:
        out.append(f"monthly surplus {money(b.monthly_surplus)}")
    out.append(f"recovered leaks {money(r.monthly)} per month")
    out.append(f"confirmed findings {r.confirmed_count}")
    out.append(f"total confirmed {money(r.confirmed_total)}")
    if result.corrected_surplus is not None:
        out.append(f"corrected surplus {money(result.corrected_surplus)}")
    out.append(f"commitment {money(result.monthly_cost)} per month")
    if result.after_decision is not None:
        out.append(f"left over after the decision {money(result.after_decision)}")
    if result.cost_share_of_revenue is not None:
        out.append(f"share of revenue {result.cost_share_of_revenue * 100:.2f}%")
    out.append(f"months of history {b.months_observed}")
    return out


def _numbers_in(text: str) -> list[float]:
    values = []
    for raw in _NUMBER_IN_TEXT_RE.findall(text):
        try:
            values.append(round(float(raw.replace(",", "")), 2))
        except ValueError:  # pragma: no cover
            continue
    return values


def offending_numbers(text: str, result: ScenarioResult) -> list[float]:
    """Numbers in `text` that the model was not given. Empty means clean.

    The runtime half of the plan's own warning. Two allowances, both about
    English rather than arithmetic: a small integer may be a word like "two
    sentences" or a month count, and a percentage's integer part may appear
    when the model writes "21%" for 21.28. Neither can express a wrong money
    figure, which is what this guard exists to stop.
    """
    allowed = result.allowed_figures()
    # integer readings of allowed values, so "$4,500" passes against 4500.0
    allowed |= {round(float(int(v)), 2) for v in allowed if float(v).is_integer()}
    # a percentage written to fewer decimals
    if result.cost_share_of_revenue is not None:
        pct = result.cost_share_of_revenue * 100
        allowed |= {round(pct, 2), round(pct, 1), float(round(pct)), float(int(pct))}

    bad = []
    for value in _numbers_in(text):
        if value in allowed:
            continue
        if value <= 12 and float(value).is_integer():
            continue  # a month count or a plain English small number
        bad.append(value)
    return bad


def fallback_explanation(result: ScenarioResult, parsed: ParsedQuestion | None = None) -> str:
    """The deterministic explanation. No model involved, and never wrong.

    Used when there is no endpoint and when the model's attempt is rejected. It
    is deliberately plainer than the model's prose — that difference is the
    honest signal that the model did not write this one.
    """
    b, r = result.baseline, result.recovery
    thing = (parsed.what if parsed and parsed.what else "this commitment").strip()
    cost = money(result.monthly_cost)

    # Order matters: an empty run has unknown expenses too, but "no history" is
    # the truer thing to say about it than "no running costs on file".
    if b.confidence == "none":
        return (
            f"There is not enough transaction history in this run to judge {thing} "
            f"against. {result.rationale}"
        )

    if result.verdict == "unknown" and not b.expenses_known:
        share = (
            f" That is {result.cost_share_of_revenue * 100:.2f}% of your monthly revenue."
            if result.cost_share_of_revenue is not None
            else ""
        )
        return (
            f"This cannot be answered yes or no, because your monthly running costs "
            f"are not on file. What is known: revenue averages "
            f"{money(b.monthly_revenue)} a month over {b.months_observed} month(s), "
            f"the {r.confirmed_count} confirmed finding(s) are worth "
            f"{money(r.monthly)} a month once recovered, and {thing} would cost "
            f"{cost} a month.{share}"
        )

    if result.verdict == "unknown":
        return (
            f"There is not enough transaction history in this run to judge {thing} "
            f"against. {result.rationale}"
        )

    assert result.corrected_surplus is not None and result.after_decision is not None

    if result.verdict == "yes":
        return (
            f"Yes. Your monthly surplus is {money(b.monthly_surplus or 0.0)}, and "
            f"recovering the {r.confirmed_count} confirmed finding(s) adds "
            f"{money(r.monthly)} a month, giving {money(result.corrected_surplus)}. "
            f"After {cost} a month for {thing}, {money(result.after_decision)} is left over."
        )

    return (
        f"No. Even with the {r.confirmed_count} confirmed finding(s) recovered — worth "
        f"{money(r.monthly)} a month — your corrected surplus is "
        f"{money(result.corrected_surplus)}, which does not cover {cost} a month for "
        f"{thing}. The shortfall is {money(abs(result.after_decision))} a month."
    )


def explain_verdict(
    result: ScenarioResult,
    parsed: ParsedQuestion | None = None,
    *,
    max_attempts: int = 2,
) -> ExplanationResult:
    """Phrase the computed verdict. Always returns usable prose.

    Signature widened from `docs/interfaces.md`'s `-> str`: the caller needs to
    know whether the model wrote this or whether its attempt was rejected, and a
    bare string cannot say. `.text` is the string the old signature promised.
    """
    figures = figures_for(result)
    rejected: list[float] = []
    attempts = 0

    for _ in range(max(1, max_attempts)):
        attempts += 1
        text = llm_client.complete(
            prompts.explain_user(result.verdict, figures, result.rationale),
            system=prompts.EXPLAIN_SYSTEM,
            temperature=0.2,
        )
        if text is None:
            log.info("explanation fell back: %s", llm_client.last_error())
            break

        text = text.strip()
        if not text:
            continue

        bad = offending_numbers(text, result)
        if not bad:
            return ExplanationResult(text=text, source="model", rejected_numbers=rejected, attempts=attempts)

        rejected.extend(bad)
        log.warning(
            "rejected an explanation quoting figures it was not given: %s — retrying",
            bad,
        )

    return ExplanationResult(
        text=fallback_explanation(result, parsed),
        source="fallback",
        rejected_numbers=rejected,
        attempts=attempts,
    )
