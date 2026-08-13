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

#: More than this and cost grows without finding much: fee terms cluster in the
#: first few pages and in the payment article.
MAX_CHUNKS = 3

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


def _ground(rules: ContractRules, document_text: str) -> tuple[ContractRules, list[str], int]:
    """Strip every rule whose quote is not in the document."""
    dropped: list[str] = []
    grounded = 0

    escalation: Escalation | None = rules.escalation
    if escalation is not None:
        if is_verbatim(escalation.clause_text, document_text):
            grounded += 1
        else:
            dropped.append(escalation.clause_text)
            escalation = None

    discounts: list[Discount] = []
    for discount in rules.discounts:
        if is_verbatim(discount.clause_text, document_text):
            discounts.append(discount)
            grounded += 1
        else:
            dropped.append(discount.clause_text)

    milestones: list[Milestone] = []
    for milestone in rules.milestones:
        if is_verbatim(milestone.clause_text, document_text):
            milestones.append(milestone)
            grounded += 1
        else:
            dropped.append(milestone.clause_text)

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

    grounded_rules, dropped, grounded = _ground(merged, doc.full_text)
    report.rules = grounded_rules
    report.dropped = dropped
    report.grounded = grounded
    if dropped:
        log.info("dropped %d ungrounded clause(s) — quotes not present in the document", len(dropped))
    return report


def extract_rules(doc: ExtractedDoc) -> ContractRules | None:
    """Contract text -> rules, or None when the model could not deliver.

    Never raises. `None` means the endpoint was down, no chunk produced valid
    JSON, or the document was not a contract.
    """
    return extract_rules_verbose(doc).rules
