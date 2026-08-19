# PROGRESS & DECISIONS — What Has Actually Been Built, And Why

> **Append-only, both halves.** Never delete or rewrite a past entry or ADR. If something
> was later changed, add a new entry saying so; if we changed our minds about a decision,
> add a new ADR and mark the old one *Superseded by ADR-0NN*. The history is the
> methodology section of the report.
>
> **This is the file an AI assistant reads to know what already exists.** If it isn't in
> Part 1, the assistant will assume it doesn't exist and rebuild it.
>
> Part 1 is written at the end of every phase, by the person who did the work. The entry
> template lives in `CLAUDE.md`. Part 2 gets one ADR per *real* choice — where a competent
> person would plausibly have chosen the other thing, not for defaults nobody argued about.

**Current phase:** 8 — done
**Last entry:** Phase 8 — Verification Agent (2026-08-17)

---

# PART 1 — PHASE LOG

## Phase 0 — Foundations & Accounts

**Completed:** 2026-07-29 · **Owners:** A + B

### Built by A
- Full directory skeleton — every file from the plan's tree exists as a one-line
  docstring stub tagged `[A]` / `[B]`, so the tree exists before either of us
  starts creating files ad hoc
- `requirements.txt` — 16 deps, all CPU-only, no GPU anywhere (ADR-001)
- `.gitignore` — `data/`, `.env`, `*.db`, `.streamlit/secrets.toml`,
  `training/data/*.jsonl` **except** `eval_set.jsonl`, which is tracked on purpose
  (ADR-009: the held-out set is built before training and never trained on)
- `docs/decisions.md` — ADR-001 through ADR-010 written out in full
  *(merged into Part 2 of this file on 2026-08-08)*
- `docs/state.json` — machine-readable phase/feature/issue/ADR state

### Built by B
- `core/config.py` — the one `settings` object. Resolution order is environment →
  `.env` (python-dotenv) → `st.secrets` → declared default, so local and deployed
  differ by zero lines of code. `settings.validate()` raises `ConfigError` naming
  every missing required variable. Only the *active* provider's credential is
  required, so a Gemini user is never blocked by an empty `GROQ_API_KEY`.
  Unedited `.env.example` placeholders (`[PASSWORD]`, `[REF]`) count as unset.
- `app/main.py` — config page: every variable with ✅ / ❌ / ⚪, secrets masked to
  `AIza...4f2a`, the resolved database URL, and an ADR-002 provider-swap table
- `.env.example` — every variable, no real values
- `scripts/memory_digest.py` — prints the compact digest from `docs/state.json`
- `README.md` — setup, env vars, commands, deployment, troubleshooting
  (the old memory-system guide moved to `docs/memory_system.md`, unedited except
  for a note about where the files live)
- Cloud accounts: Supabase, Google AI Studio, Groq, HuggingFace, Streamlit Cloud
  — **created by hand, outside the repo. Not yet confirmed done.**

### New interfaces added to interfaces.md
- `config.get_settings() -> Settings` and the module-level `config.settings`
- `Settings.validate() -> None` (raises `ConfigError`)
- `Settings.resolved_database_url -> str` — what Phase 1's `database.py` connects to
- `Settings.checks() -> list[Setting]` — drives the config page
- `config.mask(value) -> str`, `config.configure_logging(level=None) -> None`

### Decisions recorded
- ADR-001 No local GPU anywhere in the runtime path
- ADR-002 One swappable LLM client behind a single env var
- ADR-003 Supabase Postgres as the primary database
- ADR-004 Pydantic + JSON mode + repair-retry, not Outlines
- ADR-005 Code finds bounding boxes; the model never does
- ADR-006 Reconcile on client-month aggregates
- ADR-007 Contracts are sourced; actuals are derived
- ADR-008 Top-down build order: shell and database first
- ADR-009 Fine-tuning is a measured comparison, not a dependency
- ADR-010 CSV column mapping is LLM-proposed, human-confirmed

### Known gaps / deliberately deferred
- **The memory files live in `docs/`, not `memory/`.** `implementation_plan.md`
  still says `memory/` throughout — it was written before the repo existed.
  `docs/` is authoritative; the plan text was deliberately not rewritten.
- **`pytest` collects 0 tests and exits 5.** The three test files are
  docstring-only stubs until Phase 6.
- **The Streamlit sidebar shows three blank pages.** `app/pages/*.py` are stubs;
  Phase 0 explicitly forbids writing UI, so they were left pure. Phase 2 fills them.
- `core/db/` is stubs only — nothing connects to Supabase yet. Phase 1.
- **Nothing has been installed or run end to end in a real venv here.**
  `core/config.py` and `scripts/memory_digest.py` were smoke-tested on stdlib
  only; `streamlit run app/main.py` has NOT been executed. First person to
  `pip install` should confirm it and say so.
- No dependency pinning and no CI. Revisit before Phase 11.
- Cloud account creation is a manual step; the repo cannot verify it. The config
  page is the check — every key ✅ means the accounts exist and the keys work.

### How to verify this phase works
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in at least GEMINI_API_KEY
streamlit run app/main.py   # every variable ✅, secrets masked
python scripts/memory_digest.py
```
Then prove ADR-002 with no code change: set `LLM_PROVIDER=groq` and `GROQ_API_KEY`,
reload — the page shows `groq` and `llama-3.3-70b-versatile`.
And prove the loud failure: blank the active provider's key, reload — the page
names that variable at the top instead of failing later.

---

<!-- ================================================================= -->
<!-- APPEND NEW PHASE ENTRIES BELOW THIS LINE. DO NOT EDIT ABOVE.      -->
<!-- ================================================================= -->

## Design change — self-hosted inference (between Phase 0 and Phase 1)

**Recorded:** 2026-07-29 · **Owners:** A + B · **Not a phase — a decision that invalidates part of the Phase 0 entry above.**

### What changed
**No frontier model API will be used anywhere in this project.** All inference
now runs on an open-source model (Qwen 2.5 3B Instruct) that we host ourselves
on a free Colab/Kaggle GPU, behind an OpenAI-compatible tunnel. Gemini, Groq and
OpenRouter are out — including the Gemini-vision OCR path.

Recorded as **ADR-011** (self-hosted only) and **ADR-012** (base weights served
from Phase 5; the tuned adapter replaces them at Phase 10). **ADR-012 supersedes
ADR-009** — fine-tuning was "a comparison, not a dependency"; self-hosting is now
load-bearing. **ADR-002 is amended, not replaced**: one variable still swaps the
endpoint, the values are just our own sessions now.

### Corrections to the Phase 0 entry above
That entry is left intact per the append-only rule. Three things in it are now wrong:
- `.env.example` no longer has `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENROUTER_API_KEY` / `FINETUNED_TUNNEL_URL`. It has `COLAB_TUNNEL_URL`, `KAGGLE_TUNNEL_URL`, `CUSTOM_BASE_URL`, `LLM_API_KEY`, `LLM_TIMEOUT_SECONDS`.
- `LLM_PROVIDER` values are now `colab_tunnel | kaggle_tunnel | custom`, defaulting to `colab_tunnel`. `LLM_MODEL` defaults to `Qwen/Qwen2.5-3B-Instruct`.
- The accounts list changes: **Colab and Kaggle instead of Google AI Studio and Groq.** Supabase, HuggingFace and Streamlit Cloud are unaffected.

### Changed by A
- `docs/decisions.md` — ADR-011, ADR-012; ADR-002 marked amended, ADR-009 marked superseded
- `docs/project_context.md` — stack table, pipeline, hard rule 4a, success criteria
- `docs/implementation_plan.md` — amendment banner at the top, plus targeted edits to the stack table, Phase 0 accounts and `.env.example`, Phase 4 OCR options, Phase 5, Phase 10, Phase 11, the API budget (now **SESSION BUDGET**), the final architecture diagram, the tech stack summary and the narrative. Not rewritten line by line — the banner says so.
- `docs/state.json` — ADRs, phase work, three new known issues

### Changed by B
- `core/config.py` — `PROVIDER_ENDPOINT` replaces `PROVIDER_CREDENTIAL`; added `llm_api_key`, `llm_timeout_seconds`, and `api_base`, which normalises whatever URL shape gets pasted in after a restart (strips a trailing `/v1` or `/v1/chat/completions`). `validate()` now also rejects a URL missing its scheme.
- `app/main.py` — endpoint table instead of the provider table, live endpoint shown, restart warning
- `.env.example`, `README.md`, `CLAUDE.md` — rewritten for the new model
- `training/serve_finetuned.py` → **`training/serve_model.py`** (it serves base weights from Phase 5, so the old name was a lie). Stub docstrings updated on `core/ai/llm_client.py` and `core/extraction/ocr_cloud.py`.

### New interfaces added to interfaces.md
- `Settings.api_base`, `.active_base_url`, `.active_endpoint_name` replace `.active_credential*`
- `llm_client.health() -> bool` — so the UI can tell "no anomalies" apart from "the notebook died"
- `training/serve_model.py` documented under Phase 5, not Phase 10
- `evaluate(model_name, eval_set)` — the arg is a served model name now, not a vendor

### Known gaps / deliberately deferred
- **This is the biggest operational risk in the project and it is now accepted, not avoided.** A dead Colab session takes the whole app down. The three mitigations — Kaggle backup session, pre-warmed `data/cache/`, recorded demo video — are all **planned and none built**. Phase 5 owns the first, Phase 11 the last two.
- Nothing has been served yet. `serve_model.py` is still a docstring; the tunnel has never been stood up, so cold-start time and session lifetime are estimates.
- Expect Phase 5 extraction quality to start *below* what a frontier model gave. That gap is the thing Phase 10 exists to close — don't read it as a bug.
- `requirements.txt` is unchanged and still correct: no vendor SDK was ever added, and the serving side lives in Colab, not in this repo.

### How to verify this change landed
```bash
python scripts/memory_digest.py     # 12 ADRs, latest ADR-012
grep -ri "gemini\|groq\|openrouter" --include="*.py" .   # no hits outside docs
LLM_PROVIDER=kaggle_tunnel KAGGLE_TUNNEL_URL=https://x.trycloudflare.com/v1 \
  LLM_API_KEY=test python3 -c "from core.config import settings; \
  print(settings.api_base); settings.validate()"
```

---

## Docs consolidation — seven memory files to four (between Phase 0 and Phase 1)

**Recorded:** 2026-08-08 · **Owners:** A + B · **Not a phase — a documentation change, no code behaviour changed.**

### What changed
`docs/` had seven files with heavy overlap: the memory ritual was written out in
`memory_system.md`, `README.md` **and** `CLAUDE.md`; `state.json` kept a
hand-maintained copy of the feature list and ADR titles that already lived in
`progress.md` and `decisions.md`. Three of those copies had already drifted.
Four files remain:

| File | Answers |
|---|---|
| `implementation_plan.md` | *What is the plan?* — unchanged |
| `progress.md` | *What exists, and why is it this way?* — phase log **plus** the ADRs |
| `interfaces.md` | *What can I call, and what will it return?* — unchanged |
| `state.json` | *Where are we right now?* — machine-readable, slimmed |

### Changed by A + B
- `docs/decisions.md` → **merged into Part 2 of this file.** All twelve ADRs are
  verbatim; their headings and anchors are unchanged, so `#adr-011--…` links still
  resolve — the target file is now `progress.md`.
- `docs/project_context.md` → **merged into `CLAUDE.md`**, which already carried a
  compressed version of it. The stack table, data-source table, team split and
  success criteria moved across whole; nothing was dropped.
- `docs/memory_system.md` → **deleted.** Its only non-duplicated content was the
  end-of-phase checklist and the "when you skip this" rationale, both now in
  `CLAUDE.md`.
- `docs/progress.md` — lost the entry template (moved to `CLAUDE.md`) and the
  illustrative Phase-1 "worked example", which described work that was never done
  and read as real to anyone skimming.
- `docs/state.json` — dropped `implemented_features` (progress.md is the authority)
  and the separate `superseded_adrs` map (now a field on each ADR entry).
- `scripts/memory_digest.py` — header line no longer prints a feature count, since
  the feature list it counted is gone. Everything else prints as before.
- `README.md` — memory-file table and ADR links repointed.

### Known gaps / deliberately deferred
- **`implementation_plan.md` still says `memory/` and still names five memory
  files.** It was already wrong about the directory (known issue #1) and is now
  also wrong about the count. Deliberately not rewritten — it is 2130 lines and the
  amendment banner at its top already says it is not authoritative on this.
- Phase 11 still references a `changes.md` that does not exist. Untouched.
- The Phase Prompts inside `implementation_plan.md` tell you to read
  `project_context.md` / `decisions.md`. Those names no longer exist; read
  `CLAUDE.md` and Part 2 of this file instead.

### How to verify this change landed
```bash
ls docs/                          # 4 files
python scripts/memory_digest.py   # still prints; 12 ADRs, latest ADR-012
grep -rn "memory_system\|project_context\|decisions.md" --include="*.md" --include="*.py" . \
  | grep -v implementation_plan   # only historical mentions inside progress.md
```

---

## Phase 0 verification — first real install and run (2026-08-08)

**Recorded:** 2026-08-08 · **Owners:** A + B · **Not a phase — closing out the "never actually run" gap from the Phase 0 entry.**

Phase 0's entry admitted nothing had been installed or run in a real venv. It has
now been. Everything Phase 0 claims to build works; one real bug surfaced and was
fixed, and one part of the definition of done turns out to be unreachable until
Phase 5 by design.

### Verified working
- **`.venv` on Python 3.14.5, all 16 requirements install and import.** `pymupdf`
  (`fitz`) and `psycopg2-binary` both have working 3.14 wheels — the "newer
  versions may lack wheels" warning in `CLAUDE.md` was stale and has been
  corrected. Streamlit Cloud parity is a separate, still-open question (below).
- **`streamlit run app/main.py` executes for the first time.** Serves HTTP 200,
  `/_stcore/health` returns `ok`, and the page renders with **zero exceptions**
  under `streamlit.testing.v1.AppTest`. The three `app/pages/*.py` stubs also
  render with zero exceptions (blank, as documented).
- **`core/config.py` behaves as specified.** Verified by direct test: resolution
  order; `[PASSWORD]`/`[REF]` placeholders treated as unset; `validate()` naming
  every missing variable at once; schemeless URLs and unknown `LLM_PROVIDER`
  values rejected; `mask()`; and `api_base` normalising all five pasted URL
  shapes (bare, trailing `/`, `/v1`, `/v1/`, `/v1/chat/completions`) to the same
  base.
- **`.gitignore` does what it claims.** Confirmed with `git add --dry-run`, not
  `check-ignore` (which is ambiguous on negation patterns): `training/data/train_pairs.jsonl`
  is ignored, `training/data/eval_set.jsonl` is trackable, `data/**/.gitkeep`
  files are tracked while `data/` contents are not.
- **`scripts/memory_digest.py` runs** and reports 12 ADRs, latest ADR-012.
- `pytest` collects 0 tests, as documented. GitHub remote exists (`origin`).

### Bug found and fixed — a blank variable was adopting its own comment
`.env.example` wrote comments inline after empty values:

```bash
COLAB_TUNNEL_URL=              # https://<something>.trycloudflare.com  (primary)
```

python-dotenv strips an inline comment only when the variable **has** a value. On
a blank one it returns the comment text *as the value*. So a freshly copied `.env`
gave `COLAB_TUNNEL_URL = '# https://<something>.trycloudflare.com  (primary)'`,
and the config page showed it **✅ present** — precisely inverting Phase 0's
fail-loudly promise. `KAGGLE_TUNNEL_URL` and `CUSTOM_BASE_URL` were affected too.
`validate()` did still catch it via the URL-scheme check, so the app failed rather
than silently calling a bogus endpoint, but the page lied about why.

Fixed in two places, both `[B]`-owned:
- `.env.example` — every comment moved onto its own line above its variable, with
  a warning at the top of the LLM block explaining why. No variable changed name,
  value or order.
- `core/config.py` — `_read()` now treats any value starting with `#` as unset.
  Defence in depth: users paste comments into `.env` by hand too.

Re-verified after the fix: no variable in `.env.example` parses to a stray
comment, and an unfilled `COLAB_TUNNEL_URL` now correctly shows ❌.

### Two decisions taken at verification time
- **Phase 0's definition of done cannot be met until Phase 5, and that is accepted.**
  It says the config page should show "all keys ✅". But `COLAB_TUNNEL_URL` is
  marked *required*, and no tunnel exists until `serve_model.py` is stood up in
  Phase 5 (ADR-012). A correctly configured Phase-0 machine therefore shows ❌ on
  that one row and `settings.validate()` raises. **Decided: leave it.** The ❌ is
  honest — there is genuinely no endpoint yet — and demoting the variable to
  optional would move the loud failure out of startup and into `llm_client`,
  which is the silent-`None` trap `core/config.py` exists to prevent. Recorded as
  known issue #9, marked do-not-fix. Everything else is ✅ or ⚪.
- **The venv was rebuilt on Python 3.12.13** (`uv venv --python 3.12`), for
  Streamlit Community Cloud parity — Cloud does not offer 3.14, so developing on
  it would mean deploying a different Python than we test. Re-verified from
  scratch on 3.12: all 16 deps import, `app/main.py` renders with zero
  exceptions, digest and pytest behave as before. Note the old warning that 3.14
  "may lack `pymupdf` / `psycopg2-binary` wheels" was **stale** — both build fine
  on 3.14; Cloud parity was the only real reason to move.

### Known gaps / deliberately deferred
- **Import PyMuPDF as `import pymupdf`, not `import fitz`.** The `fitz` alias
  still works but emits a `DeprecationWarning` on the installed version. The plan
  and the older docs all say "fitz". Affects `clause_locator.py` and
  `pdf_renderer.py` when Phases 4 and 7 land. Known issue #12.
- `LLM_API_KEY` has been generated and written to the local `.env`. Every other
  credential is still unset: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_KEY`,
  `HF_TOKEN` (all optional until Phases 1/3) and the tunnel URL (Phase 5).
- Cloud accounts remain unverifiable from the repo. Still a manual step.
- Dependencies are still unpinned and there is still no CI (issue #5).

### How to verify this
```bash
.venv/bin/python -m pytest -q                    # 0 tests, as documented
.venv/bin/python scripts/memory_digest.py        # 12 ADRs, latest ADR-012
.venv/bin/python -c "from core.config import settings; \
  [print(c.status, c.name, c.display) for c in settings.checks()]"
.venv/bin/streamlit run app/main.py              # config page, secrets masked
```

---

## Phase 1 — Cloud Database

**Completed:** 2026-08-08 · **Owners:** A + B

All 12 tables exist and every query helper is implemented and exercised.
**Verified against the SQLite fallback only** — Supabase credentials were not
available, so `DATABASE_URL` is still unset. See known gaps.

### Built by A
- `core/db/models.py` — 12 SQLAlchemy 2.0 models (`DeclarativeBase` / `Mapped` /
  `mapped_column`). `run_id` on every run-scoped table; `clause_references.source_page`
  and `.source_bbox` nullable per ADR-005, with an `is_grounded` helper so
  consumers stop hand-checking two fields. No Postgres-only types — `JSON` not
  `JSONB`, no `ARRAY`, no native `ENUM` — so the SQLite fallback ADR-003 promises
  stays truthful. The four leak types and the anomaly lifecycle are enforced by
  `CheckConstraint`, which both backends honour. `ALL_MODELS` is the canonical
  ordered tuple everything else iterates.
- `core/db/database.py` — lazy engine (importing the module never opens a socket,
  so `streamlit run` still starts against a dead database), `get_session()`,
  a `session_scope()` contextmanager, `init_db()`, `drop_all()`,
  `check_connection()` which never raises, and `describe_backend()` which strips
  the password so it is safe to render.
- `scripts/init_db.py` — `--check` (report only), `--drop` (confirms before
  destroying populated tables), `--yes`. Prints which tables it created and
  fails loudly if any of the 12 is missing afterwards.
- `scripts/reset_run.py` — `--list`, `--run-id N`, `--yes`. Deletes one run and
  verifies the cascade actually emptied the run-scoped tables, rolling back if
  it did not.

### Built by B
- `core/db/queries.py` — 13 read helpers returning **frozen dataclasses**, never
  ORM objects: `SummaryStats`, `AnomalyRow`, `ClauseRefRow`, `ClientRow`,
  `DocumentRow`, `RunRow`. Money is rounded to 2dp exactly once, here at the
  boundary. `get_summary_stats` returns zeroed stats for an unknown run rather
  than `None`, so the dashboard renders empty cards instead of crashing.
- `app/pages/9_db_health.py` — connection status, backend (password stripped),
  per-table row counts with a run selector, and the run list. Renders an
  ordered "things to check" list instead of a traceback when the database is
  unreachable, and warns loudly when the SQLite fallback is active.

### Two schema additions beyond the plan's ER diagram
Both are additions, not changes — nothing in the diagram was altered.

- **`milestones` table.** The diagram draws 11 tables while the plan text and the
  `models.py` stub both say "all 12". Milestones are the missing one:
  `ContractRules.milestones` is in `interfaces.md`, `TimelineEntry.payment_type`
  includes `"milestone"`, and the project's own worked example turns on a $15,000
  launch milestone that was never billed. Without the table, Phase 5 extraction
  has nowhere to put milestones and Phase 6 cannot emit milestone timeline rows.
  Mirrors `price_escalations` / `discounts` deliberately. Adding it makes the
  count 12 and resolves the discrepancy.
- **`expected_timeline.source_clause_ref_id`.** `TimelineEntry` in
  `interfaces.md` already declared it; the ER diagram omitted it. Without it an
  anomaly cannot inherit the clause that proves it, which hard rule 5 requires.

### New interfaces added to interfaces.md
Full listing in the Phase 1 block, all marked ✅. One breaking change:

- **`list_anomalies(...) -> list[AnomalyRow]`, not `list[Anomaly]`.** `Anomaly`
  is already both the ORM model and the Phase-5 Pydantic schema, and the DB row
  carries fields the schema does not (`id`, `status`, `client_name`, agent
  output) while the schema carries `billing_date`, which lives on
  `expected_timeline`. Phase 5's `Anomaly` schema is untouched.

### Verified
47 assertions in one end-to-end pass, all green:
- Every one of the 12 tables populated with a realistic row and read back.
- **ADR-005 both ways:** a clause with `source_page=None, source_bbox=None,
  locate_method="failed"` stores and reports `is_grounded == False`; a located
  one round-trips its bbox as `[72.0, 340.5, 468.0, 366.0]` through JSON.
- Aggregates: `total_leaked == 15480.0`, `by_type`, `unverified_count`,
  `ungrounded_count`; ordering by gap descending; `status` and `anomaly_type`
  filters; unknown-run returning `[]` and zeroed stats rather than raising;
  every `get_*` returning `None` for a missing id.
- **Check constraints reject** an invalid `anomaly_type` and an invalid
  `status`; the `(run_id, normalized_name)` unique constraint rejects duplicates.
- **Cascade delete:** deleting a `Run` empties all 10 run-scoped tables, leaves
  `column_mappings` alone (global by design, ADR-010) and leaves a second run
  fully intact.
- `scripts/init_db.py` creates 12/12 and is idempotent; `--check` reports;
  `reset_run.py --list/--run-id/--yes` works and exits 1 on an unknown id.
- Health page renders with 0 exceptions: "Connected", 12/12 tables, 0 rows.
  Against an unreachable Postgres it renders the error box, still 0 exceptions.
- `app/main.py` and all three pages still render clean; `pytest` still collects 0.

### Known gaps / deliberately deferred
- **Nothing has touched Supabase.** Every result above is SQLite. The Phase 1
  definition of done says "12 tables visible in the Supabase table editor",
  which is **not met** — `DATABASE_URL` is unset because the account has not
  been created yet. The code path is exercised (a bogus Postgres URL produces a
  clean, correct failure), but Postgres-specific behaviour is unproven:
  `JSON` column behaviour, the `CheckConstraint` names, and connection pooling
  under Streamlit's rerun model. **Re-run `python scripts/init_db.py` once
  `DATABASE_URL` is set** and confirm before treating Phase 1 as closed.
- **No tests in `tests/`.** The 47 assertions above ran from a scratch script,
  not from pytest, because `tests/` is docstring-only until Phase 6 by plan.
  That verification is therefore not repeatable in CI. Phase 6 owns fixing it.
- No Alembic; schema changes remain drop-and-recreate until Phase 9. There is
  now real schema to lose, so `init_db.py --drop` prompts before destroying
  populated tables.
- `reset_run.py`'s stub docstring said Phase 2 and `CLAUDE.md`'s command list
  agreed, but the plan's Phase 1 task list asked for it. Built now, because the
  cascade behaviour it depends on is exactly what Phase 1 needed to prove.
- `list_transactions` returns ORM objects on purpose, for Phase 8's
  `check_split_payments` tool. The UI must not call it.

### How to verify this phase works
```bash
python scripts/init_db.py            # 12 tables, then idempotent on re-run
python scripts/init_db.py --check    # every table, 0 rows
streamlit run app/main.py            # sidebar -> DB Health -> "Connected", 12/12, 0 rows
python scripts/reset_run.py --list   # "No runs" until Phase 2 seeds one
```

---

## Phase 1 closed — verified against Supabase Postgres (2026-08-08)

**Recorded:** 2026-08-08 · **Owners:** A + B · **Closes the only gap in the Phase 1 entry above.**

The Supabase project now exists and `DATABASE_URL`, `SUPABASE_URL` and
`SUPABASE_KEY` are set. Everything Phase 1 could only prove on SQLite has been
re-proved on Postgres. **Phase 1's definition of done is met in full.**

### What was run against Postgres
- `python scripts/init_db.py` → **12/12 tables created** in schema `public`,
  and idempotent on a second run. `information_schema` confirms all twelve are
  present and visible to the Supabase table editor, with the expected column
  counts (`anomalies` 15, `expected_timeline` 11, `contract_rules` 10,
  `documents` 9, `actual_transactions` 8, `clause_references` 8, `milestones` 7,
  `discounts` 5, `price_escalations` 5, `runs` 5, `clients` 4,
  `column_mappings` 4).
- **The same 47 assertions, re-run unmodified against Supabase: all pass**, with
  byte-identical results to the SQLite run — same aggregates, same ordering,
  same `None` handling, same constraint rejections, same cascade behaviour.
- **ADR-005 confirmed at the schema level, not just in Python.**
  `clause_references.source_page` is `integer NULLABLE=YES` and `.source_bbox`
  is `json NULLABLE=YES` in Postgres. A quote that could not be located is
  storable by the database itself, not merely by our code.
- **All six `CheckConstraint`s materialised with their intended names:**
  `ck_anomaly_type`, `ck_status`, `ck_locate_method`, `ck_payment_type`,
  `ck_billing_frequency`, `ck_extraction_status`. The four leak types are now
  enforced by Postgres.
- `JSON` columns round-trip correctly: `source_bbox` returns
  `[72.0, 340.5, 468.0, 366.0]` as a list of floats, and `agent_tool_calls`
  returns a list of dicts.
- DB Health page: **0 exceptions, "Connected", 12/12 tables, 0 rows, 0 runs**,
  and the SQLite-fallback warning correctly no longer appears. `app/main.py`
  and both product pages still render with 0 exceptions.
- `scripts/reset_run.py --list` and `scripts/init_db.py --check` both behave
  correctly against Postgres.

Test rows were deleted afterwards. **Every table is empty**, which is the
correct end state for Phase 1 — `scripts/seed_demo.py` fills them in Phase 2.

### Resolved
- Known issue #13 (Phase 1 verified on SQLite only) — **closed.** Postgres
  behaviour is no longer unproven: JSON columns, constraint naming and
  nullability are all confirmed.
- `state.json` phase 1 status moves from `done_on_sqlite_pending_supabase` to
  `done`.

### Known gaps / deliberately deferred
- **Connection pooling under Streamlit's rerun model is still only lightly
  exercised.** `pool_pre_ping` and `pool_recycle=1800` are set to survive
  Supabase dropping idle connections, but nothing has yet held the app open long
  enough to prove it. Phase 2's UI work is where this will show up if it is
  wrong.
- Supabase free projects **pause after a week of inactivity**, and a paused
  project fails exactly like a wrong password. The DB Health page lists
  "resume it in the dashboard" as check #3 for that reason.
- The 47 assertions still live in a scratch script rather than `tests/`
  (issue #15). Unchanged by this entry — Phase 6 owns porting them.
- `SUPABASE_URL` / `SUPABASE_KEY` are set but **unused so far**. They are for
  Supabase Storage, which Phase 2 onward needs for uploaded files; nothing has
  called the storage client yet.
- `HF_TOKEN` is still unset. Needed in Phase 3.

### How to verify
```bash
python scripts/init_db.py --check    # 12 tables, 0 rows, against Postgres
streamlit run app/main.py            # DB Health -> Connected, 12/12, no SQLite warning
```
Then open the Supabase dashboard → **Table Editor** → all 12 tables listed.

---

## Phase 2 — Frontend Shell (The Top-Down Moment)

**Completed:** 2026-08-08 · **Owners:** A + B

The whole application is visually complete and reading real Supabase rows. No
AI anywhere. **Every number on every page traces to a database row** — there is
no hardcoded dict in `app/`, which is the rule that makes Phase 6 a data change
rather than an integration project (ADR-008).

### Built by A
- `scripts/seed_demo.py` — `seed_run()` plus a CLI (`--label`, `--replace`,
  `--list`). Writes 5 clients, 5 contract rules, 13 clause references, 61
  expected-timeline rows, 59 transactions and 7 findings across all four leak
  types, affecting 3 of 5 clients. **Nothing is hand-entered twice:** contracts
  are declared once in `SCENARIO`, the timeline is computed from them, actuals
  are the timeline with named deviations applied, and anomalies are derived from
  the difference. So `gap == expected - actual` and `total == sum(gaps)` hold
  structurally, and the script asserts both before exiting. A UI bug is
  therefore distinguishable from a data bug, which is the only reason Phase 2
  debugging is worth anything.
  Two contracts are deliberately clean controls; one clause is deliberately
  unlocatable (ADR-005).
- `core/storage/files.py` — **local-disk backend only.** `save_upload` writes to
  `data/uploads/<run_id>/` and returns a `file://` URL; `load` returns `None`
  rather than raising for seeded or missing files. The signature is the one
  Supabase Storage will need, so Phase 4 changes this module and nothing else.
  `describe()` tells the UI where files actually went, so the app never implies
  cloud storage it does not have.
- `docs/report_notes.md` — evidence log started: screenshots to take,
  measurements as produced, decisions and things that went wrong.

### Built by B
- `app/main.py` — landing page. Status strip for the three things that can fail
  (database, model endpoint, upload storage), current-run headline figures, what
  the product finds, and how the numbers stay defensible. **Phase 0's full
  configuration table is preserved verbatim** in an expander that auto-opens
  when `validate()` fails.
- `app/state.py` — the only module that touches `st.session_state` by key. Holds
  **ids, never rows**: caching row objects across reruns would let the UI drift
  from the database it is supposed to mirror.
- `app/components/summary_cards.py` — four metric cards, the leak-type
  breakdown, and the grounding note.
- `app/components/anomaly_table.py` — findings table with single-row selection,
  type/status filters built from what is actually present, and the per-finding
  detail block.
- `app/components/clause_viewer.py` — the evidence panel, handling all three
  ADR-005 states (located / quoted-but-not-located / no clause at all).
- `app/components/file_uploader.py` — dual upload zones. Files are stored and
  recorded as `documents` rows with `extraction_status="pending"`; **nothing is
  parsed**, and the UI says so.
- `app/components/client_confirm.py` — the confirmation step, display-only until
  Phase 5's fuzzy grouping.
- `app/components/cash_flow_chart.py` — Plotly two-line cumulative chart with an
  optional threshold. Draws pre-computed series; does no arithmetic.
- `app/pages/1_integrity_engine.py` — the v1 mockup, built: cards → upload →
  confirm clients → findings → evidence.
- `app/pages/2_decision_engine.py` — question box, cost slider, verdict,
  breakdown table and 12-month chart. Every figure derives from
  `SummaryStats.total_leaked` and the findings; the verdict is a template and
  the page says so.

### Two bugs found by building on top of Phase 1
- **Scoped row counts were silently global.** Five tables (`contract_rules`,
  `clause_references`, `price_escalations`, `discounts`, `milestones`) have no
  `run_id` — they hang off `contract_rules → clients → runs`. `table_counts`
  counted them globally while the health page claimed to scope to a run.
  Harmless with one run, wrong the moment a second exists. Now joined back to
  `clients.run_id`; `GLOBAL_TABLES` names the one table (`column_mappings`) that
  genuinely has no run scope, and the health page labels it. Found by a
  cascade-delete assertion, not by looking at the page.
- **Two ADR-005 failure modes were conflated in one counter.** "No clause at
  all" (unproven finding — hard rule 5) and "clause quoted but not locatable"
  (valid finding, degraded highlight) are different. `ungrounded_count` split
  into `unlinked_count` and `unlocatable_count`, with `grounding_rate` derived.
  The dashboard now states honestly how much of the headline total is provable.

### New interfaces added to interfaces.md
All Phase 2 entries marked ✅. Two deviations from the pre-written contract:
- **`render_clause_viewer(clause: ClauseRefRow | None)`**, not `(clause_ref_id: int)`.
  The page already holds a session and must handle the no-clause case anyway, so
  passing the row keeps the component free of DB access and makes `None` explicit.
- **`seed_run(session, scenario_dir=None, label="demo_v1")`** — argument order
  preserved, both optional. Passing `scenario_dir` raises `NotImplementedError`
  rather than silently seeding something other than what was asked for.

Plus two `SummaryStats` fields (`affected_client_count`, and the
`unlinked`/`unlocatable` split) so the UI never computes a figure.

### Verified
- **All four pages render with 0 exceptions** against Supabase, via
  `streamlit.testing.v1.AppTest`.
- **The dashboard's numbers match the seeder exactly**: cards read
  `$26,908 / 7 / 3 of 5`, and the findings table's Gap column sums to
  `26,908.0` — the same figure, arrived at by two different queries.
  All four leak types appear.
- **Both ADR-005 drill-down paths exercised.** A located clause renders
  "Located on page 1 · exact"; the unlocatable one renders the degradation
  warning. **Neither crashes** — which is the actual requirement.
- Decision Engine produces a coherent verdict from real figures
  ($23,000 one-off + $3,908 recurring = $26,908 against a $60,000 commitment).
- **Phase 1's 47 assertions still pass** after the `SummaryStats` changes,
  re-run against Postgres.
- Run-scoped `table_counts` now returns the demo run's real counts.

### Known gaps / deliberately deferred
- **Uploads are local-disk only and therefore not deployable.** Streamlit
  Community Cloud has an ephemeral filesystem, so uploaded files would vanish on
  restart. The Supabase Storage bucket (`finsight-documents`) **does not exist —
  creating it is a dashboard step nobody has done.** Phase 4 owns switching
  `files.backend()` over. Known issue #16.
- **`app/components/column_mapper.py` is still a stub.** It needs an LLM-proposed
  mapping to confirm (ADR-010), which is Phase 4. The plan said "build every
  component in the tree"; this is the one exception, and building an empty
  confirmation UI with nothing to confirm would have been theatre.
- **The clause viewer shows no PDF page image.** `pdf_renderer.py` is a Phase 7
  stub, and the seeded documents have `seed://` URLs with no bytes behind them.
  Real page numbers, real quotes, real `locate_method` — no picture.
- **The Decision Engine does not read your question.** The text box is inert;
  the cost comes from the slider. `decision_analyzer.py` and `cashflow.py` are
  Phase 9. The page says so in three places rather than implying otherwise.
- **The "Confirm & Analyze" button does not analyse.** It acknowledges and
  explains that the pipeline lands in Phases 5–6.
- Row selection is `st.dataframe(selection_mode="single-row")`, which
  `AppTest` cannot click. The selection path was verified by injecting
  `session_state` instead; the widget itself is only manually verified.
- Still no tests in `tests/` (issue #15). Everything above is scratch harnesses.

### How to verify this phase works
```bash
python scripts/init_db.py            # 12 tables
python scripts/seed_demo.py --replace  # asserts gap/total consistency, prints counts
streamlit run app/main.py
```
Then: landing page → **Revenue Integrity Dashboard** → cards read $26,908 / 7 /
3 of 5 → click the **Nexus Digital · Ghost Invoice · Apr 2025** row → the
evidence panel shows the quoted milestone clause with the "could not be located"
warning. Click a **Starter Labs** row instead for the located state.

---

## Supabase Storage is live — and the CDN serves stale reads (2026-08-08)

**Recorded:** 2026-08-08 · **Owners:** A + B · **Closes known issue #16 and changes how object keys are formed.**

The private `finsight-documents` bucket now exists and `core/storage/files.py`
runs on the Supabase backend. Getting there surfaced two things worth recording,
the second of which would have been a silent data-corruption bug in Phase 4.

### The anon key cannot write to a private bucket
`upload` with the anon key returns `403: new row violates row-level security
policy`. The bucket is private with no RLS policies, which denies the anon role
everything — `list()` returns `[]` rather than erroring, so the bucket looks
absent when it is merely invisible.

**Decision: use the `service_role` key**, added as `SUPABASE_SERVICE_KEY` and
read only by `core/storage/files.py`. The alternative was RLS policies granting
the anon role insert/select, which would rest the privacy of client contracts on
a key designed to be publishable. Streamlit renders entirely server-side, so
service_role never reaches a browser — that is the condition that makes it
correct here, and it would be the wrong choice in a client-rendered app. The
bucket keeps zero policies.

Verified private: `public=False` in the bucket metadata, and an unsigned public
URL returns HTTP 400 while a signed URL serves the bytes.

### The bug: Supabase's CDN ignores `cache-control`, and stale reads survive deletion
Re-uploading **different** bytes to the same key returns the **old** content.
Proved it is a read cache, not a failed write, by comparing the server's own
object listing against `download()`:

| step | server-side object size | `download()` returns |
|---|---|---|
| upload `b"AAA"` | 3 | `b"AAA"` |
| upsert `b"BBBBBBB"` | **7** | `b"AAA"` ❌ |
| `remove()` | *(object gone)* | `b"AAA"` ❌ |

So the writes were always correct and the reads were stale — **including after
the object was deleted.** Setting `cache-control: no-store` and `cacheControl: 0`
on upload both changed nothing; the CDN ignores them.

This was days away from being a real bug. Phase 4 uploads a document and
immediately extracts text from it, so re-uploading a corrected contract would
have silently extracted the *previous* version, and every downstream number
would have been confidently wrong with no error anywhere.

**Fix: content-addressed object keys** — `<run_id>/<sha256[:12]>_<safe name>`.
A key's bytes can now never change, so a stale cache is always *correct* rather
than wrong. This removes the failure mode instead of working around it, and it
is the same trick the LLM disk cache already uses (`sha256(prompt + model)`).
Two free consequences: identical content re-uploaded dedupes to the same URL,
and a changed file gets a new key while the old one stays readable.

### Changed
- `core/config.py` — `SUPABASE_SERVICE_KEY`, masked in `checks()` like any secret.
- `.env.example` — the new variable, with a warning about what it can do.
- `core/storage/files.py` — Supabase backend: `save_upload`, `load`,
  `signed_url`, `delete`, `check`. `object_key(filename, run_id, data)` now
  takes the bytes, because the key depends on them. `save_upload` raises
  `StorageError` rather than returning `None` — a dropped upload would leave a
  `documents` row pointing at nothing.
- `safe_filename` no longer leaves a trailing underscore before the extension
  (`Contract (v2).pdf` → `Contract_v2.pdf`, not `Contract_v2_.pdf`).
- `app/components/file_uploader.py` — catches `StorageError`, not `OSError`.

### Verified
11 assertions against the live bucket, all passing: content-addressed key
shape; byte-identical round trip; identical content deduping to the same URL;
**changed content getting a new key and reading back the new bytes while the old
key still serves the old bytes**; signed URL serving correctly; unsigned public
URL blocked (HTTP 400); cleanup. All four pages still render with 0 exceptions,
now with `backend() == "supabase"`.

### Known gaps / deliberately deferred
- **Nothing writes to the bucket in the product yet.** The uploader is wired to
  it, but Phase 2's seeded documents use `seed://` URLs with no bytes behind
  them. The first real traffic is Phase 4.
- **No orphan cleanup.** Deleting a run removes its `documents` rows but leaves
  the objects in the bucket. Content-addressing makes this worse, not better —
  every edited re-upload leaves its predecessor behind. Harmless at demo scale
  (free tier is 1 GB); worth a sweep before Phase 11.
- `SUPABASE_KEY` (anon) is now unused — `files.py` uses service_role and the
  database goes through SQLAlchemy, not PostgREST. Kept because Phase 11's
  deployment may want a client-side path. It is not dead config, just unused.
- The service_role key is in `.env` (gitignored) and must go into **Streamlit
  Secrets**, never the repo, at Phase 11.

---

## Pre-Phase-3 spike — CUAD/EDGAR data-source viability (Risk R1)
**Completed:** 2026-08-10 · **Owners:** A / B · **Not a phase.** No phase status changed.

Run before writing Phase 3 code, to test the assumption the plan never tested:
*do real CUAD contracts actually contain the billing rules FinSight looks for?*
They largely do not. EDGAR does. Details below; decisions in ADR-013 and ADR-014.

### Built (throwaway probes, not Phase 3 deliverables)
- `scripts/contract_scoring.py` — shared scoring so CUAD and EDGAR are judged by
  identical criteria. Five rule categories, a concrete/unredacted second stage,
  clause fingerprinting and blank counting.
- `scripts/cuad_probe.py` — downloads all 510 CUAD PDFs from HF
  `theatticusproject/cuad` (public, **no HF_TOKEN needed**), extracts text with
  PyMuPDF, scores, writes `VERDICT.md` + gold/templates/survivors/evidence.
- `scripts/edgar_probe.py` — SEC full-text search (`efts.sec.gov`), fetches
  EX-10/EX-99 exhibits, same scoring. SEC requires a contact User-Agent.
- `scripts/fill_blanks.py` — assembles the deduplicated corpus and inserts
  values into redacted clauses **deterministically**, recording each as ground
  truth by construction (ADR-014).

### The measurements that decided it

| | CUAD (510) | EDGAR (288) |
|---|---:|---:|
| Plan's ANY-keyword filter | 248 (48.6%) | — |
| Real recurring $ amount | 55 (10.8%) | 161 (55.9%) |
| Real % / CPI escalation | 18 (3.5%) | 68 (23.6%) |
| **Both, unredacted ("gold")** | **8 (1.6%)** | **51 (17.7%)** |
| Gold surviving a hand read | **3** | — |
| Redacted financials | 121 (23.7%) | 72 (25.0%) |

**Two traps the plan's filter hides, both now measured:**
1. **`escalat*` is a false friend.** 81 CUAD contracts match it; **68 mean the
   *dispute* escalation procedure**, not a price rise. Any filter containing bare
   `escalat` silently imports them as `forgotten_raise` candidates.
2. **Redaction.** ~24% of both corpora carry `[***]` where the rate should be —
   SEC confidential treatment. A perfect clause with no number is unusable as-is.

**Counting documents overstates the corpus ~2.5x.** EDGAR's 51 gold carry only
**21 distinct escalation clauses** — one administrator (Ultimus) sends every fund
trust the same fee letter. Dedupe on the clause, not the filename.

**The inversion that mattered:** the *redacted* pile is more varied than the gold
pile — 49 templates carry **33** distinct clauses vs gold's 21, with **zero
overlap**. Boilerplate fee letters publish their numbers; genuinely negotiated
commercial contracts redact them. Redaction is a signal of a *better* document.

### Result: `data/corpus/contracts_v0/` — 44 distinct contracts
One per filer, one per distinct clause wording. Target was 30.

| Bucket | N | Meaning |
|---|---:|---|
| `ready/` | 19 | Real amount + real escalation already present |
| `filled/` | 6 | 16 values inserted deterministically; key in `ground_truth_fills.json` |
| `review/` | 19 | Clause shape right, no figure found — **needs a human look** |
| `skipped/` | 0 | — |

Plus 3 CUAD contracts that survived hand-reading (UAGH `$40,000/month` + anniversary;
BNL `$5,000/month` + 10%/yr cap; SPI Energy 3%/yr at first anniversary).

### New interfaces added to interfaces.md
- None. These are spike scripts outside the A/B boundary. When
  `data_sourcing/filter_contracts.py` is written for real it should inherit the
  patterns and the three-bucket idea from `scripts/contract_scoring.py`.

### Decisions recorded
- ADR-013: EDGAR is the primary contract source; CUAD is demoted
- ADR-014: Redacted values are filled deterministically, never by a model

### Known gaps / deliberately deferred
- **The 19 in `review/` are unverified.** Some will have the amount in an exhibit
  that was never filed. Expect to lose ~a quarter, landing near 40. Nobody has
  read them yet.
- **Corpus variety is adequate, not good.** 44 contracts, and the EX-99 fund
  cluster is over-represented because the probe's queries were generic and it
  only ever read **page 1** of each result list. A broader, deeper search
  (industry-specific queries, pages 2–10, cap per filer) is written up but not
  run. Do it before Phase 10, not before Phase 3 — variety is only load-bearing
  for training and the base-vs-tuned claim.
- **EDGAR serves HTML, not PDF.** Phase 7's clause viewer locates quotes with
  PyMuPDF `page.search_for()`, which needs a PDF. Either convert before these
  enter `data/corpus/contracts/`, or accept page-level degradation (ADR-005
  already permits a null bbox). Not solved, not costed.
- `data_sourcing/fetch_contracts.py` and `filter_contracts.py` are **still
  one-line stubs**. This spike did not write Phase 3; it de-risked it.
- Contracts are large-company SEC filings. FinSight's stated customer is a 3–20
  person studio. The prose is genuine but the domain is not the target domain —
  say so in the report rather than letting a reader assume otherwise.
- No ground truth exists yet for the `ready/` 19 — only the 6 `filled/` ones have
  a recorded answer key, and that covers the inserted values only, not a full
  `ContractRules` extraction.

### How to verify this phase works
```bash
python scripts/cuad_probe.py     # -> data/corpus/cuad_probe/VERDICT.md
python scripts/edgar_probe.py    # -> data/corpus/edgar_probe/REPORT.md
python scripts/fill_blanks.py    # -> data/corpus/contracts_v0/MANIFEST.md
```
Then open `data/corpus/contracts_v0/MANIFEST.md`; `ready/` + `filled/` + `review/`
must total 44, and every value in `ground_truth_fills.json` must appear verbatim
in the corresponding `filled/*.txt`.

---

## Phase 3 — Online Data Sourcing
**Completed:** 2026-08-12 · **Owners:** A / B

**Starting condition, corrected.** `docs/state.json` and this file's own "Pre-Phase-3
spike" entry above describe a 44-contract corpus at `data/corpus/contracts_v0/`. That
directory did not exist on disk at the start of this phase — `data/` is entirely
gitignored (`.gitignore` line 7, `data/**`), so the spike's output never persisted past
the session that built it. The spike de-risked Phase 3 (proved EDGAR beats CUAD, proved
the concrete-value filter, proved deterministic filling); it did not leave artifacts.
This phase re-ran the real pipeline — now as `data_sourcing/*.py`, not throwaway
`scripts/*_probe.py` — against live EDGAR and got materially the same yield (43 vs. the
spike's 44), which is itself a second confirmation of ADR-013's numbers.

### Built by A
- `core/ai/schemas.py` — `Escalation`, `Discount`, `Milestone`, `ContractRules`,
  `TimelineEntry`, `Anomaly`, `ClauseLocation` Pydantic models, per the "Shared data
  shapes" section of `docs/interfaces.md`. **Pulled forward from Phase 5** — only the
  data shapes, not `contract_extractor.extract_rules()` — because
  `data_sourcing/scenario_builder.py`'s own documented signature takes
  `rules: list[ContractRules]` and Phase 3 runs before Phase 5 exists (ADR-008's
  top-down order). No model call lives here.
- `data_sourcing/fetch_contracts.py` — `fetch_edgar_msa()` (SEC full-text search,
  EX-10/EX-99 exhibits, compliant User-Agent + 429 backoff) and `fetch_cuad()`
  (`theatticusproject/cuad` via `huggingface_hub`, no token). Ported from
  `scripts/edgar_probe.py`/`cuad_probe.py`, cleaned up as real (non-throwaway) code.
- `data_sourcing/filter_contracts.py` — `filter_service_contracts()` and
  `deduplicate()` on **concrete unredacted values**, never keyword presence (ADR-013);
  `fill_document()`/`choose_value()` folded in from `scripts/fill_blanks.py` per
  ADR-014, including the refuse-when-unsure behaviour. Adds `build_corpus()`, an
  orchestrator (fetch → filter → dedupe → fill → write buckets) that
  `python -m data_sourcing.filter_contracts` runs end to end.
- Ran the real pipeline against live EDGAR (260 exhibits fetched, ~6 req/s, SEC-compliant):
  **43 distinct contracts** into `data/corpus/contracts/` — `ready/` 19, `filled/` 6,
  `review/` 18 — plus `ground_truth_fills.json` and `MANIFEST.md`. Matches the spike's
  19/6/19 split almost exactly, on a fresh, independently-drawn EDGAR sample.

### Built by B
- `data_sourcing/fetch_invoices.py` — `fetch_invoice_images()` (`mychen76/invoices-
  and-receipts_ocr_v1`), `fetch_invoice_ocr_ground_truth()` (`naver-clova-ix/cord-v2`),
  both HF `streaming=True` with a `limit` so nothing pulls a multi-GB dataset for a
  Phase 4 fallback path that isn't built yet. `fetch_kaggle_transactions()` wraps
  `kagglehub` (added to `requirements.txt`) and returns `None` rather than raising —
  Kaggle credentials are not part of `core/config.py` and are unverified (known_issues
  #7), so nothing downstream may hard-depend on it.
- `data_sourcing/scenario_builder.py` — `TrueRule` (one hand-read real contract),
  `expected_row()` (private, pure timeline arithmetic — deliberately duplicates the
  shape of Phase 6's future `timeline_generator.generate_timeline`, since Phase 6 does
  not exist yet and this file does not own `core/engine/`), and `build_scenario()`.
  Hand-verified **7 real contracts** from `data/corpus/contracts/` (GameznFlix Inc.,
  RMD Technologies Inc., CBS Outdoor Americas Inc., Central Garden & Pet Co., Vision
  Hydrogen Corp., Cellteck Inc., Regal Entertainment Group) — recurring amount,
  escalation %/trigger, discount %/duration and clause text all read by hand from the
  actual filing text (Regal's amount and percentage were ADR-014 fills, flagged
  `filled_by_adr014=true` in its `ground_truth.json` entry). One hand-read candidate
  (Cellteck) was caught mid-build: its automated "concrete_escalation" match was a
  **false positive** — an 18%-per-annum loan interest rate, not a fee escalation — so
  it is used only for its genuine 30%-first-year discount clause, with no escalation
  encoded. This is the same trap ADR-013 documents for CUAD's bare `escalat*`, now
  observed on EDGAR's own "gold" tier: **automated concrete-value scoring still needs a
  human read before a contract enters a scenario.**
- Built and wrote all three scenarios to `data/scenarios/{easy,realistic,edge}/`, each
  with `contracts/` (copies of the real source files), `actuals.csv`, `ground_truth.json`,
  `manifest.json`:

  | Scenario | Clients | Leaking | Anomalies | Total gap | Types present |
  |---|---:|---:|---:|---:|---|
  | `easy` | 4 | 4 | 7 | $17,815.00 | all 4 |
  | `realistic` | 4 | 3 | 5 | $22,500.00 | forgotten_raise, ghost_invoice, short_change |
  | `edge` | 2 | 0 | 0 | $0.00 | — |

  `realistic` adds what `easy` doesn't: date jitter (±1–6 days) on every transaction,
  three rotating client-name variants per client (bank-statement-style vs. natural vs.
  ACH-suffixed), one `short_change` delivered as two separate partial-payment
  transactions summing to 80% of the expected amount (for Phase 8's future
  `check_split_payments` tool), and three unrelated noise transactions (bank fees,
  interest credit) tied to no client. `edge` proves discrimination — zero anomalies
  from two contracts paid exactly as billed, escalation correctly applied on schedule.

  **What is real vs. scenario-assigned, stated once, in
  `data_sourcing/scenario_builder.py`'s module docstring and repeated here:** every
  dollar amount, percentage, trigger duration and clause quote is verbatim from a real
  EDGAR filing. `contract_start` dates are scenario-assigned so each contract's
  genuinely annual escalation/discount cutover lands at a demoable month inside the
  2025 observation window — this is arithmetic construction of a billing calendar
  (ADR-007's "actuals are derived"), not invention of a contract term.

### New interfaces added to interfaces.md
- `core/ai/schemas.py` shared data shapes — flip to ✅ (schemas only; `extract_rules()`
  itself stays ⬜ for Phase 5).
- `data_sourcing/fetch_contracts.py: fetch_edgar_msa, fetch_cuad` — ✅
- `data_sourcing/filter_contracts.py: filter_service_contracts, deduplicate,
  fill_document` — ✅
- `data_sourcing/scenario_builder.py: build_scenario` — ✅ (signature takes an
  additional keyword-only `clients: list[ClientScenario] | None` beyond the plan's four
  positional args — the richer per-client detail, real callers need to say which
  months break, which type, and whether it's a split payment)

### Decisions recorded
- No new ADR. This phase executes ADR-007, ADR-013 and ADR-014 as written; it does not
  revise them.

### Known gaps / deliberately deferred
- **18 of 43 corpus contracts sit in `data/corpus/contracts/review/`** — clause shape
  right, no figure found. Nobody has read them; expect to lose roughly a quarter on a
  hand pass, same as the spike predicted. None of the 7 scenario contracts come from
  this bucket.
- **Corpus variety is adequate, not good** — same gap the spike already flagged
  (known_issues #27): broader, deeper EDGAR search (industry-specific queries, pages
  2–10, cap per filer) is scheduled before Phase 10, not before Phase 3.
- **EDGAR serves HTML, not PDF** (known_issues #28) — unchanged, unsolved here. The
  7 scenario contracts are `.txt`, not `.pdf`; Phase 7's `page.search_for()` needs a
  PDF, so either these get converted before Phase 7 or the clause viewer degrades to
  page-level for every Phase-3-sourced document (ADR-005 already permits this).
- **`fetch_cuad()` works but was not run at scale this phase** — CUAD stays demoted to
  Phase 5 extraction-dev and Phase 10 training volume per ADR-013; the 260-document
  EDGAR pull alone cleared the 30+ contract bar.
- **`fetch_kaggle_transactions()` returns `None` in this environment** — no Kaggle
  credentials configured. `scenario_builder.py`'s own noise generator (date jitter,
  name variants, synthetic unrelated transactions) does not depend on it and is what
  `realistic` actually uses.
- **No `data/scenarios/*` loader exists yet.** `scripts/seed_demo.py`'s `scenario_dir`
  parameter still raises `NotImplementedError` by design (Phase 2's own docstring says
  so). Wiring a scenario on disk into the database is not in this phase's definition of
  done and is left for whichever later phase needs it.
- Contracts are still large/mid-cap SEC filings; FinSight's stated customer is a 3–20
  person studio. Genuine legal prose, not the target domain — say so in any report,
  per known_issues #30.

### How to verify this phase works
```bash
python -m data_sourcing.filter_contracts --count 260   # -> data/corpus/contracts/MANIFEST.md (43 contracts)
python -m data_sourcing.scenario_builder                # -> data/scenarios/{easy,realistic,edge}/
```
Then, for every scenario: `gap == expected_amount - actual_amount` on every timeline
row, `ground_truth.json.total_gap == sum(client_gap) == sum(anomaly gaps)`, and
`manifest.json.total_gap`/`n_anomalies` match `ground_truth.json` exactly — all
asserted directly against the written files as part of this phase (not eyeballed).
`edge` produces 0 anomalies from 2 real, correctly-paid contracts.

---

## Phase 4 — Document Ingestion & Text Extraction
**Completed:** 2026-08-12 · **Owners:** A / B

### Built by A
- `core/extraction/pdf_extractor.py` — `char_density()` (cheap per-page peek used
  for the text_pdf/scanned decision) and `extract_text_pdf()` (pdfplumber text +
  table extraction, page-tagged). Both raise `ValueError` with a readable message
  on a corrupt/unopenable file instead of leaking pdfminer's raw exception —
  found live (see "Known gaps" below), not anticipated.
- `core/extraction/document_router.py` — `detect_type()` and `extract()`, the
  single entry point. Routes `.pdf` by measured char density, `.png/.jpg/.jpeg`
  to the OCR fallback, `.csv` to a raw-text passthrough (structured parsing is
  csv_parser's job, not this file's).
- `core/db/models.py` — added `Document.extracted_text` / `.extracted_page_count`
  (nullable `String`/`Integer`). Not in the plan's original schema; added because
  "documents rows appear with... readable text" (Phase 4 definition of done) has
  nowhere else to live and re-extracting from storage on every page view would be
  wasteful. Same pattern as Phase 1's `milestones` table: extend, drop-and-recreate
  locally, never Alembic-migrate before Phase 9. `core/db/queries.py`'s
  `DocumentRow`/`get_document`/`list_documents` updated to carry the two fields.
- **Fixed a live bug in `core/storage/files.py`** (Phase 2 code, owned by A):
  `load()`/`delete()` stripped `file://` naively (`storage_url[len("file://"):]`),
  which leaves a stray leading `/` before the drive letter on Windows
  (`Path.as_uri()` produces `file:///C:/Users/...` — three slashes). `WindowsPath`
  then parses `/C:/Users/...` as a folder literally named `C:` under the current
  drive's root, so `is_file()` was always `False`. Every local-backend `load()`
  call was silently broken; Phase 2's own verification only exercised the
  Supabase backend. Fixed with `urllib.request.url2pathname` + `urlparse`, the
  stdlib functions that already encode the per-platform rule. Caught because this
  phase is the first code to call `files.load()` on a real local upload — CSV
  column mapping needs the bytes back after `save_upload`.

### Built by B
- `core/extraction/csv_parser.py` — `sniff_columns()` proposes a `{field: column}`
  mapping via `thefuzz` header-name matching against a synonym vocabulary, **not**
  an LLM call: `core/ai/llm_client.py` doesn't exist until Phase 5 stands up the
  self-hosted endpoint (ADR-012; `COLAB_TUNNEL_URL` is unset by design until
  then). `parse_transactions()` cleans currency strings (`"$6,000.00"`,
  `"(1,500)"` → negative) and dates (dayfirst auto-detected from parse-failure
  rate) into `list[TransactionRow]`.
- `core/ai/schemas.py` — added `DocBlock`, `ExtractedDoc`, `TransactionRow`,
  `ColumnProposal`. Not pre-declared as Phase 3's `ContractRules` was in
  `interfaces.md`'s "Shared data shapes" section; defined here because Phase 4 is
  what first needs them, in the same file since they cross the same A/B boundary
  it exists to serve.
- `app/components/column_mapper.py` — the ADR-010 human-confirmation dropdowns
  over `sniff_columns()`'s proposal. Identical UI regardless of whether the
  proposal came from the heuristic (today) or an LLM (Phase 5) — it doesn't know
  or care. Caches a confirmed mapping by header signature in `column_mappings`.
- `app/components/file_uploader.py` — rewritten to actually call extraction.
  Contracts and invoice/statement PDFs or images now route through
  `document_router.extract()` **synchronously at upload time** (bytes are
  already in memory from the upload — no storage round trip needed), landing
  with `extraction_status` already `complete`/`failed`. A CSV stays `pending`
  until `render_pending_csv_mappings()` (new) walks the human-confirmation step
  and writes `actual_transactions` with `client_id=None` (resolved later by
  Phase 5's `client_matcher`). `render_document_list()` gained a "Preview
  extracted text" expander.
- `app/pages/1_integrity_engine.py` — wired `render_pending_csv_mappings()` in
  between the upload block and "2 · Confirm clients".

### New interfaces added to interfaces.md
- `core/ai/schemas.py`: `DocBlock`, `ExtractedDoc`, `TransactionRow`,
  `ColumnProposal` — added to "Shared data shapes".
- `core/extraction/document_router.py: detect_type, extract` — ✅
- `core/extraction/pdf_extractor.py: char_density, extract_text_pdf` — ✅ (not
  in the plan's original interfaces.md stub; added to match what document_router
  actually calls)
- `core/extraction/ocr_cloud.py: has_text_layer, extract_scanned, ocr_page` — ✅
- `core/extraction/csv_parser.py: sniff_columns, parse_transactions` — ✅
- `app/components/column_mapper.py: render_column_mapper` — ✅

### Decisions recorded
- No new ADR. `sniff_columns()`'s heuristic-instead-of-LLM choice is a phasing
  consequence of ADR-012 (serving stands up in Phase 5), not a new architectural
  decision — the swap point is documented in the module docstring instead.

### Known gaps / deliberately deferred
- **`.xlsx` actuals are accepted by the upload widget but not parsed.**
  `ACTUALS_TYPES` includes it (Phase 2), but `csv_parser` only reads real CSVs.
  An uploaded `.xlsx` now fails cleanly with "only .csv is parsed today" instead
  of crashing pandas — not silently mis-parsed, just not built yet.
- **`sniff_columns()` is a heuristic, not the LLM ADR-010 describes.** Phase 5
  can swap the function body for a real `llm_client.complete_json` call with zero
  changes to `column_mapper.py` or the `ColumnProposal` shape — that boundary was
  deliberately kept clean for exactly this swap.
- **OCR fallback is untested against a real scanned document.** No scanned PDF
  exists in this project's corpus (EDGAR/CUAD are all digital-text —
  known_issue #28 is the opposite problem, EDGAR has no PDF at all). `ocr_cloud.py`'s
  logic was verified directly (`has_text_layer` correctly reads a real digital
  PDF; `ocr_page` correctly returns `None`), not through an actual OCR pass,
  because there is no Surya-on-Colab batch step to test against yet.
  Off the critical path per the plan; unchanged this phase.
- **A malformed-PDF crash was found and fixed during verification, not designed
  for up front.** `pdfplumber.open()` on a non-PDF raised a raw
  `PdfminerException` that would have taken the whole Streamlit page down.
  Fixed in `pdf_extractor._open()`; both the direct call and the full
  upload-widget path (`_extract_and_finalize`) were re-verified afterward.
  Worth remembering for Phase 5: any new pdfplumber/pymupdf call site needs the
  same "corrupt input degrades to a message" treatment, it does not come free.
- **`data/uploads/<run_id>/` has no cleanup**, same residual as Storage's orphan
  gap (known_issue #21) — content accumulates locally across test runs.

### How to verify this phase works
```bash
streamlit run app/main.py   # then, on the Revenue Integrity page:
```
- Upload a real EDGAR or CUAD contract PDF (e.g. from `data/corpus/contracts/` or
  fetched via `data_sourcing.fetch_contracts.fetch_cuad`) → `documents` row lands
  `extraction_status='complete'` immediately, with readable text in "Preview
  extracted text".
- Upload a real `actuals.csv` (e.g. `data/scenarios/easy/actuals.csv`) → stays
  `pending`, shows a column-mapping confirmation UI pre-filled from the real
  headers → confirming writes `actual_transactions` (verified: 47/47 rows for
  the `easy` scenario) and flips the document to `complete`.
- Upload a non-PDF renamed to `.pdf` → `extraction_status='failed'` with
  "file is not a readable PDF", page renders normally, no stack trace.

All four verified directly against a running `streamlit run app/main.py`
instance via browser automation, not just unit-style Python calls.

---

## Phase 5 — LLM Contract Rule Extraction (The Brain)
**Code complete:** 2026-08-13 · **Owners:** A / B · **Definition of done: NOT yet measured** — see "Known gaps"

### Built by B — serving first (ADR-012)
- `training/serve_model.py` — **one file that runs on both Colab and Kaggle.** Detects the
  host (`google.colab` import vs `KAGGLE_KERNEL_RUN_TYPE`), reads `LLM_API_KEY` from that
  platform's secret store (`google.colab.userdata` / `kaggle_secrets.UserSecretsClient`,
  environment variable overriding both), serves Qwen 2.5 3B Instruct over an
  OpenAI-compatible API, opens a Cloudflare quick tunnel and prints a paste-ready
  `COLAB_TUNNEL_URL=` or `KAGGLE_TUNNEL_URL=` line naming the right variable for the host
  it is on. `--self-test` makes one real chat completion *through the tunnel* and confirms
  a **wrong** bearer token is rejected, before the URL is pasted anywhere. `--lora NAME=PATH`
  is the entirety of Phase 10's serving change. Two backends: vLLM (default) and a
  hand-written transformers + FastAPI server (ADR-015).
- `docs/serving_setup.md` — the click-path: accounts, phone verification for Kaggle GPU,
  where each host keeps secrets, the single bootstrap cell that is *identical* on both,
  what the banner looks like, and a symptom→cause→fix table.
- `core/ai/endpoints.py` — **the swap layer** (ADR-016). `settings` is `lru_cache`d at
  import, which is right for a database URL and wrong for a tunnel URL. This module
  resolves provider/URL/model at *call* time, layering `data/endpoint_override.json` over
  `.env`, so switching Colab↔Kaggle needs no Streamlit restart. Also `probe()`, which
  distinguishes the four failures that actually happen (no URL / unreachable / 401 /
  serving a different model), and `record_answered()` so the UI can say which host really
  answered.
- `core/ai/llm_client.py` — `call()`, `complete()`, `complete_json()`, `health()`,
  `last_error()`. Cache → active endpoint → (optional) the other configured endpoint.
  JSON-mode negotiated downwards per base URL (`json_schema` → `json_object` → none) on a
  400, so vLLM's grammar-constrained decoding is used where available and the fallback
  backend still works. One cold-start retry on a timeout or refused connection. Never
  raises (ADR-004).
- `core/ai/cache.py` — sha256 over model + system + prompt + temperature + max_tokens +
  schema name, sharded two deep, written atomically. **Deliberately not keyed on the
  endpoint**, which is what makes the two hosts interchangeable rather than merely both
  available: a response cached from Colab hits from Kaggle, and keeps working after either
  session dies.
- `core/ai/prompts.py` — `EXTRACTION_SYSTEM` (13 numbered rules, one per line), a JSON
  skeleton, and a worked example whose contract deliberately contains a **dispute**
  escalation clause the model must ignore (known issue #24, taught by example rather than
  by prose). No mention of pages, coordinates or bboxes anywhere (ADR-005).
- `app/pages/8_model_endpoint.py` — pick the live host, paste a fresh URL, test either
  endpoint, see which one last answered, inspect/clear the cache, reset to `.env`.
- `app/main.py` — the model status card now *probes* instead of checking whether a variable
  is non-empty, because "configured" and "answering" are different questions.
- `app/components/client_confirm.py` — Phase 5 half added: warns when two stored clients
  fuzzy-match each other, and `render_group_confirm()` shows the extractor's proposed
  grouping for correction (rename, or split a group that was wrongly merged).
- `core/config.py` — `normalise_base_url()` extracted to module level (endpoints.py
  normalises URLs that never passed through `settings`), plus `LLM_FAILOVER`.

### Built by A
- `core/ai/contract_extractor.py` — `extract_rules(doc) -> ContractRules | None` and
  `extract_rules_verbose(doc) -> ExtractionReport`. Paragraph-packed chunks of ≤12k chars
  (never a fixed stride — a clause sliced in half gets quoted as a fragment that grounds
  against nothing), ranked by fee-language density, chunk 0 always kept because that is
  where the parties and term are declared. Per-chunk extraction, then a merge where
  scalars take the first chunk that stated them and lists de-duplicate.
  **Then it grounds every quote against the document's own text and drops the ones that
  are not there** (ADR-017).
- `core/extraction/clause_locator.py` — `locate_clause()` exact → fuzzy → `None`, plus
  `grounding_rate()`. `import pymupdf`, not `fitz` (known issue #12). Never raises: a
  missing PDF is a `None`, same as an absent quote, because the caller handles both
  identically.
- `core/ai/client_matcher.py` — `normalise()` strips corporate suffixes and *all*
  punctuation and spacing, which is what catches "StarterLabs" against "Starter Labs, Inc.";
  `group_clients()` labels each group with its longest variant.
- `core/ai/schemas.py` — `ExtractedDoc.doc_type` gained `"text"`. EDGAR serves HTML, which
  `data_sourcing` writes as `.txt`; those documents are neither a PDF nor a CSV, and
  calling them `text_pdf` to satisfy a Literal would be a lie in the data.
- `scripts/eval_extraction.py` — the definition of done, measured, written to
  `data/eval/phase5_extraction.json`.
- `scripts/verify_llm_stack.py` — 21 assertions against a stub OpenAI server on localhost:
  failover, cache-survives-host-swap, JSON-mode negotiation, repair retry, 401, never-raises.
  **No GPU needed.** Redirects `cache.CACHE_DIR` and `endpoints.OVERRIDE_PATH` into a
  temporary directory, so running it cannot delete a pre-warmed demo cache. Written in the
  repo rather than as a throwaway, because known issue #15 is the record of what happens
  otherwise.
- **The corpus was rebuilt.** `data/corpus/` was empty again on this machine — `data/**` is
  gitignored and Phase 3 ran on a different OS. Re-ran `python -m data_sourcing.filter_contracts
  --count 260` against live EDGAR: 253 exhibits fetched, **43 distinct contracts**
  (19 ready / 6 filled / 18 review) — the same shape Phase 3 got. This is the second
  recurrence of known issue #33.

### New interfaces added to interfaces.md
- `endpoints.active() / get() / list_endpoints() / set_active() / set_url() / probe() / fallback() / record_answered()`
- `llm_client.call() / complete() / complete_json() / health() / last_error()`
- `cache.key() / get() / put() / stats() / clear()`
- `contract_extractor.extract_rules() / extract_rules_verbose()`
- `clause_locator.locate_clause() / grounding_rate()`
- `client_matcher.group_clients() / similarity() / normalise() / canonical_for()`
- `client_confirm.render_group_confirm()`

### Decisions recorded
- ADR-015: the serving notebook runs vLLM's OpenAI server, with a hand-written fallback
- ADR-016: Colab and Kaggle are peers, swappable at runtime, with opt-out failover
- ADR-017: quotes are grounded twice — against text always, against a PDF when there is one

### Known gaps / deliberately deferred
- **The definition of done is NOT met yet, because no GPU session has ever run.**
  `serve_model.py` has never executed on real Colab or Kaggle hardware: the vLLM install
  path, the T4 dtype choice, the cloudflared parse and the transformers fallback are all
  unexercised on a GPU. Everything *client*-side is verified against a stub
  (`scripts/verify_llm_stack.py`, 21/21). The two numbers Phase 5 is judged on — ≥8/10 valid
  `ContractRules` and ≥80% clause grounding — are unmeasured until
  `python scripts/eval_extraction.py --pdfs 5` runs against a live endpoint.
- Base Qwen 2.5 3B will extract worse than a frontier model would. That is known issue #8
  and it is what Phase 10 exists to close — do not read the first eval as a failure.
- `complete()` returns `str | None`, not the `str` interfaces.md declared. The project's own
  convention (a function that can legitimately fail returns `None`) beats the stale signature.
- Extraction is not wired into the Streamlit upload flow. Uploading a contract still stops
  at extracted text; nothing writes `contract_rules` rows yet. The extractor is reachable
  from `scripts/eval_extraction.py` only. Phase 6 owns persistence, because a timeline is
  the first thing that needs those rows.
- `render_group_confirm()` has no caller for the same reason.
- The prompt has had exactly one iteration and no tuning against real model output.
  `prompts.py` is where the next real work is.
- Outlines/xgrammar server-side is *available* through vLLM's `response_format` and is used
  when the server accepts it, but no valid-JSON-rate comparison has been run with it on
  versus off. That row of the Phase 11 eval table is still empty.

### How to verify this phase works
```bash
python scripts/verify_llm_stack.py          # 21/21, no GPU, no network
# then, with a session running and its URL pasted in:
python scripts/eval_extraction.py --pdfs 5  # the two DoD numbers
```
In the browser: **Model endpoint** in the sidebar → paste the Colab URL → *Save* → status
goes green → switch the radio to Kaggle → status follows, with no restart.

---

## Phase 5 closed — measured on a live Colab T4 (2026-08-14)
**Owners:** A / B · **Definition of done: MET.** This entry supersedes the "not yet
measured" gap above. Nothing in the code changed; the numbers simply exist now.

### What ran
A Colab T4 served **base Qwen 2.5 3B Instruct** under **vLLM 0.27.1** behind a Cloudflare
quick tunnel, and `scripts/eval_extraction.py --limit 10 --pdfs 5` ran against it from the
Linux checkout. First time `serve_model.py` has ever executed on a GPU (known issue #40).

### The three numbers

| Measure | Result | Target | |
|---|---|---|---|
| valid `ContractRules` | **10/10** | ≥ 8/10 | PASS |
| text grounding | **80.0%** — 12 grounded, 3 dropped, of 15 quotes | ≥ 80% | PASS |
| PDF page/bbox grounding | **2/2 located** — 1 exact, 1 fuzzy | — | PASS |

Written to `data/eval/phase5_extraction.json`. ~25–45s per contract uncached.

### Read these before quoting those numbers
- **Grounding passed exactly on the line.** 80.0%, not "above 80%". One more paraphrase
  reads 73% and the phase fails. A 2-contract smoke run 40 minutes earlier read 66.7% —
  the sample is small enough to swing that hard. Known issue #48.
- **10/10 valid is softer than it reads.** Three contracts (Mammoth Energy, Regal
  Entertainment, Vantiv) extracted **zero** clauses, and an empty `ContractRules` is
  structurally valid, so it scores as a pass while proving nothing. The yield is lopsided:
  **AMERI Holdings EX-99.1 alone produced 7 of the 12 grounded quotes.** Known issue #49.
- **PDF grounding is a demonstration, not a rate.** 5 CUAD PDFs yielded 2 locatable quotes
  between them; 3 extracted nothing. "100%" of n=2 is not a capability claim. It does prove
  `locate_clause` returns real coordinates from a real PDF, exact and fuzzy paths both.
- The 3 dropped quotes were **paraphrases** — the model was told "character for character"
  and did not comply. `_ground()` caught all three, which is ADR-017 working as designed.

### What running it on real hardware found (known issue #50)
Two bugs that no stub could have surfaced. Both are documented in `README.md` →
*Starting a session*; **neither is fixed in code.**
- `google.colab.userdata.get()` reads secrets from the notebook **kernel**, so
  `serve_model.py` cannot see `LLM_API_KEY` when launched as `!python …` — it dies with
  `'NoneType' object has no attribute 'kernel'`. Read the secret in a cell and set
  `os.environ` instead, which `serve_model.py` already prefers. **Kaggle is unaffected** —
  `kaggle_secrets` works from a subprocess, so this is a Colab-only trap.
- `pip install vllm` is unpinned and pulled a torch built for **CUDA 13.0**, leaving Colab's
  preinstalled **torchaudio (CUDA 12.8)** stale. `transformers` imports `torchaudio`
  unconditionally, so the server never started. `pip uninstall torchaudio` after installing
  vLLM; we serve text and never need it. Consider pinning `vllm` before deployment.

Also observed, not fixed (known issue #51): when the vLLM child dies at import time,
`wait_until_ready()` polls a dead port for the full 900s because it never checks
`Popen.poll()`. Fifteen minutes per failed start, for a one-line fix.

### Still untested on a GPU
- The entire `--backend transformers` fallback (ADR-015). Only vLLM has run.
- **Kaggle.** Only Colab has been stood up. ADR-016 calls them peers; that claim is now
  half-verified.

### Known gaps / deliberately deferred
- `prompts.py` is still unturned — but it is now a *measured* baseline (`PROMPT_VERSION`
  `v1`, 10/10 valid, 80.0% grounding) rather than a guess. Known issue #45 updated, not
  closed. Editing a template invalidates exactly its own cache entries, so re-measuring
  after a prompt change is cheap.
- Extraction is still not wired into the Streamlit upload flow; nothing writes
  `contract_rules` rows. Unchanged, and still Phase 6's job (known issue #41).
- EDGAR's HTML-vs-PDF debt (known issue #28) is untouched. Text grounding runs everywhere;
  page/bbox still needs a PDF, which is why the CUAD pass exists at all.

### How to verify
```bash
python scripts/eval_extraction.py --limit 10 --pdfs 5   # needs a live endpoint
```
Cached responses make a re-run near-instant; add `--no-cache` to force real calls.

---

<!-- ================================================================= -->
<!-- APPEND NEW PHASE ENTRIES ABOVE THIS LINE.                         -->
<!-- ================================================================= -->

---

## Second frontend — FastAPI + Jinja2 alongside Streamlit (2026-08-14)

**Completed:** 2026-08-14 · **Owner:** B · **Not a numbered phase.** This ran in parallel with Phase 6 and changes no engine, extraction or database logic. Recorded here because it adds a whole directory and one ADR.

### Why

A designed mockup was delivered as a single 636-line file (`temp/FinSight Mockups.dc.html`) with every style inline, a `{{ }}` templating dialect and its state machine in a `<script>` tag. Streamlit cannot render it — Streamlit renders widgets, not arbitrary HTML — so the delivered design had no route into the product. Rather than approximate it in `st.markdown`, the design got its own server-rendered frontend, and Streamlit kept the operational pages it is good at.

### Built by B

- `web/main.py` — the FastAPI app: mounts `static/`, includes three routers, `/healthz`, a 500 handler
- `web/viewmodels.py` — the dataclasses every template renders. **This is the demo/live contract**: adding a field means filling it in both presenters, which is deliberate friction
- `web/presenters/demo.py` — the mockup's own `FINDINGS`/`PIPELINE`/`working` arrays, transcribed. The reference render
- `web/presenters/live.py` — the same shapes built from `core.db.queries`, plus `derive_state()` which works out which of the four Integrity screens a run has earned
- `web/format.py` — money, dates, the em dash. One place, so two pages cannot format `480` differently
- `web/chrome.py` — header, state bar, offline banner, for either mode
- `web/settings.py` — `WEB_*` variables and the cookie that overrides them
- `web/deps.py` — per-request mode, a session that yields `None` instead of raising, query-string carry-over
- `web/templating.py` — the Jinja environment and the single `render()` every route ends in
- `web/routers/{integrity,decision,system}.py` — one per page, plus the mode toggle and a read-only endpoint page
- `web/templates/` — `base.html`, `macros.html`, three partials, one file per Integrity state, `decision/index.html`
- `web/static/css/tokens.css` — the design system's own file, copied **verbatim** from `temp/_ds/modernist-*/`
- `web/static/css/app.css` — the mockup's inline styles transcribed into named classes. A transcription, not a redesign
- `web/static/js/app.js` — ~40 lines: clickable table rows and scroll-into-view. Everything else is server-rendered
- `run_web.py` — `python run_web.py [--live] [--reload] [--fixed]`

### Added to `core/db/queries.py` (additive; no existing function changed)

- `TransactionRow`, `ClientTotals` row shapes
- `list_transaction_rows(session, run_id, client_id, start, end) -> list[TransactionRow]` — UI-safe transactions, unlike `list_transactions` which hands the agent live ORM objects
- `get_client_totals(session, run_id, client_id) -> ClientTotals | None`
- `revenue_by_month(session, run_id) -> dict[str, float]`

### Decisions recorded

- ADR-018: two frontends over one database; the demo/live toggle never falls back

### Known gaps / deliberately deferred

- **Nothing in `web/` writes.** Every button is inert: upload, "Add to recoverable", "Rule it out", "Confirm and reconcile", the CSV mapping accept. They render exactly as designed and do nothing, because the actions behind them are Phases 6–9. They are `disabled` with a `title`, not greyed out — a wall of half-opacity controls would misrepresent the design.
- **The Decision Engine has no live answer and will not get one here.** `core/ai/decision_analyzer.py` is a Phase 9 stub, and no table holds expenses, so no surplus can be computed. Live mode shows the revenue and findings lines it *can* compute and dashes the rest. Demo mode shows the mockup's worked example.
- **The agent panel is empty in live mode.** Seeded anomalies carry `status='unverified'`, no `agent_reasoning` and no `agent_tool_calls`, so the panel draws skeletons and names Phase 8. `_tool_calls()` already reads the JSON defensively for when Phase 8 writes it.
- **No PDF page is rendered in the clause viewer**, same as Streamlit — `pdf_renderer.py` is a Phase 7 stub (known issue #19). The grey bars around the quote are the mockup's own placeholder, not a stand-in for a missing render.
- **Processing state is thin in live mode.** The column-mapping and client-confirmation panels only ever have content mid-import, which no stored run is; both show a stated reason rather than invented rows.
- **`app/` and `web/` are not kept in visual sync** and are not meant to be. They are two views of one database with different jobs.
- **The 1440px art board is not reproduced.** The delivered file centred a fixed 1440px canvas on a grey ground; that framing is an artefact of how the mockup was drawn, and reproducing it left grey gutters around a running app. The shell fills the window and is `min-height:100vh`. `WEB_FLUID_WIDTH=false` (or `run_web.py --fixed`) restores the exact art board for diffing against the original file.
- The mockup's own copy is carried verbatim where it is content ("Reading nine documents" heads a list of six, because the mockup does).

### How to verify this works

```bash
python run_web.py
# demo: the five state-bar buttons render the five delivered screens
open 'http://127.0.0.1:8000/?state=empty'
open 'http://127.0.0.1:8000/?state=processing'
open 'http://127.0.0.1:8000/?state=review'
open 'http://127.0.0.1:8000/?state=clean'
open 'http://127.0.0.1:8000/?state=offline'
# live: the same screens against Supabase, gaps shown as gaps
open 'http://127.0.0.1:8000/?mode=live'
open 'http://127.0.0.1:8000/decision?mode=live'
# and the original frontend, unchanged
streamlit run app/main.py
```

Verified on 2026-08-14 against the live Supabase run `demo_v1 · #4`: all five demo states and both live pages return 200, live mode reads **26,908.00 across 7 findings, 3 of 5 clients, 6 of 7 clauses located**, and `streamlit run app/main.py` still serves HTTP 200 with no exceptions.

---

## web/ UX pass — master-detail, and the query count that was the real bug (2026-08-15)

**Completed:** 2026-08-15 · **Owner:** B · **Not a numbered phase.** Follows the 2026-08-14 FastAPI entry; no engine, extraction or schema change.

### The problem

The findings screen rendered the selected finding's detail *below* the entire list. Correct at the mockup's five findings, unusable at a hundred: you click a row and scroll past everything to see what you clicked.

Chasing that turned up a second, larger problem that had nothing to do with layout.

### Measured before touching anything

| | |
|---|---|
| Page render with no database (demo mode) | **4 ms** |
| `SELECT 1` round trip to Supabase `ap-southeast-1` | **409 ms median** (min 101, max 511); a fresh connection **1127 ms** |
| Live page | **35 queries, 8.7 s** |

So a live page's response time was its query count times 400 ms and nothing else. `get_summary_stats` alone was 8 round trips and was being called **three times per render** — once by `derive_state`, once by `_cards`, once by `state_note`.

### Built by B

- `web/templates/integrity/_findings_list.html`, `_finding_detail.html` — the review screen split in two, so the detail can be re-rendered without the list
- `web/presenters/grouping.py` — sorting and grouping shared by both presenters, so demo and live cannot order the list differently
- `web/cache.py` — a TTL read cache, `WEB_CACHE_SECONDS` (default 15), `?fresh=1` to bypass
- `GET /finding/{id}` in `web/routers/integrity.py` — the detail pane as an HTML fragment
- `web/static/js/app.js` — rewritten: prefetch on hover/focus, swap on click, `pushState`, `popstate`, client-side filter, `↑`/`↓`/`j`/`k`/`/`/`Esc`

### Changed in core/db/queries.py (additive to behaviour, not to results — all figures verified identical)

- `get_summary_stats` — 8 round trips to **3**, via `SUM(CASE WHEN …)` conditional counts and scalar subqueries. Written the long way rather than with `count(…) FILTER`, which is Postgres-only; ADR-003 requires SQLite parity and it was re-verified on both.
- `get_client_totals` — 4 round trips to **1**
- `AnomalyRow.agent_tool_calls` — carried on the row, removing a per-drill-down `session.get`

### Measured after

| | |
|---|---|
| Live page | **9 queries, ~5 s** cold |
| Live page, warm cache | **0 queries, ~3 ms** |
| Detail fragment | 4 queries cold, 0 warm — and prefetched on hover, so a click is usually already resolved |
| Findings list at 500 rows | 16 ms server render, 422 KB, verified in a browser |

### UX rules applied (via the ui-ux-pro-max skill's guidelines)

Skip link; a real `h1` per page; rows as real `<a href>` with `role="option"` inside a `role="listbox"`; `aria-live` on the swapping pane; visible focus rings, inset where a pane clips them; `btn-small` raised to a 44px touch target; every state change given a 150ms transition instead of 0ms; one global `prefers-reduced-motion` rule; breakpoints at 1400 / 1180 / 900 / 640 where the panes stop being readable rather than where they stop fitting; `content-visibility: auto` on rows instead of a virtualisation library.

**The recommended design system was deliberately not adopted.** The skill proposed a dark ops-dashboard palette with Fira; the Modernist system is delivered and fixed, so only the UX and performance guidance was taken. No new colour was introduced — the four leak types are distinguished by grouped headings and labels, not by four new hues the token file does not have.

### Known gaps / deliberately deferred

- **The cold live page is still ~5 s and cannot be made faster from this repo.** The floor is the Supabase region: 9 queries at ~400 ms. Moving the instance nearer, or a connection pooler closer to the app, is the only remaining lever. The read cache hides it after the first hit.
- **The read cache is only safe while `web/` writes nothing** (known issue #52). The first write path added must call `web.cache.clear()` or narrow the TTL — this is written on the module.
- Past roughly a thousand findings the HTML payload argues for paging; nothing paginates today.
- Sorting is server-side, so it costs a round trip on a cold cache. Filtering is client-side and free.
- The demo presenter parses its own formatted strings back into floats to build group subtotals, because the mockup's figures were transcribed as strings. Live mode sums the floats it already has.

### How to verify

```bash
python run_web.py
# hover a row: the detail is already fetched before you click
# type in the filter, press / to focus it, arrow through the list
open 'http://127.0.0.1:8000/?state=review'
open 'http://127.0.0.1:8000/?mode=live'
open 'http://127.0.0.1:8000/?mode=live&fresh=1'   # bypass the read cache
streamlit run app/main.py                          # still unaffected
```

---

## Phase 6 — Expected Timeline & Reconciliation
**Completed:** 2026-08-16 · **Owners:** A / B

Zero AI in this phase, as designed. Nothing here calls a model, reads the clock
or opens a socket. The findings in the database stopped being seeded and started
being computed, and **no template in either frontend changed to make that
happen** — which is ADR-008 paying off exactly as it was supposed to.

### Built by A
- `core/engine/timeline_generator.py` — `ContractRules` → the expected billing timeline. Pure. `add_months` clamps to short months and never compounds the clamp (Jan 31 → Feb 28 → **Mar 31**); escalation compounds per anniversary by default; the order is escalation-then-discount with a **round to cents at each stage**, which is what reproduces ground truth exactly.
- `tests/test_timeline.py` — 34 assertions, every expected amount hand-computed before the code ran, including the pitch's own worked example ($6,000 / 10% for 3 months / 8% anniversary / $15,000 milestone).

### Built by B
- `core/engine/reconciliation.py` — client-month aggregation (ADR-006), plus the attribution step the plan never named: a bank line says `REGAL ENT GROUP ACH INV-202502` and the client is *Regal Entertainment Group*. Scores by `client_matcher.similarity` **or** a token-prefix abbreviation rule, and **refuses** below 85 or within 6 points of a runner-up.
- `core/engine/anomaly_classifier.py` — the four types as testable hypotheses, each returning the clause role that proves it and a plain-English reason built from computed figures.
- `core/engine/pipeline.py` — **not in the plan's tree.** The only place engine output becomes rows: `persist_rules()` (a Phase 5 extraction → `contract_rules` + clauses + escalations/discounts/milestones) and `compute_run()` (→ `expected_timeline` + `anomalies`). Idempotent.
- `app/components/reconcile_panel.py` + section 3 of `app/pages/1_integrity_engine.py` — the **first action in this app that computes rather than reads**.
- `core/db/queries.count_contract_rules`, `tests/test_reconciliation.py` (27), `tests/test_pipeline.py` (13, on throwaway SQLite), `scripts/eval_engine.py`, `scripts/run_scenario.py`.

### New interfaces added to interfaces.md
- `timeline_generator.generate_timeline(...)`, `rate_for`, `add_months`, `months_between`, `unresolved_milestones`, `ClauseRefMap`
- `reconciliation.reconcile/reconcile_detail/attribute_transactions/clean_description/name_score`, `ClientRef`, `Attribution`, `MonthBucket`, `ReconciliationResult`
- `anomaly_classifier.classify/classify_gap`, `Classification`
- `pipeline.compute_run/persist_rules/load_contract_plans`, `RunSummary`, `ContractPlan`
- `queries.count_contract_rules`, `reconcile_panel.render_reconcile_panel/render_extract_panel`
- Additive schema changes: `TimelineEntry.id`, `TransactionRow.id`, `TransactionRow.client_id`, and `Anomaly.expected_timeline_id` relaxed to `int | None` to match the DB column it always had.

### Decisions recorded
- ADR-019: a payment answers the billing it followed
- ADR-020: attribution refuses rather than guesses
- (No ADR needed for compounding escalation — see "known gaps", it is a documented default with a flag.)

### Measured — the definition of done

```
easy       7/7 findings   $17,815.00 / $17,815.00   0 unattributed
realistic  5/5 findings   $22,500.00 / $22,500.00   3 unattributed (the 3 planted noise rows)
edge       0/0 findings   $0.00 / $0.00
74 pytest assertions pass in 0.79s
```

Every expected amount, every anomaly type and every gap matches `ground_truth.json`
to the cent, and `edge` — the clean-client scenario — produces **zero** findings.
The same three scenarios then loaded into live Supabase (`runs` 12, 13, 14) and
`compute_run` reproduced the same totals through the database.

### Known gaps / deliberately deferred
- **`escalation.after_months` is treated as recurring, not one-off.** A clause saying *"increase 8% on each anniversary"* compounds: 6,000 → 6,480 → 6,998.40. `data_sourcing/scenario_builder.py` applies its escalation **once**, so the two agree only because no scenario window contains a second anniversary. A three-year scenario would diverge, and the engine is the correct side. `compound_escalation=False` is there for a genuine one-off rise.
- **Milestones are never billed automatically.** `ContractRules.Milestone` carries a condition ("on website launch"), not a date, and nothing resolves one into the other — `RunSummary.unresolved_milestones` names them instead. Resolving a condition to a date is a judgement, and guessing it would manufacture ghost invoices out of thin air. The $15,000 launch milestone in the pitch therefore needs `milestones.due_date` set by hand (or by Phase 8's agent) before it is checked.
- **Upload → extraction → `contract_rules` is code-complete but has never run against a live GPU.** `render_extract_panel` calls Phase 5's `extract_rules` and `persist_rules`; both halves are tested separately (Phase 5 on a Colab T4, `persist_rules` in `tests/test_pipeline.py`), but the joined path has only been exercised with no endpoint running, where it fails cleanly. This is the honest remainder of known issue #41.
- **`web/` still writes nothing** (known issue #52). Reconciliation runs from Streamlit only. The FastAPI app shows every computed figure and its buttons stay inert on purpose — ADR-018.
- **No clause has a page or a box.** Scenario contracts are EDGAR HTML saved as `.txt` (known issue #28), so `locate_method` is NULL and the viewer degrades to the quote. Phase 7 owns the rendering; the missing PDFs are still uncosted.
- **`scripts/seed_demo.py` was left alone.** The plan says to swap its anomaly rows for computed ones; `scripts/run_scenario.py` does that as a separate script instead, so the seeded run stays available as a fixed reference that no engine change can move. `seed_demo.scenario_dir` still raises `NotImplementedError` (known issue #35 is otherwise closed).
- **Phase 1's 47 schema assertions are still not in pytest** (known issue #15). Phase 6 was said to own porting them; it added 74 engine and pipeline assertions instead and did not do that port. Still open.

### How to verify this phase works

```bash
python -m data_sourcing.scenario_builder     # data/ is gitignored; rebuild first
python scripts/eval_engine.py                # the definition of done, three scenarios
pytest -q                                    # 74 assertions, no DB, no network
python scripts/run_scenario.py realistic     # load + compute a real run in Supabase
streamlit run app/main.py                    # section "3 · Reconcile" -> Reconcile now
python run_web.py                            # the same computed run, live mode
```

---

## Phase 7 — Clause Viewer (Real Highlighting)
**Completed:** 2026-08-16 · **Owners:** A / B

Click a finding, see the contract page with the clause boxed on it. The phase
also settled the largest piece of debt on the board — known issue #28, *EDGAR
serves HTML, not PDF, so there is nothing to highlight* — by typesetting a PDF
from the filing's own text (ADR-021) rather than leaving the headline feature
unavailable on the project's primary corpus.

### Built by A
- `core/extraction/clause_locator.py` — hardened. The box is now the **union** of
  every line a match spans (Phase 5 kept `hits[0]`, boxing eleven words of a
  four-line clause); the longest probe wins, shortening only on failure;
  typography is folded before comparing (ligatures, curly quotes, en/em dashes,
  non-breaking spaces, hyphenation across a line break); quotes wrapped in `...`
  are trimmed; the fuzzy tier matches **page-wide** through a word-indexed page
  and maps the winning window back to word rectangles.
- `tests/test_clause_locator.py` — 16 assertions, PDFs built in memory, no
  corpus and no committed binary. Three are regressions for wrong boxes this
  phase actually produced.

### Built by B
- `core/extraction/pdf_renderer.py` — `render_highlighted` (PNG bytes, amber box,
  `None` on every failure path), `typeset_pdf` (deterministic layout of a
  text-only filing, ADR-021), `ensure_pdf` (real PDF or typeset one, cached by
  content hash under `data/cache/pdf/`), `render_document_page` (the single entry
  point both frontends call, returning the image **and** whether it was typeset).
- `core/engine/pipeline.locate_run_clauses` — one pass per document, writing
  `source_page` / `source_bbox` / `locate_method` back for every clause in a run.
- `app/components/clause_viewer.py` — the real viewer, all three ADR-005 states
  plus a fourth the plan does not name: no page to render at all.
- `web/`: `GET /clause/{id}/page.png`, `FindingDetail.page_image_url` +
  `page_is_typeset` filled in **both** presenters, the image swapped into
  `_finding_detail.html` in place of the mockup's stylised page, and the CSS.
- `tests/test_pdf_renderer.py` — 17 assertions.

### New interfaces added to interfaces.md
- `pdf_renderer.render_highlighted/typeset_pdf/ensure_pdf/render_document_page/page_count`
- `clause_locator.locate_all/normalise_for_match`
- `pipeline.locate_run_clauses`, `LocateSummary`
- `web` route `GET /clause/{clause_id}/page.png`; `FindingDetail.page_image_url`, `.page_is_typeset`

### Decisions recorded
- ADR-021: a text-only filing is typeset into a PDF we generate, and labelled as such

### Measured
```
20 of 20 clauses across runs 12/13/14 placed on a page — 18 exact, 2 fuzzy, 0 not found
107 pytest assertions pass in 2.8s (34 timeline, 27 reconciliation, 13 pipeline,
                                    16 clause locator, 17 pdf renderer)
all three scenarios still reproduce ground_truth.json exactly
clause page route: 4.9s cold, 1.2ms warm; 404 in demo mode and on an unknown id
```
Every box was checked against the text it actually sits on, not merely for being
non-null.

### Two wrong highlights this phase produced, and what stops them now
Both were caught by *looking at the rendered page*, not by a test — worth
remembering, because both passed every assertion that existed at the time.

1. **A box around the digit `5` on a table of contents.** `fuzz.partial_ratio`
   normalises by its *shorter* argument, so a block containing only "5" scores
   **100** against any quote containing a 5. Now: a length floor, a shared-
   vocabulary floor, and `_window_ratio` — the quote against a same-length slice.
2. **A box on an unrelated paragraph about 3D advertising.** The clause was
   quoted as `"...a monthly payment in addition to..."` and the document contains
   no such dots, so the exact search failed and a loose fuzzy match won. Trimming
   the ellipsis makes the same clause an **exact** hit.

### Known gaps / deliberately deferred
- **A typeset page is not the filing as filed.** It is a faithful layout of the
  text `data_sourcing` extracted from EDGAR's HTML, so line breaks, tables and
  page numbers are ours, not the original's. Both frontends say so on every such
  page; the report must too. A real PDF corpus (CUAD) renders as itself.
- **The union box can be wider than the quote.** It spans from the first line to
  the last, so on a multi-line clause it includes whatever else shares those
  lines. That is ordinary PDF highlighting behaviour and it is honest, but it is
  not a word-perfect outline.
- **The clause image is 4.9 s cold** — `documents.extracted_text` is a couple of
  hundred kilobytes across a 400 ms link (known issue #53). Cached to 1.2 ms.
  A page-level column or a nearer region would fix it; neither is code.
- **Nothing re-locates automatically.** `locate_run_clauses` runs from
  `scripts/run_scenario.py` and the Reconcile button. Editing a clause quote by
  hand leaves stale coordinates until it is run again.
- **`ocr_cloud.py` is still a stub** and the scanned-document path is still
  untried on a real scan (stretch goal, Phase 11).

### How to verify this phase works
```bash
pytest tests/test_clause_locator.py tests/test_pdf_renderer.py -q   # 33 assertions
python scripts/run_scenario.py easy        # prints "8/8 clauses placed on a page"
python run_web.py                          # /?mode=live -> click a finding -> the page, boxed
streamlit run app/main.py                  # 5 - Evidence -> the same page, boxed
```


## Phase 8 — Verification Agent

**Completed:** 2026-08-17 · **Owners:** A / B

A LangGraph ReAct loop re-checks every flagged anomaly — reads the proving
clause, searches for a misattributed bank transaction, checks whether a
missing amount is actually several partial transactions — and writes a
verdict (`confirmed` / `false_positive` / `needs_review`) plus a readable
trace back to the row. Both frontends already reserved the space for this
(Phase 2's status badges, `web/`'s `NOTICE_AGENT`); this phase is the write
path that fills it, not new UI surface.

**Before writing any code, the phase prompt's own worked example was traced
against the current codebase and found to no longer hold** — see "Known gaps"
below. The rest of the phase was built to the full architecture regardless,
and proven a different way.

### Built by A
- `core/agents/tools.py` — the four DB-reading tools (`search_invoices`,
  `read_contract_clause`, `search_bank_transactions`, `check_split_payments`).
  No LLM, no writes, each independently callable. `check_split_payments`
  brute-forces `itertools.combinations` (size 1–3) over one client's
  transactions in a window — cheap and exhaustive because it only ever runs
  on the handful of transactions behind one already-flagged anomaly (ADR-006).
- `tests/test_agent_tools.py` — 13 assertions, temp SQLite, no agent and no
  model: window/amount filtering, a real 2-transaction split found, tolerance
  respected, nothing found when nothing sums.

### Built by B
- `core/agents/verification_agent.py` — `AgentDecision` (the model's
  structured per-turn output), `AnomalyContext`, `VerificationResult`,
  `build_context`, `verify_anomaly` (a small `langgraph.graph.StateGraph`
  built per call, closing over the session and context rather than
  threading them through a serialisable state), `verify_run` (the only place
  this phase writes to `anomalies`, mirroring how `pipeline.py` is the only
  place engine output becomes rows). The hard cap (5) is enforced by the
  **reason** node itself refusing to call the model once `iteration >= 5`,
  not by a prompt asking it to stop.
- `core/ai/prompts.py` — `AGENT_SYSTEM` / `AGENT_VERSION` / `agent_user`,
  same one-instruction-per-line, worked-example style as `EXTRACTION_SYSTEM`
  (known issues #45/#48/#49 apply to a 3B model here too). The model never
  supplies an id — only the optional search-widening knobs
  (`widen_days`, `amount_slack_pct`, `tolerance_pct`); every identifier a
  tool call needs comes from `AnomalyContext`.
- `app/components/verify_panel.py` — the "Verify findings" button, same
  shape as `reconcile_panel`: endpoint caption, spinner, an honest summary
  that reports a skip as a skip rather than hiding it.
- `app/components/anomaly_table.py` — `render_visibility_toggle` ("show false
  positives", off by default, only rendered once one exists); a tool-trace
  expander next to the existing (Phase 2) `agent_reasoning` expander.
  `STATUS_LABELS` needed no change — Phase 2 already had the four badges.
- `app/pages/1_integrity_engine.py` — new "4 · Verify findings" step between
  Reconcile and Findings; Findings/Evidence renumbered to 5/6; the visibility
  toggle wired into the displayed list.
- `tests/test_verification_agent.py` — 5 assertions, temp SQLite,
  `llm_client.complete_json` monkeypatched to canned `AgentDecision`
  sequences (no network, no model — the Phase-5-style "prove the client-side
  logic without a GPU" half): confirmed path with a real tool trace,
  false-positive path when a split payment covers the gap, the hard cap
  forcing `needs_review` with the mock asserted called exactly 5 times (no
  6th call), an unreachable model leaving the row **completely untouched**
  (`status` still `"unverified"`, `verified_at` still `None`), and the
  written `agent_tool_calls` JSON round-tripped through
  `web.presenters.live._tool_calls` into real `ToolCall`s — a cross-check
  against the other frontend's parser, not an assumption about its shape.
- `scripts/eval_agent.py` — the live-endpoint half (Phase-5-style
  `eval_extraction.py` counterpart). Two parts: `verify_run` over the real
  `realistic` run in the database, and a synthetic false-positive fixture
  built with the real engine (`pipeline.persist_rules` / `compute_run`, no
  scenario file) — see "Known gaps" for why the fixture exists at all and
  what it actually proves.

### `web/` — no code changed
`presenters/live.py` and `_finding_detail.html` already read `agent_reasoning`
/ `agent_tool_calls` and drop `NOTICE_AGENT` the moment those fields are
non-empty. Confirmed by loading the demo run through the Streamlit app after
a (failed, no endpoint) verify attempt and by `test_verification_agent.py`'s
round-trip through `_tool_calls` directly — the reserved space needed nothing
from this phase. The two verdict buttons in `_finding_detail.html` ("Add to
recoverable" / "Rule it out") remain inert; this phase did not wire a second
write path into `web/` (ADR-018 — the agent runs from `app/`, same as
reconciliation in Phase 6).

### New interfaces added to interfaces.md
- `core.agents.tools.{search_invoices,read_contract_clause,search_bank_transactions,check_split_payments}`
- `core.agents.verification_agent.{AgentDecision,AnomalyContext,VerificationResult,VerifyRunSummary,build_context,verify_anomaly,verify_run}`
  — `verify_run` and `VerifyRunSummary` are **not** in `interfaces.md`'s
  original Phase 8 section, the same kind of addition `pipeline.py` was in
  Phase 6: the bridge from a pure per-anomaly function to real database rows.
- `core.ai.prompts.{AGENT_SYSTEM,AGENT_VERSION,agent_user}`
- `app.components.verify_panel.render_verify_panel`
- `app.components.anomaly_table.render_visibility_toggle`

### Decisions recorded
- ADR-022: the false-positive proof lives in a synthetic fixture, not the shipped scenario

### Measured
```
125 pytest assertions pass (107 existing + 18 new: 13 tool, 5 agent-graph), all offline
demo_v1 run loaded live in Streamlit: "Verify findings" clicked with no endpoint
  configured -> graceful failure banner, all 7 anomalies still "unverified"
  afterwards (nothing lost) -- verified by browser, not assumed from the code
```
**`scripts/eval_agent.py` has NOT been run against a live GPU in this session**
— no Colab/Kaggle tunnel was available (same situation known issue #40 first
recorded in Phase 5). The graph's control-flow correctness is proven by
`test_verification_agent.py` regardless of model quality; whether the *real*
3B model reasons well enough to actually flip the synthetic fixture to
`false_positive` is unmeasured. Re-run `python scripts/eval_agent.py` against
a live endpoint before citing agent quality in the final report.

### Known gaps / deliberately deferred
- **The plan's own demo moment no longer reproduces.** Phase 8's worked
  example (`docs/implementation_plan.md`) is the agent flipping a
  name-variant false positive ("StarterLabs" vs "Starter Labs") to
  `false_positive`. Tracing the actual `realistic` scenario against today's
  code shows `core.engine.reconciliation.attribute_transactions` already does
  fuzzy client-name attribution at reconcile time — a Phase 6 addition that
  postdates the Phase 8 narrative in the plan. Every name variant in the
  shipped scenario is already correctly attributed before the agent ever
  runs; there is no false positive left in that data for it to find. This
  was found by reading the code and the scenario's `ground_truth.json`
  before writing any Phase 8 code, not discovered by a failing demo.
- **`check_split_payments` does not close known issue #57 as optimistically
  worded.** The known issue says the tool is "where that gets caught" for a
  client paying two months in one transfer. It cannot: the tool finds
  combinations of *several* transactions that *sum to* one target; a single
  transfer that is a *multiple* of one billing's amount is a different shape
  entirely (nothing to combine — one transaction, no combination sums to a
  fraction of itself within tolerance). Closing #57 for real needs a tool
  that compares a client's actual total against *several* neighbouring
  months at once, which does not exist. `#57` is amended below rather than
  silently left to look solved.
- **The eval fixture proves a different, real gap instead**: an attribution
  miss caused by a description too garbled for fuzzy matching to claim
  (`search_bank_transactions` is deliberately not client-scoped, for exactly
  this). This is faithful to the *spirit* of the plan's original demo — the
  engine's mechanical view misses a payment a human would recognise — without
  overstating what today's tools can actually find.
- **The confidence-adjustment policy is a stated heuristic, not a tuned
  one.** `confirmed -> max(original, 0.9)`, `false_positive -> min(original,
  0.1)`, `needs_review` unchanged. Disclosed in
  `verification_agent._confidence_for`'s docstring rather than hidden in
  arithmetic; nothing calibrates these two numbers against outcomes.
- **`web/` still writes nothing** (ADR-018 unchanged). The agent runs from
  `app/`'s "4 · Verify findings" only.
- **Sequential, `sleep_seconds`-paced calls only** — no batching, no async.
  Fine at the scale ADR-006 already commits to (already-flagged anomalies
  only, a handful per run), matches the API-budget note in `CLAUDE.md`.

### How to verify this phase works
```bash
pytest tests/test_agent_tools.py tests/test_verification_agent.py -q   # 18 assertions, no GPU
pytest -q                                                              # 125 total
python scripts/eval_agent.py                                          # needs a live endpoint
streamlit run app/main.py    # Revenue Integrity -> 4 - Verify findings
python run_web.py --live     # same run's findings -> agent panel, no code changed to show it
```


## Audit — Phases 0–8 re-verified, and three things they had not recorded
**Completed:** 2026-08-17 · **Owners:** A / B

Not a phase. Everything claimed by Phases 0–8 was re-run from a clean checkout
on Windows before Phase 9 was started, and three real defects were found — one
of them a **working feature that appeared in no memory file at all**, which is
exactly the failure the memory ritual exists to prevent.

### What was re-measured, and held
```
pytest -q                     125 passed (~19s)
scripts/eval_engine.py        easy 7/$17,815.00 · realistic 5/$22,500.00 · edge 0/$0.00 — all exact
scripts/verify_llm_stack.py   21/21 client-side assertions, stub server, no GPU
scripts/run_scenario.py ×3    same three figures against a real database; 20/20 clauses placed
GET /clause/{id}/page.png     20/20 render as real PNGs (18 exact, 2 fuzzy) — the Phase 7 claim,
                              re-checked through the HTTP route rather than the locator alone
every web/ route, both modes  all 200; 19/19 finding detail panes; 4/4 dashboards
all 5 Streamlit pages         render via AppTest with zero uncaught exceptions
document_router.extract       real PDFs 9.6k–10.7k chars over 5 pages; CSV column sniffing
                              correct on all four scenario actuals.csv files
```
Database invariants were asserted directly rather than trusted: **no anomaly
without a `clause_reference`**, `gap == expected − actual` to the cent on every
finding in all four runs, only the four leak types, all four demonstrated
somewhere, and per-run totals tying to $26,908 / $22,500 / $17,815.

### Fixed by B — the live `LLM_API_KEY` was committed to a public repository
**The most serious thing this audit found, and it was found by accident** while
checking whether `README.md`'s Modal section agreed with the new ADR. The live
shared secret was printed verbatim in three places across two tracked files —
`README.md` twice (the "Starting a session" note and the `modal secret create`
command) and `docs/serving_setup.md` once — and has been in git history since
Phase 5 (commits `5523704`, `3c2bc15`). `github.com/maybethemuhammadibrahim/Fin`
is **public**: confirmed against the GitHub API, `"visibility": "public"`.

This breaks hard rule #8 in `CLAUDE.md` ("No secrets in git"), and it is not a
harmless one. That key is the *only* control on a public Cloudflare tunnel — the
threat `docs/serving_setup.md` describes in its own words two lines above where
it then printed the key ("The tunnel URL is public — anyone who finds it could
use your GPU quota"). With ADR-023's Modal host it is stronger than that: Modal
bills per second of GPU time, so the exposure stops being quota and becomes
money.

All three occurrences are replaced with a pointer to the reader's own `.env`,
plus a note in both files saying the key *used* to be printed there, so nobody
re-adds it. **Redaction is not the fix — rotation is**, and only the key's owner
can do it: the old value is in public history and cannot be un-published.
`git filter-repo` on published history was deliberately **not** run here (it
rewrites every commit and requires a force-push) and is pointless before
rotation anyway. Recorded as known issue #66.

### Fixed by B — Modal was undocumented (ADR-023)
`training/serve_modal.py`, a `modal` provider in `core/ai/endpoints.py`,
`MODAL_BASE_URL`, `USE_MODAL` and a Modal-first `fallback()` order all existed
and worked, with 22 mentions in `README.md` and **zero** in `progress.md`,
`interfaces.md`, `state.json`, `todo.md` or `CLAUDE.md`. A third peer endpoint
amends ADR-016 ("Colab and Kaggle are peers"), so it needed an ADR and did not
have one. Recorded now as **ADR-023**, with the interfaces and the config
variables written down; `CLAUDE.md` no longer says there are two hosts.

### Fixed by B — Phase 8 shipped, but the UI still called it future work
The *mechanism* was correct and stayed untouched: `NOTICE_AGENT` is dropped the
moment a finding has a verdict, confirmed against a verified finding and an
unverified one. Only the copy shown in the **not-yet-verified** state was stale,
and it said the agent "lands in Phase 8" — of a phase that had closed.
- `web/presenters/live.py` — `NOTICE_AGENT` now says the finding has not been
  verified *yet* and names where to run it (`app/`), the same pattern known
  issue #56 already applied to the reconcile tooltips. Its module docstring no
  longer calls `core/agents/` a stub.
- `web/templates/integrity/_finding_detail.html` — four button tooltips no
  longer name Phase 8; two say `web/` is read-only (ADR-018) and two say that
  overriding the agent by hand is not built in *either* frontend.
- `app/components/anomaly_table.py` — the Confidence help text said the agent
  adjusts it "in Phase 8"; it does adjust it, so the text is now present tense.
- `web/viewmodels.py` — the `notices` comment now says to name the surface that
  fills a gap, never a phase number, and says why.

### Fixed by A — the uploader advertised two formats that always failed
`app/components/file_uploader.py` had offered `txt` and `docx` as contract
formats since Phase 2, while `document_router.detect_type()` rejected both —
every such upload landed as `extraction_status='failed'` with "unsupported file
type". It failed *cleanly* (no crash, known issue #37's `ValueError` contract
holds), but the UI promised formats that could never work. Same class as known
issue #38's `xlsx`, and unlike #38 it was not recorded anywhere.
- `core/extraction/document_router.py` — a real `.txt` branch returning
  `doc_type="text"`, the schema value that has existed since Phase 5 for exactly
  this shape (known issue #43) and that nothing could previously produce.
  `page_count=1` because a text file has no pages; pagination is assigned later,
  for display only, by `pdf_renderer.typeset_pdf` (ADR-021). Verified on six real
  EDGAR contracts (25k–144k chars each) and on empty/whitespace files, which
  return `page_count=0` and a `"file is empty"` warning.
- `app/components/file_uploader.py` — `docx` **removed** rather than
  implemented: reading it needs a new dependency, and a stack addition needs an
  ADR (tech-stack rule in `CLAUDE.md`). `xlsx` is left alone and #38 stays open.

### Fixed by A — Phase 1's schema assertions are finally in pytest (closes #15)
`tests/test_schema.py` — the 12 tables, ADR-005's nullable
`source_page`/`source_bbox`, all six `CheckConstraint`s, the four-leak-type
constraint and the `milestones` table / `source_clause_ref_id` column that known
issue #14 records as absent from the plan's ER diagram. Open since Phase 1, where
the assertions lived in a scratch script; Phase 6 was said to own the port and
did not do it.

### New interfaces added to interfaces.md
- `training/serve_modal.py` — `serve()`, deployed with `modal deploy`
- `core.ai.endpoints.active_provider() -> str` (the `USE_MODAL` layer)
- `core.extraction.document_router.detect_type` — now returns `"text"` too

### Decisions recorded
- ADR-023: Modal is a third peer inference host, not a departure from ADR-011

### Known gaps / deliberately deferred
- **`fastapi` was missing from the `.venv` on this machine**, so `python
  run_web.py` could not start at all, though `requirements.txt` has always
  listed it. Installed (0.141.1, no downgrades). Nothing in the repo was wrong;
  recorded because it cost real time to diagnose and because issue #5 (no
  dependency pinning, no CI) is what let an incomplete environment go unnoticed.
- **Both GPU-dependent measurements are still unrun** (#40/#65/#41).
  `data/eval/` holds only `phase6_engine.json`. `eval_agent.py` fails cleanly
  with "paste a fresh tunnel URL" — confirmed, not assumed. Agent *quality* and
  extraction *quality* remain unmeasured, and upload → extract → persist has
  still never run against a live GPU.
- **No `.env` on this machine**, so everything above ran on the SQLite
  fallback. Phase 1's Postgres claims and the Supabase runs 12/13/14 cited by
  Phases 6–7 could not be checked here at all. `test_schema.py` runs on either
  backend, which is part of why it was worth writing.
- **The `.venv` is Python 3.13.15** — a third value after #10's 3.12 and #47's
  3.14. Streamlit Cloud parity is still unverified on any machine.
- **Streamlit's `use_container_width` is past its stated removal date**
  (2025-12-31) and still in 15 call sites across `app/`. Warning-only today.
  Not swept here: it is unrelated to anything Phase 8 touched, and a
  15-site rename belongs in its own commit. Logged in `docs/todo.md`.
- The four `docx`-shaped questions this did *not* answer: no xlsx actuals path
  (#38), no orphan Storage cleanup (#21), no CI (#5), no dependency pins (#5).

### How to verify this audit's fixes
```bash
pytest -q                                  # 125 + the new schema assertions
pytest tests/test_schema.py -q             # closes known issue #15, runs on SQLite or Postgres
python -c "from core.extraction.document_router import detect_type; print(detect_type('a.txt'))"
python run_web.py --live                   # an unverified finding's agent panel names app/, not a phase
```


## Phase 9 — Decision Engine (Page 2)
**Completed:** 2026-08-17 · **Owners:** A / B

A plain-English question produces a Yes/No backed by the user's own numbers. The
model appears at both ends and never in the middle: it reads the sentence, and it
phrases figures it is forbidden to change. Everything between is
`core/engine/cashflow.py`.

### Built by A
- `core/engine/cashflow.py` — `CashFlowBaseline`, `Recovery`, `ScenarioResult`;
  pure `baseline_from_monthly` / `recovery_from_anomalies` / `apply_scenario` /
  `evaluate` / `months_spanned`; and the two database-reading functions
  `compute_baseline` / `compute_recovery`, which do nothing but shape a query
  result before delegating — so the maths is tested without a session, the same
  split Phase 6 used for `pipeline.py`. **Takes no clock**: projection labels are
  `M1..Mn`, because the engine cannot know what month it is and will not pretend.
- `tests/test_cashflow.py` — 35 assertions.
- `scripts/eval_decision.py` — Phase 9's definition of done, six cases.

### Built by B
- `core/ai/decision_analyzer.py` — `ParsedQuestion`, `ExplanationResult`,
  `extract_cost`, `detect_cadence`, `parse_locally`, `parse_question`,
  `figures_for`, `offending_numbers`, `fallback_explanation`, `explain_verdict`.
- `core/ai/prompts.py` — `PARSE_SYSTEM`, `EXPLAIN_SYSTEM`, `parse_user`,
  `explain_user`, `DECISION_VERSION = "v1"`.
- `app/pages/2_decision_engine.py` — rewritten: the question, the running-costs
  input, the verdict, the working, the projection, and an expander stating
  exactly what the model did and did not do.
- `web/presenters/live.py` — the Decision working now comes from `cashflow`
  instead of arithmetic done in the presenter, and both notices were reworded.

### The three departures from the plan, and why
1. **The amount is read by regex; the model is the fallback.** The plan has the
   LLM parse `{what, monthly_cost, start_month}`. But `monthly_cost` *is* a
   number the user sees and it drives the verdict — a 3B model reading `$5,000`
   as `50000` flips a YES to a NO with nothing on screen looking wrong.
   `extract_cost` is deterministic and returns the substring it matched, so the
   page can show that the figure is the user's own. `test_the_pattern_owns_the_
   money_even_when_the_model_disagrees` pins it. The model still supplies `what`
   and `start_month` (prose, harmless), and an amount only when the pattern found
   none — and then `needs_confirmation` is True and the page asks, which is
   ADR-010's LLM-proposed / human-confirmed shape.
2. **`recovered_monthly` divides by the run's real window, not 12.** The plan
   writes `sum(gap) / 12`. `compute_recovery` derives the window from
   `expected_timeline`'s own billing dates via `months_spanned`. On a six-month
   run the plan's formula halves the run-rate, which is enough to flip a verdict:
   `eval_decision.py`'s sixth case is exactly that, and it reads YES at $600/month
   and NO at the plan's $300.
3. **`explain_verdict` refuses its own bad output.** The plan says a number in
   the explanation that is not in its input "is a bug ... worth writing an
   assertion". An assertion catches it in CI; `offending_numbers` catches it in
   production. The explanation is checked against `ScenarioResult.allowed_figures()`,
   retried once, then replaced by `fallback_explanation`. A missing paragraph of
   prose is a far smaller failure than a confident wrong figure.

### New interfaces added to interfaces.md
- `core.engine.cashflow.*` (the three dataclasses and eight functions above)
- `core.ai.decision_analyzer.*` — note `explain_verdict` returns
  `ExplanationResult`, **widened from the declared `-> str`**, because the caller
  must be able to tell whether the model wrote the prose or whether its attempt
  was rejected. `.text` is the old contract.
- `core.ai.prompts.{PARSE_SYSTEM,EXPLAIN_SYSTEM,parse_user,explain_user}`

### Decisions recorded
- ADR-024: the Decision Engine asks the user for expenses rather than inventing a surplus

### Measured
```
pytest -q                       233 passed (155 + 78 new: 35 cashflow, 43 analyser)
scripts/eval_decision.py        6/6 cases, correct verdict AND correct after-figure,
                                0 invented numbers in any explanation
  affordable outright                 yes   $7,600.00
  affordable only after recovery      yes   $  500.00   <- the product's whole point
  not affordable at all               no    $-3,500.00
  annual figure, converted once       yes   $7,000.00   ($72,000/yr -> $6,000/mo)
  no expenses supplied                unknown          <- refuses, per ADR-024
  six-month run not divided by 12     yes   $  100.00
app/pages/2_decision_engine.py  driven through AppTest in four states, 0 exceptions;
                                run 2: $99,743.26 + $1,875.00 - $5,000.00 = $96,618.26
                                run 1: correctly EXCLUDES $26,908 of unverified findings
web/ /decision, both modes      200; working table now engine-computed
```
**The live model has NOT phrased an explanation on a GPU.** Every figure above,
and every verdict, is computed by Python and needs no model at all — but the
prose in all six eval cases came from `fallback_explanation`, because no
Colab/Kaggle/Modal endpoint was answering (the same situation as #40/#65).
`python scripts/eval_decision.py --live` is the command; run it before citing
the model's phrasing quality. What *is* proven offline is the thing that matters
more: the guard rejects an invented figure
(`test_an_invented_number_is_rejected_at_runtime_not_just_in_ci`).

### Known gaps / deliberately deferred
- **The surplus depends on one user-typed number** (ADR-024). Disclose it: FinSight
  computes what you are owed and what you earn; you tell it what you spend. An
  expenses table is the proper fix and is not built.
- **A verdict is not reproducible from `run_id` alone** and nothing persists one,
  because it depends on that input. Two people can correctly get different answers
  for the same run.
- **`web/` still writes nothing.** Its question box has no POST route (ADR-018) and
  its Decision page names the Streamlit app rather than a phase.
- **`start_month` is parsed and displayed but does not shift the projection.** The
  engine takes no clock, so "starting in September" cannot be placed on a timeline
  without one; the projection is relative (M1..Mn) and the month is shown as read.
  Honest, and it is why the label is not a calendar month.
- **The confidence rule is a threshold, not a model.** Fewer than 3 months of
  revenue is flagged `low`; nothing weights the projection by how sparse it is.
- **`cost_share_of_revenue` is the only figure the revenue basis offers.** No
  runway, no burn, no seasonality — all of which need expenses.

### How to verify this phase works
```bash
pytest tests/test_cashflow.py tests/test_decision_analyzer.py -q   # 78, offline
python scripts/eval_decision.py            # the definition of done, no DB, no GPU
python scripts/eval_decision.py --run-id 2 # same, plus a real run's figures
python scripts/eval_decision.py --live     # needs an endpoint; NEVER RUN yet
streamlit run app/main.py                  # Decision Engine -> ask, Analyse
python run_web.py --live                   # /decision shows the working, no verdict
```


## Phases 8–9 measured against a live GPU — the agent fails, the Decision Engine holds
**Completed:** 2026-08-17 · **Owners:** A / B

First run of both GPU-dependent evals against a live Colab T4 (vLLM, base
Qwen 2.5 3B). This entry records what the endpoint actually proved, and
supersedes the "NEVER RUN yet" lines above. Appended, not rewritten.

### The endpoint
Verified before anything was measured: `/v1/models` 200 in 2.8 s serving
`Qwen/Qwen2.5-3B-Instruct` (`max_model_len` 8192), `llm_client.health()` True,
a wrong bearer token correctly rejected with 401, and the trailing slash in
`.env`'s URL normalised by `settings.api_base` as designed.

### Phase 9 — passes, and the guard is doing real work
`python scripts/eval_decision.py --live` → **6/6 correct verdicts, no invented
number reached the output.** But in **3 of the 6 cases the model quoted figures
it was not given, on both attempts**, and `offending_numbers()` rejected every
one and fell back to deterministic prose: `[16500.0, 17500.0, 1500.0]`,
`[19000.0]`, `[17272.73]`. That last one is the example worth showing — it
looks computed and is pure invention. Report the guard as reliable; do **not**
report the 3B model as reliable (known issue #76).

### Phase 8 — the agent destroys genuine findings
`python scripts/eval_agent.py` against run 13 (`realistic`): the agent marked
**4 of the 5 planted anomalies `false_positive` — $21,480.00 of $22,500.00** of
ground-truth-verified leaks — keeping only the `short_change`. Its own reasoning
shows the inversion: *"The missing $5,000 was **not found** in the client's bank
activity … indicating the engine's finding is likely a false positive."* A clean
search is evidence the money **is** missing. `prompts.py` rules 5 and 6 say
exactly that, with a worked example, so **this is not a prompt bug** — the base
model does not follow the instruction. Same capability ceiling as #45/#48/#49;
Phase 10 is what closes it (known issue #74).

### The eval that let it through — fixed
`eval_agent.py` printed **"All parts passed."** while this happened, because
both parts graded bookkeeping instead of correctness. Part 1 asserted only that
every finding got *some* verdict and that the counts added up. Part 2's check
was **labelled** *"the unattributed payment was found and flipped the verdict"*
but asserted only `row.status == "false_positive"` — and the agent reached that
status having found nothing, never calling `search_bank_transactions`, the one
tool the fixture exists to exercise.

Fixed the same day (known issue #75):
- Part 1 grades every verdict against `ground_truth.json`. Planted anomalies are
  true by construction, so `false_positive` on one is always wrong;
  `needs_review` is tolerated as an honest hedge. A missing `data/scenarios/`
  now **fails loudly** instead of passing quietly (#33, #44).
- Part 2 asserts `search_bank_transactions` was actually called, and that a
  `false_positive` verdict rests on a tool result that returned a match —
  keying on the `"Found …"` prefix `_format_transactions` /
  `_format_combinations` already produce, so it checks evidence rather than
  parsing prose.

**The lesson worth keeping: an eval that counts outputs is not an eval.** Phase
11's base-vs-tuned comparison is unprovable with a test that always says pass.

### Known gaps / deliberately deferred
- **The agent is not usable in a demo as it stands.** Nothing was changed in
  `core/agents/` — this is a model-capability gap, and patching the agent to
  paper over it would corrupt the Phase 10/11 measurement.
- **`verify_run` writes its verdicts**, so a bad agent run leaves the dashboard
  reading $1,020 instead of $22,500. Run 13 was restored twice during this work
  with `python scripts/run_scenario.py realistic --recompute 13`, which is
  idempotent and also restores the engine's confidence scores.
- **`scripts/verify_llm_stack.py` reports a false FAIL on a configured machine.**
  Its first case expects no endpoint but only sandboxes the cache dir and the
  override file, not the environment, so it reads the real `.env` and reports
  "unreachable" where it expects "not set". 21/21 with the URLs cleared. Not
  fixed — the stack is fine, the verifier leaks.

### How to verify this phase works
```bash
python scripts/eval_agent.py                 # MUST now fail on run 13 until Phase 10
python scripts/eval_agent.py --skip-live-run # fixture only
python scripts/eval_decision.py --live       # 6/6, watch for rejected-figure warnings
python scripts/run_scenario.py realistic --recompute 13   # undo an agent run
```


## Phase 10 — Fine-Tuning (QLoRA adapter, trained and measured)
**Completed:** 2026-08-19 · **Owners:** A / B

### Built by A
- `training/evaluate.py` — was a one-line stub. The exam harness: reads the sealed
  eval set, asks each model every question through the app's own v4 prompt, marks
  six measures, writes `data/eval/phase11_base_vs_tuned.json`. `--dry-run` marks
  the answer key against itself and must score 100% everywhere, so a marking bug
  is found without booking a GPU.
- `docs/phase11_results.md` — the measured base-vs-tuned comparison, with the
  regression decomposed and the five disputed contracts read by hand.

### Built by B
- `training/finetune_colab.ipynb` — reviewed against the real data and the real
  dependency versions before first run; four defects fixed (below). Trained the
  adapter on a free Colab T4 and pushed it to `ibrahim404/finsight-qwen2.5-3b`.
- `training/data/eval_set.jsonl` + `data/corpus/heldout/SEALED.json` — committed.
  `.gitignore` had un-ignored both on purpose since Phase 10 opened, but neither
  had ever been `git add`ed.

### The notebook review (2026-08-18) — four defects, none found by running it
1. `SFTConfig(max_seq_length=)` — TRL renamed the field to `max_length`. Verified
   against trl 0.24.0, the newest unsloth permits; no shim in trl, unsloth or
   unsloth_zoo. Hard crash *after* the 15-minute install.
2. `apply_chat_template(..., return_tensors="pt")` returns a dict, not a tensor,
   on transformers 5.x (`return_dict` now defaults True; unsloth allows <=5.5.0).
3. `eval_set.jsonl` was never committed, so the clone found nothing and the leak
   check halted. `SEALED.json` likewise — the proof the exam was sealed fairly did
   not survive a machine change, which is its only job.
4. **The notebook trained on a two-line system prompt of its own** while the app
   sends `prompts.EXTRACTION_SYSTEM` (v4). That tunes an adapter for a prompt
   production never sends and makes the comparison vary two things, not one. It
   now loads `core/ai/prompts.py` from the clone and refuses to train without it.
   `MAX_SEQ_LEN` 2048 -> 4096 followed: with the real prompt, training tops out at
   1,973 tokens but 6 of the 22 exam prompts reach 2,378, and unsloth caps the
   session context at that value.

### Measured — 20 sealed contracts, both models, one live T4
| Out of 20 | base | tuned |
|---|---|---|
| usable answer | 20 | 20 |
| **fee amount right** | 13 | **20** |
| **billing rhythm right** | 11 | **18** |
| price rise right | 15 | 8 |
| **found anything at all** | 17 | **20** |
| quotes really in the text | 100% | 100% |

Full reading, including the hand-read of the disputed contracts:
`docs/phase11_results.md`.

### Decisions recorded
- No new ADR. The schema gap below is a candidate for one and is deliberately not
  written yet — the fix has not been scoped.

### Known gaps / deliberately deferred
- **The tuned model fabricates escalation percentages.** 3 of its false positives
  carry a percentage appearing nowhere in the document, and 5 more report a 0%
  rise. Every one of those quotes passes the grounding check, so a fabricated rate
  would reach the user beside a genuine highlighted sentence. The fix is
  deterministic and not built: reject an escalation whose percentage is not in the
  clause it quotes, mirroring `is_verbatim()`. Known issue #86.
- **`ContractRules` cannot express a rule whose rate is not a fixed number.** Both
  unmarkable eval rows and four escalation disagreements are this one gap, not six
  review errors. Known issue #87.
- **The sealed key under-reports escalations** — 4 genuine rise clauses recorded as
  absent. Not corrected: re-opening a sealed exam after seeing scores is how a
  defensible number becomes indefensible. Known issue #88.
- Discounts (n=1) and milestones (n=1) are unmeasured. No claim may rest on them.
- The adapter is private on HuggingFace and has **never been served from Modal**;
  only the Colab tunnel has run it. Deployment is Phase 11's remaining half.

### How to verify this phase works
```bash
python training/evaluate.py --dry-run      # marker self-test, no GPU: must be PASS
# with a session serving both models:
python training/evaluate.py --base Qwen/Qwen2.5-3B-Instruct --tuned finsight-tuned
```

---

## The invented-rate guard — found by the exam, fixed the same day (2026-08-19)

Appended after the Phase 10 entry above, which listed this as its first known gap.

**What was wrong.** `_ground` checked that a quoted *sentence* was in the
document — which is why quote fidelity read 100% for both models — but nothing
checked the *number inside it*. The tuned adapter exploited exactly that gap:
of its 10 wrongly-claimed price rises, 5 reported a 0.0% rise and 3 carried a
percentage appearing nowhere in the contract. All 8 passed grounding, so a
fabricated rate would have reached a user beside a genuine highlighted clause
and been multiplied by a real fee — $585,000 at Poindexter.

**The fix.** `contract_extractor.percentage_in_clause()`: a rate must be written
in the clause it quotes, in any form a contract uses (`3%`, `3.0%`,
`3 per cent`, `three percent`, `three (3) percent`), used *as* a percentage so a
`$3,000` fee cannot licence a 3% rise off the same sentence. Zero or less is
refused outright. `_ground` gained a fourth bucket, `bad_figure`, so an invented
rate is never counted as an invented sentence.

**Deliberately not extended** to month counts ("adjusted annually" means twelve
months with no digits in the text, so the same rule would discard correct
answers) or to milestone amounts. The percentage is what multiplies money.

**`grounded` was not redefined** — it still counts quotes really in the document,
whether or not their figure survives — so Phase 5's 80.0% stays comparable.

**Re-measured from cache, no GPU, one variable:**

| Out of 20 | base before | base after | tuned before | tuned after |
|---|---|---|---|---|
| price rise right | 15 | **17** | 8 | **15** |
| wrongly claimed a rise | 4 | **2** | 10 | **2** |

The regression narrows −7 → −2, inside the noise band declared before any number
existed. **With the guard in place fine-tuning is a clear net win**: fee amount
+7, billing rhythm +7, found-anything +3, price rise −2, quote fidelity 100% on
both sides.

`training/evaluate.py` now marks post-grounding output — what the product would
actually store — with `--no-guard` to reproduce the raw pre-fix numbers.

### Known gaps
- The schema still cannot record an inflation-linked rise (#87), so the CPI
  contracts now report *nothing* rather than a wrong number. Safe, not right.
- A **cap** still passes as if it were a rate: Pinnacle's *"in no event in excess
  of five percent"* is in the sentence, so the guard cannot tell it from a rate.
  Reading a number's role is beyond a verbatim check.
- `tests/test_contract_extractor.py` is the **first test file this module has ever
  had** — 15 assertions. The grounding logic the product's credibility rests on
  had zero coverage until today.

### How to verify
```bash
pytest tests/test_contract_extractor.py -q          # 15 assertions, no GPU
python training/evaluate.py --dry-run               # marker self-test, must PASS
```

---

# PART 2 — ARCHITECTURE DECISION RECORDS

> **Never delete an ADR.** If we change our minds, add a new one and mark the old one
> *Superseded by ADR-0NN*.
>
> **Format:** Context (the forcing constraint) → Decision → Consequences (including what we gave up).
>
> ADR-001 through ADR-010 were agreed at Phase 0, before any code, and are extracted from
> `implementation_plan.md`. They lived in `docs/decisions.md` until 2026-08-08.

---

## ADR-001 — No local GPU anywhere in the runtime path

**Status:** Accepted (Phase 0)

**Context.** The v1 plan ran a local model on a single RTX 3060 and budgeted VRAM. That makes the project undemoable on any machine but one, and it makes deployment impossible: Streamlit Community Cloud has no GPU.

**Decision.** Every runtime component runs on CPU or on a hosted free tier. Inference is an HTTP call. Fine-tuning happens on free Colab/Kaggle T4s, offline, and is served back over a tunnel.

**Consequences.** The scarce resource stops being VRAM and becomes **requests per minute** — see the API budget in `implementation_plan.md`. We gain a public URL, reproducibility on any laptop, and a demo that survives a dead GPU. We lose the ability to run a large model with no rate limit, and we take on a network dependency on demo day (mitigated by the disk cache and a second configured provider).

---

## ADR-002 — One swappable LLM client behind a single environment variable

**Status:** Accepted (Phase 0) · **Amended by [ADR-011](#adr-011--self-hosted-open-source-inference-only-no-frontier-api-calls)** — the principle stands, but the provider list is now our own endpoints, not vendor APIs.

**Context.** We use a hosted baseline now and a fine-tuned model in Phase 10, and Phase 11's headline claim is a measured comparison between them. If the swap touches code, the comparison is not one-variable and the result is contestable.

**Decision.** All model access goes through `core/ai/llm_client.py`. The provider is chosen by `LLM_PROVIDER` (`gemini | groq | openrouter | finetuned_tunnel`). Every provider is reached through an OpenAI-compatible interface, including our own fine-tuned model, which Colab serves behind a FastAPI `/v1/chat/completions` endpoint.

**Consequences.** Switching providers — including to the model we trained — is an env-var change with zero code edits. A dead API key on demo day is a one-line fix. Cost: we write a small compatibility shim per provider and we cannot use provider-specific features that have no equivalent elsewhere.

---

## ADR-003 — Supabase Postgres as the primary database

**Status:** Accepted (Phase 0)

**Context.** Two people on two machines need to see the same data, and the deployed app needs a database that outlives a container restart. SQLite in the repo cannot do either. Neon was the main alternative.

**Decision.** Supabase Postgres via SQLAlchemy, with `sqlite:///data/finsight.db` as an automatic fallback when `DATABASE_URL` is unset. Uploaded files go to Supabase Storage, accessed by signed URL.

**Consequences.** Both free tiers cover our volume; we chose Supabase because its table editor lets us inspect and hand-fix rows during development, which is worth more to us than Neon's branching. Offline work still functions on SQLite. We accept that Postgres-only features must be avoided or the fallback breaks silently.

---

## ADR-004 — Pydantic + JSON mode + one repair retry, not Outlines

**Status:** Accepted (Phase 0)

**Context.** Contract extraction must return valid structured data every time. Outlines constrains generation at the token level and is the stronger guarantee — but it needs local logit access, which ADR-001 removed. Over HTTP it simply does not work.

**Decision.** Ask for the provider's JSON mode, validate against a Pydantic schema, and on validation failure send exactly one repair call containing the error. If that also fails, return `None`. `complete_json` never raises to the caller.

**Consequences.** We get valid, typed objects and a measurable *repair rate* for the evaluation table. We lose hard structural guarantees: a small percentage of extractions will fail entirely, so every caller must handle `None`. That is why the interface convention is "return `None`, don't raise".

---

## ADR-005 — Code finds bounding boxes; the model never does

**Status:** Accepted (Phase 0)

**Context.** v1 asked the model to return page numbers and pixel coordinates for each clause. A model reading extracted text has no idea where anything sits on a page, so those coordinates were confidently invented — and highlighting the wrong paragraph is worse than not highlighting at all.

**Decision.** The model returns `clause_text` copied **verbatim** and nothing positional. `core/extraction/clause_locator.py` then finds that string in the PDF with PyMuPDF `page.search_for()`, falling back to fuzzy matching for OCR noise, and returns a real bbox with a `locate_method` of `exact` or `fuzzy`. `clause_references.source_page` and `.source_bbox` are **nullable**.

**Consequences.** Highlights are real. The lookup doubles as a hallucination check: a quote that cannot be found was invented, so the rule is auto-flagged low-confidence. `locate_method` gives us a clause-grounding-rate metric. The cost is that the UI must degrade honestly to a page-level view when the bbox is `NULL` — every consumer has to handle that, and it must never crash.

---

## ADR-006 — Reconcile on client-month aggregates, not transaction-to-invoice matching

**Status:** Accepted (Phase 0)

**Context.** Deciding which transactions settle which expected billings is a combinatorial assignment problem: high effort, high risk, and most of its value shows up in rare cases.

**Decision.** For each expected timeline row, sum **all** of that client's actual transactions in that calendar month (fuzzy client-name match, ±15 day tolerance at month boundaries) and compare totals.

**Consequences.** Reconciliation stays a short, pure, testable function. We lose precision on split payments — a $10,000 invoice paid as $6,000 + $4,000 across a month boundary can look like a Short-Change. That precision comes back cheaply in Phase 8: the agent's `check_split_payments` tool does transaction-level search **only on already-flagged rows**, so we pay the combinatorial cost on ~5 rows instead of ~5,000.

---

## ADR-007 — Contracts are sourced online; actuals are derived deterministically

**Status:** Accepted (Phase 0)

**Context.** We need contracts realistic enough that extraction is a genuine test, and actuals whose anomalies we know exactly so we can measure precision and recall. Model-generated contracts would make extraction trivially easy and the evaluation meaningless.

**Decision.** Contracts come from CUAD v1 (510 real expert-annotated commercial contracts, CC BY 4.0) and SEC EDGAR EX-10 filings. Actuals are **computed** from those contracts' true rules by `data_sourcing/scenario_builder.py`, which plants named anomaly types and writes `ground_truth.json` alongside them. **No model ever invents a contract.**

**Consequences.** Extraction is tested against real legal prose, and every reported anomaly can be scored against ground truth. We accept that CUAD is filed commercial contracts rather than small-studio retainers — expect only ~15–25% to survive the service/retainer filter, topped up from EDGAR.

---

## ADR-008 — Top-down build order: database and UI shell first

**Status:** Accepted (Phase 0)

**Context.** Bottom-up builds put integration last, which is where two-person projects fail: everything works alone, nothing works together, and it is discovered in the final week.

**Decision.** Phases 1–2 build the database and the complete UI, populated with real seeded rows. Every later phase replaces one seeded table with a computed one. **The UI reads only the database, never a hardcoded dict.**

**Consequences.** There is a demoable product from week two, and integration never becomes a cliff — when reconciliation lands in Phase 6, nothing is "connected", it just starts writing to a table the UI has read since week one. The cost is `scripts/seed_demo.py`, throwaway-ish code that must write every table the UI reads.

---

## ADR-009 — Fine-tuning is a measured comparison, not a dependency

**Status:** ~~Accepted (Phase 0)~~ · **Superseded by [ADR-012](#adr-012--the-base-model-is-served-from-phase-5-the-tuned-adapter-replaces-it-at-phase-10)** (2026-07-29). Kept for the record: this was true while a hosted API was the baseline. ADR-011 removed that baseline, so self-hosted inference became a hard dependency and the comparison became base-vs-tuned.

**Context.** Fine-tuning is the capstone's differentiator, and it is also the single most likely thing to fail on free compute. Anything downstream of it inherits that risk.

**Decision.** The product is complete and demoable using the hosted baseline alone. Phase 10 trains Qwen 2.5 3B with Unsloth + QLoRA and serves it via `LLM_PROVIDER=finetuned_tunnel`. Phase 11 runs **the same harness** against both and reports the numbers, whichever way they come out.

**Consequences.** A failed training run costs a section of the report, not the demo. The held-out eval set is built before training and never trained on. We accept that the fine-tuned model may lose to the baseline — that is a legitimate, reportable result, not a failure.

---

## ADR-010 — CSV column mapping is LLM-proposed and human-confirmed

**Status:** Accepted (Phase 0)

**Context.** Real exports have unpredictable headers (`Txn Date`, `Posted`, `Amount (USD)`, `Memo`). A fixed template rejects most real files; a fully automatic mapping fails silently and poisons every downstream number with no visible error.

**Decision.** Send only the header row and three sample rows to the model, have it propose a mapping, and render that proposal as pre-filled dropdowns the user confirms. Confirmed mappings are cached in the `column_mappings` table by header signature. A downloadable template stays available as the zero-friction path.

**Consequences.** Mis-parsing becomes visible and correctable instead of silent, and repeat uploads of the same export format cost no API call. The cost is one extra confirmation click in the flow, and a table that exists purely to remember it.

---

<!-- ================================================================= -->
<!-- APPEND NEW ADRs BELOW. NEVER EDIT ONE ABOVE — SUPERSEDE IT.       -->
<!-- ================================================================= -->

## ADR-011 — Self-hosted open-source inference only; no frontier API calls

**Status:** Accepted (2026-07-29, between Phase 0 and Phase 1)
**Amends:** ADR-001, ADR-002, ADR-004 · **Forces:** ADR-012 (which supersedes ADR-009)

**Context.** Phase 0 shipped with Gemini as the baseline and Groq/OpenRouter as backups. Three problems with that, and the first is the one that matters:

1. **The capstone claim is weaker.** "We called a frontier API" is a systems-integration result. "We tuned and hosted the model that reads the contracts" is an ML result. The whole differentiator of this project is the second one.
2. **No reproducibility.** A hosted model is a moving target: the vendor can change the weights behind a model name between our evaluation run and our demo, and we cannot pin a revision or explain a number that shifted.
3. **We do not control the quota.** Free-tier limits change without notice, and the failure lands on demo day.

**Decision.** Every model call in the runtime path goes to an **open-source model we host ourselves** on free Colab/Kaggle GPU, exposed as an OpenAI-compatible `/v1/chat/completions` endpoint over a public tunnel. No Gemini, Groq, or OpenRouter anywhere — not for contract extraction, not for CSV column mapping, not for OCR, not for the decision engine.

Base model: `Qwen 2.5 3B Instruct`, the model Phase 10 was already going to fine-tune.

**Consequences.**

*What we gain.* The result is reproducible — we pin the base weights and the adapter revision, and a number computed in October still computes in December. There is no per-request quota, so batch experiments and repeated eval runs are free. And ADR-004 gets *stronger*: because we control the forward pass on the server side, the serving notebook can constrain generation with a grammar (Outlines/`xgrammar`) and report a genuine valid-JSON rate — something a hosted API could never give us. The client-side repair-retry stays as the safety net.

*What it costs, and this is the real one.* Availability moves from a vendor's uptime to **our notebook session**. Free Colab/Kaggle sessions expire, disconnect when idle, and hand out a **new tunnel URL every time they restart**. Cold start is minutes, not milliseconds — the base weights have to load before the first request. Concretely this means:

- The endpoint URL must be reconfigurable **without a redeploy** (env var / Streamlit secret), because it changes daily.
- Two sessions stay configured — one Colab, one Kaggle — so a dead session is a one-line change, exactly as two providers used to be.
- `llm_client` needs a generous timeout and one retry for cold starts, and the UI must say "the model endpoint is unreachable" rather than showing a blank result.
- **The disk cache stops being an optimisation and becomes demo insurance.** Everything shown on demo day must be pre-warmed into `data/cache/`, so the demo survives the tunnel dying mid-sentence.
- Record a screen capture of the live path in advance. This is the single largest operational risk in the project and it was accepted knowingly.

*Elsewhere.* The Gemini-vision OCR option is gone; Surya on Colab (Path B) becomes the only OCR fallback, and it stays an offline batch step rather than a live path — which keeps OCR off the critical path, as it always was. A 3B model is meaningfully weaker at zero-shot extraction than a frontier model, so expect Phase 5's extraction quality to start lower; that gap is precisely what Phase 10's fine-tuning exists to close, and Phase 11 now measures it honestly instead of assuming it.

---

## ADR-012 — The base model is served from Phase 5; the tuned adapter replaces it at Phase 10

**Status:** Accepted (2026-07-29) · **Supersedes ADR-009**

**Context.** ADR-009 said fine-tuning was a measured comparison and never a dependency, because the hosted API was always there as the baseline. ADR-011 deleted that baseline. Taken naively, nothing that calls a model could work until Phase 10 — which would push Phases 5 through 9 behind the single riskiest phase in the project and destroy the top-down build order (ADR-008).

**Decision.** Stand the serving notebook up in **Phase 5**, loading the **base** Qwen 2.5 3B Instruct weights, untuned. Phases 5–9 are developed against that endpoint. Phase 10 trains a QLoRA adapter; the notebook loads it and serves it under a different model name. The app changes nothing — one `LLM_MODEL` value.

Phase 11's comparison therefore becomes **base vs tuned**, not hosted-vs-tuned.

**Consequences.** The build order survives intact, and serving infrastructure — tunnels, cold starts, session expiry — gets discovered in Phase 5 rather than in the final fortnight. That deliberately breaks the "riskiest work last" heuristic, and it is the right call here: everything downstream now depends on serving, so it must be proven early.

The comparison also gets cleaner than it was. Same base weights, adapter on or off, one variable — so any delta is attributable to our training data and nothing else. Under ADR-009 we would have been comparing a 3B model against a frontier model, which measures model scale as much as it measures our work.

The product's dependency on fine-tuning is narrower than it looks: if training fails outright, the base-weights endpoint still runs the entire application. We would lose the capstone claim, not the demo. What we cannot lose is self-hosting itself — that is now load-bearing.

---

## ADR-013 — SEC EDGAR is the primary contract source; CUAD is demoted

**Status:** Accepted (2026-08-10, pre-Phase-3 spike) · **Amends ADR-007**

**Context.** ADR-007 said contracts are *sourced* and actuals *derived*, naming CUAD and EDGAR together as if interchangeable. Risk R1 in the plan flagged CUAD's M&A skew and prescribed a keyword filter expecting 15–25% retention. The spike measured all 510 CUAD contracts and found that number is real *and meaningless*:

- 248 (48.6%) pass the plan's ANY-keyword filter.
- **8 (1.6%)** carry both a real recurring amount and a real escalation clause.
- **3** survive being read by hand.

Three usable contracts cannot support `forgotten_raise`, one of the four headline leak types. The plan's filter fails in two specific ways, both now quantified: bare `escalat*` matches 81 documents of which **68 mean the dispute-escalation procedure**, and 121 documents (23.7%) redact their financials under SEC confidential treatment.

Aiming EDGAR's full-text search at service agreements gives **51 gold in 288 documents (17.7%)** — an 11x better rate on the same underlying archive.

**Decision.** EDGAR is the primary source for the contract corpus. CUAD is retained for two narrower jobs: extraction development in Phase 5, and training volume in Phase 10. It is no longer expected to supply anomaly scenarios.

Filtering is redefined. A contract qualifies on **concrete, unredacted values** — a real amount tied to a period and a real percentage or CPI reference tied to a fee — not on keyword presence. Bare `escalat` is removed from any keep-list. Deduplication is on the **clause fingerprint and the filer**, never the filename.

**Consequences.**

*What we gain.* A 44-contract corpus against a 30 target, and an honest data-provenance section: we can state the funnel from 798 documents scanned to 44 distinct contracts, with the reason for each drop. Reporting distinct clauses rather than document counts is the defensible metric, and it is ~2.5x lower than the naive count — better to publish that ourselves than have it found.

*What it costs.* EDGAR serves **HTML, not PDF**. Phase 7's clause viewer locates quotes with PyMuPDF `page.search_for()`, which requires a PDF. Either convert on the way into `data/corpus/contracts/`, or accept page-level degradation — ADR-005 already permits a null bbox. This is unsolved and uncosted, and it is the main debt this decision creates.

Also: everything on EDGAR is a large-company filing, because that is who files with the SEC. FinSight's stated customer is a 3–20 person studio. The legal prose is genuine but the domain is not the target domain. Say so in the report rather than letting a reader infer otherwise.

*What we deliberately did not do.* The corpus still over-represents one cluster of mutual-fund service agreements, because the probe used generic queries and read only the first page of each result list. A broader search is designed but unrun. It is scheduled before **Phase 10**, not Phase 3, because variety is load-bearing only for training and the base-vs-tuned comparison — the MVP demo needs a handful of good contracts and already has them.

---

## ADR-014 — Redacted values are filled deterministically, never by a model

**Status:** Accepted (2026-08-10, pre-Phase-3 spike) · **Extends ADR-007 · Constrained by ADR-011**

**Context.** About a quarter of both corpora redact financials: *"fees shall increase by `[***]` percent per annum"*. The prose is real lawyer-written text; only the figure was withheld. Discarding these documents would be wasteful, and it turns out actively harmful — the redacted pile carries **33 distinct escalation clauses against gold's 21, with zero overlap**, because boilerplate fee letters publish their numbers while genuinely negotiated contracts hide them. Redaction correlates with *quality*.

The obvious move is to have a language model fill the blanks — and there were spare DeepSeek credits available to do it.

**Decision.** Blanks are filled by **seeded deterministic Python** (`scripts/fill_blanks.py`). No model call, no API, no vendor SDK.

Two rules make it sound:

1. **The value is substituted into the contract text, not only into the answer key.** If the document still said `[***]` while ground truth claimed 5%, we would be training the model to invent a number that is not in front of it — precisely the behaviour architecture rule 1 exists to prevent.
2. **The filler refuses when it cannot read the blank's type.** Money only when `$` immediately precedes; percentage only when `%` or "percent" immediately follows; duration only with an explicit period word and a duration verb. Anything else is left redacted.

**Consequences.**

*Why this is better than a model, not merely compliant.* If a model picks the number, we must read its output to learn what it chose and record that as ground truth — a verification step. When Python picks it, **the inserted value *is* ground truth, known by construction, recorded as it is written**. This is the same principle ADR-007 already applies to actuals: sourced prose, derived arithmetic. Using a model here would add a step and a way to be silently wrong.

*Why refusing matters.* The first implementation guessed at every blank and filled a Vantiv rate card — "Card Activation Monthly Fee `****`" — with counts like 5 and 12, corrupting a fee schedule invisibly. Precision costs nothing here: we need ~6 usable documents out of 44. Recall is worthless; a wrong value poisons ground truth without ever failing loudly. The current rules fill 16 values across 6 contracts and leave every ambiguous blank alone.

*A second pass was needed and is narrow on purpose.* Genomatica prices two services in separate sentences; a window around one clause left the other redacted, leaving the contract internally inconsistent. A document-wide pass fills only `$<blank> … per month/annum/year`. Tier tables are not caught, because `< $ **** **** $ ****` has no period word after each cell.

*What it costs.* The filled documents are no longer verbatim public records. Any report or demo using them must say which values were inserted — `ground_truth_fills.json` records every one, with the seed, so the corpus is reproducible and the claim is auditable.

*On the DeepSeek credits.* ADR-011 forbids vendor API calls in the runtime path. It does not obviously cover offline data preparation, and the plan already contemplates drafting training pairs with "the best available model" before human verification. That remains an **open decision** for Phase 10 — using DeepSeek to draft `ContractRules` JSON would be standard distillation and defensible if disclosed, but it dents the "everything runs on the model we host" story. It is not decided here, and it is not needed here.

---

## ADR-015 — The serving notebook runs vLLM's OpenAI server, with a hand-written fallback

**Status:** Accepted (2026-08-13, Phase 5) · **Implements ADR-012**

**Context.** ADR-012 requires an OpenAI-compatible `/v1/chat/completions` on a free notebook GPU from Phase 5. The plan says "FastAPI + Cloudflare tunnel", which reads as *write a FastAPI app around `transformers.generate`*. That is about 120 lines and entirely predictable — but it gives up two things we now own, because ADR-011 made us the operator of the server rather than a client of somebody else's.

**Decision.** `training/serve_model.py` launches **vLLM's OpenAI server** as its default backend, and keeps a hand-written **transformers + FastAPI** server as `--backend transformers`.

vLLM is chosen because it *is* a FastAPI app implementing the exact routes we need, it enforces the bearer token itself via `--api-key`, it is dramatically faster per token, and — the reason that actually matters — it supports **grammar-constrained decoding** through `response_format: {"type": "json_schema"}`. ADR-004 rejected Outlines because a hosted vendor API could not give us logit access. We now host it. Constrained decoding is the upgrade ADR-011 bought us, and it costs one flag rather than a rewrite.

The fallback exists for a specific, foreseeable failure: vLLM requires compute capability **7.0 or higher**, and Kaggle sometimes allocates a **P100 (6.0)**. Without a second backend, "use Kaggle as the backup" would be a claim that fails exactly when it is needed. `--backend auto` tries vLLM and falls back with a loud log line if it cannot start.

**Consequences.** Two code paths where the plan implied one, and the second is genuinely less capable: no grammar constraint, no continuous batching, slower generation. That asymmetry is acceptable because the client's repair-retry (ADR-004) was always going to be kept regardless, and it is exactly what covers the unconstrained path.

The client had to learn to **negotiate downwards**. It sends a JSON schema, and on a 400 retries with `json_object`, then with neither, memoising the answer per base URL. That is three round trips once per endpoint, not per call — and it means the same client code drives both backends without knowing which one it reached.

The real cost is install time: vLLM pulls its own torch and takes several minutes on a cold Colab runtime. Cold starts were already minutes, and the disk cache already existed to cover them, so this makes an accepted cost slightly worse rather than introducing a new one.

---

## ADR-016 — Colab and Kaggle are peers, swappable at runtime; failover is on by default

**Status:** Accepted (2026-08-13, Phase 5) · **Amends ADR-002 · Mitigates known issue #6**

**Context.** ADR-002's promise is that one variable swaps the endpoint. Phase 0 delivered that in `.env` — and then Phase 5 met the thing `.env` cannot express. `core/config.py` resolves every variable **once per process** behind `@lru_cache`, which is correct for a database URL and wrong for a tunnel URL that rotates every time a notebook restarts. Honouring ADR-002 literally meant editing `.env` and restarting Streamlit, mid-demo, while a session is dying. Meanwhile the docs described Colab as "primary" and Kaggle as "backup", which quietly encouraged only ever configuring one of them — so the backup would be discovered to be unconfigured at the moment it was needed.

**Decision.** Three things, together:

1. **`core/ai/endpoints.py` owns the mutable half of the LLM config**, resolving provider, URL and model at *call* time. It layers `data/endpoint_override.json` over `settings`. `config.py` remains the only module that reads `os.environ`.
2. **Colab and Kaggle are peers.** Both URLs are configured simultaneously; `LLM_PROVIDER` (or the in-app radio) picks which is live. The disk cache is keyed on prompt and model and **not** on the endpoint, so a response cached from one host hits from the other. That is the difference between interchangeable and merely both-available.
3. **`LLM_FAILOVER` defaults to true.** When the active endpoint is unreachable, one retry goes to the other configured one.

The bearer secret is **not** overridable from the UI. A secret typed into a text box ends up in a screenshot.

**Consequences.** Two sources of truth for the endpoint, which is a real cost. It is paid down by making precedence visible: the page states whether a URL came from `.env` or from the app, and a Reset button hands control back. A file rather than `st.session_state` because `scripts/eval_extraction.py` must see the same choice the UI made.

Silent failover would be worse than no failover — a demo where Kaggle is quietly answering while the screen says Colab is a debugging trap. So the host that answered is recorded on every successful call, the switch is logged at WARNING, and the endpoint page shows a banner when the last answer came from a failover.

What this does **not** fix: both sessions can be dead at once, cold starts are still minutes, and the URL still has to be pasted by hand after every restart. The cache remains the only mitigation that works when nothing is running, which is why it is described as demo insurance rather than an optimisation.

---

## ADR-017 — A quote is grounded against the text always, and against a PDF when there is one

**Status:** Accepted (2026-08-13, Phase 5) · **Extends ADR-005 · Partially answers known issue #28**

**Context.** ADR-005 says the model returns a verbatim `clause_text` and code finds the coordinates, and that a quote which cannot be located was hallucinated. `clause_locator` implements this with PyMuPDF — which needs a **PDF**. ADR-013 then made **EDGAR** the primary contract source, and EDGAR serves **HTML**. Taken together, the hallucination detector that ADR-005 describes as free would not run at all on the primary corpus.

**Decision.** Grounding happens at two levels, and they are reported separately.

**Text grounding** runs in `contract_extractor` on every document regardless of format: each `clause_text` is checked against the document's own extracted text (whitespace-insensitive substring, then `fuzz.partial_ratio ≥ 92`), and any rule whose quote is not there is **dropped before it can reach the caller**. Quotes under 20 characters are refused outright — a five-word quote matches by luck.

**PDF grounding** stays exactly as ADR-005 specifies, runs where a PDF exists, and produces the page and rectangle. `scripts/eval_extraction.py` measures it on CUAD PDFs, which is precisely the extraction-development role ADR-013 demoted CUAD to.

**Consequences.** The hallucination check — the part that protects the *numbers* — now covers 100% of documents instead of only the PDF ones. The highlight — the part that protects the *demo* — still needs a PDF, and EDGAR contracts will degrade to a page-level view, which ADR-005's nullable `source_page`/`source_bbox` already permit.

This does not close known issue #28. Converting EDGAR HTML to PDF on the way into the corpus remains unsolved and uncosted, and it is still the main debt ADR-013 created. What changes is that the debt is now confined to *highlighting*, not to *correctness*.

One reporting obligation follows: "clause grounding rate" is two different measurements, and a report that quotes a single number without saying which one it is would read well and mean nothing. The eval script prints both, labelled.

---

## ADR-018 — Two frontends over one database, and a demo/live toggle that never falls back

**Status:** Accepted (2026-08-14, alongside Phase 6) · **Extends ADR-008** · **Partially superseded by ADR-025 (2026-08-19):** its "`web/` writes nothing" clause no longer holds — `web/` uploads. Everything else in this ADR stands, including the two-presenter split and the rule that live never falls back to demo.

**Context.** The delivered design arrived as a single HTML file with a fixed 1440px canvas, a full inline-styled component system and five hand-built states. Streamlit renders widgets, not arbitrary markup: reproducing that design inside it would mean a wall of `st.markdown(unsafe_allow_html=True)`, which loses the layout, the hover states and the ability to edit a screen without redeploying an app. Meanwhile Streamlit is genuinely good at the things it was chosen for — the config page with its ✅/❌ table, DB health, the model-endpoint switcher, file upload widgets — and none of those are worth rewriting.

There was also a second problem the mockup surfaced. It shows five screens, and four of them are states the database can be *in*: nothing uploaded, mid-import, findings, clean run. A demo needs all five on demand. A real run has exactly one. Building only the real path means the design can never be shown; building only the mock path means the app is a picture of a product.

**Decision.** Two frontends over one database, and neither is deprecated.

`app/` (Streamlit) keeps the operational pages. `web/` (FastAPI + Jinja2) renders the delivered design. Both read through the same `core.db.queries` helpers — there is no second data path, and hard rule 3 holds for both: **the UI reads only the database.**

Within `web/`, every screen is rendered from one of two presenters, selected by a toggle:

* `presenters/demo.py` returns the mockup's own content, transcribed. It is the reference render — the thing to diff against when a template change is meant to be invisible.
* `presenters/live.py` returns the same dataclasses built from the database.

**They never call each other, and there is no fallback from live into demo.** Where the database has no answer, the view model carries `None` or an empty list, and the template draws skeleton bars plus a dashed box naming the phase that fills it. A page of dashes is a correct page.

The mode resolves cookie → `WEB_DATA_MODE` → `demo`, so the environment sets what the app boots into and the on-page toggle overrides it per browser. `?mode=live` pins it for a screenshot without touching the cookie.

**Consequences.**

The design is now in the product rather than in a folder. Each of the five screens is a file that can be opened, reviewed and changed on its own, and the mockup's six repetitions of one findings-row grid template became one CSS class.

Both presenters returning identical dataclasses is what makes this cheap rather than a second codebase: the templates cannot tell which mode produced the page, so "does live mode look right?" is answerable by eye against the demo render. The cost is that a new field must be filled in twice. That friction is the feature — a field only one presenter sets is a field the live page renders blank without anyone noticing.

The no-fallback rule is the load-bearing half. The tempting version of this feature quietly shows a demo figure when the live one is missing, and it produces a page that looks finished and is fiction. Every other rule in this project — the LLM never produces a number, every anomaly traces to a clause, engine functions are pure — exists to make the figures defensible. A frontend that invents one when the database is quiet would undo all of it at the last inch. Hence: absent data is *displayed* as absent, and the reason is named on screen.

What we gave up: two frontends drift, and they will. They are not kept in visual sync and are not meant to be. The mitigation is that they share the query layer, so they can drift in appearance but not in figures.

---

## ADR-019 — A payment answers the billing it followed

**Status:** Accepted (2026-08-16, Phase 6) · **Refines ADR-006**

**Context.** ADR-006 says to aggregate a client's calendar month and compare the total. Real payments do not respect calendar months, so the rule has always carried "±15 days of tolerance at the boundary" — and that phrase hides an assignment decision. A payment that lands inside two billings' windows has to go to exactly one of them, or a client who paid once is credited twice and a ghost invoice appears next to a surplus.

Two obvious rules both fail, in opposite directions:

* **Nearest billing date.** Billed on the 1st, paid on the 30th: the 30th is two days from *next* month's billing and twenty-nine from this one, so the money settles February and January reads as never billed.
* **Same calendar month only.** Billed on the 30th, paid on the 3rd: the payment lands in the next month and settles a billing four weeks ahead of it, leaving the invoice it was actually paying unmatched.

**Decision.** Candidates are the same client's billings in the same calendar month **or** within the tolerance either side. Among them, **a payment answers a billing that has already been issued**: the most recent billing on or before the payment date wins. Only a payment that precedes every candidate — a prepayment — attaches to the nearest future billing. Exact ties settle the older debt.

Each transaction lands in exactly one bucket. No transaction is ever counted twice.

**Consequences.** Both failing cases above come out right, and the rule is one sentence a user can be told: *money pays the last bill you sent*. What it gives up is the case of a client paying two months at once with a single transfer — that reads as one month settled and one ghost invoice. Phase 8's `check_split_payments` tool sees the whole window and is the right place to catch it, which is the same trade ADR-006 already made.

---

## ADR-020 — Attribution refuses rather than guesses

**Status:** Accepted (2026-08-16, Phase 6)

**Context.** Reconciliation needs to know whose payment a bank line is. The line says `REGAL ENT GROUP ACH INV-202502`; the client is *Regal Entertainment Group*. Fuzzy comparison of the normalised names scores that pair **62** — well below any sane threshold — because the abbreviation deletes most of the characters. Meanwhile a real statement also carries `BANK SVC FEE` and `INTEREST CREDIT`, which belong to nobody and will still score against *somebody*.

Lowering the threshold until the abbreviations pass is the move that ruins the product: at that point the bank fee matches a client too, and a wrong merge reconciles one client's money against another's contract. Every figure downstream is then confidently wrong, with a clause attached to prove it.

**Decision.** Two scoring paths, better of the two: `client_matcher.similarity` (punctuation- and suffix-blind) **or** a token-prefix abbreviation rule — every word in the description begins a word in the client's name, in order, covering at least two of them. Payment-rail words (`ACH`, `WIRE`, `PMT`, …) and reference numbers are stripped first: they say how money moved, never who sent it, and `REGAL ENT GROUP ACH` scores 62 while `REGAL ENT GROUP` scores 100.

Then two refusals. A row scoring below **85** is left unattributed. A row whose best client is within **6 points** of the runner-up is left unattributed too — *Northwind Design* and *Northwind Digital* on a line that says only `NORTHWIND` is a coin toss, and a coin toss with a confident face on it is worse than an admission.

Unattributed money is **counted and reported** (`RunSummary.unattributed`), never silently dropped and never quietly assigned.

**Consequences.** On the realistic scenario every one of the 48 client payments is attributed across four name variants each, and all three planted noise rows are correctly attributed to nobody. The cost is that a genuinely ambiguous client payment is skipped, which understates that client's collected revenue — visible as a shortfall rather than as a wrong client. Phase 8's agent, and the human confirmation step in `app/components/client_confirm.py`, are the places that resolve one.

---

## ADR-021 — A text-only filing is typeset into a PDF we generate, and labelled as such

**Status:** Accepted (2026-08-16, Phase 7) · **Resolves known issue #28** · **Extends ADR-005**

**Context.** ADR-013 made SEC EDGAR the primary contract source, and EDGAR serves **HTML**. `data_sourcing` writes it to disk as `.txt`. Phase 7's headline feature — click a finding, see the clause highlighted on the page — is built on PyMuPDF's `page.search_for()`, which needs a PDF. So the product's most demonstrable feature did not work on the product's own corpus, and known issue #28 had been carrying that as "unsolved and uncosted" since Phase 3.

Three options were open. **Accept page-level degradation permanently:** every computed finding shows a quote and no page, forever, and the clause viewer exists only for CUAD documents nobody's scenarios use. **Convert on the way into `data/corpus/`:** the conversion still has to happen, and now it happens once, invisibly, in a gitignored directory that has already vanished twice (known issues #33, #44). **Typeset on demand, from the text already stored on the document row.**

**Decision.** `pdf_renderer.typeset_pdf` lays the extracted text out as a PDF: fixed page size, one base-14 font, hard-wrapped lines, a page number in the footer, no HTML parsing and no reflow that depends on a library version. Two runs over the same text produce the same page breaks — which is load-bearing, because a clause stored as "page 4" has to still be on page 4 tomorrow. The result is cached by content hash under `data/cache/pdf/`, so an edited extraction produces a new entry rather than a stale page (the lesson of known issue #20).

**Every page carries the disclosure in three places**: printed in the PDF's own footer, in the Streamlit viewer's caption, and in the `web/` figure caption — *typeset by FinSight from the filing's text; the original is HTML, not a PDF*. `render_document_page` returns `is_typeset` alongside the image specifically so a caller cannot forget to say it.

**Consequences.**

Clause highlighting works on the real corpus: 20 of 20 clauses across three computed runs are now placed on a page, 18 exactly. The demo's strongest moment — *here is the sentence that proves you are owed $1,800* — is available on genuine SEC filings rather than only on the CUAD PDFs.

What we gave up, and must keep saying out loud: **a typeset page is not the document as filed.** Its line breaks, its pagination and its page numbers are ours. Anyone comparing our "page 61" against the filing on EDGAR will not find them the same, and a reader who assumes otherwise has been misled by us, not by the data. That is the whole reason the disclosure is printed into the PDF itself and not only into the UI — the image outlives the page it was rendered on.

This does not weaken ADR-005. A quote that cannot be found is still `failed`, still gets NULL coordinates, and still renders as a page with no box and a plain statement that we could not place it. Typesetting gives the locator something to search; it never invents a location.

---

## ADR-022 — Phase 8's false-positive proof lives in a synthetic fixture, not the shipped scenario

**Status:** Accepted (2026-08-17, Phase 8)

**Context.** `docs/implementation_plan.md`'s Phase 8 worked example is the verification agent flipping a name-variant false positive ("StarterLabs" vs "Starter Labs") to `false_positive` on the `realistic` scenario. Before writing any Phase 8 code, that example was traced against the actual codebase: `core.engine.reconciliation.attribute_transactions` (built in Phase 6, months after the plan's Phase 8 narrative was written) already does fuzzy client-name attribution — thefuzz, threshold 85 — at reconcile time. Every name variant `data_sourcing/scenario_builder.py` plants into the `realistic` scenario (`"VISIONHYDROGEN CORP WIRE"`, `"REGAL ENT GROUP ACH"`, and so on) is therefore already correctly attributed **before the agent ever runs**. There is no false positive left in that scenario's ground truth for Phase 8 to catch. The mechanical engine got smarter than the demo assumed, in a phase that shipped before this one.

Three options were open. **Extend `data_sourcing/scenario_builder.py`** with a new planted case the engine genuinely still gets wrong (e.g. a client paying two months in one transfer, known issue #57) — but `scenario_builder.py` and `data/scenarios/*/ground_truth.json` are cited by name, with exact figures, in Phase 6's `progress.md` entry, `docs/interfaces.md`, and `scripts/eval_engine.py`'s own definition of done (`easy` 7/$17,815.00, `realistic` 5/$22,500.00, `edge` 0/$0.00, all reproduced *exactly*). Touching it risks those numbers without re-running and re-documenting three separate places, for a phase that does not own that file. **Report the demo as no longer reproducible and stop there** — technically honest, but it abandons the one thing Phase 8's own definition of done asks to be shown working. **Build the agent to the full architecture regardless, and prove both halves a different way that touches neither the scenario file nor its measured ground truth.**

**Decision.** The third option. `scripts/eval_agent.py` runs two independent checks: Part 1 runs `verify_run` over the real `realistic` run's genuine (already-attributed, still-genuine) anomalies, live against the database — proof the agent handles real leaks correctly without inventing false positives on data that has none. Part 2 builds a small fixture with the real engine functions (`core.engine.pipeline.persist_rules` / `compute_run`, not `scenario_builder`) — one contract, one billing, one payment recorded under a description too garbled for fuzzy matching to attribute (`"REF 84X2Q AUTOPAY SETTLEMENT"` against `"Fixture Co"`) — a genuine `ghost_invoice` by construction, verified to reproduce before the agent is asked to touch it. `verify_run` is then asked to explain it, live against the real model. Neither part edits a file this phase does not own.

**Consequences.** The proof is honest about what changed: `docs/progress.md`'s Phase 8 entry says outright that the plan's own worked example no longer holds, and why, rather than letting a reader assume the shipped scenario still demonstrates it. The synthetic fixture is deliberately a *different* false-positive shape (an attribution miss from a garbled description, not a name variant two spaces apart) — chosen because it is the shape today's `search_bank_transactions` tool can actually resolve, not because it is the closest available stand-in for the original narrative. Known issue #57's cross-month case remains genuinely open; `check_split_payments`, as scoped by `interfaces.md`'s own signature (combinations that *sum to* a target), cannot resolve a single transaction that is a *multiple* of one — that is now recorded plainly rather than implied solved by this phase existing.

---

## ADR-023 — Modal is a third peer inference host, not a departure from ADR-011

**Status:** Accepted (2026-08-17, recorded retroactively by the post-Phase-8 audit) · **Amends [ADR-016](#adr-016--colab-and-kaggle-are-peers-not-primary-and-backup)** — there are three peers now, not two.

**Context.** This ADR is written **after** the code it describes. `training/serve_modal.py`, a `modal` provider in `core/ai/endpoints.py`, `MODAL_BASE_URL`, `USE_MODAL`, and a Modal-first `fallback()` order were all built and working, documented in `README.md` (22 mentions) and `.env.example` — and mentioned in **no memory file whatsoever**: not `progress.md`, not `interfaces.md`, not `state.json`, not `todo.md`, not `CLAUDE.md`. `CLAUDE.md` still stated flatly that there are two hosts and that they are peers. A fresh session reading the memory files would have contradicted the running code on its first suggestion, which is precisely the cost the ritual in `CLAUDE.md` exists to avoid. Recording it late is the fix; the lesson is that the code shipped without the five-minute end-of-phase step.

The forcing constraint the code was solving is real and already recorded as known issue #6: a notebook endpoint's URL rotates on every restart, the host idles out, a cold start is ~8 minutes of `pip install` plus a weight download, and a dead session takes the whole app down. ADR-016 made Colab and Kaggle peers so that one could cover the other, but they share every one of those properties — two hosts with the same failure mode are not a mitigation, they are the same bet twice.

**Decision.** Modal is a **third peer**, configured exactly like the other two (`MODAL_BASE_URL` alongside `COLAB_TUNNEL_URL` and `KAGGLE_TUNNEL_URL`, selected by `LLM_PROVIDER` or the in-app radio, resolved at call time through the same `data/endpoint_override.json` layer). It serves the same open-source Qwen 2.5 3B under the same vLLM, behind the same OpenAI-compatible routes, with the same `LLM_API_KEY` header and the same `LLM_MODEL` name. Two things make it *not* merely a fourth entry in a list:

1. **`endpoints.fallback()` tries Modal first**, ahead of the notebooks. Failover runs at the moment the active host has already failed, and the peer most likely to answer is the one whose address is stable. It costs money per call, which is the right thing to spend exactly then.
2. **`USE_MODAL=true` is a separate switch from `LLM_FAILOVER`**, resolved *above* `LLM_PROVIDER` in `endpoints.active_provider()`. `LLM_FAILOVER` only reacts after something breaks; `USE_MODAL` is the "this is a live demo, go straight to the paid host" decision, made before anything has broken.

**This is not a violation of ADR-011.** ADR-011 forbids calling a third-party *model* API — sending our data to someone else's weights and buying their inference. Modal rents hardware: the weights are the same open-source checkpoint we serve from Colab, downloaded by our own image build, running under vLLM configured by our own file. Swapping a free T4 for a rented L4 changes who owns the GPU, not who owns the model, and Phase 11's base-vs-tuned comparison stays one variable (`LLM_MODEL`) because Phase 10's adapter loads here the same way it loads in the notebook. The distinction that matters for the report's self-hosting claim is *whose weights*, not *whose electricity*.

**Consequences (ADR-023).** The demo stops depending on a URL that rotates, which is the single largest operational risk in the project (#6) and one the two notebook peers could not reduce. Weights are baked into the Modal image at build time, so a cold start loads 3B onto a card instead of downloading 6 GB, and `vllm==0.27.1` is **pinned** — the unpinned install is what broke Colab's preinstalled `torchaudio` (#50). What we give up: it is the first component that costs money per call, billed per second of GPU time while a request is in flight, with `scaledown_window` trading idle cost against cold-start latency — so an idle deployment is free but a quiet period is paid for in latency. It also adds a fourth account to the list in known issue #7, and a `modal secret create finsight-llm LLM_API_KEY=...` step that has no equivalent in the notebook flow. **Modal has not been deployed or measured from this repo** — the file is written and the client-side plumbing is exercised by `verify_llm_stack.py`'s stub server, but no `modal deploy` has run, so its cold-start and per-call figures are unknown and must not be quoted in the report until they are measured.

---

## ADR-024 — The Decision Engine asks the user for expenses rather than inventing a surplus

**Status:** Accepted (2026-08-17, Phase 9)

**Context.** `implementation_plan.md`'s Phase 9 computes `current_surplus = avg_revenue - avg_expenses`. FinSight can compute the first term: `actual_transactions` holds real client receipts and `revenue_by_month` already aggregates them. **It has no second term.** No table in the schema holds operating costs — `actual_transactions.source_type` is `invoice | bank`, amounts are unsigned, and every row is money *arriving*. Payroll, rent and software have never entered the system, because nothing in the product's pipeline reads them. The plan's own frontend amendment flags this and asks for a deliberate decision rather than a workaround.

This matters more than a missing column usually would, because the pitch's headline promise — *"can I afford a $5,000/month hire?"* — is a question about surplus, not revenue. Answering it requires a number the database does not have.

Three options were open. **Assume an expense figure** (a percentage of revenue, an industry ratio) — rejected outright: it manufactures the one number the entire verdict turns on, and unlike a mis-drawn clause box (#58, found by looking at a rendered page) a wrong surplus is invisible. Nobody can see that $4,500 should have been $1,200. It is the exact failure mode ADR-008's "the UI reads only the database" and the LLM-does-no-arithmetic rule exist to prevent, arriving through a different door. **Add an expenses table plus an upload and column-mapping path** — correct long-term, and genuinely the right answer eventually, but it is a phase of work (13th table, upload zone, ADR-010 mapping flow, seed data, `test_schema.py` update) and it is not in Phase 9's owner split; taking it on would delay the verdict Phase 9 exists to deliver. **Ask the user.**

**Decision.** The user supplies monthly running costs, as one number, on the Streamlit page. Nothing is stored and no schema changes. Consequences of that choice, all deliberate:

1. **`monthly_expenses` is `float | None`, and `None` means unknown — never `0.0`.** `0.0` would assert the business breaks exactly even, a completely different and false claim. `CashFlowBaseline.monthly_surplus` is therefore also `None` whenever expenses are unknown, and `.basis` reports `"revenue"` rather than `"surplus"`.
2. **With no expense figure, the engine refuses a Yes/No.** `verdict` is `"unknown"` and `cost_share_of_revenue` is reported instead — the commitment as a share of corrected monthly revenue, which is true, useful, and not an affordability claim. The page says so in as many words.
3. **Every figure on the page is therefore either computed from the database or typed by the user.** Nothing is assumed. That property is what makes the verdict defensible, and it is the same standard ADR-014 applied to redacted contract values (seeded deterministic Python, never a model's guess).
4. **`web/` cannot ask the question at all** and does not pretend to. It has no POST route because it writes nothing (ADR-018), and a verdict needs both a question and an expense figure — two things only a form can collect. Its Decision page shows the real engine-computed working and names the Streamlit app as the place to get an answer.

**Consequences.** The Decision Engine's headline claim is now conditional on one user-supplied number, which must be disclosed in the report: FinSight computes what you are owed and what you earn, and *you* tell it what you spend. In exchange, no figure it prints is invented. The gap is honest and visible rather than papered over, and closing it properly — an expenses source — is a well-defined piece of future work rather than a hidden assumption. A second, smaller consequence: because the surplus depends on an input rather than stored data, two people asking the same question of the same run can get different verdicts. That is correct (they have different cost bases) but it means a verdict is not reproducible from `run_id` alone, so nothing persists one.

---

## ADR-025 — `web/` writes, starting with uploads, over one shared ingest core

**Status:** Accepted (2026-08-19) · **Partially supersedes ADR-018**

**Context.** ADR-018 made `web/` read-only, and that was the right call while it was a rendering of a design over a database somebody else filled. It stopped being right the moment `web/` became the deployed demo: the first thing a visitor to a revenue-integrity tool wants to do is give it a contract, and the Upload screen's honest answer was "open a different application on a different port". A tool whose first step happens somewhere else is not a tool a stranger can try.

The obvious objection is that the uploader already exists in `app/` and rewriting it is duplication. Measured before deciding: it is not, because almost none of the uploader is Streamlit. `core/storage/files.py`, `core/extraction/document_router.py` and `core/extraction/csv_parser.py` import Streamlit zero times between them. What lived inside `app/components/file_uploader.py` was seventeen `st.` calls — all presentation — wrapped around a sequence: save, record, read, and for a `.csv` hold at `pending` until a human confirms its columns. **The sequence was the thing worth sharing; the widgets were not.**

**Decision.** Three parts.

1. **The sequence moves to `core/ingest.py`** — `ingest_files`, `extract_upload`, `actuals_category`, `propose_mapping`, `apply_mapping` — importing no framework and raising at no caller. Both frontends call it. `app/components/file_uploader.py` and `app/components/column_mapper.py` keep only their Streamlit drawing, and shrank accordingly. This is the part that matters: two implementations of "what does `extraction_status = 'complete'` mean" is the divergence a single core exists to prevent, and it would have been a *silent* divergence, since both would look right in isolation.
2. **`web/` gains `web/routers/uploads.py`** — `POST /upload`, `GET|POST /upload/{id}/columns` — and the Upload screen becomes a real form. Contracts, PDF and image invoices finish on the POST. A `.csv` lands at `pending` and the redirect goes straight to its column mapper, because a statement recorded but not confirmed is money the run does not know it has.
3. **ADR-010 is honoured identically in both frontends**, because neither owns it: the proposal and the parse are `core.ingest`'s, and only the three dropdowns differ.

**Consequences, in the order they will bite someone.**

* **The read cache now has an owner's duty.** `web/cache.py` was safe because nothing wrote; it is now safe because the write path calls `web.cache.clear()` after its session commits. That is written at the top of both modules. **A second write path that forgets it will look like a broken button for `WEB_CACHE_SECONDS`** — 300 by default, which is a very long time to stare at a page that did not change.
* **Demo mode still cannot write, and says so.** There is no database behind it, and a demo that half-accepted a file is the borrowed-figure failure ADR-018 was written to prevent. The POST is refused with a message naming the toggle.
* **Uploading is not reconciling.** `web/` can now take your files and read their text. Turning a contract into billing *rules* needs the model endpoint, and turning those into findings needs a Reconcile action that still exists only in `app/`. The Upload screen says exactly that rather than implying the round trip is finished (known issue #56 narrows but does not close).
* **A file input the user left empty is not an empty list.** Browsers post a part with `filename=""` for it, which Starlette parses as a string field, which makes a `list[UploadFile]` parameter fail validation with a raw 422 JSON page. The ordinary case — "contracts today, no statement" — would have hit it. The route reads the multipart form itself and keeps only genuine files. Found by testing a partial submission, not by reading the code.
