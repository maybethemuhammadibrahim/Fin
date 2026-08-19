# FinSight — what it is, how it works, and what it can't do yet

*A complete plain-English tour of the project. Written 2026-08-19. Self-contained —
you do not need the codebase to read it.*

---

## 1. What this tool is

**FinSight reads your client contracts, compares them to what you actually got
paid, and tells you what you're owed but never collected — with the exact
sentence from the contract that proves it.**

It is built for **small business-to-business service companies**: design studios,
dev shops, consultancies. Three to twenty people. No finance department.

### The problem, with real numbers

A studio signs a contract:

- $6,000 per month
- 10% discount for the first three months
- 8% increase every anniversary
- $15,000 when the website launches

Eighteen months later, whoever set up the recurring invoice has left. The invoice
still says **$6,000**.

| What was missed | Why |
|---|---|
| The 8% annual increase | Nobody applied it |
| The intro discount | Never switched off in month four |
| The $15,000 milestone | Delivered, never invoiced |

**About $21,000 gone.** Not stolen — just never noticed.

Accounting software cannot catch this, because **accounting software has never
read the contract.** It knows what you invoiced. It does not know what you were
owed.

### The pitch in one line

> *You are owed money you don't know about. Here it is, here is the exact clause
> that proves it, and here is what it changes about the decision you're trying to
> make.*

That last part is a second screen: ask *"can I afford a $5,000/month hire?"* and
it answers using the recovered money.

---

## 2. The four things it looks for

Every finding is exactly one of these. They cannot overlap — that is by design.

| Type | Plain meaning | How it's detected |
|---|---|---|
| 🔴 **Ghost invoice** | A bill that never went out at all | Nothing in the bank matches an expected charge |
| 🟡 **Forgotten raise** | A price rise that was never applied | The amount still matches the old rate |
| 🟠 **Zombie discount** | A temporary discount never switched off | The amount matches "expected minus an expired discount" |
| 🟣 **Short change** | A partial payment nobody chased | Paid less than expected, and no other rule explains the gap |

---

## 3. Where the data comes from

**Rule: contracts are *sourced* from the real world. Money movements are
*derived* from those contracts by arithmetic. No AI invents either.**

### Real contracts — SEC EDGAR

US companies must legally publish contracts they sign. We search that archive for
service agreements.

| | |
|---|---|
| Documents found | 700 |
| Kept on disk (150 skipped by a per-company cap) | 667 |
| Different companies | 467 |
| **Genuinely distinct contracts** | **192** |
| Ready to use / gaps filled / needs a human read | 60 / 19 / 113 |

**Why the numbers shrink so much.** Counting documents overstates a corpus by
about 2.5×. One fund administrator sends the same fee letter to every trust it
serves. We count **distinct clauses and distinct filers**, never filenames.

### Three findings that cost real time

1. **Never search for the word "escalate".** Of 81 contracts matching it, **68**
   meant *"escalate the dispute to senior management"* — a complaints procedure,
   not a price rise.
2. **About 24% of contracts black out their numbers** (`[***]`, under a
   confidentiality request). A contract can have a perfect price-rise clause and
   still be unusable.
3. **A machine calling a contract "good" is not enough.** One scored as a perfect
   price rise on *"18% per annum"* — which was **interest on late payment**, not a
   fee increase. Only a human read caught it.

### The second corpus — CUAD

510 real commercial contracts, free to use. We tested it first and **demoted it**:
only **8 of 510 (1.6%)** had both a real recurring fee and a real price rise, and
only **3** survived a human read. It is kept for practice material, not for
building test cases.

### Money movements — derived, never invented

`scenario_builder.py` takes a real contract, plants known problems in it, and
writes an answer key. Because we *chose* every planted figure, **the answer is
correct by construction** — nothing needs verifying afterwards.

Where a real contract blacks out a number, `fill_blanks.py` inserts one using
fixed arithmetic — never a model — and **refuses if it cannot tell what kind of
blank it is.** An earlier version guessed, and silently corrupted a rate card.

---

## 4. How it works, end to end

```
   You upload                 Contract PDF / text        Bank CSV
        │                            │                      │
        ▼                            ▼                      ▼
   1. ROUTE by file type ─────────────────────────────────────
        │
        ▼
   2. EXTRACT TEXT          (pdfplumber / PyMuPDF — no AI)
        │
        ▼
   3. READ THE RULES        ← the ONLY place AI is used here
        │                     self-hosted Qwen 2.5 3B
        │                     returns: fee, rhythm, rises, discounts,
        │                     milestones + the exact sentence for each
        ▼
   4. CHECK EVERY QUOTE     (no AI — is that sentence really in the document?
        │                    is that percentage really in that sentence?)
        ▼
   5. BUILD EXPECTED TIMELINE   (pure arithmetic — what SHOULD have been billed,
        │                        month by month)
        ▼
   6. COMPARE to what was actually paid  →  gaps  →  classify into the 4 types
        │
        ▼
   7. FIND THE CLAUSE ON THE PAGE   (code searches the PDF for the sentence
        │                            and draws the box — never the AI)
        ▼
   8. DASHBOARD: findings + clickable proof
        │
        ▼
   9. DECISION ENGINE: "can I afford X?" → Yes/No using the recovered money
```

### Who is allowed to do what

| Layer | May do | May **never** do |
|---|---|---|
| Screens | Show database rows, take uploads | Calculate anything, call the AI directly |
| Text extraction | Turn files into text | Interpret meaning |
| **The AI** | Turn sentences into structured data; phrase explanations | **Do arithmetic. Decide what's a problem. Produce any number you see** |
| The engine | All money maths | Touch the network, database, or AI |
| The agent | Re-check already-flagged items | Find new problems |

---

## 5. The safeguards — the part that makes the numbers trustworthy

These are not style preferences. Each exists because something went wrong without
it.

**1. The AI never does arithmetic.** Every figure on screen is computed by plain
Python. The AI only converts prose into structured fields.

**2. The AI never draws boxes.** It copies a sentence word-for-word. *Code* then
searches the page for that sentence and draws the highlight. A quote that can't be
found was invented, and is thrown away.

**3. A quoted sentence must really be in the document.** Checked every time. This
is what keeps invented quotes out of the database.

**4. A percentage must really be in the sentence it came from.** *(Added
2026-08-19.)* The fine-tuned model was caught quoting a genuine sentence and
attaching a rate that appeared nowhere in the contract — "1%" on a $585,000 fee.
It passed check 3, because the *sentence* was real. Now it fails check 4.

**5. The screens read only the database.** No hardcoded numbers anywhere. This is
why each build stage could replace one table at a time without rewriting the UI.

**6. Engine functions are pure** — no database, no network, no AI, **and no
clock**. A run reconciling a 2025 statement gives the same answer in 2027.

**7. Every finding points at a real clause.** No orphans, enforced by the database.

**8. When it doesn't know, it refuses.** The client-matcher refuses below 85%
confidence rather than guessing whose payment it was. The decision engine refuses
a Yes/No if you haven't told it your expenses. Guessing is worse than blank,
because a wrong guess is invisible.

---

## 6. What's under the hood

| Part | Choice |
|---|---|
| Screens | Streamlit (does the work) + FastAPI/Jinja2 (the designed UI, **read-only**) |
| Database | Supabase Postgres — **12 tables** |
| File storage | Supabase Storage, private bucket |
| PDF text | pdfplumber + PyMuPDF |
| Finding the clause on a page | PyMuPDF search + fuzzy fallback |
| Structured AI output | Pydantic validation + one repair retry |
| Agent | LangGraph, max 5 steps |
| Fine-tuning | Unsloth + QLoRA on a free Colab T4 |

**The 12 tables:** runs, documents, clients, contract_rules, clause_references,
price_escalations, discounts, milestones, expected_timeline, actual_transactions,
anomalies, column_mappings.

**Two screens over one database, and only one of them acts.** The Streamlit app
is where anything happens — upload, reconcile, verify, ask a decision question.
The FastAPI app renders the delivered design and **writes nothing**: every button
in it is deliberately inert, so a fully-styled page there is not a working one.
Both read the same figures through the same code, so they can look different but
cannot disagree.

### The models

| | |
|---|---|
| **The model doing the work** | **Qwen 2.5 3B Instruct** — open source, we host it ourselves |
| Which version runs by default | The **untaught** one. The taught patch of §7 is switched on by hand and is not yet the app's default — see §9 |
| Where it runs | A free Google Colab or Kaggle GPU, reached over a tunnel. Also Modal (paid, stable address) |
| **Frontier AI APIs used at runtime** | **None. Ever.** |
| DeepSeek | Used **once, offline**, only to reword training sentences. Never invents a figure, never writes an answer |

**Why self-hosted matters:** the entire claim of the project is that a small model
you run yourself, taught one specific job, can do professional work. Calling
someone else's big model would dissolve that claim.

---

## 7. Teaching the model — before and after

### What we did

- **85 practice contracts** written from six templates (73 to learn from, 12 to
  check progress). Every figure chosen *before* the document was written, so the
  answers are right by construction.
- **Every practice document contains a deliberate trap** — a "late payment
  interest of 18% per annum" line, or a dispute-escalation clause. These look like
  the target and are not. The correct answer ignores them.
- One template in six is **"flat fee, nothing to find"**, so the model learns that
  sometimes the answer is *nothing*.
- **30 real contracts sealed away as the exam** *before any practice question
  existed*, fingerprinted so they cannot be quietly changed, with a check that
  refuses to re-seal them later.
- Trained with QLoRA on a free T4 — three passes over the 73 examples, budgeted
  at **20–40 minutes**. Output is a **patch of roughly 50–100 MB**, not a new
  model. *(Both figures are the notebook's estimates. Nobody wrote down the real
  duration or the real file size — so unlike every other number in this
  document, these two are not measured.)*

### The exam

Of the 30 sealed contracts, **22** came through review with an answer key, and
**20** of those are markable — 2 keys do not parse (see §9). Both models
answered on the **same** GPU session, with the **same** prompt, in one process.
Only the model name changed.

### Results

| Out of 20 | Before teaching | **After teaching** | Change |
|---|---|---|---|
| Gave a usable answer | 20 | 20 | — |
| **Found the fee amount** | 13 (65%) | **20 (100%)** | **+7** |
| **Got the billing rhythm right** | 11 (55%) | **18 (90%)** | **+7** |
| **Found anything at all** | 17 (85%) | **20 (100%)** | **+3** |
| Got the price rise right | 17 (85%) | 15 (75%) | −2 |
| Quoted sentences that were real | 100% | 100% | — |

**Teaching worked.** Getting all 20 fee amounts right matters most — it is the
number everything else multiplies.

### The honest asterisk

Before the §5 safeguard #4 was added, the taught model looked **much worse** on
price rises (8/20). Investigating that is what found the invented-percentage bug:

| | Before the guard | After |
|---|---|---|
| Untaught model — wrongly claimed a rise | 4 | **2** |
| **Taught model — wrongly claimed a rise** | **10** | **2** |

The teaching made the model *bolder*. Boldness found every fee — and also invented
rates. A plain code rule fixed the second without touching the first.

**The remaining −2 is smaller than this exam can measure.** We wrote down before
seeing any results that a swing of one or two questions is noise.

---

## 8. Everything that was measured, not assumed

| Stage | What was proven | Result |
|---|---|---|
| Database | Same results on Postgres and SQLite | 47 checks, identical |
| Reading contracts | Valid output, quotes real | 10/10 valid, 80% quotes verified* |
| The maths engine | Reproduces three answer keys exactly | 3/3 to the cent |
| Clause highlighting | Box drawn on the right sentence | 20/20 placed |
| Verification agent | Filters false alarms | **Failed — see §9** |
| Decision engine | Right Yes/No, no invented figures | 6/6, guard caught 3 attempts |
| Fine-tuning | Better than untaught | 3 clear wins, 1 too small to call |
| Whole codebase | Automated tests | **248 passing** |

\* **Read that row thinly.** 80.0% was 12 of 15 quotes — it passed exactly on the
line, and one more paraphrase would have failed it. And 3 of the 10 "valid"
contracts returned **no clauses at all**; an empty answer is structurally valid,
so it scores as a pass while proving nothing. The 20-contract exam in §7 is the
number to quote.

### The scripts that do this

| Script | What it does |
|---|---|
| `init_db.py` / `seed_demo.py` / `reset_run.py` | Create tables, load a demo, wipe one run |
| `data_sourcing/fetch_contracts.py` + `filter_contracts.py` | Download from EDGAR and keep only usable ones |
| `data_sourcing/scenario_builder.py` | Plant known problems, write the answer key |
| `scripts/fill_blanks.py` | Fill blacked-out figures with fixed arithmetic; refuses when unsure |
| `scripts/seal_testset.py` | Seal the exam and fingerprint it; refuses to re-seal |
| `scripts/review_testset.py` | The human review screen for the exam |
| `training/build_pairs.py` | Write the 85 practice contracts |
| `training/finetune_colab.ipynb` | The teaching notebook |
| `training/evaluate.py` | The exam marker, both models in one process |
| `scripts/eval_*.py` | One measurement script per stage |
| `scripts/memory_digest.py` | Prints current state in 10 seconds |

### The safety habits worth copying

- **The exam is checked for leaks before every training run**, and the notebook
  **stops** if any exam text appears in the practice material. A leak does not
  announce itself — it just produces a wonderful score.
- **The marker is tested against the answer key itself** and must score 100%. A
  bug in the marker is found before a GPU is booked.
- **An eval that counts outputs is not an eval.** The agent's test once printed
  "All parts passed" while the agent destroyed $21,480 of real findings, because it
  checked that every item got *a* verdict rather than the *right* one.

---

## 9. Problems we have not solved

Listed plainly. These are real and none is hidden.

### 1. The verification agent destroys genuine findings 🔴

Given five real problems, it marked **four of them "false alarm" — $21,480 of
$22,500**. Its own reasoning shows the inversion: *"the missing $5,000 was not
found in the bank activity, indicating this is likely a false positive."* A clean
search is evidence the money **is** missing.

The instructions state this explicitly, with a worked example. **The 3B model does
not follow it.** This is a model-capability limit, not a prompt bug. The agent is
not usable in a demo as it stands.

### 2. It has not been deployed, and the taught model is not switched on 🔴

Two separate gaps, both easy to miss because everything above works locally.

**There is no public address.** The app has only ever run on a laptop. Nothing is
pinned to a known version, there are no automated checks on save, and no hosting
account has been set up. Putting it online is the one piece of work that has not
started.

**The taught model is not what the app uses.** The patch from §7 lives in a
private account, has only ever been loaded in one hand-started notebook, and the
app's default setting still names the **untaught** model. Every "after teaching"
figure in §7 is real; none of it reaches a user until someone changes that
setting and serves the patch. The paid host, which is the only address that does
not change, has never had it loaded either.

### 3. The data shape can't describe inflation-linked rises 🟠

A clause saying *"the fee rises each year with the Consumer Price Index"* has **no
fixed percentage**. Our data requires one. So a reviewer must either invent a
number or record no rise at all.

This single gap explains:
- Both unusable exam answers (a discount worth "50% of the cost of X"; a free
  period with no month count)
- Four contracts where the model correctly found a real rise clause and was marked
  wrong for it
- Why those contracts now report **nothing** after the §5 safeguard. Silence is
  safe. It is not right.

### 4. A price cap still reads as a price rate 🟡

One contract says the rise is inflation *"but in no event in excess of five
percent."* 5% is a **ceiling**, not the rate. Our safeguard checks the number is in
the sentence — it cannot tell a ceiling from a rate.

### 5. The model doesn't always follow instructions 🟡

Told "copy the sentence character for character", it paraphrases about 20% of the
time. In the decision engine, **3 of 6 answers quoted figures it was never given** —
including `$17,272.73`, which looks calculated and is pure invention. A guard
caught every one and fell back to fixed wording. **Report the guard as reliable;
do not report the model as reliable.**

### 6. Milestones are never billed automatically 🟡

A milestone says *"on website launch"*, not a date. Nothing turns a condition into
a date, so it is listed as unresolved rather than billed. Guessing a date would
manufacture fake findings.

### 7. Two months paid in one transfer reads as a missing bill 🟡

A client who skips a month and then sends one larger transfer settles one month
and leaves the other looking unpaid — reported as a ghost invoice that is not
real.

The re-checking tool was meant to catch this and cannot: it looks for **several**
payments that add up to one bill, not for **one** payment worth two bills. Nobody
has built the second case.

### 8. The exam is small, and thin in places 🟡

20 contracts. Only **1** has a discount and **1** has a milestone — those are
effectively unmeasured. And 18 of 20 are monthly, so answering "monthly" every time
scores 90% without reading anything. *(The taught model isn't doing that — it
answered monthly 16, annual 3, one-off 1 — but a reader shouldn't have to trust
that.)*

### 9. Everything depends on a notebook that dies 🟠

The GPU is a free Colab session. Its address changes on every restart, cold start
takes ~8 minutes, and closing the tab takes the whole app down. Fine for a local
demo; not viable for a public site without the paid host, which **has never been
set up** (§2).

### 10. Uploading a contract has never been tested against a live GPU 🟠

The two halves are proven separately — reading a contract was measured on a real
GPU, and saving the result has its own tests — but the join between them, a file
dropped into the app coming out as saved rules, has never once run end to end
with a model answering. With no model running it fails cleanly and says so.
Everything after that point (the maths, the comparison, the highlighting) needs
no model and is fully exercised.

### 11. Known limits accepted on purpose 🟢

- **Typeset pages are not the original filing.** Government filings arrive as web
  pages, so we lay the text out as a PDF to highlight it. Page numbers are ours,
  not the original's — stated on every page.
- **The contracts are large-company filings**, while the target customer is a
  20-person studio. The legal language is genuine; the setting is not.
- **The app tells you what you're owed and what you earn. You tell it what you
  spend.** No table holds expenses, so the decision engine asks — and refuses a
  Yes/No if you don't answer.
- **None of the downloaded contracts are stored in the project.** Everything
  under `data/` is deliberately kept out of version control, so a fresh machine
  starts with an empty corpus — it has been lost twice that way. One command
  rebuilds it, and the counts in §3 will not repeat exactly, because EDGAR
  changes.
- **A password was published in this project's public history** and has not been
  rotated. Harmless while the GPU is free; a billing risk the moment the paid host
  is used.

---

## 10. Why this is worth something

**For the user:** money they already earned, that nobody could otherwise find,
each item traced to the sentence that proves it. Not a guess — a citation.

**Technically:** a 3B open-source model, run on a free GPU, taught one narrow job
in well under an hour, going from **65% to 100%** on the number the product
depends on — while every figure the user sees is computed by plain, testable
Python.

**The design principle underneath all of it:** *let the AI read, never let it
count.* The model turns prose into fields. Arithmetic, classification and
highlighting are ordinary code, and every one of them is tested.

---

## Appendix — suggested diagrams

Data for anyone building visuals from this document.

1. **The pipeline** (§4) — 9 boxes; colour step 3 as "AI", steps 4–7 as "plain
   code". The point: AI touches one box, verification surrounds it.
2. **The four leak types** (§2) — 2×2 grid, keeping the colours.
3. **Before/after fine-tuning** (§7) — grouped bars, 5 measures, 0–20 scale.
   Highlight fee amount 13→20.
4. **The invented-rate story** (§7) — before/after: untaught 4→2, taught 10→2.
5. **Corpus funnel** (§3) — 700 documents → 467 companies → 192 contracts → 60
   ready → 30 sealed → 22 with an answer key → 20 marked.
6. **Layer permissions** (§4) — who may compute, call AI, touch the database.
7. **The worked example** (§1) — timeline showing $6,000 flat versus what was
   owed, with the four missed items marked.
