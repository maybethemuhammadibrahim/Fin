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

PROMPT_VERSION = "v1"

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

EXTRACTION_SYSTEM = f"""You are a contract analysis assistant. You read a commercial contract and extract its financial rules.

Output rules:
1. Output one valid JSON object and nothing else. No prose. No code fences.
2. Use exactly this shape:
{CONTRACT_RULES_SKELETON}
3. If a field is not stated in the contract, use null. Never guess a value.
4. Never calculate. Copy every number exactly as the contract writes it.
5. discounts and milestones are lists. Use [] when there are none.

Clause rules:
6. For every rule you extract, copy the exact sentence it came from into clause_text, character for character.
7. Do not paraphrase, summarise, shorten or tidy that sentence.
8. If you cannot find an exact sentence for a rule, omit the rule entirely.

Definitions:
9. base_amount is the recurring fee, not a total contract value and not a one-off payment.
10. escalation is a stated increase in the FEE over time, such as an annual percentage uplift or a CPI adjustment. A procedure for escalating a DISPUTE to senior management is not an escalation — ignore it.
11. A discount is a reduction that applies for a limited number of months. A permanent lower rate is not a discount; it is the base_amount.
12. A milestone is a one-off payment tied to a deliverable or an event.
13. If a figure is redacted (for example [***]), treat it as not stated and use null."""

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


def extraction_user(contract_text: str, *, part: int = 1, of: int = 1) -> str:
    """The user turn: one worked example, then the real contract.

    The example carries the dispute-escalation trap (clause 9.2 above) on
    purpose. 68 of the 81 CUAD contracts matching "escalat" mean dispute
    procedure rather than a price rise (known issue #24); showing the model one
    it must ignore is cheaper than any amount of prose telling it to.
    """
    header = "" if of == 1 else (
        f"This is part {part} of {of} of one contract. Extract only what THIS part "
        "states. Use null for anything it does not mention.\n\n"
    )
    return (
        "Example contract:\n"
        f"{EXTRACTION_EXAMPLE_INPUT}\n\n"
        "Example output:\n"
        f"{EXTRACTION_EXAMPLE_OUTPUT}\n\n"
        "Now do the same for this contract.\n\n"
        f"{header}"
        "Contract:\n"
        f"{contract_text}\n\n"
        "JSON:"
    )
