# Phase 10 — Fine-Tuning: the agreed plan

**Written:** 2026-08-17 · **Status:** agreed, not yet started
**Supersedes nothing.** This is the working plan for Phase 10 as decided in
session on 2026-08-17. `docs/implementation_plan.md` Phase 10 remains the
original specification; where this document differs, **this one is what we are
building**, and the differences are listed under *Departures from the plan*.

---

## The idea in one picture

Fine-tuning is studying for an exam.

| | |
|---|---|
| **Training examples** | practice questions, with the answers shown |
| **Test set** ("the sealed pile") | the real exam, locked away before anything else happens |
| **The one rule** | never practise on the exam paper, or the score means nothing |

Everything below is just doing that carefully.

---

## Where we start

**Step 1 is done — 2026-08-17.** The corpus went from 43 to **192 distinct
contracts** (`data/corpus/contracts/`):

| Tier | Was | Now | What it means |
|---|---:|---:|---|
| `ready/` | 19 | **60** | real amount and real escalation — *machine-scored, not verified* |
| `filled/` | 6 | **19** | redactions filled deterministically (ADR-014) |
| `review/` | 18 | **113** | clause shape right, no figure found — **still never read** (#29) |

Measured: 700 exhibits from **467 distinct filers**, 150 skipped by the new
per-filer cap, 667 written to disk, deduplicated to 192.

These are *distinct* contracts, not documents — `deduplicate()` keeps one per
filer **and** one per clause fingerprint, which is what known issue #26 demands
(counting documents overstates a corpus ~2.5×). The EX-99 mutual-fund cluster
that #27 complained about is now 40 of 192 (21%) rather than dominating.

> [!WARNING]
> **`ready/` means "passed automatic scoring", not "correct".** Known issue
> #34's own example is still sitting in that tier: `Cellteck_Inc_EX-99.1`
> scores ready on an *"18% per annum"* clause that is **loan interest, not a fee
> escalation**. This is exactly why step 4 exists and why the test set is
> human-checked.

`data/` is gitignored, so none of this survives a machine change (#33, #44).
Rebuild with `python -m data_sourcing.filter_contracts --count 700`.

---

## The steps

### 1. Expand the real corpus — *me, ~1 hour, no keys needed*
Widen `data_sourcing/fetch_contracts.py`: industry-varied search terms and a
per-filer cap. This is known issue #27's "broader search designed but NOT RUN",
which that note explicitly schedules for **before Phase 10**, because variety is
load-bearing only for training and for the base-vs-tuned claim.

Target: 100+ raw exhibits, 60+ distinct contracts after dedupe.

### 2. Seal the test set — **DONE 2026-08-17**
`scripts/seal_testset.py` sealed **30 real contracts** into
`data/corpus/heldout/` — 30 distinct filers, 30 distinct clause wordings,
26 `ready` + 4 `filled`. Seeded (`20260817`) and reproducible.

Sealed *before* a single training example exists, because this is the only step
that can silently destroy the phase — a leak does not announce itself, it just
produces a suspiciously good score.

Three mechanical guarantees, each tested:

| Command | Guarantee |
|---|---|
| `--verify` | re-hashes every sealed file; reports CHANGED, MISSING or UNSEALED extras |
| `--check FILE` | is this file (by bytes **or** by name) part of the test set? exit 1 if so |
| no flag, twice | **refuses to reseal**; `--force` is itself refused once `training/data/*.jsonl` exists |

That last one matters most: resealing after training is exactly how a leak
becomes a pass.

> [!IMPORTANT]
> **The sealed files are copies — the originals are still in `ready/` and
> `filled/`.** That is deliberate: `build_corpus()` wipes and rebuilds those
> folders from the raw downloads, so anything *moved* out would be silently
> restored on the next corpus rebuild and the seal would break with nothing
> failing. The sha256 manifest survives a rebuild; a moved file would not.
>
> The consequence is that **the training pool still physically contains the
> sealed contracts**, so exclusion must be enforced *in code* by the generator
> in step 3 — never by remembering. `--check` is what it calls.

### 3. Generate the training examples — *me + DeepSeek, ~85 examples*
4–6 contract templates written by hand, then varied: names, dates, fee amounts,
escalation percentages, discount windows, milestone conditions. **We choose the
figures, so we already know every correct answer** — nothing to verify.

This is ADR-014's existing precedent applied to whole contracts rather than to a
single redacted blank: *the inserted value **is** ground truth by construction,
so nothing needs verifying.*

DeepSeek's job is **wording variety only** — so the model does not simply learn
four sentence patterns. It never invents a figure and it never writes an answer
key. Both of those stay deterministic.

### 4. Verify the sealed pile — *you + teammate, ~30 min each*
The only human task in the phase. A review tool shows one card at a time:
the extracted answer, the sentence it came from, and the automatic checks.

Two questions per card:
1. Is this number in the highlighted sentence?
2. Is this sentence about the regular fee the customer pays — **not** interest
   on a late payment, **not** a complaints procedure?

**If unsure, discard.** We gather ~30 to keep ~20 precisely so that discarding is
free. A smaller clean set beats a bigger dirty one.

Machine pre-checks run first, so most cases never reach a human:

| Auto-check | Rejects |
|---|---|
| amount appears verbatim in the contract text | invented figures |
| quoted clause appears verbatim | invented quotes (Phase 5's grounding check) |
| percentage matches its own quote | mismatched extraction |
| "escalat*" near dispute wording | known issue #24 — 68 of 81 CUAD matches meant *escalate to senior management* |
| "per annum" near interest/late/overdue | known issue #34 — Cellteck's 18% was loan interest, not a fee rise |
| `[***]` in the clause | known issue #25 — ~24% of filings redact figures |

### 5. Train — *you click run, ~1 hour of waiting*
Colab, free T4, checkpoint every epoch. Produces a **patch** (a LoRA adapter),
roughly 50–100 MB — not a new model.

### 6. Sit the exam — *me*
Open the sealed pile. Run all 20 real contracts through **both** models:
base weights, and base + patch. Same endpoint, same prompt, one variable.

### 7. Report the comparison — *both*
Better → the capstone claim, measured. Not better → **a legitimate finding to
report, not a failure to hide** (the plan's own words, Phase 11 prompt).

### 8. Ship it — *me*
Patch to HuggingFace, loaded on the serving host, `LLM_MODEL` changes and
**nothing else in the codebase does** — that property was designed in at
Phase 5 (ADR-002 + ADR-012).

---

## Who does what

| Step | Me | You |
|---|---|---|
| 1 · expand corpus | ~1 h | — |
| 2 · seal test set | ~30 m | — |
| 3 · generate 85 examples | ~2 h | — |
| 4 · verify 20 cards | build the tool | **~30 min, split with teammate** |
| 5 · train | write the notebook | click run, wait ~1 h |
| 6–8 · exam, report, ship | ~2 h | — |

**Your total: about 90 minutes**, plus two keys and one open decision.

---

## Storage — where the trained model lives

**HuggingFace Hub.** Fine-tuning does not produce a new multi-gigabyte model; it
produces a ~50–100 MB patch that sits on top of public Qwen weights. Small
enough to upload like a file, free, and portable — Colab, Modal and a laptop all
download the base and drop the patch on top.

Modal has its own storage, but keeping the patch there would tie the work to
Modal. HuggingFace stays portable; `training/serve_modal.py` already pulls
weights that way.

---

## Where it runs

| Job | How often | Home | Why |
|---|---|---|---|
| **Training** | once, ~1 h | Colab (free) | a single one-off run fits free quota fine |
| **Serving** | continuously | **Modal** | stable URL; notebooks die and their URL rotates (#6, #9) |

Modal is **already built and wired** — `training/serve_modal.py`, a `modal`
provider in `core/ai/endpoints.py`, `MODAL_BASE_URL`/`USE_MODAL`, and a
Modal-first failover order (ADR-023). It has never been deployed
(`MODAL_BASE_URL` is empty). Switching it on is configuration, not development.

Modal bills per second of GPU time — real money, unlike Colab. Worth knowing
before a live demo points at it.

---

## Open decisions

### 1. 3B or 7B — **DECIDED 2026-08-17: 3B first, 7B only if it fails**
Base model stays **`Qwen/Qwen2.5-3B-Instruct`**, unchanged from Phase 5.

The reasoning is not primarily about model quality. **The first training run is a
test of the pipeline, not of the model** — data shape, training script, upload,
Modal load, `LLM_MODEL` switch. None of those depend on parameter count, and
finding them on the 3B costs ~1 hour where the 7B costs an evening. Once the
pipeline is proven, moving to 7B is a config change.

Staying on 3B also preserves the plan's original capstone argument (*a small
model fine-tuned on one task matches a much larger general one*) and keeps
Phase 5's measurements describing the shipped system.

**The failure trigger is defined in advance, deliberately:**

> Tuned 3B does not beat base 3B on the 30 sealed contracts.

A number, not an impression — otherwise "it looked disappointing" becomes the
trigger and that is not a reportable result. If it fires, switch to
`Qwen/Qwen2.5-7B-Instruct` (same family, so `serve_model.py` and
`serve_modal.py` need only a name change; Modal's default L4 holds 7B fine) and
**re-baseline** — Phase 5's numbers describe 3B and would no longer describe what
ships.

**Practical note if 7B happens:** run it on Kaggle rather than Colab. Kaggle's
fixed weekly GPU quota is more predictable than free Colab, and 7B runs are long
enough for that to matter. `serve_model.py` already treats both hosts identically.

Deferred from this decision: the 7B-versus-3B test against `eval_agent.py`
(#74 — the agent inverts its verdicts on 3B). Not run. If tuned 3B fixes
extraction but the agent still inverts, that test becomes worth doing on its own.

### 2. Keys — **RESOLVED 2026-08-17, all three verified live**
- **HF_TOKEN** — set. Verified against `whoami-v2`: user `ibrahim404`,
  **`repo.write` present**, so it can upload (a read-only token would have
  failed only at the final step).
- **DeepSeek via Baseten** — set in `.env` as `DEEPSEEK_API` (not the
  `BASETEN_API_KEY` the vendor snippet names; read both).
  `https://inference.baseten.co/v1`, model
  `deepseek-ai/DeepSeek-V4-Flash-0731`. Verified live.
- **$5 hard cap**, and low per-minute throughput — expect intermittent rate
  errors, and report a cap hit rather than failing quietly.

> [!IMPORTANT]
> **DeepSeek V4 Flash is a reasoning model and its thinking is billed.**
> Measured: rewording one sentence cost 502 completion tokens, **471 of them
> reasoning** — 94% overhead. The same four sentences batched into one request
> cost 123 tokens total with **22** reasoning. The overhead is per *request*,
> not per item, so **always batch**. `reasoning_effort: "low"` is accepted.
>
> Two response-shape traps: the answer arrives alongside a `reasoning_content`
> field, and if `max_tokens` is exhausted during thinking, `content` comes back
> **null with no error** (`finish_reason: "length"`). Hit on the first call.

---

## Departures from the plan, and why

| `implementation_plan.md` says | We are doing | Why |
|---|---|---|
| 80–120 pairs from real contracts, all human-verified | ~85 **generated** pairs + ~20 real held-out | The corpus yields 25–35 distinct contracts, not 100+. Generating from templates gives volume *and* removes verification entirely, because we choose the figures (ADR-014's precedent). |
| "verify with the BEST available model" (#31, undecided) | **DeepSeek drafts wording; figures and answer keys stay deterministic** | Closes #31. Offline prep only — never in the runtime path, and **no vendor package is added to `requirements.txt`** (hard rule 6). To be disclosed in the report. |
| Colab for everything | Colab trains, Modal serves | Notebook sessions die and their URL rotates; Modal is already built (ADR-023). |
| 3B base model | possibly 7B | Open — decided by measurement, see above. |

### The rule we are **not** departing from
**The test set is real contracts only, and it is sealed before any training
example is generated.**

Generated contracts on both sides of the split would make Phase 11's number an
artifact — and it would fail in the worst direction, scoring *high* and looking
excellent, so nothing warns anybody. This is known issue #26's own warning:
*"Near-duplicates either side of a train/test split are the invisible leak that
makes Phase 11 meaningless."*

Keeping the exam real also turns the per-customer story into a **demonstrated**
result rather than a claim: train on one contract family, measure on real
filings the model has never seen.

---

## Definition of done

Unchanged from `implementation_plan.md`: a patch on HuggingFace, and setting
`LLM_MODEL` to the tuned name runs the whole app end to end with no other
change, against the same endpoint that has served base weights since Phase 5.

Added here: **a measured base-vs-tuned comparison on a sealed set of real
contracts**, with the train/test overlap stated explicitly in the report.
