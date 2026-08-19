# Base vs tuned — the measured result

**Measured:** 2026-08-19 · **Harness:** `training/evaluate.py` · **Prompt:** v4
**Raw data:** `data/eval/phase11_base_vs_tuned.json`

One command, one process, one live Colab T4 serving **both** models at once:

```bash
python training/evaluate.py --base Qwen/Qwen2.5-3B-Instruct --tuned finsight-tuned
```

The only thing that differs between the two passes is `endpoints.set_model()`.
Same endpoint, same prompt, same questions, same marker — one variable, as the
plan required.

---

## What was on the paper

**20 questions, not 22.** Two of the sealed answers do not parse as
`ContractRules` and there is nothing to mark against; they are found by
validating every answer key, never by row number, and both are named below.

| | |
|---|---|
| Contracts marked | 20 |
| With a fee amount | 20 |
| With a price rise | 8 |
| With a discount | 1 |
| With a milestone | 1 |
| Billing mix | 18 monthly, 2 annual |

**Two measures rest on a thin base and must not be quoted bare.** Answering
"monthly" every time scores **90%** on billing rhythm without reading anything;
discounts and milestones appear once each and support no claim at all.

---

## The scorecard

| Out of 20 | base | tuned | change |
|---|---|---|---|
| Gave a usable answer | 20 (100%) | 20 (100%) | 0 |
| **Fee amount right** | 13 (65%) | **20 (100%)** | **+7** |
| **Billing rhythm right** | 11 (55%) | **18 (90%)** | **+7** |
| Price rise right | 15 (75%) | 8 (40%) | **−7** |
| **Found anything at all** | 17 (85%) | **20 (100%)** | **+3** |
| Quotes really in the text | 14/14 (100%) | 20/20 (100%) | 0 |

**Fine-tuning worked.** Every fee amount correct is the headline: it is the
figure the whole product multiplies. The base model left 3 contracts entirely
empty — the failure known issue #49 warned about, where an empty
`ContractRules` is structurally valid and proves nothing. The tuned model left
none.

**Neither model invented a sentence.** 100% of quotes from both are genuinely
in the document, which is what `clause_locator` and the clause viewer depend on.

The tuned model's 90% on billing rhythm is **not** the lazy score: it answered
monthly 16 times, annual 3, one-time once. It is reading, not guessing.

---

## The one regression, decomposed

Read the price-rise row carefully — the headline is a true sentence that gives
a false impression.

On contracts that **genuinely have** a price rise, the two models are close and
both are good:

| | base | tuned |
|---|---|---|
| Real escalations found (of 8) | 7 | 6 |
| …percentage correct | **7 of 7** | **6 of 6** |

The entire regression is **false positives** — claiming a rise where the key
says none:

| | base | tuned |
|---|---|---|
| Escalations claimed (8 exist) | 11 | 16 |
| Wrongly claimed | 4 | **10** |
| …of which the percentage was `0.0` | 0 | **5** |

A 0% rise is not a rise. That is a defect the fine-tuning introduced and the
base model never showed.

---

## Reading the five remaining false positives by hand

The other five tuned false positives quote a **real** clause. Each was read
against its contract on 2026-08-19. The result is not "the key is wrong" — it
is that **both** are wrong, in different ways.

| Contract | Is there really a rise? | Is the percentage in the text? | Verdict |
|---|---|---|---|
| Aureus Greenway EX-10.4 | **Yes** — section headed *"b. Price Increases"*: monthly fee rises every 12 months by *"the greater of i) 3% or ii) CPI"* | **Yes, 3%** | **Model right, key wrong** |
| Pinnacle Airlines EX-10.24 | **Yes** — rate rises each January by PPI | 5% is in the text but it is the **cap** (*"in no event in excess of five percent"*), not the rate | Rise real, number misread |
| Martin Midstream EX-10.6 | **Yes** — Tank Lease Fee *"adjusted annually … by a factor equal to the increase or decrease … in the CPI"* | **No — "1%" appears nowhere in the document** | Rise real, number fabricated |
| Poindexter EX-10.9 | **Yes** — Management Fee *"adjusted annually, on each anniversary date … in accordance with the percentage increase in the CPI"* | **No — "1%" appears nowhere** | Rise real, number fabricated |
| InterDent EX-10.15 | **Arguably not** — a right to *"review"* and *"be entitled to adjust"* the fee to reflect actual costs; no rate, no guarantee it rises | **No — "5%" appears nowhere** | **Key right, model wrong** |

**Score: the rise is real in 4 of 5; the percentage is text-supported in 1 of 5.**

Two things follow, and the second is the more serious.

1. **The sealed key under-reports escalations.** Four genuine rise clauses are
   recorded as absent. The base model hit the same wall — 3 of its 4 false
   positives are also real clauses the key omits.
2. **The tuned model fabricates rates.** Three percentages appear nowhere in
   their documents. It also does not read a number's *role*: it took a 3%
   **floor** at Aureus and a 5% **cap** at Pinnacle as if both were the rate.

**Why (2) is the dangerous one.** Every one of those quotes passed the grounding
check, so the clause viewer would show a genuine, highlighted sentence with an
invented percentage beside it, and the engine would multiply that percentage by
a real fee — $585,000 at Poindexter. A fabricated finding that *looks verified*
is worse than an obviously broken one.

---

## The root cause the exam exposed

`ContractRules` cannot express **"this rule exists, but its rate is not a fixed
number."** `Escalation.percentage` and `Discount.percentage` are required
floats.

A reviewer meeting *"rises with CPI"* has two bad options: invent a number, or
record no escalation. They correctly refused to invent — so it went down as
absent, and a model that reads the clause correctly is now marked wrong.

**The two unmarkable rows are the same defect, not a separate one:**

| Row | What the reviewer met | What they had to write |
|---|---|---|
| `HIRTLE_CALLAGHAN_TRUST_EX-99.H.6.B` | *"Foreside will waive a portion of the annual fee equal to fifty percent (50%) of the cost of Citigroup Fund Services' compliance data…"* — a real discount whose size depends on another cost | `percentage: null` → row unparseable |
| `StableCoinX_Inc_EX-10.14` | *"During the Free Service Period … no fees shall be payable"* — a real discount with no stated month count | `duration_months: null` → row unparseable |

So the two unmarkable rows and the four escalation disagreements are **one
schema gap, not six review errors**.

---

## What this does and does not license

**Can be said:** fine-tuning measurably improved fee extraction (65% → 100%),
billing frequency (55% → 90%) and refusal-to-answer (85% → 100%), on 20 sealed
real contracts, with quote fidelity holding at 100% on both sides.

**Cannot be said:** anything about discounts or milestones (n=1 each); that the
tuned model is better at price rises; or that the price-rise column measures
what it claims to, while the key cannot record inflation-linked rises.

**Deliberately not done:** the key was **not** re-opened after seeing results.
Correcting a sealed exam once the scores are visible is how a defensible number
becomes an indefensible one, even when the correction is legitimate. The
disagreements are reported instead.

---

## The fix this points at

Not "reject 0%" — too narrow. The rule the codebase already applies to
sentences, applied to figures:

> **Reject an escalation whose percentage does not appear in the clause it
> quotes**, exactly as `contract_extractor.is_verbatim()` rejects a quote that
> does not appear in the document.

Deterministic, no model involved, and it removes 8 of the tuned model's 10 false
positives (5 zero-percent, 3 fabricated) while leaving Aureus standing. Not yet
built.
