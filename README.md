# 💸 FinSight

**You are owed money you don't know about. Here it is, here is the exact clause that proves it, and here is what it changes about the decision you're trying to make.**

FinSight reads a small B2B service business's client contracts, compares them against its actual invoices and bank transactions, and finds revenue that was contractually owed but never collected. Every finding traces back to a specific sentence on a specific page of a specific contract. A second page then answers a strategic question — *"can I afford a $5,000/month hire starting in September?"* — with the recovered money factored in.

> **Status: Phase 0 of 12 — Foundations.** The repo skeleton, dependencies, and configuration loader exist. There are no features yet. `streamlit run app/main.py` shows the resolved configuration and nothing else. See [`docs/progress.md`](docs/progress.md) for what is actually built and [`docs/implementation_plan.md`](docs/implementation_plan.md) for what comes next.

---

## The problem

A studio signs a contract: $6,000/month, 10% discount for the first three months, 8% increase on the anniversary, plus a $15,000 milestone on launch.

Eighteen months later, whoever set up the recurring invoice has left. The invoice still says $6,000. The 8% increase was never applied. The intro discount was never switched off in month four. The milestone was delivered but never billed. That is roughly **$21,000 gone** — not stolen, just never noticed.

Accounting software cannot catch this, because accounting software has never read the contract.

## The four leak types

| | Type | What happened |
|---|---|---|
| 🔴 | **Ghost Invoice** | An expected billing that never happened at all |
| 🟡 | **Forgotten Raise** | A price escalation clause that was never applied |
| 🟠 | **Zombie Discount** | A temporary discount that was never switched off |
| 🟣 | **Short-Change** | A partial payment accepted with no follow-up |

The load-bearing principle: **the LLM only reads documents and turns prose into structured data.** It never does arithmetic, never decides whether something is an anomaly, and never produces a number the user sees. All money math is deterministic Python. That is what makes the results defensible.

---

## Quickstart

### 1. Prerequisites

- **Python 3.11 or 3.12.** Some dependencies (`pymupdf`, `psycopg2-binary`) may not have wheels for the newest releases yet; Streamlit Community Cloud runs 3.11–3.12, so match it.
- A free account at each of: [Supabase](https://supabase.com), [Google AI Studio](https://aistudio.google.com/apikey), [Groq](https://console.groq.com/keys), [HuggingFace](https://huggingface.co/settings/tokens), [Streamlit Community Cloud](https://share.streamlit.io). About 20 minutes total. See [Getting the keys](#getting-the-keys).

### 2. Install

```bash
git clone <this-repo> finsight
cd finsight

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
```

Open `.env` and fill it in. **The only thing you strictly need to start is the API key for your chosen `LLM_PROVIDER`** — everything else has a working default or is needed in a later phase.

Leave `DATABASE_URL` blank (or as the unedited placeholder) and FinSight falls back to `sqlite:///data/finsight.db`, which is enough for offline work.

### 4. Run

```bash
streamlit run app/main.py
```

The config page lists every variable with **✅ set · ❌ required and missing · ⚪ optional, needed in a later phase**, with every secret masked to `AIza...4f2a`. If a required variable is missing, the page says so by name at the top instead of failing somewhere deep in the stack an hour later.

---

## Environment variables

All of these live in `.env` locally and in **Streamlit Secrets** when deployed. `.env` is gitignored and must never be committed.

| Variable | Required | Default | What it's for |
|---|---|---|---|
| `LLM_PROVIDER` | ✅ | `gemini` | `gemini` \| `groq` \| `openrouter` \| `finetuned_tunnel`. The one variable that swaps models (ADR-002). |
| `LLM_MODEL` | — | per provider | Model name. Defaults sensibly for whichever provider is active. |
| `GEMINI_API_KEY` | ✅ if provider is `gemini` | — | [Google AI Studio](https://aistudio.google.com/apikey). The primary baseline. |
| `GROQ_API_KEY` | ✅ if provider is `groq` | — | [Groq](https://console.groq.com/keys). The backup — configure it too, so a dead key on demo day is a one-line fix. |
| `OPENROUTER_API_KEY` | ✅ if provider is `openrouter` | — | [OpenRouter](https://openrouter.ai/keys). |
| `FINETUNED_TUNNEL_URL` | ✅ if provider is `finetuned_tunnel` | — | Filled in Phase 10, when Colab serves our own model over a tunnel. |
| `DATABASE_URL` | — | SQLite fallback | Supabase Postgres URI. Blank → `sqlite:///data/finsight.db`. |
| `SUPABASE_URL` | Phase 1 | — | Supabase project URL, for file storage. |
| `SUPABASE_KEY` | Phase 1 | — | Supabase anon key. |
| `HF_TOKEN` | Phase 3 | — | HuggingFace read token, for downloading the contract and invoice corpora. |
| `LLM_CACHE_ENABLED` | — | `true` | Cache LLM responses on disk by `sha256(prompt + model)`. Keep this on — you will re-run the same contracts fifty times while debugging, and only the first costs quota. |
| `LOG_LEVEL` | — | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`. |

Two conveniences worth knowing:

- **Unedited placeholders count as unset.** If you copy `.env.example` and leave `DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[REF]...` as-is, FinSight treats it as blank and uses SQLite rather than failing at the first connection with a confusing error.
- **Switching provider needs no code change.** Set `LLM_PROVIDER=groq`, make sure `GROQ_API_KEY` is set, restart. That is the whole procedure — including switching to the model we fine-tune ourselves in Phase 10.

### Getting the keys

| Account | What to copy | Where it goes |
|---|---|---|
| **Supabase** → new project | Settings → Database → Connection string (URI) | `DATABASE_URL` |
| | Settings → API → Project URL and anon key | `SUPABASE_URL`, `SUPABASE_KEY` |
| **Google AI Studio** | Create API key | `GEMINI_API_KEY` |
| **Groq** | Create API key | `GROQ_API_KEY` |
| **HuggingFace** | Settings → Access Tokens → read token | `HF_TOKEN` |
| **Streamlit Community Cloud** | Sign in with GitHub | Deployment only, no key |

---

## Commands

```bash
streamlit run app/main.py        # the app  (Phase 0: the config page)

python scripts/memory_digest.py  # compact "where are we" summary for an AI session
```

These exist as stubs and land in the phase noted:

```bash
python scripts/init_db.py        # Phase 1 — create all 12 tables
python scripts/seed_demo.py      # Phase 2 — load a built scenario into the DB
python scripts/reset_run.py      # Phase 2 — wipe one run, keep the others
```

### Tests

```bash
pytest                                       # everything
pytest tests/test_timeline.py                # the most important file in the project
pytest tests/test_timeline.py::test_name -v  # one test
pytest -k discount                           # by keyword
```

The test files are docstring-only stubs until Phase 6, so `pytest` currently collects nothing and exits 5. What matters most is `tests/test_timeline.py`: when an examiner asks *"how do you know $6,480 is right?"*, the answer needs to be a fifteen-line pure function and a known-answer test, not a model's opinion.

---

## Layout

```
app/            [B] Streamlit: pages/ and components/. Renders DB rows, computes nothing.
core/
  config.py     [B] The one settings object. Nothing else reads os.environ.
  extraction/   Files in, text out. Plus clause_locator — real bboxes, never model-invented.
  ai/           Everything that talks to a model. Prose in, validated Pydantic out.
  engine/       All money math. Pure functions: no DB, no network, no LLM.
  agents/       LangGraph verification agent and its four DB-backed tools.
  db/           SQLAlchemy models, session factory, read helpers.
  storage/      Supabase Storage.
data_sourcing/  One-time sourcing of real contracts (CUAD, SEC EDGAR) + scenario building.
training/       QLoRA fine-tuning pipeline and the evaluation harness.
scripts/        Operational entry points.
tests/          pytest. The engine layer is what must be right.
docs/           Planning + the memory system. Read these first.
data/           Gitignored: sourced corpora, built scenarios, uploads, LLM cache.
```

Every file is tagged `[A]` or `[B]` in its docstring and in the directory tree in [`docs/implementation_plan.md`](docs/implementation_plan.md).

---

## Deployment

Streamlit Community Cloud, connected to this GitHub repo, main file `app/main.py`.

Secrets go in **Settings → Secrets** as TOML — never in the repo:

```toml
DATABASE_URL = "postgresql://postgres:...@db....supabase.co:5432/postgres"
SUPABASE_URL = "https://....supabase.co"
SUPABASE_KEY = "..."
LLM_PROVIDER = "gemini"
LLM_MODEL = "gemini-2.5-flash"
GEMINI_API_KEY = "..."
GROQ_API_KEY = "..."
HF_TOKEN = "..."
LLM_CACHE_ENABLED = "true"
LOG_LEVEL = "INFO"
```

`core/config.py` reads `.env` locally and `st.secrets` when deployed, with no code change between the two.

---

## How we work

Two people, twelve phases, many separate AI sessions. Three rules keep that from diverging:

1. **One owner per file.** Files are tagged `[A]` (data & determinism) / `[B]` (interface & intelligence). Need a change in a file you don't own? Ask — don't edit.
2. **Interfaces before implementations.** A signature that crosses the A/B boundary goes into [`docs/interfaces.md`](docs/interfaces.md) *before* it is implemented, so the other person can code against a stub immediately and neither of you blocks.
3. **Both people work every phase.** Nobody waits.

At the end of every phase, five minutes: append to `docs/progress.md`, flip statuses in `docs/interfaces.md`, add any ADR to `docs/decisions.md`, update `docs/state.json`, commit as `memory: close phase N`. The full ritual is in [`docs/memory_system.md`](docs/memory_system.md).

### Read these, in this order

| File | Answers |
|---|---|
| [`docs/project_context.md`](docs/project_context.md) | What are we building, and with what? |
| [`docs/progress.md`](docs/progress.md) | What already exists? *(append-only — if it isn't here, it doesn't exist)* |
| [`docs/interfaces.md`](docs/interfaces.md) | What can I call, and what will it return? |
| [`docs/decisions.md`](docs/decisions.md) | Why is it this way and not the obvious other way? |
| [`docs/state.json`](docs/state.json) | Where are we right now? |
| [`docs/implementation_plan.md`](docs/implementation_plan.md) | The full 12-phase plan, with a copy-paste prompt per phase. |

### The rules that matter

1. The LLM never does arithmetic. Ever.
2. The LLM never produces bounding boxes — it returns verbatim `clause_text`, and `clause_locator.py` finds the coordinates.
3. The UI reads only the database, never a hardcoded dict.
4. Every anomaly traces to a clause reference. No orphans.
5. Engine functions are pure: no DB, no network, no model.
6. No local GPU in the runtime path.
7. No secrets in git.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `FinSight cannot start. Fix these in .../.env` | Working as designed — it names the missing variable. Fill it in and rerun. |
| Config page shows `Config source: environment only` | No `.env` found and no Streamlit secrets. Did you `cp .env.example .env` in the repo root? |
| `DATABASE_URL` shows `—` though you set it | The value still contains the `[PASSWORD]` / `[REF]` placeholders, so it is treated as unset. |
| Sidebar shows three blank pages | Expected until Phase 2 — `app/pages/*.py` are stubs. |
| `pytest` exits 5, "no tests ran" | Expected until Phase 6 — the test files are stubs. |
| `pip install` fails on `pymupdf` or `psycopg2-binary` | You are probably on a Python version with no wheels yet. Use 3.11 or 3.12. |

---

## Data & licences

Contracts are **sourced**, never generated: [CUAD v1](https://huggingface.co/datasets/theatticusproject/cuad) (510 real expert-annotated commercial contracts, CC BY 4.0) and SEC EDGAR EX-10 filings. Invoice ledgers and bank transactions are **derived** from those contracts' true terms by deterministic arithmetic in `data_sourcing/scenario_builder.py`, which plants known anomalies and writes the matching `ground_truth.json`. No model invents a contract, and every reported anomaly can be scored against ground truth.
