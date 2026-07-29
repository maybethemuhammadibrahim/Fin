# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

**Phase 0 of 12 is complete; there are no features yet.** What exists: the full directory skeleton (every file from the plan's tree present as a one-line docstring stub tagged `[A]`/`[B]`), `requirements.txt`, `.gitignore`, `.env.example`, a working `core/config.py`, a config page at `app/main.py`, and `scripts/memory_digest.py`. Everything under `core/db/`, `core/ai/`, `core/engine/`, `core/agents/`, `core/extraction/`, `data_sourcing/`, `training/`, and `tests/` is a stub.

Run `python scripts/memory_digest.py` first — it prints current phase, features, and open issues from `docs/state.json`. Then read, in this order:

| File | Purpose |
|---|---|
| `docs/project_context.md` | What FinSight is, the stack, the hard rules, the A/B ownership split. Stable. |
| `docs/progress.md` | Append-only log of what actually exists. **If it isn't here, it doesn't exist** — do not assume a module is built. |
| `docs/interfaces.md` | Function signatures across the A/B boundary, per phase, with ⬜/✅ status. |
| `docs/decisions.md` | ADR-001…ADR-010, with what each one cost us. |
| `docs/state.json` | Machine-readable phase / feature / known-issue / ADR state. |
| `docs/implementation_plan.md` | 2000-line phase-by-phase plan: directory tree with per-file ownership, DB schema, algorithms, per-phase "definition of done". |
| `docs/memory_system.md` | The end-of-phase memory ritual. |

Known drift — do not silently "fix" by guessing:
- **The memory files live in `docs/`, not `memory/`.** `implementation_plan.md` says `memory/` throughout because it predates the repo. `docs/` is authoritative; the plan text was deliberately left alone.
- Phase 11 references a `changes.md` that does not exist.
- Nothing has been `pip install`ed or run in a real venv here — `core/config.py` and `scripts/memory_digest.py` were smoke-tested on stdlib only, and `streamlit run app/main.py` has never actually been executed.

## What FinSight is

A Streamlit web app for small B2B service businesses. It reads client contracts, compares them against actual invoices/bank transactions, and reports revenue that was contractually owed but never collected — each finding traced to the exact clause that proves it. Page 2 then answers a strategic question ("can I afford a $5k/month hire?") with the recovered money factored in.

Every finding is one of four mutually exclusive leak types: **ghost_invoice** (never billed), **forgotten_raise** (escalation clause never applied), **zombie_discount** (temporary discount never switched off), **short_change** (partial payment, gap ignored).

## Architecture — the load-bearing constraints

These are the rules that make the product's numbers defensible. Violating them is not a style issue.

1. **The LLM never does arithmetic**, never decides whether something is an anomaly, and never produces a number the user sees. It only turns prose into structured data and phrases explanations around already-computed figures. All money math is deterministic Python in `core/engine/`.
2. **The LLM never produces bounding boxes.** It returns `clause_text` copied *verbatim*; `core/extraction/clause_locator.py` finds the coordinates via PyMuPDF `page.search_for()` with a `thefuzz` fallback. A quote that cannot be located was hallucinated → flag low-confidence. `source_page`/`source_bbox` are nullable and the UI must degrade to a page-level view, never crash (ADR-005).
3. **The UI reads only the database**, never a hardcoded dict. This is why the build is top-down: the DB and UI shell come first (Phases 1–2) populated by `scripts/seed_demo.py`, and each later phase replaces one seeded table with a computed one. Integration is never a cliff at the end (ADR-008).
4. **Engine functions are pure** — `timeline_generator.generate_timeline`, `reconciliation.reconcile`, `anomaly_classifier.classify` take no DB, no network, no LLM. They are the unit-tested core.
5. **Every anomaly traces to a `clause_reference` row.** No orphans.
6. **No local GPU in the runtime path.** Fine-tuning happens on free Colab/Kaggle T4 and is served back over a tunnel; it is a measured comparison, never a dependency (ADR-009).

Pipeline: upload → route by file type → extract text → LLM extracts `ContractRules` → deterministic expected timeline → reconcile expected vs actual → LangGraph agent filters false positives → dashboard with clickable clause → decision engine.

Layer rules: Streamlit renders DB rows and collects uploads (computes nothing, never calls a model directly); extraction turns files into text (interprets nothing); the engine does all money math (no I/O); the agent only investigates *already-flagged* anomalies.

## Key design decisions worth knowing before writing code

- **Reconciliation aggregates per client-month** (ADR-006) rather than matching transaction-to-invoice, which is a combinatorial assignment problem. Sum all of a client's transactions in the calendar month (fuzzy name match, ±15 day tolerance), compare to expected, classify the gap. The precision lost on split payments is recovered in Phase 8 by the agent's `check_split_payments` tool, which does transaction-level search on the ~5 flagged rows instead of ~5,000.
- **Structured output is Pydantic + JSON mode + one repair retry** (ADR-004), not Outlines — Outlines needs local logit access and doesn't work over HTTP. `llm_client.complete_json` returns `None` on failure and **never raises to the caller**.
- **One swappable LLM client** (ADR-002): provider chosen by the `LLM_PROVIDER` env var (`gemini | groq | openrouter | finetuned_tunnel`), all OpenAI-compatible, so Phase 11's baseline-vs-fine-tuned comparison is a one-variable change with zero code edits.
- **Contracts are sourced, actuals are derived** (ADR-007). Real contracts come from CUAD v1 and SEC EDGAR. Invoice ledgers and transactions are computed from those contracts' true rules by `data_sourcing/scenario_builder.py`, which plants known anomalies and writes `ground_truth.json`. No model ever invents a contract.
- **CSV column mapping is LLM-proposed, human-confirmed** (ADR-010), cached by header signature in the `column_mappings` table.
- **`runs` table with `run_id` on everything** so demos can be re-run without wiping the DB and baseline/fine-tuned results can sit side by side.

## Conventions (from `docs/interfaces.md`)

- Money is `float`, run's base currency, rounded to 2dp at the boundary. Dates are `datetime.date` — never strings, never `datetime`. IDs are `int` DB primary keys.
- Any function touching the DB takes `session: Session` as its **first** argument; anything producing run-scoped data takes `run_id: int`.
- Return Pydantic models or dataclasses, never bare dicts.
- A function that can legitimately fail returns `None` rather than raising. Callers handle `None`.
- Shared schemas live in `core/ai/schemas.py` and are imported by everyone.

## Workflow rules this project actually enforces

- **One owner per file.** Every file in the plan's directory tree is tagged `[A]` (data & determinism: DB, extraction, timeline, training, eval) or `[B]` (interface & intelligence: Streamlit, LLM client, agent, decision engine, deploy). Do not edit a file you don't own — ask.
- **Signatures go into `docs/interfaces.md` before the implementation exists**, so the other person can code against a stub immediately.
- **Append a Phase N entry to `docs/progress.md` at the end of every phase.** It is append-only: never rewrite a past entry, add a new one saying what changed. The "known gaps" line is the highest-value line — write it honestly.
- **Never delete an ADR**; supersede it and mark the old one superseded.
- Each phase in `implementation_plan.md` has a copy-paste **Phase Prompt** whose first instruction is to read the memory files and print a numbered summary before writing code. When starting phase work, follow it.

## Commands

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

Use Python 3.11–3.12 (matches Streamlit Cloud; newer versions may lack `pymupdf` / `psycopg2-binary` wheels — the system python here is 3.14).

## Configuration

`core/config.py` is the only module that reads `os.environ`. Everything imports `settings` from it. Resolution order: environment → `.env` (python-dotenv) → `st.secrets` (deployed) → declared default, so local and deployed differ by zero lines of code.

- `settings.validate()` raises `ConfigError` naming **every** missing required variable at once. Only the *active* provider's credential is required — a Gemini user is not blocked by an empty `GROQ_API_KEY`.
- Unedited `.env.example` placeholders (`[PASSWORD]`, `[REF]`) are treated as unset, so a half-filled `.env` fails at startup rather than at the first connection.
- `settings.checks()` returns every variable with `.status` (✅/❌/⚪) and `.display` (masked when secret) — it drives the config page and can fail scripts early.
- Vars: `LLM_PROVIDER`, `LLM_MODEL`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `FINETUNED_TUNNEL_URL`, `DATABASE_URL` (falls back to `sqlite:///data/finsight.db`), `SUPABASE_URL`, `SUPABASE_KEY`, `HF_TOKEN`, `LLM_CACHE_ENABLED`, `LOG_LEVEL`.

`.gitignore` covers `data/`, `.env`, `__pycache__/`, `*.db`, `.streamlit/secrets.toml`, and `training/data/*.jsonl` **except** `eval_set.jsonl` — the held-out eval set is tracked on purpose and never trained on.

## API budget

The scarce resource is requests-per-minute, not GPU memory. A full run (5 contracts, 1 CSV, 7 anomalies) is ~35–55 LLM calls. Cache every response on disk keyed by `sha256(prompt + model)` — the same contracts get re-run dozens of times while debugging. Fire agent calls sequentially with a small sleep; bursting is what trips per-minute limits, not volume.
