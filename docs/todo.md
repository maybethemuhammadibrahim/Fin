# TODO — what is not finished

**Last updated:** 2026-08-17, at the close of Phase 9. The post-Phase-8 audit's
findings are in `docs/progress.md` → *"Audit — Phases 0–8 re-verified"*.

---

## 🔴 DO THIS FIRST — rotate the leaked API key · `#66`

The live `LLM_API_KEY` was committed to this **public** repository and printed in
`README.md` (twice) and `docs/serving_setup.md` (once) from Phase 5 until
2026-08-17. It is redacted from the working tree now, **but it is still in git
history and cannot be un-published.** That key is the only control on a public
tunnel to your GPU, and with Modal (ADR-023) the exposure is billed GPU-seconds,
not just quota.

*To close it:* generate a replacement —

```bash
python -c "import secrets; print('finsight-' + secrets.token_urlsafe(24))"
```

— then update it in **four** places: `.env`, the Colab secret, the Kaggle secret,
the Modal secret (`modal secret create finsight-llm LLM_API_KEY=...`). Nothing in
the code changes. Consider whether the repo needs to be public at all before
Phase 11 deployment; if it does, treat every value in it as published.

---

A working list, not a memory file. `docs/progress.md` stays authoritative and
append-only; `docs/state.json` stays the machine-readable status. This file
exists so the open work is in one place instead of scattered across 57 numbered
known issues, and it should be **edited freely** — tick things off, delete them,
re-order them.

Each item says where it lands. `#n` refers to `known_issues` in `docs/state.json`.

---

## Left over from Phase 9

### 0c. No live model has ever phrased a decision explanation · `#71`
Every verdict and every figure is computed by Python and needs no model — all six
`eval_decision.py` cases pass offline — but the prose in all six came from
`fallback_explanation`, because no endpoint was answering. The guard that matters
*is* proven offline: `explain_verdict` rejects an explanation quoting a figure it
was not given, retries once, then falls back.

*To close it:* start any of the three hosts, then
`python scripts/eval_decision.py --live`. Same GPU precondition as `#40`/`#65`, so
all three are worth doing in one session.

### 0d. An expenses source, so the surplus stops depending on a typed number · `#70`
ADR-024 ships the Decision Engine with monthly running costs supplied by the user,
because no table holds them. It is honest and visible, but it is the one number the
verdict turns on and it is not in the database.

*To close it:* a 13th table (`operating_expenses`: `run_id`, `month`, `category`,
`amount`), an upload zone, a column mapping through the existing ADR-010 flow, a
queries helper, and `test_schema.py` updated to expect 13 tables. Then
`compute_baseline` reads expenses instead of taking them as an argument, and the
`verdict == "unknown"` branch becomes unreachable for a run that has them. Sizeable
— treat it as its own phase, not a Phase 11 tidy-up.

---

## Left over from Phase 8

### 0a. `scripts/eval_agent.py` has never been run against a live GPU  · `#65`
Written and self-tested (it fails cleanly with a clear message when no
endpoint is configured — confirmed by running it), but the live-model half of
Phase 8's own definition of done is unmeasured. The offline half
(`tests/test_verification_agent.py`, 5 assertions) proves the graph's control
flow regardless of model quality.

*To close it:* start a Colab or Kaggle session, paste the tunnel URL on the
Model endpoint page, then `python scripts/eval_agent.py`. Ten minutes, and it
needs a live GPU — same shape as leftover #1 above.

### 0b. `check_split_payments` does not close known issue #57  · `#57`, `#63`
The tool finds combinations of *several* transactions summing to one target.
A single transfer that bundles two months into one payment — #57's actual
shape — is a *multiple* of one billing's amount, not a sum of several. No
tool compares a client's total against several neighbouring months at once
yet.

*Options, none chosen:* a fifth tool that widens the aggregation window
itself and asks "does this and the next month's total match two expected
billings"; or accept the gap and disclose it (current state).

### 0c. `web/`'s two verdict buttons stay inert  · `#52`, `#56`
"Add to recoverable" / "Rule it out" in `_finding_detail.html` were reserved
for Phase 8 but not wired — the agent runs from `app/`'s "4 · Verify
findings" only, matching how reconciliation stayed `app/`-only in Phase 6.

*If that changes:* it is `web/`'s first write path, and must call
`web.cache.clear()` (same warning `compute_run` already carries).

---

## Left over from Phase 7

### 0. The scanned-document path has still never been tried on a real scan
`core/extraction/ocr_cloud.py` is a stub and Surya-on-Colab has never run. This
is the *stretch* goal in the definition of success, not a requirement — but if
it is going to be demoed, it needs a genuinely scanned contract and a Colab
session, and neither exists yet.

---

## Left over from Phase 6

### 1. Upload → extract → `contract_rules` has never run end to end on a GPU  · `#41`
`app/components/reconcile_panel.render_extract_panel()` calls Phase 5's
`extract_rules()` and then `pipeline.persist_rules()`. Both halves are tested
separately — extraction measured on a Colab T4 (2026-08-14), persistence covered
by 13 assertions in `tests/test_pipeline.py` — but **the join has only ever run
with no endpoint up**, where it fails cleanly and prints a readable message.

*To close it:* start a notebook session, paste the tunnel URL on the Model
endpoint page, upload one real contract, press the button, and check that
`contract_rules` + `clause_references` rows appear and reconcile. Half an hour,
and it needs a live GPU — which is the only reason it is still open.

### 2. `web/` still writes nothing  · `#52`, `#56`
Reconciliation runs from the Streamlit app only. Every button in the FastAPI
frontend is inert by design (ADR-018) and its tooltips now name the other
frontend rather than a phase.

*If that changes:* the first write path added to `web/` **must** call
`web.cache.clear()`, or a user sees a stale page for up to `WEB_CACHE_SECONDS`
after their own click. `core.engine.pipeline.compute_run` carries the warning in
its docstring.

### 3. Undated milestones are never billed  · `#55`
`ContractRules.Milestone` carries a condition ("on website launch"), not a date.
`generate_timeline` leaves an undated milestone out and
`RunSummary.unresolved_milestones` names it — deliberate, because guessing a due
date manufactures ghost invoices. But the pitch's own **$15,000 launch
milestone** is therefore never checked in a computed run.

*Options, none chosen yet:* set `milestones.due_date` by hand in the UI; let
Phase 8's agent resolve a condition against the document; or bill it at
`contract_end` and mark it low-confidence.

### 4. Escalation compounds in the engine, once in the scenario builder  · `#54`
`timeline_generator` compounds per anniversary (6,000 → 6,480 → 6,998.40);
`data_sourcing/scenario_builder.py` applies its rise exactly once. They agree
today **only** because no scenario window contains a second anniversary.

*The engine is the correct side* — the clauses say "on each anniversary". Do not
"fix" the engine down to match. If a longer scenario is ever built, fix the
builder, and use `compound_escalation=False` for a genuine one-off rise.

### 5. Phase 1's 47 schema assertions are still not in pytest  · `#15`
Phase 6 was said to own this port and did not do it — it added 74 engine and
pipeline assertions instead. The schema verification therefore still is not
repeatable in CI. `tests/test_pipeline.py` already creates all 12 tables on a
throwaway SQLite file, which is the natural place to put them.

### 6. `seed_demo.py --scenario` still raises `NotImplementedError`  · `#35`
Left alone on purpose: `scripts/run_scenario.py` loads a scenario now, and the
seeded `demo_v1` run stays a fixed reference that no engine change can move.
Delete the parameter or implement it — but decide, rather than leaving a
raising code path in a script people run.

---

## Debts that will block a later phase

### 7. ~~EDGAR serves HTML, not PDF~~ — **done in Phase 7 (ADR-021)**  · `#28`
Settled by typesetting the extracted text into a real, deterministic PDF rather
than converting the corpus or accepting permanent degradation. 20 of 20 clauses
across three computed runs are now placed on a page.

**What is left of it, and it is a reporting duty, not a code task:** a typeset
page is *not* the filing as filed — its line breaks, pagination and page numbers
are ours, so "page 61" will not match the document on EDGAR. Both frontends and
the PDF footer say so; **the report must say so too**.

### 8. Corpus variety is adequate, not good  · `#27`, `#29`
The EX-99 mutual-fund cluster is over-represented because `edgar_probe.py` used
generic queries and read only page 1 of each result list. The broader search is
designed and **has never been run**. 19 contracts in `review/` have never been
read by a human; expect to lose about a quarter of them.

*Do this before Phase 10*, not before Phase 7 — variety is load-bearing only for
training and the base-vs-tuned claim.

### 9. The training-pair drafting decision is still open  · `#31`
Whether to use a vendor model offline to draft the 80–120 `ContractRules`
training pairs. ADR-011 forbids vendor calls in the runtime path; drafting
offline is standard distillation and defensible if disclosed, but it dents the
self-hosting story. **Not decided.** Phase 10 cannot start until it is.

### 10. Prompts have had one iteration and one measurement  · `#45`, `#48`, `#49`
`PROMPT_VERSION v1` scored 10/10 valid and 80.0% grounding — but grounding passed
*exactly* on the line at n=15, and 3 of the 10 contracts extracted zero clauses
while still counting as valid. Re-run with `--limit 20` before either number is
cited in the Phase 11 report, and add a "contracts with ≥1 grounded clause"
metric.

### 11. Grammar-constrained decoding has never been measured on vs off  · `#46`
vLLM accepts `response_format=json_schema` and `llm_client` negotiates down
automatically, but no valid-JSON-rate comparison exists. That row of the Phase 11
table is empty.

### 12. Deployment is two apps, and only one has a home  · plan §Phase 11
Streamlit Community Cloud hosts `app/`. `web/` needs an ASGI host, the same
secrets, and `WEB_DATA_MODE=demo` for a public URL so a paused Supabase project
never produces an empty page. Decide, do it, and say in the report which one the
demo used.

---

## Small fixes worth doing when passing

| | Fix | Ref |
|---|---|---|
| 13 | `serve_model.py` polls a dead port for the full 15 minutes when vLLM's child dies at import. `wait_until_ready()` never checks `Popen.poll()`. One line; costs 15 minutes per failed start. | `#51` |
| 14 | `pip install vllm` is unpinned and breaks Colab's preinstalled `torchaudio`. Worked around in a notebook cell, not fixed in code. Pin it before deployment. | `#50` |
| 15 | No dependency pinning and no CI anywhere. Revisit before Phase 11. | `#5` |
| 16 | The `.venv` on the Linux checkout is Python 3.14.6; Streamlit Cloud does not offer 3.14, so the parity guarantee does not hold. `uv venv --python 3.12` before deploying. | `#47` |
| 17 | `.xlsx` is offered in the uploader's accepted types but only `.csv` is parsed. Fails cleanly with a message; nobody has built the path. The `.txt`/`.docx` version of this trap was fixed on 2026-08-17 (`.txt` now really routes, `docx` removed) — `xlsx` is the same shape and still open. | `#38` `#68` |
| 24 | `use_container_width` is past the removal date Streamlit prints (2025-12-31) and is still in 15 call sites in `app/`. Warning-only today. Mechanical fix: `width='stretch'` for True, `width='content'` for False. Do it in its own commit, before Phase 11 pins a Streamlit version. | `#69` |
| 25 | Modal (ADR-023) has never been deployed — no `modal deploy` has run from this repo, so its cold-start and per-call cost figures are unknown. Do not quote them in the report until measured. | `#67` |
| 26 | `fastapi` was missing from the `.venv` even though `requirements.txt` lists it, so `python run_web.py` could not start until the audit installed it. Nothing in the repo was wrong; it is what no pinning and no CI (`#5`) lets through. | `#5` |
| 18 | Deleting a run leaves its Storage objects behind, and content-addressing means every re-upload leaves its predecessor. Fine at demo scale; sweep before deployment. | `#21` |
| 19 | `SUPABASE_SERVICE_KEY` must go into Streamlit Secrets at deploy time. It bypasses all RLS. | `#22` |
| 20 | A client paying two months in one transfer reads as one month settled and one ghost invoice (ADR-019's accepted cost). **Still open after Phase 8** — `check_split_payments` only finds several transactions that sum to one target; a single transfer that's a *multiple* of one billing's amount is a different shape it cannot recognise. See `#57`, amended by `#63`. | `#57` `#63` |
| 21 | Nothing re-locates clauses automatically. Editing a quote by hand, or re-extracting a contract, leaves stale `source_page`/`source_bbox` until `locate_run_clauses` runs again (Reconcile button, or `scripts/run_scenario.py`). | `#62` |
| 22 | A located bbox is the union of every line the match spans, so on a multi-line clause it covers whatever else shares those lines. Honest, but not a word-perfect outline — do not describe it as one. | `#60` |
| 23 | The clause page image is ~4.9 s cold (a 200 KB `extracted_text` column across the 400 ms link), 1.2 ms warm. Not fixable in code from this repo. | `#61` |
