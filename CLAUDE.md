# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

**Phases 0–9 of 12 are complete, and 0–8 were re-verified from a clean checkout on 2026-08-17** before Phase 9 was started — every command in this file's *Commands* section was actually run, not trusted. Phase 0 (skeleton, deps, `core/config.py`, config page, digest) was installed and run for real on 2026-08-08 — all 16 deps import, `streamlit run app/main.py` renders with zero exceptions.

**Read this before believing any figure below.** That audit found three real defects and one urgent one, all recorded in `docs/progress.md` → *"Audit — Phases 0–8 re-verified"*:
1. **The live `LLM_API_KEY` was committed to this public repo** and is still in its history (#66). Redacted now; **it must be rotated** — see hard rule 8.
2. **Modal serving existed in no memory file at all** (#67) — now ADR-023.
3. The uploader advertised `.txt`/`.docx` contracts that always failed (#68) — `.txt` now works, `docx` removed.
4. Phase 8's UI copy still called the verification agent future work; the mechanism was fine, only the strings were stale.

What *did* hold, measured: 155 pytest assertions, all three engine scenarios exact to the cent, 20/20 clause pages rendering as real PNGs through the HTTP route, every `web/` route in both modes, all 5 Streamlit pages, and the database invariants (no anomaly without a clause, `gap == expected − actual` everywhere, only the four leak types).

**Phase 1 (database) is complete and live on Supabase.** All 12 tables in `core/db/models.py`, engine/session in `core/db/database.py`, 13 read helpers in `core/db/queries.py`, plus `scripts/init_db.py`, `scripts/reset_run.py` and `app/pages/9_db_health.py`. The same 47 assertions pass identically on SQLite and on Postgres; ADR-005 nullability and all six `CheckConstraint`s are confirmed in `information_schema`. **All 12 tables exist and are empty** — that is the correct state; Phase 2's `scripts/seed_demo.py` fills them.

**Phase 2 (frontend shell) is complete.** The whole UI exists and reads real Supabase rows — landing page, Revenue Integrity dashboard, Decision Engine, DB Health, plus six components and `app/state.py`. `scripts/seed_demo.py` writes an internally consistent demo run ($26,908 across 7 findings, all four leak types, 3 of 5 clients) where `gap == expected - actual` and `total == sum(gaps)` hold *by construction*. **There is no hardcoded dict anywhere in `app/`** — that is what makes Phase 6 a data change rather than an integration project.

**Phase 3 (data sourcing) is complete.** `data_sourcing/{fetch_contracts,filter_contracts,fetch_invoices,scenario_builder}.py` are real. `core/ai/schemas.py` was pulled forward here.

**Phase 4 (text extraction) is complete.** Uploads route through `document_router.extract()` (PDFs/images) or a human-confirmed CSV column mapping (ADR-010) that writes `actual_transactions`. `csv_parser.sniff_columns()` is a `thefuzz` heuristic, not an LLM call.

**Phase 5 (LLM extraction) is complete and measured.** On 2026-08-14 a Colab T4 served base Qwen 2.5 3B under vLLM 0.27.1 and `scripts/eval_extraction.py --limit 10 --pdfs 5` scored **10/10 valid `ContractRules`**, **80.0% text grounding** (12 of 15 quotes) and **2/2 PDF locations** — all three targets met. Read known issues #48/#49 before quoting them: grounding passed *exactly* on the line, and 3 of the 10 contracts extracted zero clauses yet still counted as valid, while one contract produced 7 of the 12 grounded quotes. **Kaggle and the `--backend transformers` fallback have still never run on a GPU.** Running it for real also found two Colab-only traps recorded in `README.md` → *Starting a session* (known issue #50): notebook secrets are unreachable from a `!python` subprocess, and unpinned `pip install vllm` breaks Colab's preinstalled `torchaudio`. Written: `training/serve_model.py` (one file that serves Qwen 2.5 3B on **either Colab or Kaggle** — detects the host, reads `LLM_API_KEY` from its secret store, vLLM by default with a transformers fallback, Cloudflare tunnel, `--self-test`), `core/ai/{endpoints,llm_client,cache,prompts,contract_extractor,client_matcher}.py`, `core/extraction/clause_locator.py`, `app/pages/8_model_endpoint.py`. Re-measure with `python scripts/eval_extraction.py --limit 10 --pdfs 5` against a live endpoint; results land in `data/eval/phase5_extraction.json`. Client-side behaviour is separately verified: `python scripts/verify_llm_stack.py` drives 21 assertions against a stub server with no GPU. Setup walkthrough: `docs/serving_setup.md`.

**Phase 6 (timeline & reconciliation) is complete and measured.** The findings in the database are now **computed, not seeded**, and no template in either frontend changed to make that happen (ADR-008 paying off). `core/engine/{timeline_generator,reconciliation,anomaly_classifier}.py` are pure — no DB, no network, no model, **and no clock**: the billing window is passed in, so a run reconciling a 2025 statement gives the same answer in 2027. On 2026-08-16 `python scripts/eval_engine.py` reproduced all three scenarios' `ground_truth.json` **exactly** — easy 7 findings/$17,815.00, realistic 5/$22,500.00, edge 0/$0.00 — and `pytest` runs **74 assertions** in under a second. `core/engine/pipeline.py` is new and **not in the plan's tree**: it is the only place engine output becomes rows (`compute_run`, `persist_rules`), it is idempotent, and it is what keeps a `session` argument out of the maths. `scripts/run_scenario.py` loads a built scenario's *inputs* into a real run and lets the engine produce the findings — runs 12/13/14 in Supabase are exactly that. Reconciliation is reachable from the UI at `app/pages/1_integrity_engine.py` → **3 · Reconcile**, the first action in the app that computes rather than reads. Two new ADRs: **ADR-019** (a payment settles the most recent billing on or before its date, not the nearest one — read it before "fixing" a ghost invoice next to a surplus) and **ADR-020** (attribution refuses below 85, or within 6 points of a runner-up, rather than guessing which client sent the money). Four things it deliberately does not do: bill an undated milestone (#55), compound-match `scenario_builder`'s single escalation (#54 — the engine is the correct side), write anything from `web/` (#56), or resolve a two-months-in-one-transfer payment (#57, Phase 8's job).

**Phase 7 (clause viewer) is complete and measured.** Clicking a finding shows the contract page with the clause boxed on it, in **both** frontends. The blocker it had to clear first was known issue #28 — EDGAR serves HTML, so the primary corpus had no PDF to highlight — and **ADR-021** settles it: `core/extraction/pdf_renderer.typeset_pdf` lays a document's extracted text out as a real, searchable, **deterministic** PDF (same text, same page breaks, or every stored `source_page` silently rots), cached by content hash under `data/cache/pdf/`. Every such page says so — in the PDF's own footer, in the Streamlit caption and in the `web/` figure caption — because *a typeset page is not the filing as filed*: its line breaks and page numbers are ours, so "page 61" will not match EDGAR. Measured on 2026-08-16: **20 of 20 clauses across runs 12/13/14 placed on a page** (18 exact, 2 fuzzy), each box checked against the text it actually sits on, and 107 pytest assertions pass. `clause_locator` was hardened — the box is the union of every line a match spans, the longest probe wins, typography is folded, and the fuzzy tier matches page-wide through a word index. **Two wrong highlights were found by looking at rendered pages, not by tests** (#58: `partial_ratio` scores a lone "5" at 100 against any quote containing a 5; #59: quotes wrapped in `...` never match exactly) — both are now regression-tested. `web/` gained `GET /clause/{id}/page.png`; it is still read-only.

**Phase 9 (decision engine) is complete and measured.** A plain-English question produces a Yes/No backed by the user's own figures. `core/engine/cashflow.py` does every calculation and, like Phase 6's engine, **takes no clock** — projection labels are `M1..Mn` because it cannot know what month it is. `core/ai/decision_analyzer.py` is the model's two ends: it reads the sentence and phrases the finished numbers. On 2026-08-17 `python scripts/eval_decision.py` passed **6 of 6 cases** on both the verdict *and* the after-decision figure, with **0 invented numbers** in any explanation, and `pytest` runs **233 assertions**. Three departures from the plan, each deliberate and each regression-tested — read them before "fixing" any of them back:
- **The money is read by regex, not by the model** (#73). `monthly_cost` is a number the user sees and it drives the verdict; a 3B model reading `$5,000` as `50000` flips a YES to a NO with nothing on screen looking wrong. `extract_cost` is deterministic and returns the substring it matched so the page can prove the figure is the user's own. The model supplies only `what`/`start_month`, plus an amount when the pattern found none — and then it must be confirmed (ADR-010's shape).
- **`recovered_monthly` divides by the run's real window, not the plan's hardcoded 12** (#72). On a six-month run `/12` halves the run-rate, enough to flip a verdict.
- **`explain_verdict` rejects its own output** if it quotes a figure it was not given, retries once, then falls back to a deterministic sentence. The plan calls this "the most likely place in the whole project for a plausible-sounding wrong number to reach a user" and asks for an assertion; this is the runtime guard as well as the assertion.

**ADR-024 is the one to read first about Phase 9.** No table holds expenses, so a surplus is not derivable from the database — the user types their monthly running costs, and with none supplied the engine **refuses a Yes/No** and reports the commitment as a share of revenue instead. `monthly_expenses`/`monthly_surplus` are `None` for unknown, never `0.0` (which would assert break-even). Consequence to disclose: FinSight computes what you are owed and what you earn; *you* tell it what you spend. A verdict is therefore not reproducible from `run_id` alone and nothing persists one.

**There are now two frontends over one database, and both work (ADR-018).** `app/` is the original Streamlit shell and keeps the operational pages (config ✅/❌ table, DB health, model-endpoint switcher, uploads). `web/` is a FastAPI + Jinja2 app that renders the delivered design — `python run_web.py`. Neither is deprecated, neither is kept in visual sync with the other, and **both read only through `core.db.queries`**, so they can differ in appearance but not in figures. `web/` **writes nothing**: every button is inert. Some of those actions now exist — reconciliation shipped in Phase 6 — but they live in `app/`, so the tooltips say which frontend to use rather than naming a phase (known issues #52, #56). Inside `web/`, a state-bar toggle picks between `presenters/demo.py` (the mockup's own content, transcribed — the reference render) and `presenters/live.py` (the database). **They never call each other and live never falls back to demo**: a missing figure renders as a skeleton and a dashed box naming the phase that fills it. Default mode is `WEB_DATA_MODE` in `.env`; the on-page toggle overrides it per browser via a cookie. Both presenters return the same dataclasses from `web/viewmodels.py` — add a field and you must fill it in both. The findings screen is a **master-detail split** (list pane + detail pane, each scrolling itself); `GET /finding/{id}` returns just the detail pane and `app.js` prefetches it on hover, so selection never reloads the page. **Performance is query count, not SQL** (known issue #53): Supabase is in ap-southeast-1 at ~400 ms per round trip, so a live page costs `queries × 400 ms`. It was cut 35 → 9; `web/cache.py` then caches reads for `WEB_CACHE_SECONDS` (default 15), which is safe only while `web/` writes nothing — **the first write path must call `web.cache.clear()`**.

**There are three peer inference hosts, not two, and not a primary with backups (ADR-016 + ADR-023).** Colab, Kaggle **and Modal**. All their URLs live in `.env` at once; the active one is `LLM_PROVIDER` or the in-app radio on the Model endpoint page. `core/ai/endpoints.py` resolves the URL at *call* time over a `data/endpoint_override.json` layer, so swapping hosts needs no restart — `settings` is `lru_cache`d and cannot express a URL that rotates. The disk cache is keyed on prompt + model and **not** on the endpoint, which is what makes the hosts interchangeable. `LLM_FAILOVER` defaults to true and the app always says which host answered.

**Modal (ADR-023) is the one whose URL does not rotate**, which is why `endpoints.fallback()` reaches for it *first* when the active host has just died. `training/serve_modal.py` serves the same Qwen 2.5 3B under the same pinned vLLM behind the same routes — **rented hardware, not a vendor model API, so ADR-011 is untouched**: the distinction that matters for the self-hosting claim is whose *weights*, not whose electricity. Two things to know before touching it: `USE_MODAL=true` is resolved *above* `LLM_PROVIDER` and is **not** `LLM_FAILOVER` (failover reacts after a break; `USE_MODAL` decides where calls go in the first place — the "live demo, use the paid host" switch), and it **bills per GPU-second**, so it is the first component in the project that costs money. **It has never been deployed from this repo** — no `modal deploy` has run, so do not quote cold-start or cost figures. ADR-023 was written *retroactively* on 2026-08-17: the feature shipped with no memory-file entry at all (known issue #67), which is the exact failure the end-of-phase ritual below exists to prevent.

Still stubs: `core/extraction/ocr_cloud.py`, `training/{build_pairs,evaluate}.py`. (`core/agents/` came off this list in Phase 8; `core/engine/cashflow.py` and `core/ai/decision_analyzer.py` came off in Phase 9.)

What the UI deliberately does *not* do yet: let a human override an agent verdict by hand (neither frontend), or write anything at all from `web/` (ADR-018 — reconcile, verify and ask a decision question from the Streamlit app). Agent verdicts and the Decision Engine's answer **do** now show — the question box is read (Phase 9), and `web/`'s copy of it names the Streamlit app because a verdict needs a question *and* an expense figure, neither of which a read-only frontend can collect. Extraction-on-upload is wired in `app/` (Phase 6) but has **never run end to end against a live GPU** (known issue #41). Each says so on screen rather than implying otherwise — and when a phase closes, **go and fix the copy that called it future work**: Phase 8 shipped with four UI strings still saying the agent "lands in Phase 8", caught only by the audit. Name the surface that fills a gap, never a phase number.

**Supabase Storage is live** — private bucket `finsight-documents`, reached with `SUPABASE_SERVICE_KEY` (service_role) because the anon key gets a 403 from RLS on a private bucket. That key is safe here *only* because Streamlit renders server-side; it must go into Streamlit Secrets, never the repo. **Object keys are content-addressed** (`<run_id>/<sha256[:12]>_<name>`) because Supabase's CDN ignores `cache-control` and serves stale bytes after a re-upload — verified, and it survives deletion. Never build a bucket key by hand; use `files.save_upload` and the `documents.storage_url` it returns.

**A pre-Phase-3 spike ran on 2026-08-10 and changed the data source (ADR-013 + ADR-014).** Before writing any Phase 3 code, the plan's untested assumption was tested: *do real CUAD contracts contain the billing rules FinSight looks for?* Mostly not. **8 of 510 (1.6%)** carry both a real recurring amount and a real escalation clause; **3** survive a hand read. EDGAR, aimed at service agreements, hits **17.7%**. So **EDGAR is now the primary source and CUAD is demoted** to extraction development and training volume.

**`data/` is gitignored, so no corpus survives a machine change — verify before building on it.** The spike's `contracts_v0/` was gone by the time Phase 3 ran, and Phase 3's `data/corpus/contracts/` was gone again by the time Phase 5 ran on a different OS. Both times the fix was one command: `python -m data_sourcing.filter_contracts --count 260`, which fetches ~253 EDGAR exhibits and writes **43 distinct contracts** (19 ready / 6 filled / 18 review). `data/scenarios/` was rebuilt on 2026-08-16 with `python -m data_sourcing.scenario_builder` (easy / realistic / edge) because Phase 6 is measured against it — and it will be gone again on the next machine.

Three findings a fresh session must not rediscover the hard way:
- **Never put bare `escalat` in a keep-list.** 81 CUAD contracts match it; **68 mean the *dispute* escalation procedure**, not a price rise. The plan's `KEEP` list contains it.
- **~24% of both corpora redact financials** with `[***]`. Counter-intuitively the redacted pile is *more* varied — 33 distinct clauses vs gold's 21, zero overlap — because boilerplate fee letters publish their numbers while negotiated contracts hide them.
- **Counting documents overstates the corpus ~2.5x.** 51 EDGAR "gold" documents carry only **21 distinct clauses**. Dedupe on clause fingerprint *and* filer, never filename, and report distinct clauses.

**Since Phase 0 closed, the inference design changed (ADR-011 + ADR-012):** no frontier model API is used anywhere. All inference runs on an open-source model we host on free Colab/Kaggle GPU. `core/config.py`, `.env.example`, `README.md` and the docs were updated; `docs/progress.md` carries the correction entry.

Run `python scripts/memory_digest.py` first — it prints current phase, open issues and latest ADR from `docs/state.json`. Then read, in this order:

| File | Purpose |
|---|---|
| `docs/progress.md` | **Part 1** — append-only log of what actually exists. *If it isn't here, it doesn't exist* — do not assume a module is built. **Part 2** — ADR-001…ADR-014, with what each one cost us. **ADR-011/012 changed the inference design after Phase 0**; **ADR-013/014 changed the data source before Phase 3** — read all four before touching anything LLM- or corpus-shaped. |
| `docs/interfaces.md` | Function signatures across the A/B boundary, per phase, with ⬜/✅ status. |
| `docs/state.json` | Machine-readable phase / known-issue / ADR state. |
| `docs/todo.md` | **Working list of what is not finished**, written 2026-08-16 at the close of Phase 6 — Phase 6 leftovers, debts that block a later phase, and small fixes worth doing when passing. Not a memory file: edit it freely, tick things off, delete them. `progress.md` stays authoritative and append-only. |
| `docs/implementation_plan.md` | 2000-line phase-by-phase plan: directory tree with per-file ownership, DB schema, algorithms, per-phase "definition of done". **Amended 2026-08-16** with *"There are two frontends now — where a feature lands (ADR-018)"*, right after the directory tree: which of `app/` and `web/` owns which surface, and the four things every remaining phase owes `web/`. Phases 6–9 and 11 each carry a matching *Frontend amendment* note. |

Everything stable about the project — what it is, the stack, the data sources, the hard rules, the A/B split, the memory ritual — is in this file, below.

Known drift — do not silently "fix" by guessing:
- **The memory files live in `docs/`, not `memory/`, and there are four of them, not five.** `implementation_plan.md` says `memory/` throughout and names `project_context.md` / `decisions.md` / `memory_system.md`, because it predates the repo and predates the 2026-08-08 consolidation. `docs/` is authoritative; the plan text was deliberately left alone.
- Phase 11 references a `changes.md` that does not exist.
- **Phase 3's `KEEP` keyword list in `implementation_plan.md` is measurably wrong** and must not be copied as written. It contains bare `escalat` (68 of its 81 CUAD matches are dispute-resolution boilerplate) and it passes a contract on *any one* keyword, which is how 48.6% retention coexists with a 1.6% usable rate. ADR-013 replaces it with a concrete-value test. The plan text was deliberately left alone.
- The plan's Phase 3 fetch example uses `dvgodoy/CUAD_v1_Contract_Understanding_PDF`. Use `theatticusproject/cuad` instead — it is the same corpus with the real PDFs, needs no token, and is what the probes already download.
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
8. **No secrets in git.** `.env` is gitignored; deployment uses Streamlit Secrets. **This rule was broken and the repo is public** — the live `LLM_API_KEY` sat in `README.md` and `docs/serving_setup.md` from Phase 5 until the 2026-08-17 audit, and it is still in git history (known issue #66). It is redacted from the working tree now, but **redaction is not the fix — the key needs rotating**, in four places: `.env`, the Colab secret, the Kaggle secret, the Modal secret. Never paste a key into a doc to be helpful; point at `.env`.
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
| Model serving | **FastAPI + Cloudflare tunnel** in a Colab/Kaggle notebook, **or Modal** | OpenAI-compatible `/v1/chat/completions`. Three peers (ADR-016 + ADR-023); Modal is `training/serve_modal.py`, rented GPU, stable URL, billed per second |
| Structured output | **Pydantic** + JSON mode + repair-retry | NOT Outlines (doesn't work over HTTP) |
| Agent | **LangGraph** ReAct, max 5 iterations | Verification agent |
| Charts | **Plotly** | Cash-flow projection |
| Fine-tuning | **Unsloth + QLoRA** on free Colab/Kaggle T4 | |

**No local GPU is required anywhere in the runtime path** — the GPU is a free Colab/Kaggle T4, reached over HTTP.

## Data sources — sourced online, never generated locally

| Purpose | Source | Access |
|---------|--------|--------|
| **Primary contracts** | **SEC EDGAR** EX-10 / EX-99 exhibits, aimed at master/professional services agreements (ADR-013) | `efts.sec.gov` full-text search — needs a contact address in the User-Agent |
| Secondary contracts | **CUAD v1** — 510 real commercial contracts, CC BY 4.0. Demoted by ADR-013: use for Phase 5 extraction dev and Phase 10 volume, **not** for anomaly scenarios | HuggingFace `theatticusproject/cuad` — **public, no `HF_TOKEN` needed**; it carries the PDFs directly (510 of them, 311 with an uppercase `.PDF` extension) |
| Invoice images | `mychen76/invoices-and-receipts_ocr_v1`, `Voxel51/high-quality-invoice-images-for-ocr` | HuggingFace |
| Receipt OCR ground truth | SROIE / CORD | HuggingFace |
| Transaction realism | Kaggle bank-transaction datasets | `kagglehub` |

**Rule:** contracts are **sourced**. Actuals (invoice ledgers, transactions) are **derived** from those real contracts by deterministic arithmetic in `data_sourcing/scenario_builder.py`, which plants known anomalies and writes `ground_truth.json`. No model invents a contract.

**Corollary (ADR-014).** Where a real contract redacts its figures — *"fees shall increase by `[***]` percent"* — the missing values are supplied by **seeded deterministic Python**, never by a model, and written **into the contract text** as well as the answer key. The inserted value *is* ground truth by construction, so nothing needs verifying. If a model chose it, you would have to read its output to learn what it picked — a step, and a way to be silently wrong. The filler **refuses when it cannot read a blank's type**; an early version guessed and corrupted a rate card invisibly.

## Key design decisions worth knowing before writing code

Full reasoning for each is in Part 2 of `docs/progress.md`.

- **Reconciliation aggregates per client-month** (ADR-006) rather than matching transaction-to-invoice, which is a combinatorial assignment problem. Sum all of a client's transactions in the calendar month (fuzzy name match, ±15 day tolerance), compare to expected, classify the gap. The precision lost on split payments is recovered in Phase 8 by the agent's `check_split_payments` tool, which does transaction-level search on the ~5 flagged rows instead of ~5,000.
- **Structured output is Pydantic + JSON mode + one repair retry** (ADR-004). `llm_client.complete_json` returns `None` on failure and **never raises to the caller**. Outlines was rejected because it needs logit access, which a hosted API could not give — but ADR-011 means we now run the server, so grammar-constrained decoding is available *server-side* in the notebook. Keep the client-side repair-retry regardless.
- **One swappable LLM client** (ADR-002, amended by ADR-011): endpoint chosen by `LLM_PROVIDER` (`colab_tunnel | kaggle_tunnel | custom`) — all of them our own notebook sessions, all OpenAI-compatible. Phase 11's base-vs-tuned comparison is likewise one variable, `LLM_MODEL`.
- **The Decision Engine asks the user for expenses rather than inventing a surplus** (ADR-024). No table holds operating costs, so the one number the verdict turns on is typed by the user, and with none supplied the engine refuses a Yes/No. An assumed expense figure was rejected because a wrong surplus is *invisible* — unlike a mis-drawn clause box, nobody can see that $4,500 should have been $1,200.
- **Modal is a third peer inference host, not a departure from ADR-011** (ADR-023). Rented hardware serving our own open-source weights is not a vendor model API. It is the only host whose URL is stable, so `endpoints.fallback()` tries it first; `USE_MODAL=true` sends everything there and is resolved above `LLM_PROVIDER`. Written retroactively — the code shipped undocumented (#67). Never deployed.
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

streamlit run app/main.py        # the Streamlit shell
python run_web.py                # the FastAPI shell (ADR-018), :8000 — --live, --reload, --fixed
python scripts/memory_digest.py  # compact orientation summary

python scripts/init_db.py        # create all 12 tables
python scripts/seed_demo.py      # a complete demo run in every table
python scripts/reset_run.py      # wipe one run, keep others

python -m data_sourcing.filter_contracts --count 260   # rebuild data/corpus/ (gitignored!)

# ---- Phase 5 ----
python scripts/verify_llm_stack.py           # 21 assertions, stub server, no GPU
python scripts/eval_extraction.py --pdfs 5   # the Phase 5 definition of done; needs a live endpoint
python training/serve_model.py --self-test   # runs IN a Colab or Kaggle notebook, not here

# ---- Phase 6 ----
pytest -q                                    # 233 assertions across 10 files (74 of them Phase 6's)
python -m data_sourcing.scenario_builder     # data/ is gitignored — rebuild the 3 scenarios first
python scripts/eval_engine.py                # the Phase 6 definition of done; no DB, no network
python scripts/run_scenario.py realistic     # load a scenario's INPUTS, let the engine compute the rest
python scripts/run_scenario.py --recompute 13  # re-run the engine over an existing run
```

Also working:

```bash
# ---- Phase 7 ----
pytest tests/test_clause_locator.py tests/test_pdf_renderer.py -q   # 33 assertions, no DB

# ---- Phase 8 ----
pytest tests/test_agent_tools.py tests/test_verification_agent.py -q  # 18 assertions, no GPU
python scripts/eval_agent.py                 # needs a live endpoint; NEVER run on a GPU (#65)
python scripts/eval_agent.py --skip-live-run # fixture only — still needs the model

# ---- Phase 9 ----
pytest tests/test_cashflow.py tests/test_decision_analyzer.py -q  # 78, offline
python scripts/eval_decision.py               # the definition of done; no DB, no GPU
python scripts/eval_decision.py --run-id 2    # same, plus a real run's figures
python scripts/eval_decision.py --live        # needs an endpoint; NEVER RUN yet (#71)

# ---- the 2026-08-17 audit ----
pytest tests/test_schema.py -q                # 30 schema assertions; closes #15
FINSIGHT_TEST_DATABASE_URL=postgresql://...  pytest tests/test_schema.py -q   # same, on Postgres
modal deploy training/serve_modal.py          # ADR-023's third host — NEVER RUN yet
```

The `.venv` should be **Python 3.12**, built with `uv` for Streamlit Community Cloud parity (Cloud does not offer 3.14). The Linux checkout is currently on **3.14.6**, so that parity does not hold there — see known issue #47. To rebuild:

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
- Vars: `LLM_PROVIDER` (`colab_tunnel | kaggle_tunnel | modal | custom`), `COLAB_TUNNEL_URL`, `KAGGLE_TUNNEL_URL`, **`MODAL_BASE_URL`**, `CUSTOM_BASE_URL`, `LLM_API_KEY` (shared secret — the tunnel is a public URL; see rule 8 and known issue #66), `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_FAILOVER`, **`USE_MODAL`** (default false; resolved *above* `LLM_PROVIDER`, and not the same thing as `LLM_FAILOVER` — ADR-023), `DATABASE_URL` (falls back to `sqlite:///data/finsight.db`), `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY`, `HF_TOKEN` (not needed — Qwen 2.5 3B is public), `LLM_CACHE_ENABLED`, `LOG_LEVEL`.
- **From Phase 5, `settings.api_base` is the `.env` default, not the live value.** `llm_client` asks `core/ai/endpoints.py`, which layers the in-app switcher's choice over it at call time (ADR-016). Read the endpoint from `endpoints.active()`, never from `settings`.

`.gitignore` covers `data/`, `.env`, `__pycache__/`, `*.db`, `.streamlit/secrets.toml`, and `training/data/*.jsonl` **except** `eval_set.jsonl` — the held-out eval set is tracked on purpose and never trained on.

# API budget

The scarce resource is requests-per-minute, not GPU memory. A full run (5 contracts, 1 CSV, 7 anomalies) is ~35–55 LLM calls. Cache every response on disk keyed by `sha256(prompt + model)` — the same contracts get re-run dozens of times while debugging. Fire agent calls sequentially with a small sleep; bursting is what trips per-minute limits, not volume.
