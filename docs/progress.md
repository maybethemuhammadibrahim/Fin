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

**Current phase:** 0 — done
**Last entry:** Docs consolidation (2026-08-08)

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

<!-- ================================================================= -->
<!-- APPEND NEW PHASE ENTRIES ABOVE THIS LINE.                         -->
<!-- ================================================================= -->

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
