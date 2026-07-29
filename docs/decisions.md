# DECISIONS — Architecture Decision Records

> **Never delete an ADR.** If we change our minds, add a new one and mark the old one *Superseded by ADR-0NN*. The history is the methodology section of the report.
> One ADR per *real* choice — where a competent person would plausibly have chosen the other thing. Not for defaults nobody argued about.

**Format:** Context (the forcing constraint) → Decision → Consequences (including what we gave up).

ADR-001 through ADR-010 were agreed at Phase 0, before any code, and are extracted from `implementation_plan.md`.

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
