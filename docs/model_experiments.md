# Model selection and extraction experiments

**What this file is for.** A plain-English record of which model we chose, what
went wrong when we first ran it for real, and what we did about it. Written so
it can be read straight into a report or a presentation.

Everything here was measured, not estimated. The commands are at the bottom so
any number can be re-checked.

---

## The setup

| | |
|---|---|
| **Model** | Qwen 2.5 3B Instruct — open source, base weights, no fine-tuning yet |
| **Where it runs** | A free Google Colab notebook with a T4 graphics card |
| **How the app reaches it** | An ordinary web address, opened by the notebook |
| **What we test it on** | 10 real contracts filed with the US SEC |
| **First measured** | 14 August 2026 |

We deliberately do not use any paid AI service. Every answer in FinSight comes
from a model we host ourselves, which means the results are ours to explain and
nobody can change the model underneath us between testing and demo day.

---

## Choosing the contracts: why we switched sources

Before any of the model work, we had to decide what to test on. This decision
came first and it changed everything after it.

We started with **CUAD** — a well-known public set of 510 real commercial
contracts. It looked ideal. It wasn't.

FinSight only works on contracts that state **a recurring fee** and **a rule for
that fee changing over time**. We checked how many CUAD contracts actually have
both:

| Source | Contracts with a real fee *and* a real increase clause |
|---|---|
| CUAD | **8 of 510 — 1.6%** (only 3 survived a human read) |
| SEC EDGAR, searching for service agreements | **17.7%** |

So we switched to **EDGAR** as the main source and kept CUAD for side tasks.
That is roughly a tenfold improvement in usable material, and it cost one
afternoon to discover.

**Three traps we hit while building the contract set** — each one would have
quietly corrupted our results:

1. **Searching for the word "escalation" does not find price rises.** Of 81
   contracts containing it, **68 meant escalating a *dispute* to senior
   management.** Wrong meaning entirely. We now search for an actual percentage
   attached to a fee.
2. **About a quarter of contracts hide their numbers.** Companies are allowed to
   redact commercially sensitive figures, so a contract reads *"fees shall
   increase by [***] percent"*. Where we needed those numbers we filled them in
   with ordinary Python code using a fixed seed — never with a model — and wrote
   down every value we inserted. Because our code chose the number, the answer
   key is correct by definition.
3. **Counting documents overstated our collection by about 2.5x.** 51 documents
   contained only 21 genuinely different clauses, because one administrator sends
   every client the same letter. We now count distinct clauses, not files.

---

## Getting the model running: two problems that only appear on real hardware

The serving code had been written and tested against a fake server. It had never
run on an actual graphics card. Both problems below appeared within minutes of
trying, and neither could have been caught any earlier.

**1. The notebook could not read its own password.**

Colab keeps secrets in a locked drawer that only the notebook itself can open.
Our script ran as a *separate program*, so it found the drawer locked and
stopped with a confusing message about a missing "kernel".

*Fix:* the notebook opens the drawer and passes the secret to the program as an
ordinary setting. Two extra lines. Kaggle does not have this problem at all.

**2. Installing the serving software broke the notebook.**

Installing our serving tool upgraded a core library. A second library that Colab
pre-installs was then out of step with it, and the server refused to start —
complaining about an audio component we never use and do not need.

*Fix:* remove the audio component after installing. We serve text.

Both fixes are written up in `README.md` under *Starting a session*.

**One rough edge we chose not to fix while measuring:** when the server dies at
startup, our script does not notice and waits a full **15 minutes** before giving
up. One-line fix, deliberately left until measurement was finished.

---

## The first real measurement

The model had to pass two tests:

- **Valid output** — did it return a properly structured answer? Target: 8 of 10.
- **Honest quotes** — when it says a rule came from a sentence, is that sentence
  really in the contract? Target: 80%.

That second test is the important one. It is what stops the app showing a
customer a rule that the model invented.

**Result: 10/10 valid, 80.0% honest quotes. Both passed.**

And both were weaker than they looked.

---

## The problem we found by looking past the score

Passing did not mean working. When we read what the model had actually pulled
out of ten contracts:

| What we asked for | How often it found it |
|---|---|
| Client name | 10 of 10 |
| The money amount | **2 of 10** |
| How often to bill | **1 of 10** |
| The price increase rule | **1 of 10** |

**Every one of those ten contracts was chosen *because* it contains a fee and a
price increase.** The model was handed ten contracts that definitely have this
information and found the fee in two.

It passed anyway, because the test only checked whether quotes were honest —
and a model that says almost nothing tells almost no lies.

*This is the single most useful thing we learned all day: our scoreboard
rewarded silence.*

---

## Why it was staying silent

We checked whether the model was even being shown the money. For long contracts,
it wasn't:

| Length | Contract pieces sent to the model | Money it could see |
|---|---|---|
| Short (10k–30k characters) | all of them | 100% |
| Long (100k+ characters) | 3 of 9–13 | **22–33%** |

Long contracts were being cut into pieces and only the best three were sent. We
were blaming the model for not finding figures it had never been shown.

But that only explained three of the ten. For the other seven, the money was
right there in what it read. The clearest case was a contract saying:

> "…in the amount of **$6,000 per month** … which additional amount shall
> **increase**…"

Three of our answers sit in that one sentence. The model reported the $6,000,
then said it did not know the billing frequency and that there was no price
increase.

That is not a model that is too small to read. That is a model following its
instructions — and our instructions said:

> *"If a field is not stated in the contract, use null. Never guess a value."*

That sounds careful, but it asks for two different things at once: *don't invent
facts* (good) and *don't answer when unsure* (bad). A small model cannot
separate them, so it stays quiet.

---

## What we changed, and what happened

We ran four versions of the instructions. Each row is a real measurement on the
same ten contracts.

| | v1 (original) | v2 | v3 | v4 |
|---|---|---|---|---|
| Honest quotes | **80.0%** | 51.5% | 65.4% | *see below* |
| — invented quotes | 3 | 4 | **1** | |
| — copied from our own example | ~0 | 8 | 8 | |
| — wrote "null" instead of a sentence | 0 | 4 | **0** | |
| Found the money amount | 2/10 | **5/10** | 3/10 | |
| Found the billing frequency | 1/10 | **4/10** | 2/10 | |
| Found the price increase | 1/10 | **3/10** | 1/10 | |

**v2 — separate "unsure" from "not stated".** We rewrote the rule so that blank
means *the contract is silent*, not *you are uncertain*, and we listed the real
wordings contracts use ("shall increase" rather than "escalation"). We also
raised the number of contract pieces sent from 3 to 6, which lifted the money
the model can see from 77% to 94%.

*Result:* everything we wanted roughly **tripled**. Honest quotes **halved**.

**Why the score fell — and it is not what it looks like.** We sorted every
rejected quote by cause:

- **8** were sentences copied out of *our own teaching example*
- **4** were the literal word `"null"` typed into the sentence box
- **1–4** were genuine inventions

Invented quotes barely moved: 3 before, 4 after. The collapse was two mechanical
faults, and the bigger one was ours. Our instructions show the model a pretend
contract to demonstrate the format. When we pushed it to find more, it reached
for the nearest thing resembling a contract clause — the pretend one.

**v3 — fix the mechanical faults.** We told it not to write "null", fixed a real
bug in our own code that counted *"gave no quote"* identically to *"invented a
quote"*, and told it plainly not to copy the example.

*Result:* the `"null"` problem went to zero. Invented quotes fell to **1**, the
best of any version. But the copying **did not change at all — still 8.** And
being stricter made it timid again, giving back most of v2's gains.

**v4 — stop asking, start moving.** If instructions cannot stop it copying the
example, position might. The example used to sit directly above the real
contract. We moved it into the rules section, far away, and left the contract
alone in its own message.

---

## Honest notes on method

Things that could make these numbers misleading, stated so a reader can judge
them:

- **Small sample.** 10 contracts, 15–33 quotes. An early 2-contract check read
  66.7% where the full run read 80.0%. Individual figures move a lot.
- **We nearly cheated by accident.** The first draft of the v2 instructions used
  a real sentence from one of the ten test contracts as its worked example —
  handing the model an answer from its own exam. We caught it and replaced it
  with an invented sentence.
- **We changed how we count mid-way.** In v3 we separated "no quote" from
  "invented quote". We checked this: it changed the v3 score by **0.0
  percentage points**, because the instruction fix removed the problem at source.
  None of the improvement is bookkeeping.
- **These are not our customers' contracts.** They are large-company SEC filings.
  FinSight is aimed at 3–20 person studios. The legal language is genuine; the
  business context is not.

---

## What we decided to do next, and why

**We are not upgrading the model, and we are not fine-tuning yet.**

Every failure examined so far was fixable through instructions or a bug in our
own code — not a lack of model intelligence. Buying a bigger model before
finishing that diagnosis would mean paying for a bigger model to make the same
mistakes.

A larger model does fit our free hardware (a compressed 7B version), and it is
kept in reserve for the moment we choose what to fine-tune. Fine-tuning locks us
to one model, so it has to be the last choice made, not the first.

Fine-tuning is already scheduled as its own phase, with its own comparison
against the untuned model. Doing it now — with no training examples built —
would be doing that work early and badly.

**A new number is now tracked on every run: coverage.** Not "were the quotes
honest" but "did it find what the contract actually states". Without it, a model
that says nothing scores perfectly, and there is no way to prove fine-tuning
improved anything.

---

## How to reproduce any of this

```bash
# the full measurement, against a running notebook
python scripts/eval_extraction.py --limit 10 --pdfs 5

# results, one file per version
data/eval/phase5_extraction.json   # v1
data/eval/phase5_v2.json
data/eval/phase5_v3.json
data/eval/phase5_v4.json
```

The instruction versions are in `core/ai/prompts.py`; each carries a dated
comment explaining what it changed and why. Answers are cached on disk, so
re-running a version already measured costs nothing and takes seconds.
