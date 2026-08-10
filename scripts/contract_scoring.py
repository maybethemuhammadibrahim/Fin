"""Shared scoring for the Phase 3 data-source probes.

Imported by scripts/cuad_probe.py and scripts/edgar_probe.py so both sources are
judged by IDENTICAL criteria -- otherwise the comparison that decides where
Phase 3's contracts come from would be meaningless.

NOT a Phase 3 deliverable. When data_sourcing/filter_contracts.py is written for
real, it should inherit these patterns and the three-bucket idea, not the file.

Three buckets, in descending order of usefulness:

    GOLD      concrete unredacted recurring amount AND concrete escalation.
              Usable exactly as-is: scenario_builder can derive a ledger and
              know the right answer.

    TEMPLATE  the right clause STRUCTURE, but the numbers are redacted ([***])
              or live in an exhibit that was never filed. The lawyer-written
              prose is real; only the figures are missing. Write dummy numbers
              on top and you keep the "tested on genuine legal prose" claim.

    REJECT    everything else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# The plan's filter, verbatim from implementation_plan.md, for comparison only.
# --------------------------------------------------------------------------
PLAN_KEEP = [
    "monthly fee", "retainer", "shall increase", "escalat", "annual increase",
    "discount", "net 30", "net 45", "milestone", "recurring", "per month",
    "monthly payment",
]

# --------------------------------------------------------------------------
# Stage 1 -- five rule categories. Deliberately generous; see the escalation
# false-friend warning below.
# --------------------------------------------------------------------------
CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "recurring_fee": (
        "A repeating billing obligation -- the spine of every expected timeline",
        [
            r"\bretainer\b",
            r"monthly (?:fee|fees|rate|charge|payment|installment|instalment|amount|sum)",
            r"(?:fee|amount|sum|payment)s? of \$[\d,]+(?:\.\d+)? per month",
            r"\$[\d,]+(?:\.\d+)?\s*(?:per|each|/)\s*month",
            r"payable monthly",
            r"per month(?:ly)? in advance",
            r"annual (?:fee|fees|subscription)",
            r"\brecurring\s+(?:fee|charge|payment|revenue)",
            r"quarterly (?:fee|fees|payment|installment)",
        ],
    ),
    "escalation": (
        "A price increase over time -- WITHOUT THIS, forgotten_raise is undemonstrable",
        [
            r"(?:shall|will|may) (?:be )?increase[sd]?(?:.{0,80}?)\d+(?:\.\d+)?\s?%",
            r"\d+(?:\.\d+)?\s?%(?:.{0,60}?)(?:increase|escalation|uplift|adjustment)",
            r"\bescalat(?:e|es|ed|ion|or)\b",
            r"annual(?:ly)? (?:increase|adjust|escalat|uplift)",
            r"(?:increase|adjust)(?:.{0,60}?)(?:consumer price index|\bcpi\b)",
            r"(?:on|upon) each anniversary(?:.{0,80}?)(?:increase|adjust)",
            r"price (?:increase|escalation|adjustment)",
        ],
    ),
    "discount": (
        "A reduction, ideally time-limited -- the basis for zombie_discount",
        [
            r"\d+(?:\.\d+)?\s?%\s*discount",
            r"discount of \d+(?:\.\d+)?\s?%",
            r"discount(?:ed)? (?:rate|price|fee|amount)",
            r"(?:introductory|promotional|initial|trial) (?:rate|price|period|discount)",
            r"\brebate\b",
            r"fees? (?:shall be |will be |are )?waived",
        ],
    ),
    "milestone": (
        "A one-off payment tied to an event -- the basis for ghost_invoice",
        [
            r"\bmilestone\b",
            r"upon (?:completion|delivery|acceptance|launch|execution)(?:.{0,60}?)(?:pay|payment|\$)",
            r"(?:pay|payment|\$)(?:.{0,60}?)upon (?:completion|delivery|acceptance|launch)",
            r"payment schedule",
            r"lump[- ]sum",
            r"one[- ]time (?:fee|payment|charge)",
        ],
    ),
    "payment_terms": (
        "Net-N terms -- lets reconciliation set a realistic due date",
        [
            r"\bnet (?:thirty|30|forty[- ]five|45|sixty|60|fifteen|15)\b",
            r"within (?:thirty|30|forty[- ]five|45|sixty|60|fifteen|15) \(?\d*\)? ?days? (?:of|after|from|following)",
            r"due (?:and payable )?within \d+ days",
            r"payment terms",
        ],
    ),
}

CORE_PAIR = ("recurring_fee", "escalation")

# --------------------------------------------------------------------------
# Stage 2 -- the sharp test.
#
# Measured on all 510 CUAD contracts: bare `escalat*` matched 81 documents, and
# 68 of them meant the DISPUTE escalation procedure ("escalate to senior
# management"), not a price rise. Any filter containing bare `escalat` silently
# imports those as forgotten_raise candidates. Stage 2 therefore demands a real
# percentage or CPI reference tied to a fee.
# --------------------------------------------------------------------------
REDACTION_RE = r"\[\s*\*{2,}\s*\]|\[\*+\]|\[redacted\]|\*{5,}|\[\s*\.{3,}\s*\]"

CONCRETE_ESCALATION = [
    r"(?:fee|fees|rate|rates|price|prices|payment|compensation)(?:.{0,120}?)(?:increase|escalat|adjust)(?:.{0,120}?)\d+(?:\.\d+)?\s?(?:%|percent)",
    r"(?:increase|escalat|adjust)(?:.{0,120}?)\d+(?:\.\d+)?\s?(?:%|percent)(?:.{0,120}?)(?:per year|annually|each year|per annum|anniversary)",
    r"\d+(?:\.\d+)?\s?(?:%|percent)(?:.{0,80}?)(?:increase|escalat)(?:.{0,80}?)(?:per year|annually|each year|per annum|anniversary)",
    r"(?:fee|price|rate)(?:.{0,120}?)(?:increase|adjust)(?:.{0,120}?)consumer price index",
]

CONCRETE_RECURRING = [
    r"\$\s?[\d,]{3,}(?:\.\d{2})?\s*(?:per|/|each)\s*(?:month|year|annum|quarter)",
    r"(?:monthly|annual|quarterly)\s+(?:fee|retainer|payment|charge|rate)[^.]{0,80}?\$\s?[\d,]{3,}",
    r"\$\s?[\d,]{3,}(?:\.\d{2})?[^.]{0,60}?(?:per month|monthly|per annum|annually|per year)",
    r"retainer[^.]{0,100}?\$\s?[\d,]{3,}",
]

# --------------------------------------------------------------------------
# TEMPLATE tier -- right shape, missing numbers.
#
# These look for the LANGUAGE of a rule without requiring the figure, so a
# contract whose amount was redacted or pushed into an unfiled exhibit still
# qualifies. Pair with REDACTION_RE / absence of a concrete value.
# --------------------------------------------------------------------------
SHAPE_RECURRING = [
    r"(?:monthly|annual|quarterly)\s+(?:fee|fees|retainer|payment|charge|rate)",
    r"\bretainer\b",
    r"payable (?:monthly|quarterly|annually)",
    r"(?:fee|fees)(?:.{0,60}?)(?:per month|per annum|per year|each month)",
    r"(?:fees|compensation|amounts)(?:.{0,60}?)set forth in (?:exhibit|schedule|appendix|annex)",
]

SHAPE_ESCALATION = [
    r"(?:fee|fees|rate|rates|price|prices|compensation)(?:.{0,120}?)(?:shall|will|may) (?:be )?(?:increase|escalat|adjust)",
    r"(?:increase|escalat|adjust)(?:.{0,100}?)(?:annually|each year|per annum|anniversary|calendar year)",
    r"(?:annual|yearly)(?:.{0,40}?)(?:price|fee|rate)(?:.{0,40}?)(?:increase|adjustment|escalation)",
    r"consumer price index|\bcpi\b",
    r"price (?:increase|escalation|adjustment)",
]

DISPUTE_ESCALATION = [
    r"escalat(?:e|ed|ion)(?:.{0,60}?)(?:dispute|senior|executive|management|committee|level \d)",
    r"(?:dispute|disagreement)(?:.{0,60}?)escalat",
    r"escalation procedure",
]


@dataclass
class Hit:
    category: str
    pattern: str
    snippet: str
    page: int


@dataclass
class ContractResult:
    """Source-agnostic score for one contract."""

    name: str
    source: str  # "cuad" | "edgar"
    origin: str  # folder name, or the EDGAR accession id
    n_pages: int
    n_chars: int
    hits: list[Hit] = field(default_factory=list)
    plan_filter_pass: bool = False
    redacted: bool = False
    concrete_escalation: str | None = None
    concrete_recurring: str | None = None
    shape_escalation: str | None = None
    shape_recurring: str | None = None
    dispute_only_escalation: bool = False

    @property
    def categories(self) -> set[str]:
        return {h.category for h in self.hits}

    @property
    def score(self) -> int:
        return len(self.categories)

    @property
    def has_core_pair(self) -> bool:
        return all(c in self.categories for c in CORE_PAIR)

    @property
    def is_gold(self) -> bool:
        """Buildable as-is: both values present and unredacted."""
        return bool(self.concrete_escalation and self.concrete_recurring)

    @property
    def is_template(self) -> bool:
        """Right clause shapes, but at least one number is missing or redacted.

        This is the fill-in-the-blank pool: keep the real prose, supply the
        figures ourselves.
        """
        if self.is_gold:
            return False
        return bool(self.shape_recurring and self.shape_escalation)

    @property
    def tier(self) -> str:
        if self.is_gold:
            return "gold"
        if self.is_template:
            return "template"
        return "reject"


def _first(patterns: list[str], flat: str, pad: int = 110) -> str | None:
    for pat in patterns:
        m = re.search(pat, flat)
        if m:
            return flat[max(0, m.start() - pad):m.end() + pad].strip()
    return None


def normalise(text: str) -> str:
    """Lowercased, whitespace-collapsed. All patterns assume this shape."""
    return re.sub(r"\s+", " ", text).lower()


def scan_text(name: str, source: str, origin: str, text: str, n_pages: int) -> ContractResult:
    """Score one contract's extracted text. Pure -- no I/O."""
    flat = normalise(text)
    res = ContractResult(
        name=name, source=source, origin=origin, n_pages=n_pages, n_chars=len(text)
    )
    res.plan_filter_pass = any(k in flat for k in PLAN_KEEP)

    # Page offsets so a snippet can report where it came from.
    page_starts, cursor = [], 0
    for page_text in text.split("\f"):
        page_starts.append(cursor)
        cursor += len(normalise(page_text)) + 1

    def page_of(idx: int) -> int:
        lo = 0
        for i, start in enumerate(page_starts):
            if start <= idx:
                lo = i
            else:
                break
        return lo + 1

    # ---- stage 1 ----
    for cat, (_desc, patterns) in CATEGORIES.items():
        seen: list[tuple[int, int]] = []
        for pat in patterns:
            for m in re.finditer(pat, flat):
                if any(s <= m.start() < e for s, e in seen):
                    continue
                seen.append((m.start(), m.end()))
                lo, hi = max(0, m.start() - 160), min(len(flat), m.end() + 160)
                res.hits.append(Hit(cat, pat, flat[lo:hi].strip(), page_of(m.start())))
                if len([h for h in res.hits if h.category == cat]) >= 4:
                    break
            if len([h for h in res.hits if h.category == cat]) >= 4:
                break

    # ---- stage 2 ----
    res.redacted = bool(re.search(REDACTION_RE, flat))
    res.concrete_escalation = _first(CONCRETE_ESCALATION, flat)
    res.concrete_recurring = _first(CONCRETE_RECURRING, flat)
    res.shape_escalation = _first(SHAPE_ESCALATION, flat)
    res.shape_recurring = _first(SHAPE_RECURRING, flat)

    if "escalation" in res.categories and not res.concrete_escalation:
        res.dispute_only_escalation = any(re.search(p, flat) for p in DISPUTE_ESCALATION)

    return res


# --------------------------------------------------------------------------
# Duplicate detection.
#
# Measured on the 288-document EDGAR run: 51 documents scored GOLD but carried
# only 21 distinct escalation clauses, because one administrator (Ultimus) sends
# every fund trust the same fee letter. Counting documents overstates the corpus
# by ~2.5x, and near-duplicates either side of a train/test split are the
# invisible leak that makes Phase 11's numbers meaningless.
#
# So: dedupe on the CLAUSE, not the filename, and cap one document per filer.
# --------------------------------------------------------------------------
# Order matters: the bracketed forms must be tried before bare `***`, or a
# marker like `[…***…]` gets partially matched and the substitution leaves
# `[…5…]` behind in the contract text.
BLANK_RE = re.compile(
    r"\[\s*[.…]*\s*\*+\s*[.…]*\s*\]"   # [***]  [*]  […***…]  [..**..]
    r"|\[\s*redacted\s*\]"
    r"|\[\s*\.{3,}\s*\]"
    r"|\*{3,}",                          # bare **** (last resort)
    re.I,
)


def clause_fingerprint(clause: str | None) -> str:
    """Stable id for a clause, ignoring punctuation, spacing and digits.

    Digits are stripped deliberately: two fee letters that differ only in the
    dollar amount are the same clause for training purposes.
    """
    import hashlib

    s = re.sub(r"[^a-z ]", " ", (clause or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    return hashlib.md5(s[:150].encode()).hexdigest()[:8]


def filer_of(name: str) -> str:
    """Company portion of a probe filename (everything before the exhibit tag)."""
    return name.rsplit("_EX", 1)[0]


def count_blanks(*clauses: str | None) -> int:
    """Redaction markers inside the clauses we actually extract from.

    Only these matter. A contract can carry 2,000 `****` markers in pricing
    tables we never read and still be perfectly usable.
    """
    return len(BLANK_RE.findall(" ".join(c or "" for c in clauses)))


def summarise(results: list[ContractResult]) -> dict[str, int | float]:
    n = len(results) or 1
    return {
        "total": len(results),
        "plan_filter": sum(r.plan_filter_pass for r in results),
        "core_pair": sum(r.has_core_pair for r in results),
        "redacted": sum(r.redacted for r in results),
        "concrete_fee": sum(bool(r.concrete_recurring) for r in results),
        "concrete_esc": sum(bool(r.concrete_escalation) for r in results),
        "dispute_only": sum(r.dispute_only_escalation for r in results),
        "gold": sum(r.is_gold for r in results),
        "template": sum(r.is_template for r in results),
        "gold_pct": round(sum(r.is_gold for r in results) / n * 100, 1),
        "template_pct": round(sum(r.is_template for r in results) / n * 100, 1),
    }
