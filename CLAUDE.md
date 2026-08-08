# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

**Phases 0 and 1 of 12 are complete.** Phase 0 (skeleton, deps, `core/config.py`, config page, digest) was installed and run for real on 2026-08-08 — `.venv` on Python 3.12, all 16 deps import, `streamlit run app/main.py` renders with zero exceptions.

**Phase 1 (database) is complete and live on Supabase.** All 12 tables in `core/db/models.py`, engine/session in `core/db/database.py`, 13 read helpers in `core/db/queries.py`, plus `scripts/init_db.py`, `scripts/reset_run.py` and `app/pages/9_db_health.py`. The same 47 assertions pass identically on SQLite and on Postgres; ADR-005 nullability and all six `CheckConstraint`s are confirmed in `information_schema`. **All 12 tables exist and are empty** — that is the correct state; Phase 2's `scripts/seed_demo.py` fills them.

**Phase 2 (frontend shell) is complete.** The whole UI exists and reads real Supabase rows — landing page, Revenue Integrity dashboard, Decision Engine, DB Health, plus six components and `app/state.py`. `scripts/seed_demo.py` writes an internally consistent demo run ($26,908 across 7 findings, all four leak types, 3 of 5 clients) where `gap == expected - actual` and `total == sum(gaps)` hold *by construction*. **There is no hardcoded dict anywhere in `app/`** — that is what makes Phase 6 a data change rather than an integration project.

Still stubs: everything under `core/ai/`, `core/engine/`, `core/agents/`, `core/extraction/`, `data_sourcing/`, `training/`, `tests/`, and `app/components/column_mapper.py`.

What the UI deliberately does *not* do yet: parse uploads (Phase 4), read the Decision Engine's question box (Phase 9), or render a PDF page in the clause viewer (Phase 7). Each says so on screen rather than implying otherwise.

**Supabase Storage is live** — private bucket `finsight-documents`, reached with `SUPABASE_SERVICE_KEY` (service_role) because the anon key gets a 403 from RLS on a private bucket. That key is safe here *only* because Streamlit renders server-side; it must go into Streamlit Secrets, never the repo. **Object keys are content-addressed** (`<run_id>/<sha256[:12]>_<name>`) because Supabase's CDN ignores `cache-control` and serves stale bytes after a re-upload — verified, and it survives deletion. Never build a bucket key by hand; use `files.save_upload` and the `documents.storage_url` it returns.

**Since Phase 0 closed, the inference design changed (ADR-011 + ADR-012):** no frontier model API is used anywhere. All inference runs on an open-source model we host on free Colab/Kaggle GPU. `core/config.py`, `.env.example`, `README.md` and the docs were updated; `docs/progress.md` carries the correction entry.

Run `python scripts/memory_digest.py` first — it prints current phase, open issues and latest ADR from `docs/state.json`. Then read, in this order:

| File | Purpose |
|---|---|
| `docs/progress.md` | **Part 1** — append-only log of what actually exists. *If it isn't here, it doesn't exist* — do not assume a module is built. **Part 2** — ADR-001…ADR-012, with what each one cost us. **ADR-011/012 changed the inference design after Phase 0** — read them before touching anything LLM-shaped. |
| `docs/interfaces.md` | Function signatures across the A/B boundary, per phase, with ⬜/✅ status. |
| `docs/state.json` | Machine-readable phase / known-issue / ADR state. |
| `docs/implementation_plan.md` | 2000-line phase-by-phase plan: directory tree with per-file ownership, DB schema, algorithms, per-phase "definition of done". |

Everything stable about the project — what it is, the stack, the data sources, the hard rules, the A/B split, the memory ritual — is in this file, below.

Known drift — do not silently "fix" by guessing:
- **The memory files live in `docs/`, not `memory/`, and there are four of them, not five.** `implementation_plan.md` says `memory/` throughout and names `project_context.md` / `decisions.md` / `memory_system.md`, because it predates the repo and predates the 2026-08-08 consolidation. `docs/` is authoritative; the plan text was deliberately left alone.
- Phase 11 references a `changes.md` that does not exist.
- Phase 0's stated definition of done ("config page with all keys ✅") **cannot be met until Phase 5**: `COLAB_TUNNEL_URL` is required but no tunnel exists until `serve_model.py` is stood up (ADR-012). Expect one ❌ row and a raising `settings.validate()`. Plan-vs-ADR conflict, not a code fault — do not "fix" it either way without asking.

---

# The project

## What FinSight is

A Streamlit web app for **small B2B service businesses** (design studios, dev shops, consultancies — 3 to 20 people, no finance department). It reads client contracts, compares them against actual invoices/bank transactions, and reports revenue that was contractually owed but never collected — each finding traced to the exact clause that proves it. Page 2 then answers a strategic question ("can I afford a $5k/month hire?") with the recovered money factored in.

**One-sentence pitch:** *"You are owed money you don't know about. Here it is, here is the exact clause that proves it, and here is what it changes about the decision you're trying to make."*

**The problem, concretely.** A studio signs a contract: $6,000/month, 10% discount for the first three months, 8% increase on the anniversary, plus a $15,000 milestone on website launch. Eighteen months later, whoever set up the recurring invoice has left. The invoice still says $6,000. Nobody applied the 8% increase. The intro discount was never switched off in month four. The milestone was delivered but never billed. That is roughly **$21,000 gone** — not stolen, just never noticed. Accounting software cannot catch this, because accounting software has never read the contract.

## The four leak types (the core taxonomy)

Every finding is exactly one of these — they are mutually exclusive by design, and each traces back to a specific clause in a specific contract.

| Type | Definition | Detection rule |
|------|-----------|----------------|
| 🔴 **ghost_invoice** | An expected billing that never happened at all | No actual transaction matches an expected timeline row |
| 🟡 **forgotten_raise** | A price escalation clause that was never applied | Actual amount ≈ the pre-escalation rate |
| 🟠 **zombie_discount** | A temporary discount that was never switched off | Actual amount ≈ expected minus an expired discount % |
| 🟣 **short_change** | A partial payment accepted with no follow-up | Actual < expected, and the gap matches no other rule |

## Pipeline

```
Upload  →  Route by type  →  Extract text  →  Our self-hosted model
                                              extracts contract rules
                                                        ↓
                                    Deterministic Python builds Expected Timeline
                                                        ↓
                              Reconciliation compares Expected vs Actual → anomalies
                                                        ↓
                                  LangGraph agent verifies / filters false positives
                                                        ↓
                          Dashboard + clickable clause  →  Decision Engine (Page 2)
```

Layer rules: Streamlit renders DB rows and collects uploads (computes nothing, never calls a model directly); extraction turns files into text (interprets nothing); the engine does all money math (no I/O); the agent only investigates *already-flagged* anomalies.

## Architecture — the load-bearing constraints

These are the rules that make the product's numbers defensible. Violating them is not a style issue.

1. **The LLM never does arithmetic**, never decides whether something is an anomaly, and never produces a number the user sees. It only turns prose into structured data and phrases explanations around already-computed figures. All money math is deterministic Python in `core/engine/`.
2. **The LLM never produces bounding boxes.** It returns `clause_text` copied *verbatim*; `core/extraction/clause_locator.py` finds the coordinates via PyMuPDF `page.search_for()` with a `thefuzz` fallback. A quote that cannot be located was hallucinated → flag low-confidence. `source_page`/`source_bbox` are nullable and the UI must degrade to a page-level view, never crash (ADR-005).
3. **The UI reads only the database**, never a hardcoded dict. This is why the build is top-down: the DB and UI shell come first (Phases 1–2) populated by `scripts/seed_demo.py`, and each later phase replaces one seeded table with a computed one. Integration is never a cliff at the end (ADR-008).
4. **Engine functions are pure** — `timeline_generator.generate_timeline`, `reconciliation.reconcile`, `anomaly_classifier.classify` take no DB, no network, no LLM. They are the unit-tested core.
5. **Every anomaly traces to a `clause_reference` row.** No orphans.
6. **No local GPU in the runtime path**, and **no frontier model API calls, ever** (ADR-011). Every model call goes to an open-source model (Qwen 2.5 3B Instruct) that we host ourselves on free Colab/Kaggle GPU, behind an OpenAI-compatible tunnel. Adding a vendor SDK to `requirements.txt` is a violation, not a shortcut.
7. **The endpoint is a notebook session, not a service.** Its URL changes on every restart, so `settings.api_base` must be read at call time and never captured at import. Cold starts take minutes. A dead session takes the whole app down — which is why the disk cache is demo insurance rather than an optimisation.
8. **No secrets in git.** `.env` is gitignored; deployment uses Streamlit Secrets.
9. **Nobody edits a file they don't own.**

## Tech stack (authoritative — do not substitute without an ADR)

| Layer | Choice | Notes |
|-------|--------|-------|
| Frontend | **Streamlit** (multipage) | Deployed to Streamlit Community Cloud |
| Database | **Supabase Postgres** via SQLAlchemy | SQLite fallback for offline dev |
| File storage | **Supabase Storage** | Signed URLs; `data/uploads/` locally |
| PDF text | **pdfplumber** + **PyMuPDF (fitz)** | CPU only, free |
| Clause location | **PyMuPDF `page.search_for()`** | Code finds bboxes — never the LLM |
| CSV | **pandas** | LLM-assisted column mapping, human-confirmed |
| OCR (optional) | **Surya on Colab** | Offline batch step, fallback branch only |
| LLM (baseline) | **Qwen 2.5 3B Instruct**, base weights, self-hosted | Served from Colab/Kaggle from Phase 5 (ADR-011, ADR-012) |
| LLM (upgrade) | **Qwen 2.5 3B + QLoRA**, trained on Colab | Phase 10; same endpoint, one `LLM_MODEL` value apart |
| Model serving | **FastAPI + Cloudflare tunnel** in a Colab/Kaggle notebook | OpenAI-compatible `/v1/chat/completions` |
| Structured output | **Pydantic** + JSON mode + repair-retry | NOT Outlines (doesn't work over HTTP) |
| Agent | **LangGraph** ReAct, max 5 iterations | Verification agent |
| Charts | **Plotly** | Cash-flow projection |
| Fine-tuning | **Unsloth + QLoRA** on free Colab/Kaggle T4 | |

**No local GPU is required anywhere in the runtime path** — the GPU is a free Colab/Kaggle T4, reached over HTTP.

## Data sources — sourced online, never generated locally

| Purpose | Source | Access |
|---------|--------|--------|
| Real contracts | **CUAD v1** — 510 real commercial contracts, expert-annotated, CC BY 4.0 | HuggingFace `theatticusproject/cuad`, PDFs via `dvgodoy/CUAD_v1_Contract_Understanding_PDF` |
| More contracts | **SEC EDGAR** EX-10 material contracts | `efts.sec.gov` full-text search |
| Invoice images | `mychen76/invoices-and-receipts_ocr_v1`, `Voxel51/high-quality-invoice-images-for-ocr` | HuggingFace |
| Receipt OCR ground truth | SROIE / CORD | HuggingFace |
| Transaction realism | Kaggle bank-transaction datasets | `kagglehub` |

**Rule:** contracts are **sourced**. Actuals (invoice ledgers, transactions) are **derived** from those real contracts by deterministic arithmetic in `data_sourcing/scenario_builder.py`, which plants known anomalies and writes `ground_truth.json`. No model invents a contract.

## Key design decisions worth knowing before writing code

Full reasoning for each is in Part 2 of `docs/progress.md`.

- **Reconciliation aggregates per client-month** (ADR-006) rather than matching transaction-to-invoice, which is a combinatorial assignment problem. Sum all of a client's transactions in the calendar month (fuzzy name match, ±15 day tolerance), compare to expected, classify the gap. The precision lost on split payments is recovered in Phase 8 by the agent's `check_split_payments` tool, which does transaction-level search on the ~5 flagged rows instead of ~5,000.
- **Structured output is Pydantic + JSON mode + one repair retry** (ADR-004). `llm_client.complete_json` returns `None` on failure and **never raises to the caller**. Outlines was rejected because it needs logit access, which a hosted API could not give — but ADR-011 means we now run the server, so grammar-constrained decoding is available *server-side* in the notebook. Keep the client-side repair-retry regardless.
- **One swappable LLM client** (ADR-002, amended by ADR-011): endpoint chosen by `LLM_PROVIDER` (`colab_tunnel | kaggle_tunnel | custom`) — all of them our own notebook sessions, all OpenAI-compatible. Phase 11's base-vs-tuned comparison is likewise one variable, `LLM_MODEL`.
- **Serving is stood up in Phase 5 on base weights** (ADR-012, superseding ADR-009). Without a hosted API there is no baseline, so `training/serve_model.py` runs untuned Qwen 2.5 3B from Phase 5 and Phases 5–9 develop against it; Phase 10 loads the QLoRA adapter into the same notebook under a second model name. This keeps the top-down build order intact and makes the final comparison identical-weights, adapter on/off. Fine-tuning is now load-bearing for the *claim* but not for the *product* — if training fails, base weights still run everything.
- **Contracts are sourced, actuals are derived** (ADR-007).
- **CSV column mapping is LLM-proposed, human-confirmed** (ADR-010), cached by header signature in the `column_mappings` table.
- **`runs` table with `run_id` on everything** so demos can be re-run without wiping the DB and baseline/fine-tuned results can sit side by side.

## Build philosophy

**Top-down.** The UI shell and the database come first (Phases 1–2), populated with *seeded real rows*. Every phase after that replaces one seeded table with a computed one. **Riskiest work last** — extraction → math → clause viewer → agent → decision engine → fine-tuning — with the one deliberate exception of model serving, which ADR-012 pulls forward to Phase 5 because everything downstream depends on it.

## Definition of success

- **Minimum (must have):** deployed public URL; upload a real contract + a CSV; get correctly classified anomalies with working clause highlighting; the Decision Engine returns a verdict — **all of it running against our own self-hosted open-source model** (base weights are enough).
- **Target:** the above, plus the verification agent visibly filtering a false positive, plus the QLoRA-tuned adapter with a measured base-vs-tuned comparison on the held-out eval set.
- **Stretch:** OCR path demoed on a genuinely scanned document.

---

# Conventions

From `docs/interfaces.md`:

- Money is `float`, run's base currency, rounded to 2dp at the boundary. Dates are `datetime.date` — never strings, never `datetime`. IDs are `int` DB primary keys.
- Any function touching the DB takes `session: Session` as its **first** argument; anything producing run-scoped data takes `run_id: int`.
- Return Pydantic models or dataclasses, never bare dicts.
- A function that can legitimately fail returns `None` rather than raising. Callers handle `None`.
- Shared schemas live in `core/ai/schemas.py` and are imported by everyone.

# The team and the memory ritual

## Who owns what

| | User A — *data & determinism* | User B — *interface & intelligence* |
|---|---|---|
| Owns | DB schema, extraction, timeline, reconciliation, training data, evaluation | Streamlit UI, LLM client, agent, decision engine, deployment |
| Strength of the work | Highly testable — pure functions, known I/O | Highly visible — screenshots, demos |

1. **One owner per file.** Every file in the plan's directory tree is tagged `[A]` or `[B]`. Need a change in a file you don't own? Ask. Don't edit.
2. **Interfaces before implementations.** The moment you know a function will be called by the *other* person, its signature goes into `docs/interfaces.md` *before* it is implemented — they code against it with a stub and neither of you blocks.
3. **Both people work every phase.** No idle waiting, and both people update memory: you each know things the other doesn't.

## Why the memory files exist

Twelve phases, two people, many separate assistant sessions. A fresh session knows nothing. Without these files it re-suggests things you already built, contradicts decisions you already made, and invents function names that don't match yours — and with two people running two sessions, that divergence doubles. Skipping the ritual costs you a week across the project, slowly: duplicate modules that shadow real ones, and evenings spent re-litigating settled choices because nobody remembers *why* Supabase beat Neon.

## Start of phase

Each phase in `implementation_plan.md` has a copy-paste **Phase Prompt** whose first instruction is to read the memory files and print a numbered summary before writing code. **Do not skip the summary** — it forces the model to actually condition on the files rather than skim them, it gives you a 10-second check that the assistant is oriented, and it catches conflicts early (the prompt asks the assistant to stop if the phase contradicts memory). If the summary is thin, your memory files are thin — fix them before code gets written on a bad foundation.

## End of phase — five minutes, both of you

- Append your Phase N entry to Part 1 of `docs/progress.md` (template below)
- Flip statuses in `docs/interfaces.md` (⬜ → ✅)
- Append any ADR to Part 2 of `docs/progress.md`
- Update `docs/state.json`: `current_phase`, phase `status`, `known_issues`, `adrs`
- Commit as `memory: close phase N`

Rules: **`progress.md` is append-only** — if something changed later, add a new entry saying so; never rewrite history. **Never delete an ADR** — supersede it and mark the old one superseded. **If it isn't in `progress.md`, it doesn't exist.** And **write the "known gaps" line honestly** — it is the highest-value line in an entry, because it stops an assistant from assuming something works that doesn't.

## Progress entry template

```markdown
## Phase N — <name>
**Completed:** YYYY-MM-DD · **Owners:** A / B

### Built by A
- `path/to/file.py` — one line on what it does

### Built by B
- `path/to/file.py` — one line on what it does

### New interfaces added to interfaces.md
- `module.function(args) -> Return`

### Decisions recorded
- ADR-00N: <title>

### Known gaps / deliberately deferred
- <thing that does not work yet, and which phase handles it>

### How to verify this phase works
- <the exact command or click-path that proves it>
```

Keep it factual and short. The two things that matter most are **the file paths** and **the "known gaps" line**.

---

# Commands

Working now:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # fill in at least the active provider's key

streamlit run app/main.py        # Phase 0: the config page
python scripts/memory_digest.py  # compact orientation summary
```

Stubs — each lands in the phase noted:

```bash
python scripts/init_db.py        # Phase 1 — create all 12 tables
python scripts/seed_demo.py      # Phase 2 — scenario -> DB rows
python scripts/reset_run.py      # Phase 2 — wipe one run, keep others

pytest                                       # collects 0 tests until Phase 6
pytest tests/test_timeline.py                # the most important test file
pytest tests/test_timeline.py::test_name -v  # a single test
```

The `.venv` is **Python 3.12.13**, built with `uv` for Streamlit Community Cloud parity (the system python is 3.14, which Cloud does not offer). All 16 dependencies install and import. To rebuild:

```bash
uv venv --python 3.12 && uv pip install -r requirements.txt
```

**Import PyMuPDF as `import pymupdf`, not `import fitz`** — the `fitz` alias still works but emits a deprecation warning. Relevant to `clause_locator.py` and `pdf_renderer.py` (Phases 4 and 7); the plan text says "fitz".

# Configuration

`core/config.py` is the only module that reads `os.environ`. Everything imports `settings` from it. Resolution order: environment → `.env` (python-dotenv) → `st.secrets` (deployed) → declared default, so local and deployed differ by zero lines of code.

- `settings.validate()` raises `ConfigError` naming **every** missing required variable at once. Only the *active* endpoint's URL is required.
- `settings.api_base` normalises whatever tunnel URL shape got pasted in (strips a trailing `/v1` or `/v1/chat/completions`); `llm_client` appends the path itself. **Read it at call time** — the URL rotates.
- Unedited `.env.example` placeholders (`[PASSWORD]`, `[REF]`) are treated as unset, so a half-filled `.env` fails at startup rather than at the first connection.
- `settings.checks()` returns every variable with `.status` (✅/❌/⚪) and `.display` (masked when secret) — it drives the config page and can fail scripts early.
- Vars: `LLM_PROVIDER`, `COLAB_TUNNEL_URL`, `KAGGLE_TUNNEL_URL`, `CUSTOM_BASE_URL`, `LLM_API_KEY` (shared secret — the tunnel is a public URL), `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `DATABASE_URL` (falls back to `sqlite:///data/finsight.db`), `SUPABASE_URL`, `SUPABASE_KEY`, `HF_TOKEN`, `LLM_CACHE_ENABLED`, `LOG_LEVEL`.

`.gitignore` covers `data/`, `.env`, `__pycache__/`, `*.db`, `.streamlit/secrets.toml`, and `training/data/*.jsonl` **except** `eval_set.jsonl` — the held-out eval set is tracked on purpose and never trained on.

# API budget

The scarce resource is requests-per-minute, not GPU memory. A full run (5 contracts, 1 CSV, 7 anomalies) is ~35–55 LLM calls. Cache every response on disk keyed by `sha256(prompt + model)` — the same contracts get re-run dozens of times while debugging. Fire agent calls sequentially with a small sleep; bursting is what trips per-minute limits, not volume.
