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

**Status:** Accepted (Phase 0)

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

**Status:** Accepted (Phase 0)

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
