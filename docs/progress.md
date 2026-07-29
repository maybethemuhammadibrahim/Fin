# PROGRESS LOG — What Has Actually Been Built

> **Append-only.** Never delete or rewrite a past entry. If something was later changed, add a new entry saying so.
> **Written at the end of every phase, by the person who did the work.**
> **This is the file an AI assistant reads to know what already exists.** If it isn't here, the assistant will assume it doesn't exist and rebuild it.

**Current phase:** 0 — done
**Last entry:** Phase 0 (2026-07-29)

---

## How to write an entry

Copy the template below. Keep it factual and short. The two things that matter most are **the file paths** and **the "known gaps"** line — those are what stop an assistant from rebuilding something or from assuming something works that doesn't.

```markdown
## Phase N — <name>
**Completed:** YYYY-MM-DD · **Owners:** A / B

### Built by A
- `path/to/file.py` — one line on what it does
- ...

### Built by B
- `path/to/file.py` — one line on what it does
- ...

### New interfaces added to interfaces.md
- `module.function(args) -> Return`

### Decisions recorded in decisions.md
- ADR-00N: <title>

### Known gaps / deliberately deferred
- <thing that does not work yet, and which phase handles it>

### How to verify this phase works
- <the exact command or click-path that proves it>
```

---

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

### Decisions recorded in decisions.md
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

---

## Worked example — what a good entry looks like

*(This is illustrative only. It describes work that has NOT been done. Delete this section once Phase 1 is real.)*

```markdown
## Phase 1 — Cloud Database
**Completed:** 2026-08-04 · **Owners:** A / B

### Built by A
- `core/db/models.py` — all 11 SQLAlchemy ORM models incl. new `runs` table;
  `clause_references.source_bbox` nullable, `locate_method` added
- `core/db/database.py` — engine + session factory; reads DATABASE_URL,
  falls back to sqlite:///data/finsight.db
- `scripts/init_db.py` — creates all tables against Supabase

### Built by B
- `core/db/queries.py` — 9 read helpers (get_run, list_anomalies,
  get_clause_reference, get_summary_stats, ...)
- `app/pages/9_db_health.py` — dev-only page: connection status + row counts

### New interfaces added to interfaces.md
- queries.list_anomalies(run_id, status=None) -> list[AnomalyRow]
- queries.get_summary_stats(run_id) -> SummaryStats

### Decisions recorded in decisions.md
- ADR-003: Supabase over Neon — table editor UI is worth more to us than
  branching, and both free tiers cover our volume

### Known gaps / deliberately deferred
- All tables empty. Seeding is Phase 2 [A].
- No migrations tool (Alembic). Schema changes = drop and recreate until Phase 9.

### How to verify this phase works
- `python scripts/init_db.py` then open the Supabase table editor: 11 tables
- `streamlit run app/main.py` -> DB Health page shows "connected", all counts 0
```
