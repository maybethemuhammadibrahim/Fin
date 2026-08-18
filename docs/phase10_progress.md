# Phase 10 in plain English — where we are, what's next

**Last updated:** 2026-08-17

This is the no-jargon version. The detailed one is `docs/phase10_plan.md`.

---

## What Phase 10 is trying to do

Teach the small AI model we run ourselves to read contracts better, by showing
it lots of worked examples — then **measure whether it actually got better.**

The product already works without this. If the teaching fails completely, the
app runs exactly as it does today. We'd lose a claim, not the demo.

---

## The idea, as an exam

| Thing | What it really is |
|---|---|
| **Training examples** | practice questions, with the answers shown |
| **Test set** | the real exam, sealed in an envelope before anything starts |
| **The one rule** | never practise on the exam paper |

If practice questions and exam questions come from the same place, the model has
seen the answers. It scores brilliantly and the score means nothing. Worse, it
*looks* like success, so nothing warns you.

That is the single thing this phase can get catastrophically wrong, and it is
why the exam was sealed first, before anything else was built.

---

## What is DONE

### 1. We found a lot more contracts ✅

We had 43 real contracts. We now have **192**.

These come from a US government website where companies are legally required to
publish contracts they sign. They are real documents, not made up.

**How we got more:** the old search asked ten very general questions, and general
questions kept returning the same few companies' paperwork over and over. We now
ask forty questions naming specific industries — software, staffing, cleaning,
transport, laboratories, payroll, advertising — and we **cap it at 3 documents
per company** so one company can't flood the results.

Result: 700 documents from **467 different companies**, boiled down to 192
genuinely different contracts.

We also added searches for **discounts**, which we had almost none of, even
though "a discount that was never switched off" is one of the four problems the
product is built to find.

### 2. The exam is sealed ✅

**30 real contracts** are locked away in a separate folder. They were sealed
**before** a single practice question existed.

Three protections, all tested:

- **Nothing can be quietly changed.** Every sealed file has a fingerprint. If one
  is edited, deleted, or an extra is slipped in, a check command says so.
- **A leak can be detected.** We can ask "is this file part of the exam?" and get
  a straight yes or no — and it compares the actual contents, so renaming a file
  doesn't fool it.
- **It refuses to be re-sealed.** Re-sealing after teaching has started is exactly
  how a contaminated exam turns into a clean-looking one. The command refuses.

We also made sure the **record of what was sealed is saved into the project
itself**, not just sitting on this laptop. The contracts folder gets wiped
whenever the project moves to a different machine — it has already happened
twice. The proof that the exam was fair has to survive that, or it proves
nothing.

### 3. The keys were checked ✅

Not just accepted — actually tested:

- **HuggingFace** (where the finished model will be stored) — works, and
  importantly it has *upload* permission, not just download. Getting that wrong
  is a mistake you'd only discover at the very last step.
- **DeepSeek**, through Baseten — works.

One useful discovery while testing: DeepSeek "thinks out loud" before answering,
and you pay for the thinking. Asked to rewrite one sentence, it spent 94% of the
cost thinking and 6% answering. Sending **four sentences at once** cut the
thinking cost by twenty times for the same work. So we'll always send work in
batches, and keep a running total against your $5 limit. If it gets close, we
stop and tell you rather than quietly burning through it.

---

## Decisions made

| Question | Decision |
|---|---|
| Which model? | **Start with the small one (3B).** If it doesn't improve, try the bigger one (7B). |
| Where does the teaching happen? | Free notebook GPU (Colab, or Kaggle for longer runs) |
| Where is the finished model stored? | HuggingFace |
| Where does the app get its answers from? | Modal — a paid service with a stable address |
| Where do practice questions come from? | Written by us from templates, with DeepSeek varying the wording |
| Where do exam questions come from? | **Real contracts only.** Never negotiable. |

### Why small model first

The first attempt is really about **checking the machinery works** — is the data
in the right shape, does the training script run, does the upload succeed, does
the app pick up the result?

None of those depend on which model you used. Finding those problems on the fast
cheap one takes an hour. Finding them on the slow expensive one takes an evening.

If the small model works, you also keep a stronger story: *a small model taught
one specific job can match a much bigger general-purpose one.*

### What counts as "it didn't work"

Decided in advance, on purpose, so it's a measurement and not a mood:

> **The taught model does not beat the untaught model on the 30 sealed
> contracts.**

If that happens, we try the bigger model. And either way, "teaching didn't help"
is a legitimate result to write up — the project plan says so explicitly.

---

## What is NEXT

### ~~Step 3 — Build the practice questions~~ ✅ **DONE 2026-08-17**

**85 practice questions written**, in `training/data/` (73 to learn from, 12 to
check progress against while learning).

Six kinds of contract, roughly 14 of each:

| Kind | What it teaches |
|---|---|
| Monthly fee + yearly increase | a rise that was never applied |
| Monthly fee + introductory discount | a discount never switched off |
| Monthly fee + one-off milestone | a payment never invoiced |
| Quarterly fee + inflation-linked rise | real contracts phrase it this way |
| All three at once | the case where a reader finds one rule and stops |
| **Flat fee, no rules at all** | **that sometimes the answer is "nothing"** |

That last one matters more than it looks. If every practice question contains a
price rise, the model learns to find one whether or not it's there — which is
exactly the mistake it already makes elsewhere in this project.

**Every document also contains a trap on purpose.** A "late payment interest of
18% per annum" line, or a "disputes are escalated to senior management" clause.
These look like the thing we're hunting and are not. The correct answer ignores
them. That's the same mistake the computer made on a real contract, and now the
model is taught not to make it.

**Nothing needs checking**, because we chose every figure before writing the
document. The answer is right by construction.

Three things were proven rather than assumed:

- **The exam guard works.** Asked to use a sealed contract, it refuses and stops.
  Tested before a single question was generated.
- **The quotes are exact.** Every clause quoted in an answer appears
  word-for-word in its document — checked on all 85, zero failures. Without
  this the app can't highlight the clause on the page.
- **DeepSeek can't corrupt anything.** It only rewords, and every reworded clause
  is re-checked for changed figures. **Two rewrites were caught and thrown away**
  for moving a number. The original wording is kept, which is always safe.

**Variety check:** 85 different documents, 85 different answers, 83 different
company names, 71 different ways of wording a clause. Not one document is a
copy of another.

**Cost:** about 27,000 words of API usage — a small fraction of your $5.

### ~~Step 4 — Build the review screen~~ ✅ **DONE 2026-08-17**

```bash
streamlit run scripts/review_testset.py
```

One card at a time: the contract on the left with the quoted sentence
**highlighted**, the answer on the right, the automatic checks underneath, and
three buttons. Every click saves, so closing the tab loses nothing.

**Two things had to be solved first.**

*The contracts were unreadable.* The 30 sealed documents came to **9.4 million
characters** — one of them 5.3 MB by itself. Each is now cut down to a ~4 KB
excerpt: the opening, the fee clause, and the increase clause. You review the
excerpt and the model is scored on the same excerpt, so you are approving
exactly what gets tested.

*The first version threw away good contracts.* It could only approve or discard,
and it binned anything failing a machine check — 22 of 30. But look at why:
Regal Entertainment's contract plainly reads **$6,000** and the draft said there
was no fee. **Discarding a real contract because a machine misread it is
backwards** — that machines misread these is the entire reason this product
exists.

So you can now **fix a wrong answer**, not just accept or reject it. Type the
right number and the contract is saved in seconds. The plan always asked for
*"corrected pairs"*; approve-or-discard was my under-build.

**What reaches you now:**

| | |
|---|---|
| Checks all passed — a quick yes | **8** |
| A fee is there but the draft is wrong — correct it | **20** |
| Nothing to find — you never see these | 2 |

The checks re-run **as you type**, so you can see a ⚠️ turn into a ✅ when you
enter the right value. You are never guessing whether a correction worked.

### Step 5 — YOU check the cards ← **YOU ARE HERE**

```bash
streamlit run scripts/review_testset.py     # 28 cards
python scripts/prepare_testset.py finalize  # when you are done
```

**About 45 minutes, or ~20 minutes each if you split it with your teammate.**
Slightly more than the 30 minutes first estimated, because correcting a card
takes longer than waving one through — and it is what saves the test set from
being too small to prove anything.

Two questions per card:

1. Is this number in the highlighted sentence?
2. Is this sentence about the regular fee the customer pays — **not** interest on
   a late payment, not a complaints procedure?

**If you're unsure, throw it away.** We sealed 30 to keep about 20, precisely so
discarding is free. You cannot damage this by being cautious. The only way to
harm it is waving through something you didn't understand.

There is a real example of why this matters already sitting in the pile: one
contract passed the automatic check on a clause saying "18% per annum" — which
is a **late-payment penalty, not a fee increase.** The computer can't tell.
Your team spotted that exact one by hand once before.

### Step 6 — Teach the model ← **NOTEBOOK IS READY**

`training/finetune_colab.ipynb` — 23 cells, written 2026-08-18. Open it in
Colab, set the runtime to a **T4 GPU**, add `HF_TOKEN` to the Secrets panel,
and run the cells in order. **10–20 minutes of actual training**, about an hour
end to end including the install and the download.

Out comes a **patch** — not a whole new model, just a file of about 50–100 MB
that adjusts the existing one's behaviour. It uploads to your HuggingFace
account as `ibrahim404/finsight-qwen2.5-3b`.

**Cell 5 is the important one.** It compares every training example against
every exam question and **stops the notebook** if any exam text has leaked in.
Do not skip it. Verified against the real files: 22 exam contracts, 85 training
examples, no overlap.

Other things built in because they bite in practice:

- **Checks for a GPU first**, rather than failing confusingly five cells later
- **Removes `torchaudio`** after the install — otherwise the notebook cannot
  import anything (known issue #50, hit for real on Colab in Phase 5)
- **Re-checks the install succeeded**, because a failed one is silent until much later
- **Saves a checkpoint every epoch**, so a dropped tab costs one epoch, not the run

**One thing to know before you run it.** `train.jsonl` is excluded from git, so
the notebook cannot simply clone the repo to find it. It tries three routes in
order: your HuggingFace account, files you drag into Colab's file panel, then
regenerating them from `build_pairs.py`. The simplest is to **drag
`training/data/train.jsonl` and `val.jsonl` into the file panel** on the left.
`eval_set.jsonl` and `core/ai/prompts.py` arrive on their own with the clone.

#### Reviewed 2026-08-18 — four defects found and fixed

The notebook was checked against the real data files and the real dependency
versions before anyone ran it. The data was clean; the notebook was not.

| What was wrong | Effect |
|---|---|
| `SFTConfig(max_seq_length=…)` | TRL renamed the field to `max_length`. Hard crash at the training cell — *after* the 15-minute install and model download. |
| `apply_chat_template(…, return_tensors="pt")` | On transformers 5.x that hands back a dictionary, not a tensor (`return_dict` now defaults to `True`), so `.shape` raised `AttributeError` in the after-training check. |
| `eval_set.jsonl` was never committed | `.gitignore` un-ignores it on purpose, but it had never been `git add`ed, so the clone found nothing and the leak check halted. Same for `data/corpus/heldout/SEALED.json` — the proof the exam was sealed fairly did not survive a machine change, which is the exact thing it exists to do. Both are committed now. |
| **The notebook trained on its own short prompt** | The worst one, because it would not have failed. The app sends `prompts.EXTRACTION_SYSTEM` (v4 — 1,343 tokens of numbered rules, a JSON skeleton and a worked example) plus `extraction_user()`; the notebook taught the model with a two-line substitute. That trains an adapter for a prompt production never sends, and Phase 11 would then be varying two things at once, against its own stated "same endpoint, same prompt, one variable". The notebook now loads `core/ai/prompts.py` out of the clone and **refuses to train if it is missing**. |

Token budget, re-measured with the real Qwen tokenizer once the real prompt was
in place — this is why `MAX_SEQ_LEN` went 2,048 → 4,096:

| | max tokens | fits in 2,048? |
|---|---|---|
| training examples (73) | 1,973 | yes, by 75 |
| validation examples (12) | 1,968 | yes |
| **exam prompts (22)** | **2,378** | **no — 6 of 22 overflow** |

The exam is never trained on, but section 9 runs one through the model and
unsloth caps the session's context at that value, so 2,048 would have quietly
truncated the longest exam contracts and blamed the model for the clause it
never saw.

Two things left open on purpose:

- **2 of the 22 sealed exam answers fail `ContractRules` validation** — rows 6
  and 11 carry a discount with a null percentage / duration. Phase 11's scorer
  will trip on them if it parses gold answers through the schema. Editing a
  sealed test set is a seal-integrity decision, so it was flagged, not fixed.
- The commits are **local**. The clone route only works once they are pushed.

### Step 7 — Sit the exam *(me)*
Open the sealed envelope. Run all 30 contracts through **both** models — with the
patch and without — and compare. One thing changes between the two runs and
nothing else.

### Step 8 — Report the result *(both)*
Better, or not better. Both are real answers.

### Step 9 — Switch it on *(me)*
Upload the patch, load it on Modal, point the app at it. One setting changes and
no code does — that was designed in months ago.

---

## Time, honestly

| | Wall clock | Your attention |
|---|---|---|
| Steps 3–4 (mine) | ~half a day | none |
| Step 5 (yours) | — | **~30 min, or 15 each with your teammate** |
| Step 6 (teaching) | ~1 hour, likely 2 attempts | click run, glance occasionally |
| Steps 7–9 (mine) | ~2 hours | none |

**Your total is under an hour.** If the small model doesn't work and we move to
the bigger one, add roughly 3 hours of waiting — still mostly not yours.

---

## Still needed from you

| | When |
|---|---|
| Nothing right now | — |
| Check the 30 sealed contracts | when the review screen is ready |
| Click run on the teaching notebook | after that |
| A Modal login | only when we switch the app over |

Everything else is already in place.

---

## One thing deliberately set aside

The shared password for your own GPU was published in the project's public
history. You've chosen to leave it, and that's recorded. It can't cost you money
today — but once the app is served from Modal, which bills by the second, the
same exposure stops being about someone borrowing a free GPU and starts being
about a bill. Worth revisiting before that switch, not now.
