"""[B] Every prompt template, in one place. Phase 5.

Versioned on purpose, so Phase 11 can report which template produced a number.
Cache invalidation is automatic and needs no version bump: `cache.key()` hashes
the rendered prompt and system text, so editing a template invalidates exactly
the answers that template produced and leaves every other entry alone.

Two hard rules govern everything in this file:

* **No coordinates, ever** (ADR-005). The model is never asked for a page, a
  bounding box or a position. It copies a sentence; `clause_locator` finds where
  that sentence lives. A prompt that mentions pages invites a hallucinated one.
* **No arithmetic.** The model copies figures as written. Every calculation in
  FinSight happens in `core/engine/`, in Python, deterministically.

The instructions are deliberately one-per-line and blunt. A 3B model needs a
tighter prompt than a frontier model did — that is the expected starting point,
not a failure (known issue #8), and Phase 10 is what closes the gap.
"""

from __future__ import annotations

#: v2 (2026-08-14) — first revision made against real model output rather than
#: guesswork. v1 scored 10/10 valid but extracted a base_amount in 2 of 10
#: contracts, a billing frequency in 1 and an escalation in 1, on a corpus
#: selected *because* every contract has all three. The diagnosis was rule 3,
#: "If a field is not stated, use null. Never guess a value." A 3B model reads
#: that as "when unsure, leave it blank", and it is unsure often. v2 splits the
#: two ideas the old rule conflated: null means the contract is silent, not that
#: the reader is uncertain. It also names the wordings real contracts use, since
#: the failures were on sentences that said "shall increase" rather than
#: "escalation" and "per month" rather than "monthly".
#: v3 (2026-08-14) — v2 tripled what was extracted (base_amount 2->5 of 10,
#: frequency 1->4, escalation 1->3) and halved quote fidelity, 80% -> 51.5%.
#: Splitting the 16 rejected quotes showed the model had NOT got sloppier:
#: genuine fabrication went 3 -> 4. The collapse was two mechanical faults —
#: 8 quotes copied out of this file's own worked example, and 4 written as the
#: literal string "null". Rule 11 addresses the first; rule 12 and
#: contract_extractor.is_absent() address the second.
#: v4 (2026-08-14) — v3's explicit "never copy from the example" rule changed
#: nothing: still 8 copied quotes in 10 contracts, identical to v2. Adjacency
#: beat instruction. v4 therefore MOVES the example out of the user turn (where
#: it sat immediately above the contract) into the tail of this system prompt,
#: and the user turn now carries the contract alone. It also drops v3's "worse
#: than no answer at all", which bought quote fidelity by making the model
#: timid again (base_amount 5 -> 3 of 10).
PROMPT_VERSION = "v4"

#: The shape the model must produce. Shown to the model literally, because a 3B
#: model follows an example far better than it follows a description of one.
CONTRACT_RULES_SKELETON = """{
  "client_name": "string",
  "contract_start_date": "YYYY-MM-DD or null",
  "contract_end_date": "YYYY-MM-DD or null",
  "base_amount": number or null,
  "currency": "USD",
  "billing_frequency": "monthly | quarterly | annual | one_time | unknown",
  "payment_terms": "string or null",
  "escalation": {"percentage": number, "after_months": number, "clause_text": "string"} or null,
  "discounts": [{"percentage": number, "duration_months": number, "clause_text": "string"}],
  "milestones": [{"description": "string", "amount": number, "due_condition": "string or null", "clause_text": "string"}]
}"""

EXTRACTION_EXAMPLE_INPUT = """MASTER SERVICES AGREEMENT between Northwind Studio LLC ("Provider") and Starter Labs, Inc. ("Client"), effective January 15, 2025 and continuing for twelve (12) months.

3.1 Client shall pay Provider a monthly retainer of $6,000, invoiced on the first day of each month, payable Net 30.
3.2 A 10% introductory discount applies for the first three months of the Term.
3.3 Fees shall increase by 8% on each anniversary of the Effective Date.
3.4 A milestone payment of $15,000 is due upon delivery of the final website.
9.2 Any dispute not resolved within ten days shall be escalated to the parties' senior executives."""

EXTRACTION_EXAMPLE_OUTPUT = """{
  "client_name": "Starter Labs, Inc.",
  "contract_start_date": "2025-01-15",
  "contract_end_date": "2026-01-14",
  "base_amount": 6000.0,
  "currency": "USD",
  "billing_frequency": "monthly",
  "payment_terms": "Net 30",
  "escalation": {"percentage": 8.0, "after_months": 12, "clause_text": "Fees shall increase by 8% on each anniversary of the Effective Date."},
  "discounts": [{"percentage": 10.0, "duration_months": 3, "clause_text": "A 10% introductory discount applies for the first three months of the Term."}],
  "milestones": [{"description": "Final website delivery", "amount": 15000.0, "due_condition": "Upon delivery of the final website", "clause_text": "A milestone payment of $15,000 is due upon delivery of the final website."}]
}"""


EXTRACTION_SYSTEM = f"""You are a contract analysis assistant. You read a commercial contract and extract its financial rules.

Your job is to FIND what the contract says. The contract you are given does contain payment terms — locate them.

Output rules:
1. Output one valid JSON object and nothing else. No prose. No code fences.
2. Use exactly this shape:
{CONTRACT_RULES_SKELETON}
3. Never calculate. Copy every number exactly as the contract writes it.
4. discounts and milestones are lists. Use [] when there are none.

When to use null — read this carefully:
5. null means THE CONTRACT DOES NOT SAY. It does not mean you are unsure.
6. If the contract states something in any wording at all, extract it. Contracts rarely use the words in this schema; "shall pay", "compensation", "consideration", "fees" and "charges" all describe the same thing.
7. Do not use null just because the wording is unusual, the sentence is long, or the figure appears far from the word "fee".
8. Only a genuinely absent fact is null. A redacted figure ([***], [REDACTED], blank) counts as absent.

Clause rules:
9. For every rule you extract, copy the exact sentence it came from into clause_text, character for character.
10. Do not paraphrase, summarise, shorten or tidy that sentence. Copy it, including its numbers and punctuation.
11. Every clause_text must be a sentence from the contract in the user message. The illustration at the end of these instructions uses a different, imaginary contract — never quote from it.
12. If you cannot find an exact sentence for a rule, omit the rule entirely. Do not write "null" into clause_text; leave the whole rule out.

Definitions:
13. base_amount is the recurring fee — the amount paid over and over. Not the total contract value, not a one-off payment.
14. billing_frequency comes from how the contract describes the timing. "per month", "monthly", "each month", "a month" -> monthly. "per quarter", "quarterly" -> quarterly. "per annum", "per year", "annually", "annual fee" -> annual. Use "one_time" for a single payment. Use "unknown" ONLY when no timing word appears anywhere near the amount.
15. escalation is a stated increase in the FEE over time. It is often not called an escalation. "shall increase by", "shall be increased", "shall be adjusted", "uplift", "subject to an annual increase", and any reference to the consumer price index or CPI all count.
16. A procedure for escalating a DISPUTE to senior management is NOT an escalation. Ignore it.
17. A discount is a reduction that applies for a limited number of months. A permanent lower rate is not a discount; it is the base_amount.
18. A milestone is a one-off payment tied to a deliverable or an event.

Worked reasoning for one hard sentence:
    "...payment of the Platform Access Charge per Licensed Unit shall be made from Operator to Supplier in the amount of $4,250 per month through the end of Operator's 2019 fiscal year which stated amount shall increase..."
    base_amount is 4250 — it is an amount paid repeatedly.
    billing_frequency is "monthly" — the sentence says "per month".
    escalation is present — the sentence says "shall increase".
    All three facts came from one sentence. Read the whole sentence before deciding anything is absent.

ILLUSTRATION ONLY — an imaginary contract, shown so you can see the output format. Its sentences are NOT available to quote.

Imaginary contract:
{EXTRACTION_EXAMPLE_INPUT}

Correct output for that imaginary contract:
{EXTRACTION_EXAMPLE_OUTPUT}

The real contract follows in the user message. Quote only from that."""


def extraction_user(contract_text: str, *, part: int = 1, of: int = 1) -> str:
    """The user turn: **the real contract only.**

    v4 moved the worked example out of here and into `EXTRACTION_SYSTEM`. It
    used to sit directly above the contract, and the model copied sentences out
    of it into `clause_text` 8 times in 10 contracts — v3 added an explicit
    "never copy from the example" rule and the count did not move at all. For a
    3B model, adjacency beats instruction: the example was the nearest thing
    that looked like a contract clause, so it got quoted. The fix is distance,
    not more prose.

    The example still carries the dispute-escalation trap on purpose. 68 of the
    81 CUAD contracts matching "escalat" mean dispute procedure rather than a
    price rise (known issue #24); showing the model one it must ignore is
    cheaper than any amount of prose telling it to.
    """
    header = "" if of == 1 else (
        f"This is part {part} of {of} of one contract. Extract only what THIS part "
        "states. Use null for anything it does not mention.\n\n"
    )
    return (
        f"{header}"
        "Read this contract and extract its financial rules as JSON.\n"
        "Every clause_text must be a sentence copied from the contract below.\n\n"
        "Contract:\n"
        f"{contract_text}\n\n"
        "JSON:"
    )
