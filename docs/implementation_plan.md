# FinSight — Complete Architecture & Implementation Plan (v2, Cloud)

> **Version 2 changes:** cloud-first (no GPU required), online-sourced data, top-down build order, split across two developers, with an AI memory system. Every change is justified in **`changes.md`** — read that once before starting.

---

## What Is FinSight?

A web tool for small B2B service businesses that **automatically reads their contracts and compares them against their actual invoices/bank statements** to find money they forgot to collect — then helps them make smarter financial decisions with the recovered revenue factored in.

---

## The 10,000-Foot View (Full Pipeline)

```mermaid
flowchart TD
    A["👤 User uploads files\n(Contracts + Invoices/Bank Statements)"] --> B["📄 Document Type Detection\n(Is it scanned? Is it CSV?)"]
    B --> C["🔍 Text Extraction\n(pdfplumber for text PDFs, cloud OCR for scans, pandas for CSV)"]
    C --> D["🧠 AI Extraction\n(Hosted LLM reads contract text → structured rules + verbatim clause quotes)"]
    D --> D2["📍 Clause Grounding\n(PyMuPDF text-search finds the real bbox of each quote)"]
    D2 --> E["🏗️ Expected Timeline\n(Pure Python math builds what SHOULD have been billed)"]
    E --> F["⚖️ Reconciliation Engine\n(Python compares Expected vs Actual, client-month aggregate)"]
    F --> G["🕵️ AI Verification Agent\n(LangGraph agent double-checks for false alarms)"]
    G --> H["📊 Dashboard\n(Anomaly table + clickable contract clauses)"]
    H --> I["💬 Decision Engine\n(User asks a question, gets a Yes/No backed by data)"]
```

**One new box versus v1: `📍 Clause Grounding`.** In v1 the model was asked to output pixel coordinates. It cannot — a model reading text has no idea where anything sits on a page. Now the model returns the clause **verbatim**, and code finds where it lives. See ADR-005.

**The load-bearing principle of the whole design:** the LLM only turns prose into structured data. It never does arithmetic, never decides what counts as an anomaly, and never produces a number the user sees. All money math is deterministic Python. This is what makes your results defensible when someone asks how you know the number is right.

---

## The Cloud Stack (Nothing Runs On Your GPU)

| Layer | Service | Free? | Who sets it up |
|-------|---------|-------|----------------|
| App hosting | Streamlit Community Cloud | ✅ | B |
| Database | Supabase Postgres | ✅ free tier | A |
| File storage | Supabase Storage | ✅ free tier | A |
| LLM inference | Google AI Studio (Gemini) primary; Groq / OpenRouter as backups | ✅ rate-limited | B |
| OCR (optional) | Gemini vision, or Surya batch-run in Colab | ✅ | B |
| Fine-tuning | Google Colab **or** Kaggle free T4 | ✅ | A + B |
| Model hosting (fine-tuned) | HF Hub adapter + Colab FastAPI tunnel | ✅ | B |
| Version control | GitHub | ✅ | A |

> [!IMPORTANT]
> **Configure two providers from day one.** Free tiers change quotas, and one dead key on demo day should be a one-line env change, not a crisis. Because most of these expose OpenAI-compatible endpoints, `llm_client.py` handles all of them with one code path.

---

## How To Use This Plan

Each of the 12 phases below contains:

1. **🎯 Goal** — one sentence
2. **🤖 Phase Prompt** — copy-paste this into your AI assistant *before writing any code*
3. **👤 User A tasks** and **👤 User B tasks** — separate files, no overlap
4. **📐 Architecture detail** — the how, at the depth you need to actually build it
5. **✅ Definition of done** — the exact check that proves the phase works
6. **🧠 Memory update** — what to write down before moving on

### The Phase Prompt template

Every phase's prompt is generated from this shape. Its first instruction is always the memory summary.

```
Before writing ANY code for Phase N:

1. Read these files in full:
   - memory/project_context.md
   - memory/progress.md
   - memory/interfaces.md
   - memory/decisions.md
   - memory/state.json

2. Print a numbered summary of every feature already implemented.
   For each: phase number, owner (A/B), file path, current status.

3. State which interfaces from memory/interfaces.md this phase will
   CONSUME, and which new ones it will ADD.

4. List anything in memory that CONFLICTS with this phase's goal.
   If you find a conflict, STOP and ask me before proceeding.

Only after printing that summary, begin Phase N.
```

**Why the summary step is not busywork.** Reading a file and *restating* it forces the model to actually condition on it instead of skimming. It also gives you a 10-second check that the assistant is oriented before it starts generating files — if the summary is thin or wrong, your memory files are thin or wrong, and you want to know that *before* code lands on a bad foundation.

---

## Build Order At A Glance

```mermaid
gantt
    title FinSight — 12 Phases (top-down: shell first, intelligence second)
    dateFormat X
    axisFormat %s
    section Foundation
    P0 Setup & Accounts       :0, 1
    P1 Cloud Database         :1, 2
    P2 Frontend Shell         :2, 4
    section Data
    P3 Online Data Sourcing   :2, 4
    P4 Text Extraction        :4, 6
    section Intelligence
    P5 LLM Rule Extraction    :6, 8
    P6 Timeline + Reconcile   :8, 10
    P7 Clause Viewer          :10, 11
    P8 Verification Agent     :11, 13
    P9 Decision Engine        :11, 13
    section Capstone
    P10 Fine-Tuning           :13, 16
    P11 Eval & Deploy         :16, 18
```

| # | Phase | User A | User B | Visible result |
|---|-------|--------|--------|----------------|
| 0 | Foundations | Repo, deps, memory files | Cloud accounts, config loader | `streamlit run` shows "Hello" |
| 1 | Cloud Database | ORM models, init script | Query helpers, DB health page | 11 tables live in Supabase |
| 2 | **Frontend Shell** | Seed script writing real rows | All pages, all components | **A complete-looking product** |
| 3 | Data Sourcing | Fetch CUAD + EDGAR | Scenario builder + ground truth | Real contracts on disk |
| 4 | Text Extraction | PDF router + text path | CSV parser + cloud OCR | Upload → text in DB |
| 5 | LLM Extraction | Schemas, extractor, clause locator | `llm_client`, prompt, caching | Contract → structured rules |
| 6 | Timeline + Reconcile | Timeline generator | Reconciliation + classifier | Real anomalies replace seeds |
| 7 | Clause Viewer | Locator hardening | PDF render + drill-down UI | Click a row → see the clause |
| 8 | Verification Agent | Agent tools (DB-backed) | LangGraph loop + UI badges | Agent kills a false positive |
| 9 | Decision Engine | Cash-flow math | Question parser + chart | Page 2 answers a question |
| 10 | Fine-Tuning | Training pairs from CUAD | Colab QLoRA + tunnel serving | A model you trained |
| 11 | Eval & Deploy | Eval harness + metrics | Deploy + README + demo script | Public URL |

---

## Complete Directory Structure (with ownership)

Every file is tagged. **If a file isn't yours, don't edit it — ask.**

```
finsight/
│
├── memory/                                  # 🧠 AI MEMORY — both maintain
│   ├── README.md                            # [A] how to use the memory system
│   ├── project_context.md                   # [A] what & why (stable)
│   ├── progress.md                          # [A+B] append-only build log
│   ├── interfaces.md                        # [A+B] the A↔B contract
│   ├── decisions.md                         # [A+B] ADRs
│   └── state.json                           # [A+B] machine-readable status
│
├── app/                                     # 🎨 USER B OWNS THIS ENTIRE FOLDER
│   ├── main.py                              # [B] Streamlit entry, run selector
│   ├── pages/
│   │   ├── 1_integrity_engine.py            # [B] Page 1: upload & detect
│   │   ├── 2_decision_engine.py             # [B] Page 2: question & verdict
│   │   └── 9_db_health.py                   # [B] dev-only diagnostics
│   ├── components/
│   │   ├── file_uploader.py                 # [B] dual upload zones + toggle
│   │   ├── column_mapper.py                 # [B] CSV header confirmation UI
│   │   ├── client_confirm.py                # [B] "we found 4 clients" step
│   │   ├── summary_cards.py                 # [B] the 4 metric cards
│   │   ├── anomaly_table.py                 # [B] anomaly table + row click
│   │   ├── clause_viewer.py                 # [B] highlighted PDF page
│   │   └── cash_flow_chart.py               # [B] Plotly projection
│   └── state.py                             # [B] st.session_state helpers
│
├── core/
│   ├── config.py                            # [B] env vars, provider selection
│   │
│   ├── extraction/
│   │   ├── document_router.py               # [A] detect type → route
│   │   ├── pdf_extractor.py                 # [A] pdfplumber text + tables
│   │   ├── clause_locator.py                # [A] ⭐ text-search → real bbox
│   │   ├── csv_parser.py                    # [B] pandas + mapping
│   │   ├── ocr_cloud.py                     # [B] Gemini-vision OCR fallback
│   │   └── pdf_renderer.py                  # [B] render page w/ highlight
│   │
│   ├── ai/
│   │   ├── llm_client.py                    # [B] ⭐ ONE client, many providers
│   │   ├── prompts.py                       # [B] all prompt templates
│   │   ├── cache.py                         # [B] hash→response disk cache
│   │   ├── schemas.py                       # [A] Pydantic contract schemas
│   │   ├── contract_extractor.py            # [A] text → ContractRules
│   │   ├── client_matcher.py                # [A] fuzzy client grouping
│   │   └── decision_analyzer.py             # [B] question parse + explain
│   │
│   ├── engine/
│   │   ├── timeline_generator.py            # [A] ⭐ pure math, no AI
│   │   ├── reconciliation.py                # [B] expected vs actual
│   │   ├── anomaly_classifier.py            # [B] the 4 types
│   │   └── cashflow.py                      # [A] baseline + scenario math
│   │
│   ├── agents/
│   │   ├── tools.py                         # [A] 4 DB-backed agent tools
│   │   └── verification_agent.py            # [B] LangGraph ReAct loop
│   │
│   ├── storage/
│   │   └── files.py                         # [A] Supabase Storage up/download
│   │
│   └── db/
│       ├── models.py                        # [A] SQLAlchemy ORM
│       ├── database.py                      # [A] engine + session
│       └── queries.py                       # [B] read helpers for the UI
│
├── data_sourcing/                           # 🌐 ONLINE DATA — no local generation
│   ├── fetch_contracts.py                   # [A] CUAD + SEC EDGAR downloader
│   ├── filter_contracts.py                  # [A] keep only service/retainer docs
│   ├── fetch_invoices.py                    # [B] HF invoice/receipt datasets
│   └── scenario_builder.py                  # [B] ⭐ derive actuals + ground truth
│
├── training/
│   ├── build_pairs.py                       # [A] contracts → instruction pairs
│   ├── finetune_colab.ipynb                 # [B] Unsloth QLoRA notebook
│   ├── serve_finetuned.py                   # [B] Colab FastAPI + tunnel
│   ├── evaluate.py                          # [A] baseline vs fine-tuned
│   └── data/
│       ├── train.jsonl                      # [A] generated, gitignored
│       ├── val.jsonl                        # [A]
│       └── eval_set.jsonl                   # [A] held-out, COMMITTED
│
├── scripts/
│   ├── init_db.py                           # [A] create all tables
│   ├── seed_demo.py                         # [A] scenario → DB rows
│   ├── reset_run.py                         # [A] wipe one run, keep others
│   └── memory_digest.py                     # [B] print compact memory summary
│
├── tests/
│   ├── test_timeline.py                     # [A] the most important tests
│   ├── test_reconciliation.py               # [B]
│   ├── test_clause_locator.py               # [A]
│   └── fixtures/                            # [A] tiny known-answer inputs
│
├── data/                                    # gitignored
│   ├── corpus/contracts/                    # sourced PDFs
│   ├── corpus/invoices/
│   ├── scenarios/                           # built scenarios + ground_truth
│   └── cache/                               # LLM response cache
│
├── docs/
│   ├── demo_script.md                       # [B] the 5-minute walkthrough
│   └── report_notes.md                      # [A+B] capstone writing material
│
├── .env.example                             # [B] every var, no real values
├── .gitignore                               # [A]
├── requirements.txt                         # [A]
└── README.md                                # [B]
```

**Ownership rules, restated because they matter:**
1. One owner per file. Need a change elsewhere? Ask.
2. `memory/interfaces.md` gets the signature **before** the implementation exists.
3. Both people work every phase — nobody waits.

---

# PHASE 0 — Foundations & Accounts

## 🎯 Goal
A repo both of you can run, with every cloud account created and every key working. No features.

## 🤖 Phase Prompt

```
Before writing ANY code for Phase 0:

1. Read memory/project_context.md in full. (progress.md, interfaces.md and
   decisions.md are still templates at this point — read them anyway so you
   know their structure.)

2. Print a numbered summary of what the project is, the confirmed tech stack,
   and the A/B ownership split. State that no features are implemented yet.

3. State which new interfaces Phase 0 will ADD to memory/interfaces.md.

4. List anything in memory/project_context.md you find ambiguous or
   contradictory. STOP and ask me before proceeding if you find any.

Only then begin Phase 0: create the repo skeleton, dependency list,
configuration loader, and secrets template.

Owner split — A: repo/deps/gitignore/memory files. B: config.py, .env.example,
cloud account setup, memory_digest.py.
Do NOT write any application logic, database models, or UI in this phase.

Definition of done: both of us can clone, install, and run `streamlit run
app/main.py` to see a page that prints the resolved config with secrets masked.

After finishing, append a Phase 0 entry to memory/progress.md and update
memory/state.json.
```

## 👤 User A — tasks

1. Create the GitHub repo. Add User B as a collaborator.
2. Create the full directory skeleton above (empty files with a one-line docstring each — this alone prevents half your future merge conflicts, because the tree exists before either of you starts creating files ad hoc).
3. `requirements.txt`:

```txt
streamlit>=1.40
sqlalchemy>=2.0
psycopg2-binary
pandas
pdfplumber
pymupdf
pydantic>=2.0
python-dotenv
requests
thefuzz[speedup]
plotly
langgraph
langchain-core
datasets            # HuggingFace, for sourcing corpora
supabase            # storage client
pytest
```

4. `.gitignore` — `data/`, `.env`, `__pycache__/`, `*.db`, `.streamlit/secrets.toml`, `training/data/*.jsonl` (except `eval_set.jsonl`)
5. Copy the five `memory/` files into the repo. Commit them **first**, before any code.

## 👤 User B — tasks

1. **Create the accounts** (all free, ~20 minutes total):
   - Supabase → new project → copy the Postgres connection string and the anon key
   - Google AI Studio → API key (primary LLM)
   - Groq → API key (backup LLM)
   - HuggingFace → account + read token (for datasets in Phase 3)
   - Streamlit Community Cloud → sign in with GitHub

2. `.env.example` — every variable, no real values:

```bash
# ---- Database ----
DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres
SUPABASE_URL=https://[REF].supabase.co
SUPABASE_KEY=

# ---- LLM (ADR-002: swap provider with ONE variable) ----
LLM_PROVIDER=gemini            # gemini | groq | openrouter | finetuned_tunnel
GEMINI_API_KEY=
GROQ_API_KEY=
OPENROUTER_API_KEY=
FINETUNED_TUNNEL_URL=          # filled in Phase 10
LLM_MODEL=gemini-2.5-flash

# ---- Data sourcing ----
HF_TOKEN=

# ---- Behaviour ----
LLM_CACHE_ENABLED=true
LOG_LEVEL=INFO
```

3. `core/config.py` — loads `.env` locally and `st.secrets` when deployed, exposes one `settings` object, and **fails loudly at startup** with a readable message if a required key is missing. A beginner debugging a silent `None` API key loses an hour; a startup error that names the missing variable costs thirty seconds.

4. `app/main.py` — a placeholder page rendering the resolved config with every secret masked to `sk-...abcd`.

5. `scripts/memory_digest.py` — prints the compact summary described in `memory/README.md`.

## ✅ Definition of done
Both of you can clone, `pip install -r requirements.txt`, copy `.env.example` → `.env`, fill it, and run `streamlit run app/main.py` to see a config page with all keys marked ✅ present.

## 🧠 Memory update
Append Phase 0 to `progress.md`. Add ADR-001 through ADR-010 to `decisions.md` (they're pre-written — confirm you both agree with each before committing; if you disagree with one, that's a real conversation to have now rather than in week five). Set `state.json` phase 0 → `done`.

---

# PHASE 1 — Cloud Database

## 🎯 Goal
The complete schema exists in Supabase. Every table your UI will ever need, live and empty.

## 🤖 Phase Prompt

```
Before writing ANY code for Phase 1:

1. Read in full: memory/project_context.md, memory/progress.md,
   memory/interfaces.md, memory/decisions.md, memory/state.json.

2. Print a numbered summary of every feature already implemented.
   For each: phase number, owner (A/B), file path, current status.

3. State which interfaces from memory/interfaces.md this phase will CONSUME
   and which it will ADD.

4. List anything in memory that CONFLICTS with building the database schema.
   Pay particular attention to ADR-003 (Supabase over SQLite) and ADR-005
   (bbox nullability). STOP and ask me if you find a conflict.

Only then begin Phase 1: implement the full SQLAlchemy schema and query layer.

Owner split — A: core/db/models.py, core/db/database.py, scripts/init_db.py.
B: core/db/queries.py, app/pages/9_db_health.py.
A must NOT write query helpers. B must NOT edit models.py.

Constraints:
- clause_references.source_page and .source_bbox MUST be nullable (ADR-005)
- every run-scoped table carries run_id
- no Alembic yet; schema changes are drop-and-recreate until Phase 9

Definition of done: `python scripts/init_db.py` creates all tables in Supabase,
visible in the table editor; the DB Health page connects and shows 0 rows each.

After finishing, append a Phase 1 entry to memory/progress.md, mark the new
interfaces ✅ in memory/interfaces.md, and update memory/state.json.
```

## 📐 Database Schema

```mermaid
erDiagram
    runs {
        int id PK
        string label
        string llm_provider
        string model_name
        datetime created_at
    }

    documents {
        int id PK
        int run_id FK
        string filename
        string file_type
        string category
        string storage_url
        string extraction_status
        string error_message
        datetime uploaded_at
    }

    clients {
        int id PK
        int run_id FK
        string name
        string normalized_name
    }

    contract_rules {
        int id PK
        int client_id FK
        int document_id FK
        float base_amount
        string currency
        string billing_frequency
        date contract_start
        date contract_end
        string payment_terms
        json raw_extraction
    }

    clause_references {
        int id PK
        int contract_rule_id FK
        int document_id FK
        string clause_type
        string clause_text
        int source_page
        json source_bbox
        string locate_method
    }

    price_escalations {
        int id PK
        int contract_rule_id FK
        int clause_reference_id FK
        float percentage
        int after_months
    }

    discounts {
        int id PK
        int contract_rule_id FK
        int clause_reference_id FK
        float percentage
        int duration_months
    }

    expected_timeline {
        int id PK
        int run_id FK
        int client_id FK
        int contract_rule_id FK
        date billing_date
        float expected_amount
        string payment_type
        bool applied_escalation
        float applied_discount_pct
        string notes
    }

    actual_transactions {
        int id PK
        int run_id FK
        int document_id FK
        int client_id FK
        date transaction_date
        float amount
        string description
        string source_type
    }

    anomalies {
        int id PK
        int run_id FK
        int client_id FK
        int expected_timeline_id FK
        int actual_transaction_id FK
        int clause_reference_id FK
        string anomaly_type
        float expected_amount
        float actual_amount
        float gap
        float confidence_score
        string status
        string agent_reasoning
        json agent_tool_calls
        datetime verified_at
    }

    column_mappings {
        int id PK
        string header_signature
        json mapping
        datetime confirmed_at
    }

    runs ||--o{ documents : contains
    runs ||--o{ clients : contains
    runs ||--o{ anomalies : contains
    clients ||--o{ contract_rules : has
    documents ||--o{ contract_rules : sourced_from
    contract_rules ||--o{ clause_references : contains
    contract_rules ||--o{ price_escalations : has
    contract_rules ||--o{ discounts : has
    contract_rules ||--o{ expected_timeline : generates
    clients ||--o{ expected_timeline : for
    clients ||--o{ actual_transactions : from
    documents ||--o{ actual_transactions : sourced_from
    expected_timeline ||--o{ anomalies : compared_in
    clause_references ||--o{ anomalies : references
```

**What changed from v1 and why:**

| Change | Reason |
|--------|--------|
| New `runs` table, `run_id` everywhere | Re-run a demo without wiping the DB; compare baseline vs fine-tuned side by side (Phase 11 needs this) |
| `source_page` / `source_bbox` nullable | ADR-005: clause grounding can legitimately fail, and the app must degrade to a page-level view rather than crash |
| New `locate_method` | Enables the clause-grounding-rate metric |
| New `documents.storage_url` | Files live in Supabase Storage, not on a laptop |
| New `extraction_status` + `error_message` | Failures become visible in the UI instead of vanishing |
| `anomalies`: `confidence_score`, `agent_tool_calls`, `verified_at` | Agent output was under-specified in v1; also needed by the eval harness |
| New `column_mappings` | ADR-010: remember confirmed CSV headers |

## 👤 User A — tasks
- `core/db/models.py` — all 12 models above
- `core/db/database.py` — engine + `get_session()`; reads `DATABASE_URL`, falls back to `sqlite:///data/finsight.db` so you can still work offline
- `scripts/init_db.py` — `Base.metadata.create_all()`
- `scripts/reset_run.py` — delete one run's rows, leave the rest

## 👤 User B — tasks
- `core/db/queries.py` — the read helpers listed in `interfaces.md`
- `app/pages/9_db_health.py` — connection status, row counts per table, active run selector

**Note the split:** A shapes the data, B reads it. Neither blocks — B writes queries against A's model *names*, which are already in `interfaces.md` before A finishes.

## ✅ Definition of done
`python scripts/init_db.py` → open the Supabase table editor → 12 tables. DB Health page shows "connected" and 0 rows.

---

# PHASE 2 — Frontend Shell (The Top-Down Moment)

## 🎯 Goal
**The entire application, visually complete, reading real database rows.** No AI anywhere. This is the phase that makes the project feel real.

> [!IMPORTANT]
> **The one rule that makes top-down work:** the UI reads **only** the database — never a hardcoded Python dict. Seeded rows are real rows in real tables. That's why Phase 6 won't need to "connect" the reconciliation engine to the UI: it will just start writing to the `anomalies` table the UI has been reading since week one. Integration becomes continuous instead of a cliff at the end.

## 🤖 Phase Prompt

```
Before writing ANY code for Phase 2:

1. Read in full: memory/project_context.md, memory/progress.md,
   memory/interfaces.md, memory/decisions.md, memory/state.json.

2. Print a numbered summary of every feature already implemented.
   For each: phase number, owner (A/B), file path, current status.
   You should find the full DB schema and query layer from Phase 1.

3. State which query functions from memory/interfaces.md the UI will CONSUME,
   and which new component interfaces this phase will ADD.

4. Re-read ADR-008 (top-down build order) and confirm you understand the hard
   rule: the UI reads ONLY the database, never a hardcoded dict. List anything
   in memory that conflicts. STOP and ask me if you find a conflict.

Only then begin Phase 2: build the complete Streamlit UI against seeded rows.

Owner split — A: scripts/seed_demo.py (writes real rows into every table the
UI reads). B: everything under app/.
B must NOT create mock data structures in Python — if a page needs data that
doesn't exist yet, ask A to seed it.

Definition of done: `python scripts/seed_demo.py` then `streamlit run
app/main.py` gives a screenshottable product — summary cards with real
numbers, a populated anomaly table, a clause viewer placeholder, and a
Decision Engine page with a working chart.

After finishing, append a Phase 2 entry to memory/progress.md and update
memory/state.json.
```

## 👤 User A — tasks

`scripts/seed_demo.py` — creates a run and writes plausible rows into every table: 5 clients, 5 contract_rules, ~15 clause_references, ~60 expected_timeline rows, ~55 actual_transactions, 7 anomalies across all four types.

> Numbers should be internally consistent — the anomaly `gap` should equal `expected_amount - actual_amount`, the summary total should equal the sum of the gaps. If B's summary card and B's table disagree, you want that to be a *bug in B's code*, not a bug in your seed data.

Also: `docs/report_notes.md` — start logging screenshots and decisions now, while they're fresh.

## 👤 User B — tasks

Everything in `app/`. Page 1 layout — this is the v1 mockup, preserved:

```
┌─────────────────────────────────────────────────────────────────┐
│  📊 Revenue Integrity Dashboard              Run: [demo_v1 ▾]   │
├─────────────┬──────────────┬──────────────┬────────────────────┤
│  💰 Total   │  🔍 Anomalies│  👥 Clients  │  📈 Recovery       │
│  Leaked     │  Found       │  Affected    │  Potential         │
│  $14,280    │  7           │  3 of 5      │  $14,280/year      │
├─────────────┴──────────────┴──────────────┴────────────────────┤
│                                                                 │
│  Upload Area A: Contracts      Upload Area B: Invoices/Stmts    │
│  ┌──────────────────────┐      ┌──────────────────────────┐     │
│  │  📎 Drop PDFs here   │      │  📎 Drop files here      │     │
│  │  or click to browse  │      │  Toggle: [Scanned] [CSV] │     │
│  └──────────────────────┘      └──────────────────────────┘     │
│                                                                 │
│  ┌──── Client Confirmation ────────────────────────────────┐    │
│  │  We identified 3 clients:                               │    │
│  │  ✅ Starter Labs (2 contracts)                          │    │
│  │  ✅ Nexus Digital (1 contract)                          │    │
│  │  ✅ Bloom Agency (1 contract)                           │    │
│  │  [Confirm & Analyze]                                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌──── Anomaly Table ──────────────────────────────────────┐    │
│  │ Client      │ Type              │ Expected │ Actual │Gap│    │
│  │─────────────│───────────────────│──────────│────────│───│    │
│  │ Starter Labs│ 🟡 Forgotten Raise│ $6,480   │ $6,000 │480│    │
│  │ Starter Labs│ 🟠 Zombie Discount│ $6,000   │ $5,400 │600│    │
│  │ Nexus Digi  │ 🔴 Ghost Invoice  │ $15,000  │ $0     │15K│    │
│  │ Bloom Agency│ 🟣 Short-Change   │ $10,000  │ $8,500 │1.5K│   │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  👆 Click any row to see the original contract clause           │
│                                                                 │
│  ┌──── Clause Viewer (shown when row clicked) ─────────────┐    │
│  │  📄 Contract: starter_labs_2025.pdf — Page 3            │    │
│  │  ┌───────────────────────────────────────────────────┐  │    │
│  │  │  [PDF page rendered as image]                     │  │    │
│  │  │  ┌─── highlighted box ──────────────────────┐     │  │    │
│  │  │  │ "Fees shall increase by 8% on each       │     │  │    │
│  │  │  │  anniversary of the Effective Date."     │     │  │    │
│  │  │  └──────────────────────────────────────────┘     │  │    │
│  │  └───────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

Build every component listed in the tree. Upload widgets accept files and store them, but **do not process them yet** — that's Phase 4. The clause viewer shows a static placeholder image until Phase 7.

Page 2 gets the same treatment: question box, cash-flow breakdown reading seeded numbers, a Plotly chart with two lines, and a hardcoded verdict string. It looks finished; it just isn't thinking yet.

## ✅ Definition of done
A screenshot of this phase would convince someone the project is done. Every number on screen traces to a database row.

## 🧠 Memory update
Log every component file with a one-line description of what data it reads. Future you will need to know which query each page depends on.

---

# PHASE 3 — Online Data Sourcing

## 🎯 Goal
Real contracts on disk, sourced from the internet. Derived actuals with known ground truth. **No contract is invented by a model.**

## 🤖 Phase Prompt

```
Before writing ANY code for Phase 3:

1. Read in full: memory/project_context.md, memory/progress.md,
   memory/interfaces.md, memory/decisions.md, memory/state.json.

2. Print a numbered summary of every feature already implemented.
   For each: phase number, owner (A/B), file path, current status.

3. State which interfaces this phase will CONSUME and which it will ADD.

4. Re-read ADR-007 (source contracts online, derive actuals deterministically)
   and Risk R1 in changes.md (CUAD domain mismatch). Confirm you understand
   that NO contract may be generated by a language model. List anything in
   memory that conflicts. STOP and ask me if you find one.

Only then begin Phase 3: build the data-sourcing pipeline.

Owner split — A: data_sourcing/fetch_contracts.py, filter_contracts.py.
B: data_sourcing/fetch_invoices.py, scenario_builder.py.

Constraints:
- Contracts come from CUAD and SEC EDGAR only
- scenario_builder derives actuals by ARITHMETIC from true contract rules,
  never by calling a model
- every scenario writes ground_truth.json listing the planted anomalies

Definition of done: data/corpus/contracts/ holds 30+ filtered real contracts,
and data/scenarios/scenario_01/ holds contracts + actuals.csv +
ground_truth.json + manifest.json.

After finishing, append a Phase 3 entry to memory/progress.md and update
memory/state.json.
```

## 📐 Where the data comes from

```mermaid
flowchart LR
    subgraph SOURCED["🌐 SOURCED (real, from the internet)"]
        C1["CUAD v1<br/>510 real contracts<br/>CC BY 4.0"]
        C2["SEC EDGAR<br/>EX-10 material contracts<br/>public domain"]
        I1["HF invoice datasets<br/>images + parsed JSON"]
    end
    subgraph FILTER["🔍 FILTERED"]
        F1["keyword filter:<br/>retainer / escalat / discount /<br/>monthly fee / Net 30"]
    end
    subgraph DERIVED["🧮 DERIVED (arithmetic, not AI)"]
        D1["timeline_generator<br/>over TRUE rules"]
        D2["plant known anomalies"]
        D3["actuals.csv +<br/>ground_truth.json"]
    end
    C1 --> F1
    C2 --> F1
    F1 --> D1 --> D2 --> D3
    I1 --> D3
```

**The principle:** contracts are *sourced*, actuals are *derived*. The hard part — understanding real, messy, lawyer-written prose — is trained and tested on genuinely real documents. Only the ledger is derived, and it's derived by arithmetic, so you know the right answer exactly. That gives you real precision/recall in Phase 11 instead of eyeballed numbers.

## 👤 User A — tasks

**`data_sourcing/fetch_contracts.py`**

```python
from datasets import load_dataset

def fetch_cuad(limit=200, out_dir="data/corpus/contracts"):
    """CUAD v1: 510 real commercial contracts, 13k+ expert clause
    annotations across 41 categories, CC BY 4.0, sourced from EDGAR.
    Use the PDF-preserving mirror so PyMuPDF search_for() works later."""
    ds = load_dataset("dvgodoy/CUAD_v1_Contract_Understanding_PDF", split="train")
    # write PDFs to out_dir, keep the annotation CSV alongside
```

**`data_sourcing/filter_contracts.py`** — the important one.

> [!WARNING]
> **Risk R1.** CUAD skews toward M&A, licensing and distribution agreements — not the monthly-retainer B2B service contracts FinSight targets. You **must** filter, and you must say so in your report.

```python
KEEP = ["monthly fee", "retainer", "shall increase", "escalat",
        "annual increase", "discount", "net 30", "net 45",
        "milestone", "recurring", "per month", "monthly payment"]

def filter_service_contracts(paths):
    """Expect ~15-25% retention on CUAD. Log the retention rate —
    it belongs in your report's data section."""
```

Top up from EDGAR, which hits the target document type far more directly:

```python
def fetch_edgar_msa(count=50, out_dir="data/corpus/contracts"):
    """SEC full-text search: efts.sec.gov/LATEST/search-index?q=...
    Query "master services agreement" with forms=EX-10.
    Public domain, unlimited, and far closer to our target domain
    than CUAD's M&A skew."""
```

Target: **30+ usable contracts** after filtering. That's enough for Phase 5 development and Phase 10 training.

## 👤 User B — tasks

**`data_sourcing/fetch_invoices.py`** — pull invoice/receipt corpora for the OCR path and for realistic transaction descriptions:

| Dataset | Use |
|---------|-----|
| `mychen76/invoices-and-receipts_ocr_v1` | Invoice images + OCR + parsed JSON — the scanned-invoice path |
| `Voxel51/high-quality-invoice-images-for-ocr` | Clean invoice images for OCR testing |
| SROIE / CORD | Receipt OCR with bounding-box ground truth — validates your OCR path |
| Kaggle bank-transaction datasets | Realistic transaction description strings and amount distributions |

**`data_sourcing/scenario_builder.py`** — the heart of the phase.

```python
def build_scenario(contract_paths, rules, plant, out_dir) -> ScenarioManifest:
    """
    1. For each real contract, take its TRUE rules (hand-verified once).
    2. Run the deterministic timeline generator over them.
       -> this is what SHOULD have been billed
    3. Copy that timeline into an actuals ledger, then BREAK it on purpose:
         ghost_invoice    -> delete a milestone row
         forgotten_raise  -> keep billing the pre-escalation amount
         zombie_discount  -> keep applying an expired discount
         short_change     -> pay 85% of one invoice
    4. Add realistic noise sourced from the Kaggle transaction data:
       date jitter (±1-6 days), client-name variants ("Starter Labs" ->
       "StarterLabs", "Starter Labs Inc"), a few unrelated transactions.
    5. Write actuals.csv, ground_truth.json, manifest.json.
    """
```

**Why the noise matters.** Without it your reconciliation engine passes on data that's too clean, and then fails on the demo. The name variants in particular are what make the Phase 8 verification agent look genuinely smart — the agent catching "StarterLabs" vs "Starter Labs" is your single best demo moment, and it only exists if you plant the variation here.

Build **three scenarios**: `easy` (all four anomaly types, minimal noise), `realistic` (noise + name variants + split payments), `edge` (no anomalies at all — a clean client, to prove you don't produce false positives).

> That third scenario is the one examiners ask about. A leak detector that finds leaks everywhere is worthless; being able to show a clean run with zero anomalies is what proves the system discriminates.

## ✅ Definition of done
`data/corpus/contracts/` has 30+ filtered real PDFs. `data/scenarios/` has three built scenarios, each with `ground_truth.json`. Retention rate of the CUAD filter is logged.

---

# PHASE 4 — Document Ingestion & Text Extraction

## 🎯 Goal
Upload a real file through the UI → clean text lands in the database. Still no AI reasoning.

## 🤖 Phase Prompt

```
Before writing ANY code for Phase 4:

1. Read in full: memory/project_context.md, memory/progress.md,
   memory/interfaces.md, memory/decisions.md, memory/state.json.

2. Print a numbered summary of every feature already implemented.
   For each: phase number, owner (A/B), file path, current status.
   You should find: DB schema, query layer, full UI, sourced corpora.

3. State which interfaces this phase CONSUMES (upload widgets from Phase 2,
   corpora from Phase 3) and which it ADDS.

4. Re-read ADR-001 (no local GPU) and the Phase 4 section on OCR being an
   OPTIONAL branch, not the primary path. Confirm you understand that CUAD
   and EDGAR contracts are digital-text PDFs and need no OCR at all.
   List conflicts; STOP and ask me if you find one.

Only then begin Phase 4: implement the extraction pipeline.

Owner split — A: core/extraction/document_router.py, pdf_extractor.py,
core/storage/files.py. B: core/extraction/csv_parser.py, ocr_cloud.py,
app/components/column_mapper.py.

Constraints:
- the text-PDF path must work with zero API calls and zero GPU
- OCR is a fallback branch only; never on the critical path
- CSV column mapping is LLM-proposed, HUMAN-confirmed (ADR-010)

Definition of done: upload a real CUAD PDF and a real actuals.csv through the
UI; documents rows appear with extraction_status='success' and readable text.

After finishing, append a Phase 4 entry to memory/progress.md and update
memory/state.json.
```

## 📐 Three paths, one router

```mermaid
flowchart TD
    U["Uploaded file"] --> R{"document_router.detect_type()"}
    R -->|".csv"| CSV["pandas + LLM column mapping"]
    R -->|"PDF, >50 chars/page"| TXT["pdfplumber ✅ PRIMARY PATH"]
    R -->|"PDF, <50 chars/page"| OCR["cloud OCR ⚠️ FALLBACK"]
    R -->|"PNG/JPG"| OCR
    TXT --> OUT["ExtractedDoc"]
    CSV --> OUT
    OCR --> OUT
    OUT --> DB[("documents +<br/>actual_transactions")]
```

### Path A — Text-based PDFs (the primary path, 90% of your work)

**How we know it's text-based:** try `pdfplumber`. More than ~50 characters per page → it's digital.

**Tool:** `pdfplumber` [a Python library that reads text and tables directly from digital PDFs].

- Extracts raw text paragraph by paragraph
- Detects and extracts tables as structured rows/columns
- Records which page each block came from

**Output:** a list of blocks, each `{page_number, text_content, is_table}`.

> [!NOTE]
> **This is why Phase 3's data choice matters.** CUAD and EDGAR contracts are digital-text PDFs. This path handles them instantly, on CPU, for free — and PyMuPDF's `page.search_for()` works perfectly on them in Phase 5. Your highest-risk component (OCR) is off the critical path entirely.

### Path B — Scanned PDFs / images (the fallback branch)

**Step 1 — pages to images:** `PyMuPDF (fitz)` [a fast library that renders each PDF page as a high-resolution image] at 300 DPI. Skip if the upload is already an image.

**Step 2 — OCR in the cloud.** Two free options, no GPU:

| Option | How | Trade-off |
|--------|-----|-----------|
| **A — Gemini vision** (recommended) | Send the page PNG to the free Gemini tier, ask for markdown | One API call, dead simple, no bboxes — which is fine, ADR-005 means we don't need them |
| **B — Surya OCR in Colab** | Batch pre-process in a Colab notebook, write a text layer back into the PDF | Free GPU, gives real bboxes, but a manual step — not live |

> [!IMPORTANT]
> **The v1 plan ran Surya live on a local 3060 and budgeted VRAM for it.** That's gone. There is no VRAM budget in v2 because nothing loads a model onto your hardware. What replaced it is the **API budget** section near the end of this document — requests-per-minute is now your scarce resource.

### Path C — CSV files (ADR-010: template *and* smart mapping)

```mermaid
flowchart LR
    A["CSV uploaded"] --> B["read header + 3 rows ONLY"]
    B --> C["LLM proposes mapping<br/>(one tiny API call)"]
    C --> D["UI shows dropdowns<br/>👤 human confirms"]
    D --> E["save to column_mappings"]
    E --> F["pandas parses full file"]
```

**Tool:** `pandas` [Python's standard data analysis library].

Cleaning: strip whitespace, parse dates with `dayfirst` detection, convert currency strings (`"$6,000.00"`, `"6000"`, `"(1,500)"` for negatives) to floats.

The human-confirmation step is what makes this safe: it can never *silently* mis-parse. And it demos well — it looks like intelligence and costs one call on four rows.

## 👤 User A — tasks
- `document_router.py` — `detect_type()` + `extract()` single entry point
- `pdf_extractor.py` — pdfplumber text + table extraction, page-tagged
- `core/storage/files.py` — Supabase Storage upload/download, signed URLs
- Write `documents` rows with `extraction_status` and `error_message`

## 👤 User B — tasks
- `csv_parser.py` — `sniff_columns()` + `parse_transactions()`
- `ocr_cloud.py` — Gemini-vision page OCR
- `app/components/column_mapper.py` — the confirmation dropdowns
- Wire Phase 2's upload widgets to actually call A's `extract()`

## ✅ Definition of done
Upload a real CUAD contract and a real `actuals.csv` through the UI. Both appear in `documents` with `extraction_status='success'`, transactions land in `actual_transactions`, and a failed upload shows a readable error in the UI rather than a stack trace.

---

# PHASE 5 — LLM Contract Rule Extraction (The Brain)

## 🎯 Goal
Contract text → structured `ContractRules` JSON, with every rule traceable to a real, located clause.

## 🤖 Phase Prompt

```
Before writing ANY code for Phase 5:

1. Read in full: memory/project_context.md, memory/progress.md,
   memory/interfaces.md, memory/decisions.md, memory/state.json.

2. Print a numbered summary of every feature already implemented.
   For each: phase number, owner (A/B), file path, current status.

3. State which interfaces this phase CONSUMES (document_router.extract from
   Phase 4) and which it ADDS (llm_client, contract_extractor, clause_locator).

4. Re-read ADR-002 (one swappable LLM client), ADR-004 (Pydantic + JSON mode
   + repair-retry, NOT Outlines) and ADR-005 (code finds bboxes, never the
   model). These three constrain almost everything in this phase. Confirm you
   understand that the model must return VERBATIM clause_text and must NOT be
   asked for coordinates. List conflicts; STOP and ask me if you find one.

Only then begin Phase 5: implement LLM contract rule extraction.

Owner split — A: core/ai/schemas.py, contract_extractor.py, client_matcher.py,
core/extraction/clause_locator.py. B: core/ai/llm_client.py, prompts.py,
cache.py, app/components/client_confirm.py.

Constraints:
- llm_client.complete_json NEVER raises to the caller; it returns None
- every LLM call goes through the cache, keyed by hash(prompt + model)
- the extraction prompt must not mention coordinates, pages or bboxes

Definition of done: run the extractor over 10 sourced contracts; >=8 produce
valid ContractRules, and the clause-grounding rate (exact+fuzzy) is >=80%.

After finishing, append a Phase 5 entry to memory/progress.md and update
memory/state.json.
```

## 📐 What the model receives

```
System: You are a contract analysis assistant. Read the following contract
text and extract all financial rules. Output valid JSON matching the
required schema. If a field is not mentioned, use null.

For every rule you extract, copy the exact sentence it came from into
clause_text, character for character. Do not paraphrase, summarise, or
shorten it. If you cannot find an exact sentence, omit the rule.

User: [raw contract text from Phase 4]
```

> [!IMPORTANT]
> Read that second system paragraph carefully — it is doing two jobs. It gets you the quote you need for grounding, **and** it is a hallucination check. If the model paraphrases, `clause_locator` won't find the text, and you'll know the rule is unreliable without ever having to verify it by hand.

## 📐 What the model outputs

```json
{
  "client_name": "Starter Labs",
  "contract_start_date": "2025-01-15",
  "contract_end_date": "2026-01-14",
  "base_amount": 6000.00,
  "currency": "USD",
  "billing_frequency": "monthly",
  "payment_terms": "Net 30",
  "escalation": {
    "percentage": 8.0,
    "after_months": 12,
    "clause_text": "Fees shall increase by 8% on each anniversary of the Effective Date."
  },
  "discounts": [
    {
      "percentage": 10.0,
      "duration_months": 3,
      "clause_text": "A 10% introductory discount applies for the first three months of the Term."
    }
  ],
  "milestones": [
    {
      "description": "Website launch",
      "amount": 15000.00,
      "due_condition": "Upon delivery of final website",
      "clause_text": "A milestone payment of $15,000 is due upon delivery of the final website."
    }
  ]
}
```

> [!NOTE]
> **Compare this to v1.** Every rule used to carry `source_page` and `source_bbox` straight from the model. Those are gone. The model gives us `clause_text`; the *next step* produces the page and box. Same feature, honest mechanism.

## 📐 Clause grounding — the step that replaces hallucinated coordinates

```python
# core/extraction/clause_locator.py                                    [A]
import fitz
from thefuzz import fuzz

def locate_clause(pdf_path: str, clause_text: str) -> ClauseLocation | None:
    doc = fitz.open(pdf_path)
    probe = clause_text[:80]                       # long enough to be unique

    # 1. EXACT — PyMuPDF returns real rectangles in PDF points
    for page_num, page in enumerate(doc, start=1):
        hits = page.search_for(probe)
        if hits:
            return ClauseLocation(page=page_num, bbox=list(hits[0]), method="exact")

    # 2. FUZZY — OCR noise, ligatures, line-break hyphenation
    best = (0, None, None)
    for page_num, page in enumerate(doc, start=1):
        for block in page.get_text("blocks"):
            score = fuzz.partial_ratio(probe.lower(), block[4].lower())
            if score > best[0]:
                best = (score, page_num, block[:4])
    if best[0] >= 80:
        return ClauseLocation(page=best[1], bbox=list(best[2]), method="fuzzy")

    # 3. UNGROUNDED — the model probably invented this quote.
    #    Return None. Caller flags the rule low-confidence; UI shows the
    #    page with no highlight rather than a wrong highlight.
    return None
```

**Three things you get from this, beyond correctness:**

| Payoff | Why it matters |
|--------|----------------|
| Highlights are never *wrong* | Worst case is absent. A confidently wrong highlight destroys trust in a demo |
| Free hallucination detector | A quote that isn't in the document was fabricated. No manual checking needed |
| A real metric | "Clause grounding rate: N% exact, M% fuzzy, K% ungrounded" goes straight into your report |

## 📐 The swappable client (ADR-002)

```python
# core/ai/llm_client.py                                                [B]
def complete_json(prompt, schema, system="", max_repairs=1):
    """
    1. Call the provider with response_format = schema.model_json_schema()
    2. Pydantic-validate the response
    3. On failure, ONE repair call including the broken output AND the
       validation error text
    4. On second failure, return None  -- NEVER raise to the caller

    Provider chosen by LLM_PROVIDER. Most expose OpenAI-compatible
    endpoints, so one code path covers gemini / groq / openrouter /
    finetuned_tunnel. Phase 10's comparison is then one env var, not a
    refactor.
    """
```

> [!WARNING]
> **Why not `Outlines`, as v1 planned?** Outlines works by masking logits during token generation, which needs local access to the model's forward pass. **It cannot work against a hosted HTTP API.** v1's guarantee — *"the model literally cannot produce invalid output"* — silently stops being true the moment you move to the cloud. The three-layer replacement above reaches ~99% in practice, and its failures are *visible* rather than silent. Outlines stays valid in one place only: the Colab notebook in Phase 10, where the model runs locally. That's worth one honest row in your eval table.

**Caching is not optional.** `core/ai/cache.py` keys on `sha256(prompt + model)` and writes to `data/cache/`. Reasons: free tiers are rate-limited (Risk R2), you'll re-run the same 10 contracts fifty times while debugging, and on demo day every document you've already processed responds instantly with zero quota consumed.

## 📐 Client attribution

When multiple contracts are uploaded, the model extracts `client_name` from each. Then:

1. Group extracted rules by client name
2. `thefuzz` fuzzy matching to handle variations — "Starter Labs" / "Starter Labs Inc." / "StarterLabs"
3. Confirmation view: *"We found 4 clients: Starter Labs, Nexus Digital, Bloom Agency, TechForge. Is this correct?"*
4. User can merge or rename if the system guessed wrong

That step-4 human check is the safety net for Risk R8, and it was already in v1 — kept unchanged.

## 👤 User A — tasks
- `core/ai/schemas.py` — the Pydantic models in `interfaces.md`
- `contract_extractor.py` — chunk long contracts, call B's client, merge results
- `clause_locator.py` — the function above, plus tests against known contracts
- `client_matcher.py` — fuzzy grouping

## 👤 User B — tasks
- `llm_client.py` — the multi-provider client
- `prompts.py` — every prompt template in one file, versioned
- `cache.py` — disk cache
- `client_confirm.py` — the confirmation UI

## ✅ Definition of done
Run over 10 sourced contracts: ≥8 produce valid `ContractRules`; clause-grounding rate ≥80% (exact + fuzzy); switching `LLM_PROVIDER` from `gemini` to `groq` requires no code change.

---

# PHASE 6 — Expected Timeline & Reconciliation

## 🎯 Goal
Real, computed anomalies replace Phase 2's seeded ones. **Zero AI in this phase** — it's all arithmetic.

## 🤖 Phase Prompt

```
Before writing ANY code for Phase 6:

1. Read in full: memory/project_context.md, memory/progress.md,
   memory/interfaces.md, memory/decisions.md, memory/state.json.

2. Print a numbered summary of every feature already implemented.
   For each: phase number, owner (A/B), file path, current status.

3. State which interfaces this phase CONSUMES (ContractRules from Phase 5,
   TransactionRow from Phase 4) and which it ADDS.

4. Re-read ADR-006 (client-month aggregate reconciliation) and the hard rule
   in project_context.md that the LLM never does arithmetic. Confirm that
   NOTHING in this phase may call a language model. List conflicts; STOP and
   ask me if you find one.

Only then begin Phase 6: implement the timeline generator and reconciliation.

Owner split — A: core/engine/timeline_generator.py + tests/test_timeline.py.
B: core/engine/reconciliation.py, anomaly_classifier.py +
tests/test_reconciliation.py.

Constraints:
- both modules must be PURE FUNCTIONS: no DB access, no network, no LLM
- reconciliation aggregates actuals per client per calendar month
- every anomaly carries a confidence_score and a clause_reference_id

Definition of done: run all three Phase 3 scenarios; the easy and realistic
scenarios reproduce ground_truth.json exactly, and the edge scenario (clean
client) produces ZERO anomalies.

After finishing, append a Phase 6 entry to memory/progress.md and update
memory/state.json.
```

## 📐 Stage A — Expected Timeline Generation (pure math, no AI)

```python
def generate_expected_timeline(contract_rules, client_id, contract_rule_id):
    timeline = []
    current_amount = contract_rules.base_amount
    start = contract_rules.contract_start_date

    for month_offset in range(contract_duration_months):
        billing_date = add_months(start, month_offset)

        # Price escalation at the anniversary
        escalation_applied = False
        if (contract_rules.escalation and
                month_offset >= contract_rules.escalation.after_months):
            current_amount = base * (1 + contract_rules.escalation.percentage / 100)
            escalation_applied = True

        # Discount, only while it's still alive
        discount = 0.0
        for d in contract_rules.discounts:
            if month_offset < d.duration_months:
                discount = d.percentage

        expected_amount = current_amount * (1 - discount / 100)

        timeline.append(TimelineEntry(
            client_id=client_id,
            contract_rule_id=contract_rule_id,
            billing_date=billing_date,
            expected_amount=round(expected_amount, 2),
            payment_type="recurring",
            applied_escalation=escalation_applied,
            applied_discount_pct=discount,
            source_clause_ref_id=...,
            notes=...,
        ))

    # Milestones
    for milestone in contract_rules.milestones:
        timeline.append(TimelineEntry(
            payment_type="milestone",
            expected_amount=milestone.amount,
            ...
        ))

    return timeline
```

**Example output for one client:**

| # | Date | Expected Amount | Notes |
|---|------|----------------|-------|
| 1 | Jan 2025 | $5,400 | Base $6,000 minus 10% intro discount |
| 2 | Feb 2025 | $5,400 | Discount still active |
| 3 | Mar 2025 | $5,400 | Discount still active |
| 4 | Apr 2025 | $6,000 | Discount expired → full rate |
| … | … | … | … |
| 13 | Jan 2026 | $6,480 | 8% annual escalation applied |

> [!IMPORTANT]
> **This function is the most important thing User A writes all project.** It is a pure function with no dependencies — no database, no network, no model. That means it is completely unit-testable, and it is the reason your anomaly numbers are defensible. When an examiner asks *"how do you know $6,480 is right?"*, the answer is a fifteen-line function and a test file, not a model's opinion. Write the tests first.

## 📐 Stage B — Reconciliation (finding the leaks)

**ADR-006 — client-month aggregation:**

```
For each expected payment in the timeline:
  1. Sum ALL actual transactions for that client in that calendar month
     (fuzzy client-name match, ±15 day tolerance at month boundaries)

  2. If total == 0                     -> "Ghost Invoice"    (never billed)

  3. If total < expected:
       - gap matches an expired discount %      -> "Zombie Discount"
       - total ≈ the pre-escalation amount      -> "Forgotten Raise"
       - otherwise                              -> "Short-Change"

  4. If total ≈ expected (within 1%)   -> ✅ no anomaly
```

Why aggregate rather than match transaction-to-invoice? Full matching is a combinatorial assignment problem — high effort, high risk, low MVP value. The precision you lose (mostly split payments) comes back cheaply in Phase 8: the agent's `check_split_payments` tool does transaction-level search **only for already-flagged anomalies**. You pay the complexity cost on ~5 rows instead of ~5,000.

## 📐 The four anomaly types

| Anomaly Type | What Happened | Example |
|-------------|---------------|---------|
| 🔴 Ghost Invoice | Expected billing never happened | Project milestone delivered but never invoiced |
| 🟡 Forgotten Raise | Price escalation clause ignored | Still billing $6,000 after a 12-month 8% increase should make it $6,480 |
| 🟠 Zombie Discount | Temporary discount never removed | 10% intro discount still applied in month 6 |
| 🟣 Short-Change | Partial payment received, gap ignored | Paid $8,500 of a $10,000 invoice |

**Output record:**

```python
{
    "anomaly_type": "forgotten_raise",
    "client_id": 3,
    "expected_timeline_id": 47,
    "actual_transaction_id": 112,
    "clause_reference_id": 19,      # -> the clause that proves it
    "expected_amount": 6480.00,
    "actual_amount": 6000.00,
    "gap": 480.00,
    "billing_date": "2026-01-15",
    "confidence_score": 0.92,
    "status": "unverified"          # Phase 8 changes this
}
```

## 👤 User A — tasks
- `timeline_generator.py` + `tests/test_timeline.py` — **write the tests first**; the fixtures are known-answer inputs (a contract with a discount and an escalation, hand-computed)
- Month arithmetic edge cases: Jan 31 + 1 month, leap years, contracts starting mid-month

## 👤 User B — tasks
- `reconciliation.py` + `anomaly_classifier.py` + `tests/test_reconciliation.py`
- Swap `seed_demo.py`'s anomaly rows for computed ones in the pipeline
- **Nothing in the UI changes.** It already reads the `anomalies` table. This is ADR-008 paying off.

## ✅ Definition of done
All three Phase 3 scenarios run. `easy` and `realistic` reproduce `ground_truth.json` exactly. `edge` (the clean client) produces **zero** anomalies — that's the one that proves you discriminate rather than just flag everything.

---

# PHASE 7 — Clause Viewer (Real Highlighting)

## 🎯 Goal
Click an anomaly → see the actual contract page with the actual violated clause highlighted.

## 🤖 Phase Prompt

```
Before writing ANY code for Phase 7:

1. Read in full: memory/project_context.md, memory/progress.md,
   memory/interfaces.md, memory/decisions.md, memory/state.json.

2. Print a numbered summary of every feature already implemented.
   For each: phase number, owner (A/B), file path, current status.

3. State which interfaces this phase CONSUMES (clause_locator from Phase 5,
   anomalies from Phase 6, the Phase 2 clause_viewer placeholder) and which
   it ADDS.

4. Re-read ADR-005. Confirm you understand that source_bbox may be NULL and
   locate_method may be 'none', and that the UI must degrade gracefully to a
   page-level view rather than crash or invent a box. List conflicts; STOP and
   ask me if you find one.

Only then begin Phase 7: wire real clause highlighting.

Owner split — A: harden core/extraction/clause_locator.py (multi-page clauses,
hyphenation, ligatures) and add tests. B: core/extraction/pdf_renderer.py and
replace the Phase 2 placeholder in app/components/clause_viewer.py.

Definition of done: clicking each of the four anomaly types opens the correct
page with the correct clause highlighted, and an ungrounded clause shows the
page with an honest "exact location not found" note.

After finishing, append a Phase 7 entry to memory/progress.md and update
memory/state.json.
```

## 📐 How it works

1. User clicks an anomaly row
2. Look up `clause_reference_id` → `document_id`, `source_page`, `source_bbox`, `locate_method`
3. `PyMuPDF (fitz)` renders that page as an image
4. Draw a highlight rectangle at `source_bbox`
5. Display in Streamlit with `st.image()`

```python
import fitz

def render_highlighted(pdf_path, page_num, bbox, dpi=150):
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]                      # 0-indexed

    if bbox is not None:                          # ADR-005: may be None
        rect = fitz.Rect(bbox)
        page.draw_rect(rect, color=(1, 0.8, 0), fill=(1, 0.95, 0.6), width=2)

    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes("png")
```

**The three display states** — build all three:

| `locate_method` | What the user sees |
|-----------------|--------------------|
| `exact` | Page image, yellow highlight, quoted clause below |
| `fuzzy` | Same, plus a small note: *"approximate location"* |
| `none` | Page image, **no** highlight, note: *"exact location not found — clause text shown below"* |

> [!TIP]
> That third state is worth building properly rather than hiding. Showing "we couldn't locate this precisely" is more credible than a confident highlight on the wrong paragraph, and if an examiner asks about failure modes you have an answer already on screen.

## 👤 User A — tasks
- Harden `clause_locator.py`: clauses spanning two pages, hyphenated line breaks, ligatures (`ﬁ` vs `fi`), whitespace normalisation
- `tests/test_clause_locator.py` with real sourced contracts
- Log the grounding-rate breakdown for the report

## 👤 User B — tasks
- `pdf_renderer.py`
- Replace the Phase 2 placeholder with the real viewer, all three states
- Fetch PDFs from Supabase Storage via signed URL

## ✅ Definition of done
All four anomaly types open the correct page with the correct clause highlighted. The ungrounded case degrades honestly instead of crashing.

---

# PHASE 8 — LangGraph Verification Agent

## 🎯 Goal
An AI agent reviews every flagged anomaly and filters out false positives before the user ever sees them.

## 🤖 Phase Prompt

```
Before writing ANY code for Phase 8:

1. Read in full: memory/project_context.md, memory/progress.md,
   memory/interfaces.md, memory/decisions.md, memory/state.json.

2. Print a numbered summary of every feature already implemented.
   For each: phase number, owner (A/B), file path, current status.

3. State which interfaces this phase CONSUMES (anomalies from Phase 6,
   llm_client from Phase 5, queries from Phase 1) and which it ADDS.

4. Re-read ADR-006 -- the agent's check_split_payments tool is where we
   recover the precision that client-month aggregation gives up. Confirm you
   understand the agent runs ONLY on already-flagged anomalies, never over the
   whole transaction set. List conflicts; STOP and ask me if you find one.

Only then begin Phase 8: build the verification agent.

Owner split — A: core/agents/tools.py (4 DB-backed tools).
B: core/agents/verification_agent.py (LangGraph loop) + UI status badges.

Constraints:
- hard cap of 5 iterations per anomaly; on cap, verdict = 'needs_review'
- every tool call is recorded to anomalies.agent_tool_calls (JSON)
- agent failure must never lose an anomaly -- it stays 'unverified'

Definition of done: run the 'realistic' scenario; the agent correctly marks
the planted name-variant case FALSE_POSITIVE with a readable explanation, and
leaves the genuine anomalies CONFIRMED.

After finishing, append a Phase 8 entry to memory/progress.md and update
memory/state.json.
```

## 📐 Why an agent at all?

The reconciliation engine is mechanical — it doesn't understand context. Real situations it gets wrong:

- A client negotiated a one-time fee reduction by email, not in the contract
- A payment was split across two bank transactions
- An invoice uses a different spelling of the client's name

Each of those produces a confident, wrong anomaly. That's exactly the class of error a tool-using agent is good at killing.

## 📐 The ReAct loop

**Tool:** `LangGraph` [a Python framework by LangChain for building agents that reason step-by-step and call tools].

```mermaid
flowchart TD
    A["Receive anomaly to verify"] --> B["REASON: why might this be a false positive?"]
    B --> C["ACT: call a tool\n(search invoices, re-read clause, search transactions)"]
    C --> D["OBSERVE: what did the tool return?"]
    D --> E{"More investigation needed?"}
    E -->|Yes, and iterations < 5| B
    E -->|No| F["CONCLUDE: CONFIRMED / FALSE_POSITIVE / NEEDS_REVIEW\n+ explanation"]
    E -->|Iteration cap hit| G["NEEDS_REVIEW\n(honest: we couldn't decide)"]
```

**State:**

```python
class VerificationState(TypedDict):
    anomaly: dict
    reasoning_steps: list[str]
    tools_called: list[dict]
    verdict: Literal["confirmed", "false_positive", "needs_review"]
    explanation: str
    iteration_count: int              # hard cap 5
```

**The four tools** [A owns these]:

| Tool | Signature | What it's for |
|------|-----------|---------------|
| `search_invoices` | `(client_id, start, end)` | Look up actual invoices for a client |
| `read_contract_clause` | `(clause_ref_id)` | Re-read the original contract text |
| `search_bank_transactions` | `(run_id, amount_min, amount_max, start, end)` | Find a payment that might be the missing amount |
| `check_split_payments` | `(client_id, target, start, end, tol)` | **The ADR-006 payoff** — find combinations summing to the expected amount |

## 📐 Worked example (this is your demo moment)

```
Anomaly: Ghost Invoice — Starter Labs, $15,000 milestone "Website launch",
         expected May 2025

REASON:  This is a large milestone payment. Let me check whether there is a
         payment near this amount around May 2025.

ACT:     search_bank_transactions(amount_min=14000, amount_max=16000,
                                  start="2025-04-01", end="2025-06-30")

OBSERVE: Found transaction: "StarterLabs Wire Transfer" $15,000 on 2025-05-22

REASON:  There IS a matching payment. The reconciliation engine missed it
         because the bank line says "StarterLabs" but the contract says
         "Starter Labs" (no space). This is a false positive.

CONCLUDE: FALSE_POSITIVE — Payment found in bank records under a slightly
          different client name "StarterLabs".
```

> [!TIP]
> **Plant this case deliberately in Phase 3's `realistic` scenario.** It is the single best thing you can show in a live demo: a mechanical rule produces a confident $15,000 error, and the agent catches it by reasoning about a missing space. It takes twenty seconds to demonstrate and it makes the agent's existence obviously justified rather than decorative.

**Model used:** the same hosted model via `llm_client`. No separate model needed. In Phase 10 you can point the agent at the fine-tuned endpoint too and compare — though extraction is where fine-tuning will help most.

## 👤 User A — tasks
- `core/agents/tools.py` — the four tools, each a plain DB function with a docstring the agent reads as its tool description
- Make each independently testable without the agent

## 👤 User B — tasks
- `verification_agent.py` — the LangGraph graph, iteration cap, verdict writing
- UI: status badges (✅ confirmed / ⚪ false positive / ⚠️ needs review), an expandable "agent reasoning" panel per row, and a toggle to show or hide filtered false positives

## ✅ Definition of done
The `realistic` scenario runs. The planted name-variant case comes back `FALSE_POSITIVE` with a readable explanation. Genuine anomalies stay `CONFIRMED`. No anomaly is ever lost by an agent error.

---

# PHASE 9 — Decision Engine (Page 2)

## 🎯 Goal
The user asks a strategic question in plain English and gets a Yes/No backed by their own numbers.

## 🤖 Phase Prompt

```
Before writing ANY code for Phase 9:

1. Read in full: memory/project_context.md, memory/progress.md,
   memory/interfaces.md, memory/decisions.md, memory/state.json.

2. Print a numbered summary of every feature already implemented.
   For each: phase number, owner (A/B), file path, current status.

3. State which interfaces this phase CONSUMES (confirmed anomalies from
   Phase 8, actual_transactions from Phase 4, the Phase 2 Page-2 shell) and
   which it ADDS.

4. Re-read the hard rule in project_context.md: the LLM never does arithmetic
   and never produces a number the user sees. In this phase the LLM parses the
   question and writes the explanation; Python computes every figure. Confirm
   you understand this split. List conflicts; STOP and ask me if you find one.

Only then begin Phase 9: build the decision engine.

Owner split — A: core/engine/cashflow.py (all math).
B: core/ai/decision_analyzer.py (parse + explain), the Plotly chart, and
replacing the Phase 2 hardcoded verdict.

Constraints:
- only CONFIRMED anomalies count toward recovered revenue (not unverified,
  not false positives)
- the explanation generator receives COMPUTED numbers and may only phrase
  them; if it states a number not in its input, that is a bug

Definition of done: three different strategic questions produce correct
verdicts, and every number in the explanation matches the computed figure.

After finishing, append a Phase 9 entry to memory/progress.md and update
memory/state.json.
```

## 📐 Page 2 layout (preserved from v1)

```
┌─────────────────────────────────────────────────────────────────┐
│  💬 Decision Engine                                             │
│                                                                 │
│  Ask a strategic question about your business:                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Can I afford to hire a $5,000/month senior designer       │   │
│  │ starting in September?                                    │   │
│  └──────────────────────────────────────────────────────────┘   │
│  [Analyze]                                                      │
│                                                                 │
│  ┌──── Cash Flow Analysis ─────────────────────────────────┐    │
│  │                                                          │    │
│  │  Current Monthly Cash Flow:        $22,500               │    │
│  │  Monthly After Fixing Leaks:       $23,690  (+$1,190)    │    │
│  │  Cost of Proposed Decision:        -$5,000               │    │
│  │                                                          │    │
│  │  ────────────────────────────────────────────            │    │
│  │  Without fixing leaks:  $22,500 - $5,000 = $17,500       │    │
│  │  With fixing leaks:     $23,690 - $5,000 = $18,690       │    │
│  │                                                          │    │
│  │  ✅ VERDICT: YES — You can afford this hire.             │    │
│  │                                                          │    │
│  │  "Your current cash flow supports the hire even without  │    │
│  │   recovering leaked revenue. However, by correcting the  │    │
│  │   7 anomalies found ($14,280/year = $1,190/month), your  │    │
│  │   effective buffer increases from $17,500 to $18,690     │    │
│  │   per month — a 6.8% improvement."                       │    │
│  │                                                          │    │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──── Cash Flow Projection Chart ─────────────────────────┐    │
│  │  [Line chart: monthly projected cash flow,               │    │
│  │   two lines: "Current" vs "After Recovery"]              │    │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 📐 The logic — note carefully what the LLM does and doesn't do

```mermaid
flowchart TD
    Q["User question (free text)"] --> P["🧠 LLM: parse into
    {what, monthly_cost, start_month}"]
    P --> M1["🧮 Python: baseline from actual_transactions
    (avg revenue - avg expenses, last 6 months)"]
    M1 --> M2["🧮 Python: recovered = sum(CONFIRMED anomaly gaps) / 12"]
    M2 --> M3["🧮 Python: after = baseline + recovered - monthly_cost
    verdict = YES if after > 0 else NO"]
    M3 --> E["🧠 LLM: phrase the COMPUTED numbers
    as 2-3 readable sentences"]
    E --> UI["Verdict + explanation + chart"]
```

```python
current_surplus   = avg_revenue - avg_expenses
recovered_monthly = sum(a.gap for a in confirmed_anomalies) / 12
corrected_surplus = current_surplus + recovered_monthly
after_decision    = corrected_surplus - proposed_cost
verdict           = "YES" if after_decision > 0 else "NO"
```

> [!IMPORTANT]
> **The model appears at both ends and never in the middle.** It reads the question, and it phrases the answer. Every figure between those two points is computed by the four lines above. If the explanation ever contains a number that isn't in its input, that's a bug — and it's worth writing an assertion that checks exactly this, because it's the most likely place in the whole project for a plausible-sounding wrong number to reach a user.

**Only `confirmed` anomalies count.** Not `unverified`, not `false_positive`. Phase 8 exists precisely so this number is trustworthy.

## 👤 User A — tasks
- `core/engine/cashflow.py` — `compute_baseline()` and `apply_scenario()`, pure functions
- Handle sparse data honestly: fewer than three months of transactions → return a low-confidence flag rather than a confident projection

## 👤 User B — tasks
- `decision_analyzer.py` — `parse_question()` and `explain_verdict()`
- Plotly projection chart, two lines
- Replace the Phase 2 hardcoded verdict with real output

## ✅ Definition of done
Three different questions produce correct verdicts. Every number in the explanation matches the computed figure exactly.

---

# PHASE 10 — Fine-Tuning (The Capstone Differentiator)

## 🎯 Goal
Train your own model and measure it against the hosted baseline. **The product already works without this** (ADR-009) — this phase makes the capstone claim.

## 🤖 Phase Prompt

```
Before writing ANY code for Phase 10:

1. Read in full: memory/project_context.md, memory/progress.md,
   memory/interfaces.md, memory/decisions.md, memory/state.json.

2. Print a numbered summary of every feature already implemented.
   For each: phase number, owner (A/B), file path, current status.

3. State which interfaces this phase CONSUMES (llm_client from Phase 5, the
   sourced corpus from Phase 3, schemas from Phase 5) and which it ADDS.

4. Re-read ADR-009 (fine-tuning is a measured comparison, not a dependency)
   and ADR-007 (contracts are sourced, never generated). Confirm you
   understand that: (a) the app must keep working if this phase fails, and
   (b) training pairs are built from REAL sourced contracts only. List
   conflicts; STOP and ask me if you find one.

Only then begin Phase 10: build training data and fine-tune.

Owner split — A: training/build_pairs.py and the train/val/test split.
B: training/finetune_colab.ipynb and training/serve_finetuned.py.

Constraints:
- the held-out eval set is created BEFORE training and never trained on
- the served model must expose an OpenAI-compatible endpoint so
  core/ai/llm_client.py needs ZERO changes to point at it
- no code outside training/ may change in this phase

Definition of done: a fine-tuned adapter on HF Hub, and setting
LLM_PROVIDER=finetuned_tunnel runs the whole app end to end unchanged.

After finishing, append a Phase 10 entry to memory/progress.md and update
memory/state.json.
```

## 📐 What we're fine-tuning

**Base model:** `Qwen 2.5 3B Instruct` [a 3-billion-parameter open model by Alibaba, already instruction-tuned].

**Task:** contract text → structured `ContractRules` JSON.

**Why 3B and not 14B?** A 3B model at 4-bit fits comfortably on a free Colab/Kaggle T4 for both training and inference. The whole point of fine-tuning is that a small model trained on *this one task* can match a much larger general model on *this one task*. That's the capstone argument, and it's a testable claim rather than an assumption: *"we measured whether a fine-tuned 3B matches a much larger zero-shot model on contract extraction."*

## 📐 Training data — from real sourced contracts (ADR-007)

```mermaid
flowchart LR
    A["30+ real contracts<br/>Phase 3 (CUAD + EDGAR)"] --> B["Run the Phase 5 extractor<br/>with the BEST available model"]
    B --> C["👤 HUMAN VERIFIES<br/>every output"]
    C --> D["Corrected pairs"]
    D --> E["train.jsonl 70%<br/>val.jsonl 15%<br/>eval_set.jsonl 15%"]
    E -.->|"eval_set created FIRST,<br/>never trained on"| F["Phase 11"]
```

**Target: 80–120 instruction pairs**, format:

```json
{
  "instruction": "Extract all financial rules from this contract text as JSON.",
  "input": "[real contract text]",
  "output": "[verified ContractRules JSON]"
}
```

> [!TIP]
> **Creating good training data is 80% of the fine-tuning work.** Spend the time here — the model will only ever be as good as what you show it. Split the human verification between both of you; it's roughly an evening's work for 100 contracts and it's the highest-leverage hour in the project.

**The one rule you cannot break:** build `eval_set.jsonl` **before** you train, and never let it touch training. If the eval set leaks into training, every number in Phase 11 is meaningless and you won't be able to tell.

## 📐 Fine-tuning process

**Tool:** `Unsloth` [makes LLM fine-tuning 2–3× faster and much lighter on memory by optimising the underlying math].
**Technique:** `QLoRA` [freezes the base weights and trains a tiny set of adapter weights, so a 3B model fits on a free T4].
**Where:** Google Colab or Kaggle, free T4 (16GB).

1. Load Qwen 2.5 3B in 4-bit via Unsloth
2. Attach LoRA adapters (rank 16–32, targeting attention layers)
3. Train 3–5 epochs on 80–120 examples
4. ~30–60 minutes on a T4
5. Save adapter weights (~50–100MB) and push to HF Hub

> [!WARNING]
> **Colab disconnects.** Checkpoint every epoch to Google Drive or HF Hub. Losing a 45-minute run to a dropped tab is the most common way this phase eats a day.

## 📐 Serving it — the Colab tunnel

This is what makes Phase 11's comparison a one-variable change (ADR-002):

```
Colab notebook:
  load base + adapter  ->  FastAPI exposing /v1/chat/completions
                           (OpenAI-compatible shape)
                        ->  Cloudflare quick tunnel  ->  public https URL

Your app:
  FINETUNED_TUNNEL_URL=<that url>
  LLM_PROVIDER=finetuned_tunnel
  # llm_client.py needs ZERO changes
```

> [!IMPORTANT]
> **Risk R4 — the tunnel dies when the notebook stops.** Plan for it: keep the notebook running through your demo, and **record a screen capture of the fine-tuned path in advance** as a backup. The hosted-model path is always live, so the product never breaks — only the comparison does.

This is also the one place `Outlines` remains valid: inside Colab the model is local, so you can genuinely constrain generation and report a true 100% valid-JSON rate for that configuration.

## 👤 User A — tasks
- `training/build_pairs.py`, the split, and the human-verification workflow
- Commit `eval_set.jsonl` to git (it's small, and it must not drift)

## 👤 User B — tasks
- `finetune_colab.ipynb` — Unsloth + QLoRA, checkpointing
- `serve_finetuned.py` — FastAPI + tunnel
- Add the `finetuned_tunnel` branch to `llm_client.py`

## ✅ Definition of done
Adapter on HF Hub. `LLM_PROVIDER=finetuned_tunnel` runs the entire app end to end with no other change.

---

# PHASE 11 — Evaluation & Deployment

## 🎯 Goal
Real measured numbers, and a public URL.

## 🤖 Phase Prompt

```
Before writing ANY code for Phase 11:

1. Read in full: memory/project_context.md, memory/progress.md,
   memory/interfaces.md, memory/decisions.md, memory/state.json.

2. Print a numbered summary of every feature already implemented, phase by
   phase. This is the full-project summary -- be complete, since it becomes
   the backbone of our capstone report.

3. State which interfaces this phase CONSUMES. This phase should ADD only the
   evaluation harness.

4. Re-read ADR-009 and change C12 in changes.md: the v1 accuracy table was
   ESTIMATED, not measured, and must be replaced with real numbers from a real
   harness. Confirm you understand that a result showing fine-tuning did NOT
   beat the baseline is a legitimate finding to report, not a failure to hide.
   List conflicts; STOP and ask me if you find one.

Only then begin Phase 11: build the eval harness and deploy.

Owner split — A: training/evaluate.py and running the full comparison.
B: Streamlit Community Cloud deployment, secrets, README.md,
docs/demo_script.md.

Definition of done: a public URL that works from a phone on mobile data, and a
completed results table with measured numbers.

After finishing, append a Phase 11 entry to memory/progress.md, set every
phase in memory/state.json to done, and record the deployed URL.
```

## 📐 The evaluation harness

```python
# training/evaluate.py                                                 [A]
def evaluate(provider: str, eval_set: str) -> EvalReport:
    """Identical harness for every configuration. One argument apart.
    Run it three times: baseline, fine-tuned, and (optionally) a larger
    hosted model for the size comparison."""
```

**Metrics — every one of these is measurable, none is guessed:**

| Metric | How it's computed |
|--------|-------------------|
| Field extraction accuracy | Exact match per field vs. the verified eval set |
| Money-field accuracy | Within $0.01 tolerance |
| Date accuracy | Exact date match |
| Valid JSON rate | % parsing into `ContractRules` without a repair call |
| Repair rate | % needing the ADR-004 repair retry |
| **Clause grounding rate** | % of `clause_text` values located by `clause_locator` — *this one is uniquely yours* |
| End-to-end anomaly precision/recall | Detected anomalies vs. `ground_truth.json` from Phase 3 |
| Mean latency per contract | Wall clock |
| Cost per contract | $0 on free tiers — state it |

## 📐 Results table — **fill this in with measurements**

> [!WARNING]
> The v1 plan carried this table pre-filled with round numbers marked *"estimated targets"*. In a capstone report, a table that looks like results but is actually a hope is a serious liability the moment someone asks how you measured it. Leave these cells empty until `evaluate.py` fills them.

| Metric | Hosted baseline (zero-shot) | Fine-tuned Qwen 3B | Larger hosted model |
|--------|------------------------------|--------------------|---------------------|
| Field extraction accuracy | ___ | ___ | ___ |
| Money-field accuracy | ___ | ___ | ___ |
| Valid JSON rate | ___ | ___ | ___ |
| Repair rate | ___ | ___ | ___ |
| Clause grounding rate | ___ | ___ | ___ |
| Anomaly precision | ___ | ___ | ___ |
| Anomaly recall | ___ | ___ | ___ |
| Latency / contract | ___ | ___ | ___ |
| Cost / contract | $0 | $0 | ___ |

**If fine-tuning doesn't win, report that.** A negative result with proper error analysis — *which* fields got worse, and your hypothesis about why, e.g. only 100 training examples, or CUAD's domain skew from Risk R1 — is a stronger piece of work than a table of convenient numbers. Examiners have seen a great many convenient tables.

## 📐 Deployment

1. Push to GitHub
2. Streamlit Community Cloud → connect the repo → point at `app/main.py`
3. Paste every secret into Streamlit Secrets (**never** commit `.env`)
4. Verify the deployed app reaches Supabase
5. Pre-load one demo run so the URL is never empty for a visitor

**`docs/demo_script.md`** — the five-minute walkthrough, timed:

| Time | Beat |
|------|------|
| 0:00 | The problem: a real contract, a real invoice, $21K quietly gone |
| 0:45 | Upload both files live |
| 1:30 | Anomalies appear, all four types |
| 2:15 | **Click a row → the clause highlights.** Pause here; this is the moment |
| 3:00 | Show the agent killing the "StarterLabs" false positive |
| 3:45 | Page 2: ask the hiring question, get the verdict |
| 4:30 | The results table: baseline vs. the model we trained |

## ✅ Definition of done
A public URL that works from a phone on mobile data. A results table with real numbers. A rehearsed demo.

---

# FINAL BUILD ARCHITECTURE

```mermaid
flowchart TB
    subgraph CLOUD["☁️ ALL CLOUD — no local GPU anywhere"]
        subgraph FE["🎨 Streamlit Community Cloud"]
            P1["Page 1: Integrity Engine"]
            P2["Page 2: Decision Engine"]
        end

        subgraph DATA["🗄️ Supabase"]
            DB[("Postgres — 12 tables")]
            ST[("Storage — uploaded PDFs")]
        end

        subgraph AI["🧠 Hosted inference (swappable, ADR-002)"]
            L1["Gemini / Groq / OpenRouter"]
            L2["Fine-tuned Qwen 3B<br/>Colab + tunnel"]
        end
    end

    subgraph LOCALCPU["💻 Runs in the app process — CPU only, free"]
        E1["pdfplumber — text PDFs"]
        E2["PyMuPDF — render + search_for"]
        E3["pandas — CSV"]
        E4["timeline_generator — pure math"]
        E5["reconciliation — pure math"]
    end

    subgraph OFFLINE["🔬 Offline / one-time"]
        D1["CUAD + SEC EDGAR"]
        D2["scenario_builder"]
        D3["Colab QLoRA training"]
    end

    P1 --> ST --> E1 --> L1
    L1 --> E2
    E2 --> DB
    DB --> E4 --> E5 --> DB
    DB --> AG["🕵️ LangGraph agent"] --> L1
    AG --> DB
    DB --> P1
    DB --> E6["cashflow math"] --> P2
    P2 --> L1
    D1 --> D2 --> DB
    D1 --> D3 --> L2
    L2 -.->|"LLM_PROVIDER=finetuned_tunnel"| AI
```

## The layer rules

| Layer | Does | Never does |
|-------|------|-----------|
| **Streamlit** | Renders DB rows, collects uploads | Computes anything, calls a model directly |
| **Extraction** | Files → text | Interprets meaning |
| **LLM** | Prose → structured data; phrases explanations | **Arithmetic. Anomaly decisions. Coordinates.** |
| **Engine** | All money math, pure functions | Network, database, model calls |
| **Agent** | Investigates flagged anomalies with tools | Runs over unflagged data |
| **Database** | Single source of truth | Business logic |

---

# API BUDGET (replaces v1's VRAM Budget)

v1 budgeted GPU memory because everything ran on one 3060. In v2 nothing loads onto your hardware, so the scarce resource changed: **requests per minute**.

| Operation | Calls | When |
|-----------|-------|------|
| Contract rule extraction | 1–3 per contract (chunked) | On upload, **cached** |
| CSV column mapping | 1 per new header signature | On upload, **cached by signature** |
| Agent verification | 2–6 per flagged anomaly | After reconciliation |
| Decision question parse | 1 | On question |
| Decision explanation | 1 | On verdict |

**A typical full run** — 5 contracts, 1 CSV, 7 anomalies: roughly **35–55 calls**. Comfortably inside free-tier daily limits, and comfortably *outside* per-minute limits if you fire them in a burst.

**Four rules that keep you inside the limits:**

1. **Cache everything.** `sha256(prompt + model)` → response, on disk. You will re-run the same contracts fifty times while debugging; only the first costs quota.
2. **Sequential, not parallel.** Add a small sleep between agent calls. Bursting is what trips per-minute limits, not volume.
3. **Two providers configured.** A dead key on demo day should be a one-line env change (Risk R3).
4. **Pre-run the demo documents.** On demo day, everything you show is already in the cache and responds instantly at zero quota.

> [!TIP]
> Free-tier quotas change often — check your provider's current limits before your demo rather than trusting a number written here.

---

# COMPLETE TECH STACK SUMMARY

| Layer | Tool | What It Does |
|-------|------|-------------|
| **Frontend** | Streamlit (multipage) | The web interface users interact with |
| **Hosting** | Streamlit Community Cloud | Public URL, free, GitHub-connected |
| **Database** | Supabase Postgres + SQLAlchemy | All extracted data, anomalies, references |
| **File storage** | Supabase Storage | Uploaded PDFs, signed-URL access |
| **PDF text** | pdfplumber | Text and tables from digital PDFs — the primary path |
| **PDF render + search** | PyMuPDF (fitz) | Page images, highlights, and `search_for()` clause grounding |
| **CSV** | pandas | Reads and cleans spreadsheet data |
| **OCR (fallback)** | Gemini vision, or Surya in Colab | Scanned documents only, never on the critical path |
| **LLM (baseline)** | Gemini / Groq / OpenRouter via `llm_client` | Contract prose → structured rules |
| **LLM (upgrade)** | Qwen 2.5 3B + QLoRA, Colab-served | The capstone comparison |
| **Structured output** | Pydantic + JSON mode + repair-retry | Valid, validated JSON (**not** Outlines — ADR-004) |
| **Clause grounding** | PyMuPDF text search + `thefuzz` | Real bounding boxes, never model-invented |
| **Client matching** | thefuzz | "Starter Labs" vs "StarterLabs" |
| **Agent framework** | LangGraph | The verification agent's ReAct loop |
| **Charts** | Plotly | Cash-flow projection on Page 2 |
| **Fine-tuning** | Unsloth + QLoRA | Trains the small model |
| **Training compute** | Google Colab / Kaggle (free T4) | Where fine-tuning happens |
| **Data sourcing** | HuggingFace `datasets`, SEC EDGAR API | Real contracts and invoices |
| **Testing** | pytest | The engine layer, which must be right |

---

# The Capstone Answer: Problem → Solution Narrative

> **How does your AI system solve the problem?**

The user opens FinSight at a public URL and sees two upload zones. In the first they drop their client contracts — typically PDF documents with tables setting out payment terms, billing frequencies and price escalation clauses. In the second they upload their billing records: invoice PDFs, bank statements, or CSV exports from their accounting workflow. A toggle tells the system which kind of file it's looking at.

On upload, each document is routed through the appropriate extraction path. Digital PDFs — which is what real contracts filed with regulators actually are — go through pdfplumber, which pulls text and table structure directly, instantly, at no cost. Scanned documents and images fall back to a cloud OCR path. CSVs are parsed with pandas, with the column mapping proposed by a language model from just the header row and three sample rows, then confirmed by the user in a dropdown so it can never silently mis-parse. At this point we have clean, machine-readable text from every uploaded document.

The contract text is then sent to a large language model through a provider-agnostic client, which forces a JSON-schema response, validates it against a Pydantic schema, and issues a single self-correcting repair call if validation fails. The model returns the client name, base fees, billing frequency, price escalation percentages and triggers, temporary discount terms, milestone payment conditions — and, critically, **the exact sentence each rule came from, copied verbatim**. It is not asked for page numbers or pixel coordinates, because a model reading text cannot know them. Instead, a separate deterministic step takes each verbatim quote and locates it in the source PDF using PyMuPDF's text search, with a fuzzy fallback for OCR noise. This yields a genuine bounding box, and it doubles as a hallucination check: a quote that cannot be found in the document was invented, and the rule is flagged low-confidence automatically. When multiple contracts arrive, the system groups them by client using fuzzy name matching and asks the user to confirm.

A deterministic Python engine — no AI, just arithmetic — then takes the extracted rules and generates an Expected Timeline: a month-by-month schedule of what *should* have been billed to each client, applying escalations at the correct anniversary dates and removing temporary discounts when they expire. This is compared against actual invoices and transactions, aggregated per client per calendar month. Every discrepancy is classified into one of four types: a Ghost Invoice (a billing that never happened), a Forgotten Raise (an escalation clause never applied), a Zombie Discount (a temporary discount never removed), or a Short-Change (a partial payment accepted without follow-up).

Before results are shown, a LangGraph ReAct agent reviews each flagged anomaly. It can re-read the original clause, search bank transactions for a payment near the missing amount, and check whether an expected sum was split across several transfers — filtering out false positives and attaching a reasoned explanation to each confirmed leak. In practice its most common catch is a client name that differs by a space or a suffix between the contract and the bank record.

The user sees summary cards (total leaked revenue, anomaly count, clients affected) and a detailed anomaly table. Clicking any row renders the original contract page as an image with the violated clause highlighted — showing exactly which contractual promise was broken, and where. When the clause cannot be located precisely, the system says so rather than highlighting the wrong paragraph. On a second page the user types a strategic question — *"Can I afford to hire a $5,000/month senior designer starting in September?"* The model parses the question into a structured cost and date; Python computes the cash-flow baseline from actual transactions, adds back only the **confirmed** recoverable revenue, subtracts the proposed cost, and produces a Yes or No. The model then phrases those computed figures in two or three sentences. It never calculates any of them.

Everything runs in the cloud on free tiers, requires no GPU, no accounting-software integration, and no local installation — and every anomaly it reports can be traced back to a specific sentence in a specific contract on a specific page.

---

# Verification Plan

## Automated tests

| Test | Owner | What it proves |
|------|-------|----------------|
| `test_timeline.py` — known contract rules → known timeline | A | The math is right. **The most important test file in the project** |
| `test_reconciliation.py` — known expected + actuals → known anomalies | B | Detection logic is right |
| `test_clause_locator.py` — known clause text → known page | A | Grounding works on real PDFs |
| Scenario regression — all three Phase 3 scenarios vs `ground_truth.json` | A | End-to-end precision and recall |
| **Clean-client test** — the `edge` scenario returns zero anomalies | B | **No false positives.** The one examiners ask about |
| Extraction eval — held-out set, per-field accuracy | A | Model quality, measured not assumed |

## Manual verification

- Upload a real CUAD contract never seen during development; check extraction by hand
- Click all four anomaly types; verify each highlight is on the right clause
- Force an ungrounded clause; verify the UI degrades honestly instead of crashing
- Force a malformed CSV; verify the column mapper recovers
- Ask the Decision Engine four different questions; check every number in every explanation against the computed figure
- Open the deployed URL on a phone, on mobile data, with the laptop closed

## The three demo scenarios

| Scenario | Contains | Proves |
|----------|----------|--------|
| `easy` | All four anomaly types, minimal noise | The core pipeline works |
| `realistic` | Noise, name variants, split payments | The agent earns its place |
| `edge` | A clean client, no anomalies at all | **You discriminate rather than just flag** |

---

# Quick Reference — The Rules That Matter

1. **The LLM never does arithmetic.** Ever.
2. **The LLM never produces bounding boxes.** Verbatim `clause_text` in, `clause_locator` finds the box.
3. **The UI reads only the database.** Never a hardcoded dict.
4. **Every anomaly traces to a clause reference.** No orphans.
5. **Engine functions are pure.** No DB, no network, no model.
6. **Nobody edits a file they don't own.** Ask.
7. **Interfaces go in `memory/interfaces.md` before implementations.**
8. **Update `memory/progress.md` at the end of every phase.** Five minutes. Non-negotiable.
9. **Read the memory files and print the summary before every phase.** No summary, no code.
10. **The held-out eval set is created before training and never trained on.**
