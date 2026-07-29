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

And the model doing that reading is **ours** — an open-source model we tune and host on free Colab/Kaggle GPU. No frontier model API is called anywhere in this project (ADR-011).

---

## Quickstart

### 1. Prerequisites

- **Python 3.11 or 3.12.** Some dependencies (`pymupdf`, `psycopg2-binary`) may not have wheels for the newest releases yet; Streamlit Community Cloud runs 3.11–3.12, so match it.
- A free account at each of: [Supabase](https://supabase.com), [Google Colab](https://colab.research.google.com), [Kaggle](https://www.kaggle.com), [HuggingFace](https://huggingface.co/settings/tokens), [Streamlit Community Cloud](https://share.streamlit.io). About 20 minutes total. See [Getting the keys](#getting-the-keys).
- **From Phase 5 onward, a running Colab or Kaggle notebook serving the model.** There is no vendor API behind this app — see [Where the intelligence runs](#where-the-intelligence-runs).

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
```pip install -r requirements.txt


Open `.env` and fill it in. **The only things you strictly need to start are the tunnel URL for your chosen `LLM_PROVIDER` and `LLM_API_KEY`** — everything else has a working default or is needed in a later phase. Until Phase 5 stands the notebook up, nothing calls the endpoint, so placeholder values are fine for now.

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
| `LLM_PROVIDER` | ✅ | `colab_tunnel` | `colab_tunnel` \| `kaggle_tunnel` \| `custom`. The one variable that swaps endpoint (ADR-002). |
| `COLAB_TUNNEL_URL` | ✅ if provider is `colab_tunnel` | — | The `https://….trycloudflare.com` URL your notebook printed. **Changes every restart.** |
| `KAGGLE_TUNNEL_URL` | ✅ if provider is `kaggle_tunnel` | — | Same, for the backup session. |
| `CUSTOM_BASE_URL` | ✅ if provider is `custom` | — | Any other OpenAI-compatible endpoint. |
| `LLM_API_KEY` | ✅ | — | Shared secret the notebook checks. A quick tunnel is a **public URL** — without this, anyone who finds it gets free inference on your GPU quota. |
| `LLM_MODEL` | ✅ | `Qwen/Qwen2.5-3B-Instruct` | The served model name. Becomes `finsight-qwen2.5-3b` in Phase 10 — that one value is the whole base-vs-tuned comparison. |
| `LLM_TIMEOUT_SECONDS` | — | `120` | A cold start loads 3B of weights before answering. |
| `DATABASE_URL` | — | SQLite fallback | Supabase Postgres URI. Blank → `sqlite:///data/finsight.db`. |
| `SUPABASE_URL` | Phase 1 | — | Supabase project URL, for file storage. |
| `SUPABASE_KEY` | Phase 1 | — | Supabase anon key. |
| `HF_TOKEN` | Phase 3 | — | HuggingFace read token — the contract/invoice corpora, and the model weights in Phase 5. |
| `LLM_CACHE_ENABLED` | — | `true` | Cache responses on disk by `sha256(prompt + model)`. Keep this on: it is what lets a demo survive the tunnel dying. |
| `LOG_LEVEL` | — | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`. |

Three conveniences worth knowing:

- **Unedited placeholders count as unset.** If you copy `.env.example` and leave `DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[REF]...` as-is, FinSight treats it as blank and uses SQLite rather than failing at the first connection with a confusing error.
- **Paste the tunnel URL in whatever shape the notebook gives you.** `https://x.trycloudflare.com`, `.../v1`, or `.../v1/chat/completions` all normalise to the same thing.
- **Switching endpoint needs no code change.** Set `LLM_PROVIDER=kaggle_tunnel`, make sure `KAGGLE_TUNNEL_URL` is set, restart. That is the whole procedure — and swapping base weights for our tuned adapter in Phase 10 is likewise just `LLM_MODEL`.

### Getting the keys

| Account | What to copy | Where it goes |
|---|---|---|
| **Supabase** → new project | Settings → Database → Connection string (URI) | `DATABASE_URL` |
| | Settings → API → Project URL and anon key | `SUPABASE_URL`, `SUPABASE_KEY` |
| **Google Colab** | Sign in. From Phase 5 it runs `training/serve_model.py` and prints a tunnel URL | `COLAB_TUNNEL_URL` |
| **Kaggle** | Sign in, verify the account for GPU. The backup session | `KAGGLE_TUNNEL_URL` |
| **HuggingFace** | Settings → Access Tokens → read token | `HF_TOKEN` |
| **Streamlit Community Cloud** | Sign in with GitHub | Deployment only, no key |

`LLM_API_KEY` is not issued by anyone — invent a long random string, put it in `.env`, and have the serving notebook reject requests without it.

> Earlier drafts of this project used Google AI Studio and Groq API keys. **They are not used and not needed** — see [ADR-011](docs/decisions.md).

## Where the intelligence runs

**No frontier model API is called anywhere in this project** (ADR-011). Every model call — contract extraction, CSV column mapping, agent verification, the decision engine — goes to an open-source model we host ourselves:

```
Colab / Kaggle notebook (free T4)
  Qwen 2.5 3B Instruct              base weights, live from Phase 5
  + our QLoRA adapter               from Phase 10
  -> FastAPI /v1/chat/completions
  -> Cloudflare tunnel -> public https URL
                                    |
FinSight (Streamlit Cloud)  --------+  LLM_PROVIDER + <provider>_TUNNEL_URL
```

Phase 5 stands the notebook up on **base** weights so the rest of the build has something to call; Phase 10 trains the adapter and serves it under a second model name; Phase 11 measures base against tuned on identical weights (ADR-012).

**What this costs you, stated plainly.** Availability is now a notebook session rather than a vendor's uptime:

| Reality | What you do about it |
|---|---|
| The tunnel URL changes on **every** notebook restart | Update `.env`, or Streamlit Secrets — no redeploy needed |
| Sessions expire and disconnect when idle | Keep the Kaggle session configured as a backup; start the notebook *before* a demo |
| Cold start loads 3B of weights — minutes | Generous timeout, one retry, and send a warm-up request yourself |
| A dead session takes the whole app down | Pre-warm `data/cache/` with every demo document, and record a video of the live path |

That last row is the largest operational risk in the project. It was accepted knowingly, in exchange for a system whose weights, tuning and serving are entirely ours to explain — and for results that are reproducible, because nobody can change the model out from under us between the evaluation run and the demo.

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
training/       serve_model.py (live from Phase 5), QLoRA fine-tuning, evaluation harness.
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
LLM_PROVIDER = "colab_tunnel"
COLAB_TUNNEL_URL = "https://....trycloudflare.com"
KAGGLE_TUNNEL_URL = "https://....trycloudflare.com"
LLM_API_KEY = "..."
LLM_MODEL = "Qwen/Qwen2.5-3B-Instruct"
LLM_TIMEOUT_SECONDS = "120"
HF_TOKEN = "..."
LLM_CACHE_ENABLED = "true"
LOG_LEVEL = "INFO"
```

`core/config.py` reads `.env` locally and `st.secrets` when deployed, with no code change between the two.

> **You will edit `COLAB_TUNNEL_URL` in Streamlit Secrets on the morning of every demo**, because it changes when the notebook restarts. Confirm early that this takes effect without a redeploy — that check is part of Phase 11's definition of done.

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
6. No local GPU in the runtime path — the GPU is a free Colab/Kaggle T4 reached over HTTP.
7. **No frontier model API calls, ever.** Adding a vendor SDK to `requirements.txt` is a violation, not a shortcut.
8. No secrets in git.

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
| `COLAB_TUNNEL_URL is not set` | Expected before Phase 5 — nothing serves the model yet. Put any `https://` placeholder in to get past it. |
| The app can't reach the model *(Phase 5+)* | The notebook restarted and the tunnel URL changed. Copy the new one into `.env` / Streamlit Secrets. |
| First request after starting the notebook times out | Cold start: 3B of weights are loading. Raise `LLM_TIMEOUT_SECONDS`, send one warm-up request, then use the app. |

---

## Data & licences

Contracts are **sourced**, never generated: [CUAD v1](https://huggingface.co/datasets/theatticusproject/cuad) (510 real expert-annotated commercial contracts, CC BY 4.0) and SEC EDGAR EX-10 filings. Invoice ledgers and bank transactions are **derived** from those contracts' true terms by deterministic arithmetic in `data_sourcing/scenario_builder.py`, which plants known anomalies and writes the matching `ground_truth.json`. No model invents a contract, and every reported anomaly can be scored against ground truth.
