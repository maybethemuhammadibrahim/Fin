# PROJECT CONTEXT — FinSight

> **Read this first, in every new session, before writing any code.**
> This file is stable. It changes only when the project's goals or stack change.
> For *what has been built so far*, read `progress.md`. For *how modules talk to each other*, read `interfaces.md`.

**Last updated:** Phase 0
**Status:** see `state.json`

---

## 1. What FinSight is

A web application for **small B2B service businesses** (design studios, dev shops, consultancies — 3 to 20 people, no finance department).

It reads their **client contracts** and compares them against their **actual invoices and bank statements** to find **revenue they were contractually owed but never collected**. It then lets them ask a strategic business question and answers it with that recovered money factored in.

**One-sentence pitch:** *"You are owed money you don't know about. Here it is, here is the exact clause that proves it, and here is what it changes about the decision you're trying to make."*

---

## 2. The problem, concretely

A studio signs a contract: $6,000/month, 10% discount for the first three months, 8% increase on the anniversary, plus a $15,000 milestone on website launch.

Eighteen months later, whoever set up the recurring invoice has left. The invoice still says $6,000. Nobody applied the 8% increase. The intro discount was never switched off in month four. The milestone was delivered but never billed.

That is roughly **$21,000 gone** — not stolen, just never noticed. Accounting software cannot catch this, because accounting software has never read the contract.

---

## 3. The four leak types (the core taxonomy)

| Type | Definition | Detection rule |
|------|-----------|----------------|
| 🔴 **Ghost Invoice** | An expected billing that never happened at all | No actual transaction matches an expected timeline row |
| 🟡 **Forgotten Raise** | A price escalation clause that was never applied | Actual amount ≈ the pre-escalation rate |
| 🟠 **Zombie Discount** | A temporary discount that was never switched off | Actual amount ≈ expected minus an expired discount % |
| 🟣 **Short-Change** | A partial payment accepted with no follow-up | Actual < expected, and the gap matches no other rule |

These four are mutually exclusive by design. Every one traces back to a specific clause in a specific contract.

---

## 4. The pipeline (10,000-foot view)

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

**The load-bearing principle:** the LLM **only** reads documents and turns prose into structured data. It never does arithmetic, never decides whether something is an anomaly, and never produces a number the user sees. All money math is deterministic Python. This is what makes the results defensible.

---

## 5. Tech stack (authoritative — do not substitute without an ADR)

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
| Model serving | **FastAPI + Cloudflare tunnel** in a Colab/Kaggle notebook | OpenAI-compatible `/v1/chat/completions` |
| Structured output | **Pydantic** + JSON mode + repair-retry | NOT Outlines (doesn't work over HTTP) |
| Agent | **LangGraph** ReAct, max 5 iterations | Verification agent |
| Charts | **Plotly** | Cash-flow projection |
| Fine-tuning | **Unsloth + QLoRA** on free Colab/Kaggle T4 | |

**No local GPU is required anywhere in the runtime path** — the GPU is a free Colab/Kaggle T4, reached over HTTP.

> **Amendment (2026-07-29, ADR-011).** This table originally listed Gemini/Groq/OpenRouter as the LLM baseline. **No frontier model API is used anywhere in this project.** All inference runs on an open-source model we host and tune ourselves. The consequence to keep in mind at all times: our endpoint is a notebook session, so its URL changes when the session restarts, cold starts take minutes, and the disk cache is demo insurance rather than an optimisation.

---

## 6. Data sources — sourced online, never generated locally

| Purpose | Source | Access |
|---------|--------|--------|
| Real contracts | **CUAD v1** — 510 real commercial contracts, expert-annotated, CC BY 4.0 | HuggingFace `theatticusproject/cuad`, PDFs via `dvgodoy/CUAD_v1_Contract_Understanding_PDF` |
| More contracts | **SEC EDGAR** EX-10 material contracts | `efts.sec.gov` full-text search |
| Invoice images | `mychen76/invoices-and-receipts_ocr_v1`, `Voxel51/high-quality-invoice-images-for-ocr` | HuggingFace |
| Receipt OCR ground truth | SROIE / CORD | HuggingFace |
| Transaction realism | Kaggle bank-transaction datasets | `kagglehub` |

**Rule:** contracts are **sourced**. Actuals (invoice ledgers, transactions) are **derived** from those real contracts by deterministic arithmetic in `data_sourcing/scenario_builder.py`, which plants known anomalies and writes `ground_truth.json`. No model invents a contract.

---

## 7. Team

| | User A — *data & determinism* | User B — *interface & intelligence* |
|---|---|---|
| Owns | DB schema, extraction, timeline, reconciliation, training data, evaluation | Streamlit UI, LLM client, agent, decision engine, deployment |
| Strength of the work | Highly testable — pure functions, known I/O | Highly visible — screenshots, demos |

**Three collaboration rules:**
1. **One owner per file.** Files are tagged `[A]` / `[B]` in the plan. Need a change in a file you don't own? Ask. Don't edit.
2. **Interfaces before implementations.** The signature goes in `interfaces.md` *first*; the other person codes against it with a stub immediately.
3. **Both people work every phase.** No idle waiting.

---

## 8. Build philosophy

**Top-down.** The UI shell and the database come first (Phases 1–2), populated with *seeded real rows*. Every phase after that replaces one seeded table with a computed one.

**The UI never reads a hardcoded Python dict — only the database.** This is why integration never becomes a cliff at the end: by Phase 6 the reconciliation engine isn't being "connected" to anything, it just starts writing to a table the UI has read since week one.

**Riskiest work last:** extraction → math → clause viewer → agent → decision engine → fine-tuning.

---

## 9. Hard rules — violating these breaks the project

1. The LLM never does arithmetic. Ever.
2. The LLM never produces bounding boxes. It returns verbatim `clause_text`; `clause_locator.py` finds the coordinates.
3. Every anomaly shown to the user must trace to a `clause_reference` row.
4. No local GPU dependency in the runtime path.
4a. **No frontier model API calls. Ever** (ADR-011). Every model call goes to an open-source model we host on Colab/Kaggle. Adding a vendor SDK to `requirements.txt` is a violation, not a shortcut.
5. No secrets in git. `.env` is gitignored; deployment uses Streamlit Secrets.
6. Update `progress.md` at the end of every phase. Non-negotiable.
7. Nobody edits a file they don't own.

---

## 10. Definition of success

**Minimum (must have):** deployed public URL; upload a real contract + a CSV; get correctly classified anomalies with working clause highlighting; the Decision Engine returns a verdict — **all of it running against our own self-hosted open-source model** (base weights are enough).

**Target:** the above, plus the verification agent visibly filtering a false positive, plus the QLoRA-tuned adapter with a measured base-vs-tuned comparison on the held-out eval set.

**Stretch:** OCR path demoed on a genuinely scanned document.
