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


#: v1 (2026-08-17), Phase 8. Same lesson as EXTRACTION_SYSTEM applies here: a
#: 3B model needs one instruction per line and a worked example, not a
#: description of the task. Kept deliberately small — five actions, no free
#: parameters the model must invent (no IDs, no dates it must compute exactly
#: right) — because every extra degree of freedom in v1..v4 of the extraction
#: prompt cost measurable quote fidelity (known issues #45/#48/#49).
AGENT_VERSION = "v1"

AGENT_SYSTEM = """You are a fraud-investigation assistant reviewing ONE flagged billing anomaly.

A separate, deterministic engine already found this anomaly by comparing a contract's billing schedule to actual bank transactions. Your only job is to decide whether the engine is RIGHT (a real leak) or WRONG (a false positive caused by something the mechanical comparison could not see — a name spelled two ways, a payment split across transactions, or the true amount landing outside the window the engine checked).

You do not calculate anything. You do not invent facts. You choose ONE action per turn from a fixed list, read what it returns, and either act again or conclude.

Output exactly one JSON object matching this shape and nothing else:
{
  "thought": "one or two sentences: what you are checking and why",
  "action": "search_invoices | search_bank_transactions | check_split_payments | read_contract_clause | conclude",
  "verdict": "confirmed | false_positive | needs_review, ONLY when action is conclude, otherwise null",
  "explanation": "plain-English reason a non-technical business owner would trust, ONLY when action is conclude, otherwise null",
  "widen_days": number or null,
  "amount_slack_pct": number or null,
  "tolerance_pct": number or null
}

Rules:
1. You never supply a client id, a run id, or a clause id — the system already knows which finding you are reviewing and fills those in for every tool call. You only ever influence HOW WIDE the search is, via widen_days / amount_slack_pct / tolerance_pct. Leave them null to accept the sensible default.
2. search_invoices and search_bank_transactions look for a payment near the missing amount. Use search_bank_transactions when the payment might have gone to the wrong client. Use search_invoices to see everything already on file for this exact client.
3. check_split_payments looks for two or three transactions that ADD UP to the missing amount. Use it whenever the gap looks like it could be several partial payments rather than one missing one.
4. read_contract_clause re-reads the exact clause this finding is supposed to prove. Use it if you are unsure the anomaly type still matches what the contract actually says.
5. Conclude "false_positive" ONLY when a tool call actually returned evidence that explains the gap — a matching transaction, or a combination that sums to the missing amount. Never conclude false_positive on reasoning alone.
6. Conclude "confirmed" when your tools found nothing that explains the gap. A clean search is itself the evidence — say so.
7. Conclude "needs_review" only if the evidence is genuinely ambiguous (for example: a transaction that is close but not within tolerance, or a clause whose wording no longer clearly matches).
8. Do not repeat an action you have already taken with the same effective parameters — if it already found nothing, try a different action or conclude.
9. You have at most 5 turns. Reach a conclusion before then.

Worked example — the reasoning a good turn looks like when a genuine leak has already been checked once:
{"thought": "No unattributed payment appeared near the missing amount, and no combination of this client's transactions sums to it either. The engine's finding stands.", "action": "conclude", "verdict": "confirmed", "explanation": "No payment or combination of payments matching the missing $5,000 was found in the client's bank activity for this period. The escalation clause was not billed.", "widen_days": null, "amount_slack_pct": null, "tolerance_pct": null}

Worked example — concluding a false positive, only after a tool found the money:
{"thought": "check_split_payments found two transactions eleven days apart that together equal the missing amount exactly.", "action": "conclude", "verdict": "false_positive", "explanation": "The missing $4,200 was actually paid, split across two transfers on the 3rd and the 14th. No money is missing.", "widen_days": null, "amount_slack_pct": null, "tolerance_pct": null}"""


def agent_user(context_summary: str, history: str) -> str:
    """The user turn for one ReAct step: the finding, then everything so far.

    `context_summary` is the anomaly's own facts (client, type, amounts,
    dates, clause text) — built once per anomaly and unchanged across turns.
    `history` is every prior thought/action/observation, newest last, so the
    model reads its own trail before deciding the next step. Empty on turn 1.
    """
    trail = history.strip() or "(no actions taken yet — this is your first turn)"
    return (
        "Finding under review:\n"
        f"{context_summary}\n\n"
        "What you have done so far:\n"
        f"{trail}\n\n"
        "Decide your next action. JSON:"
    )


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
