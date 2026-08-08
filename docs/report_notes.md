# REPORT NOTES — raw material for the write-up

> **Append-only, like `progress.md`.** Log things *while they are fresh*: the
> screenshot you just took, the number you just measured, the decision you just
> argued about. Reconstructing this at the end is how reports become vague.
>
> This is not documentation. It is the pile of evidence the report gets built
> from — screenshots, measurements, and the honest version of what happened.

**Started:** 2026-08-08 (Phase 2)

---

## What each section of the report will need

| Section | Evidence needed | Where it comes from |
|---|---|---|
| Problem statement | The worked example ($21k across four leak types) | `CLAUDE.md` |
| Method — architecture | The layer diagram, the four hard rules | ADRs 001–012 in `progress.md` Part 2 |
| Method — why not X | The rejected alternatives, with reasons | Every ADR's "Consequences" |
| Results — extraction | Valid-JSON rate, repair rate, clause-grounding rate | Phase 5, Phase 11 eval harness |
| Results — detection | Precision/recall against `ground_truth.json` | Phase 3 scenarios + Phase 11 |
| Results — base vs tuned | Same harness, `LLM_MODEL` the only variable | Phase 11 (ADR-012) |
| Limitations | The "known gaps" lines, honestly | `progress.md`, every phase |

---

## Screenshots taken

| # | What | Phase | File | Notes |
|---|---|---|---|---|
| — | *none yet* | | | Phase 2's dashboard is the first one worth capturing |

**To capture at the end of Phase 2** (the plan calls this "a screenshot that
would convince someone the project is done"):

1. Landing page with the status strip — database connected, model endpoint not
   yet configured. Honest about what exists.
2. Dashboard: four cards reading $26,908 / 7 / 3 of 5, the type breakdown, the
   findings table with all four leak types visible.
3. A selected finding with a **located** clause — the green "Located on page N"
   state.
4. A selected finding with an **unlocatable** clause — the ADR-005 degradation.
   This one matters more than it looks: it is the difference between a system
   that admits what it cannot prove and one that quietly fabricates a citation.
5. Decision Engine with the chart and the template verdict.

---

## Measurements

*(Numbers go here as they are produced. Never retype one from memory.)*

| Date | Metric | Value | How measured |
|---|---|---|---|
| 2026-08-08 | Tables in schema | 12 | `information_schema`, Supabase |
| 2026-08-08 | Phase 1 assertions passing | 47/47 | scratch harness, SQLite **and** Postgres, identical results |
| 2026-08-08 | Seeded demo total leaked | $26,908.00 | `scripts/seed_demo.py` |
| 2026-08-08 | Seeded findings | 7 across 4 types, 3 of 5 clients | same |
| 2026-08-08 | Seeded clause grounding | 6/7 locatable (1 `failed`) | same |

---

## Decisions and arguments worth reporting

**2026-08-08 — The ER diagram was missing a table.** The plan drew 11 tables but
said 12 in two places. The missing one was `milestones`, which is required by
`ContractRules.milestones` and by `payment_type="milestone"`. Worth reporting as
an example of the memory system working: the discrepancy was caught because
three documents had to agree, not because anyone re-read the diagram.

**2026-08-08 — Seed data is generated, not typed.** Every figure in the demo run
is derived: expected timeline from the contract, actuals from the timeline plus
named deviations, anomalies from the difference. So `gap == expected - actual`
and `total == sum(gaps)` hold structurally. This is what makes a UI bug
distinguishable from a data bug during Phase 2, and it is the same argument
ADR-007 makes about `ground_truth.json` at full scale.

**2026-08-08 — Two ADR-005 failure modes, not one.** "No clause at all"
(unproven finding, hard rule 5 violation) and "clause quoted but not locatable"
(valid finding, degraded highlight) are different things and were initially
conflated in one counter. The dashboard now reports them separately, and the
grounding rate is the honest headline: *how much of this total can we actually
point at?*

---

## Things that went wrong (report these — they are the methodology)

**2026-08-08 — A blank env var adopted its own comment.** `.env.example` had
`COLAB_TUNNEL_URL=    # https://...`, and python-dotenv strips inline comments
only when a value is present. On a blank variable the comment became the value,
so the config page showed ✅ for a variable that was unset. Caught only by
actually running the thing. A good illustration of why "it looks configured" is
not evidence.

**2026-08-08 — Scoped row counts were silently global.** Five tables have no
`run_id` and hang off `contract_rules`; the health page counted them globally
while claiming to scope to a run. Harmless with one run, wrong with two. Found
by a cascade-delete assertion, not by looking at the page.

---

## Open questions for the write-up

- How much worse is base Qwen 2.5 3B than a frontier model at clause extraction?
  Phase 5 gives the first honest number; Phase 11 measures the gap the tuning
  closes. **Report it whichever way it comes out** (ADR-009's principle survives
  even though the ADR was superseded).
- What is the real clause-grounding rate on CUAD contracts, as opposed to the
  seeded 6/7? That number caps how much of the headline total is provable.
- Did the notebook-session architecture (ADR-011) cost more time than the
  reproducibility was worth? Log the hours lost to dead tunnels honestly.
