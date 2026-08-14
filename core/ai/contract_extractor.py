"""[A] Contract text -> validated ContractRules. Phase 5.

Three jobs, in order:

1. **Choose what the model sees.** A real EDGAR exhibit runs to tens of
   thousands of characters and the served context is 8k tokens. Chunks are
   ranked by how much fee language they carry, and the opening chunk is always
   kept because that is where the parties and the term are declared.
2. **Call the model once per chunk** through `llm_client.complete_json`, which
   validates against `ContractRules` and returns `None` rather than raising.
3. **Merge, then ground.** Every `clause_text` is checked against the document's
   own text before it is allowed into the result. A quote that is not in the
   document was invented, and an invented quote is how a wrong number reaches a
   dashboard.

That last step is worth being precise about. `clause_locator` grounds a quote
against a **PDF** and returns a page and a box; it cannot help with an EDGAR
contract, which arrives as HTML (known issue #28). Grounding against the
extracted *text* works for every document regardless of source, so it happens
here, unconditionally, and the locator's page/box is a further step for the
documents that can support it.

The model never computes anything and is never asked where a clause sits on a
page (ADR-005).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

from thefuzz import fuzz

from core.ai import llm_client, prompts
from core.ai.schemas import ContractRules, Discount, Escalation, ExtractedDoc, Milestone

log = logging.getLogger(__name__)

#: Characters of contract per call. The served context is 8192 tokens; the
#: system prompt and worked example cost roughly 900 and the answer up to 800,
#: which leaves ~6000 tokens. Legal prose runs near 3.5 characters per token, so
#: 12000 characters is deliberately under the line rather than at it.
CHUNK_CHARS = 12_000

#: Measured 2026-08-14 on the 10 EDGAR contracts of the Phase 5 eval, counting
#: what share of a contract's dollar amounts survive selection:
#:
#:     3 chunks -> 77%   4 -> 86%   5 -> 92%   6 -> 94%   8 -> 98%
#:
#: The old value of 3 was costing real money on long contracts specifically:
#: Bedminster (130k chars, 12 chunks) showed the model 30% of its figures and
#: Bryn Mawr 33%, so those extractions were blank for want of context rather
#: than for want of a better model. Returns flatten after 6, and 6 keeps a
#: 10-contract run at ~40 calls, inside the 35-55 budget in CLAUDE.md.
MAX_CHUNKS = 6

#: A clause_text at or above this partial-ratio counts as present in the
#: document. Below it, the quote is treated as fabricated and the rule dropped.
#: 92 tolerates PDF ligatures and line-break hyphenation without tolerating a
#: paraphrase.
GROUNDING_THRESHOLD = 92

#: Ranking only — NOT a gate. The gate that decides whether a contract is usable
#: at all lives in data_sourcing/filter_contracts.py, where the bare-`escalat`
#: trap (known issue #24) is handled properly. Here a false positive costs one
#: chunk of context, not a corrupted corpus.
RELEVANCE_PATTERNS = (
    (r"\$\s?[\d,]{3,}", 3),
    (r"\d+(?:\.\d+)?\s?(?:%|percent)", 3),
    (r"\b(?:fee|fees|retainer|invoice|payable|compensation)\b", 2),
    (r"\b(?:per month|monthly|per annum|annually|quarterly|per year)\b", 2),
    (r"\b(?:discount|rebate|credit)\b", 2),
    (r"\b(?:milestone|deliverable|upon delivery|upon completion)\b", 2),
    (r"\b(?:increase|escalation|adjust|consumer price index|cpi)\b", 1),
    (r"\bnet\s?\d{2}\b", 1),
)
_COMPILED = tuple((re.compile(pattern, re.I), weight) for pattern, weight in RELEVANCE_PATTERNS)


@dataclass
class ExtractionReport:
    """What `extract_rules` did, for the eval harness and the known-gaps line."""

    rules: ContractRules | None
    chunks_total: int = 0
    chunks_sent: int = 0
    chunks_parsed: int = 0
    #: Quotes the model produced that are not in the document — hallucinations,
    #: dropped before they could reach the database.
    dropped: list[str] = field(default_factory=list)
    #: Rules the model returned with no quote at all (a literal "null" in the
    #: string field). Also discarded, but not evidence of fabrication.
    blank: list[str] = field(default_factory=list)
    grounded: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.rules is not None


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def split_chunks(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Pack paragraphs into windows of at most `limit` characters.

    Paragraph boundaries rather than a fixed stride, so a clause is not sliced
    down the middle and then quoted as a fragment that grounds against nothing.
    """
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not paragraphs:
        return [text[:limit]] if text.strip() else []

    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        # One monstrous paragraph (common in HTML-derived text) gets hard-split.
        if len(paragraph) > limit:
            if current:
                chunks.append("\n\n".join(current))
                current, size = [], 0
            for start in range(0, len(paragraph), limit):
                chunks.append(paragraph[start : start + limit])
            continue
        if size + len(paragraph) > limit and current:
            chunks.append("\n\n".join(current))
            # One paragraph of overlap, so a rule spanning a boundary survives.
            current, size = [current[-1]], len(current[-1])
        current.append(paragraph)
        size += len(paragraph) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def score_chunk(chunk: str) -> int:
    return sum(weight * len(pattern.findall(chunk)) for pattern, weight in _COMPILED)


def select_chunks(text: str, max_chunks: int = MAX_CHUNKS) -> list[str]:
    """The opening chunk, plus the highest-scoring others, in document order."""
    chunks = split_chunks(text)
    if len(chunks) <= max_chunks:
        return chunks
    ranked = sorted(range(1, len(chunks)), key=lambda i: score_chunk(chunks[i]), reverse=True)
    keep = sorted({0, *ranked[: max_chunks - 1]})
    return [chunks[i] for i in keep]


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------


def _flatten(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


#: A model that has no sentence to give sometimes writes the *word* null into
#: the string field rather than omitting the rule. That is an absent quote, not
#: a fabricated one, and conflating the two overstates the hallucination rate:
#: on the v2 prompt, 4 of 16 rejected quotes were this (2026-08-14).
NULLISH = frozenset({"", "null", "none", "n/a", "na", "nil", "not stated", "not specified"})


def is_absent(clause_text: str | None) -> bool:
    """Did the model decline to quote, rather than quote something wrong?"""
    return (clause_text or "").strip().strip(".\"'").lower() in NULLISH


def is_verbatim(clause_text: str, document_text: str) -> bool:
    """Is this quote actually in the document?

    Whitespace-insensitive substring first — that is what a correctly copied
    sentence looks like. Fuzzy second, for ligatures and hyphenation. A
    paraphrase fails both, which is the point.
    """
    if not clause_text or not clause_text.strip():
        return False
    needle = _flatten(clause_text)
    haystack = _flatten(document_text)
    if len(needle) < 20:
        # Too short to be evidence of anything; a five-word quote matches by luck.
        return False
    if needle in haystack:
        return True
    return fuzz.partial_ratio(needle, haystack) >= GROUNDING_THRESHOLD


def _ground(
    rules: ContractRules, document_text: str
) -> tuple[ContractRules, list[str], int, list[str]]:
    """Strip every rule whose quote is not in the document.

    Three outcomes, not two. A rule is kept only when its quote is really in the
    document; but a rule with *no* quote is discarded as **blank**, separately
    from one whose quote was invented. Both leave the database equally empty —
    the distinction is for the eval, where calling an absent quote a
    hallucination makes the model look worse than it is.
    """
    dropped: list[str] = []
    blank: list[str] = []
    grounded = 0

    def verdict(clause_text: str) -> bool:
        """True to keep. Records why, when not."""
        nonlocal grounded
        if is_absent(clause_text):
            blank.append(clause_text)
            return False
        if is_verbatim(clause_text, document_text):
            grounded += 1
            return True
        dropped.append(clause_text)
        return False

    escalation: Escalation | None = rules.escalation
    if escalation is not None and not verdict(escalation.clause_text):
        escalation = None

    discounts = [d for d in rules.discounts if verdict(d.clause_text)]
    milestones = [m for m in rules.milestones if verdict(m.clause_text)]

    return (
        rules.model_copy(
            update={
                "escalation": escalation,
                "discounts": discounts,
                "milestones": milestones,
            }
        ),
        dropped,
        grounded,
        blank,
    )


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


def _first_set(values: list, default=None):
    for value in values:
        if value is not None and value != "":
            return value
    return default


def merge(results: list[ContractRules]) -> ContractRules | None:
    """Fold per-chunk extractions into one.

    Scalars take the first chunk that stated them, because chunk 0 is the front
    of the contract where the parties, the term and the headline fee live.
    Lists concatenate and de-duplicate — the same discount quoted in two
    overlapping chunks is one discount.
    """
    if not results:
        return None
    if len(results) == 1:
        return results[0]

    names = [r.client_name for r in results if r.client_name and r.client_name.lower() != "null"]
    client_name = Counter(names).most_common(1)[0][0] if names else results[0].client_name

    seen_discounts: dict[tuple, Discount] = {}
    for result in results:
        for discount in result.discounts:
            seen_discounts.setdefault(
                (discount.percentage, discount.duration_months), discount
            )

    seen_milestones: dict[tuple, Milestone] = {}
    for result in results:
        for milestone in result.milestones:
            seen_milestones.setdefault(
                (milestone.description.strip().lower(), milestone.amount), milestone
            )

    return ContractRules(
        client_name=client_name,
        contract_start_date=_first_set([r.contract_start_date for r in results]),
        contract_end_date=_first_set([r.contract_end_date for r in results]),
        base_amount=_first_set([r.base_amount for r in results]),
        currency=_first_set([r.currency for r in results], "USD"),
        billing_frequency=_first_set(
            [r.billing_frequency for r in results if r.billing_frequency != "unknown"],
            "unknown",
        ),
        payment_terms=_first_set([r.payment_terms for r in results]),
        escalation=_first_set([r.escalation for r in results]),
        discounts=list(seen_discounts.values()),
        milestones=list(seen_milestones.values()),
    )


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


def extract_rules_verbose(doc: ExtractedDoc, *, max_chunks: int = MAX_CHUNKS) -> ExtractionReport:
    """`extract_rules` with the numbers the eval harness needs."""
    if doc.doc_type == "csv":
        return ExtractionReport(None, error="a CSV of actuals carries no contract rules")
    if not doc.full_text or not doc.full_text.strip():
        return ExtractionReport(None, error="the document has no extractable text")

    all_chunks = split_chunks(doc.full_text)
    chunks = select_chunks(doc.full_text, max_chunks)
    report = ExtractionReport(None, chunks_total=len(all_chunks), chunks_sent=len(chunks))

    parsed: list[ContractRules] = []
    for index, chunk in enumerate(chunks, start=1):
        result = llm_client.complete_json(
            prompts.extraction_user(chunk, part=index, of=len(chunks)),
            ContractRules,
            system=prompts.EXTRACTION_SYSTEM,
        )
        if result is None:
            log.warning("chunk %d/%d produced no valid JSON", index, len(chunks))
            continue
        parsed.append(result)

    report.chunks_parsed = len(parsed)
    if not parsed:
        report.error = llm_client.last_error() or "no chunk produced valid ContractRules"
        return report

    merged = merge(parsed)
    if merged is None:
        report.error = "nothing to merge"
        return report

    grounded_rules, dropped, grounded, blank = _ground(merged, doc.full_text)
    report.rules = grounded_rules
    report.dropped = dropped
    report.blank = blank
    report.grounded = grounded
    if dropped:
        log.info("dropped %d ungrounded clause(s) — quotes not present in the document", len(dropped))
    if blank:
        log.info("dropped %d clause(s) the model left unquoted", len(blank))
    return report


def extract_rules(doc: ExtractedDoc) -> ContractRules | None:
    """Contract text -> rules, or None when the model could not deliver.

    Never raises. `None` means the endpoint was down, no chunk produced valid
    JSON, or the document was not a contract.
    """
    return extract_rules_verbose(doc).rules
