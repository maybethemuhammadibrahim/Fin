# The Memory System — How To Use It

> **Where the files live:** all of them are in `docs/`, alongside this file and `implementation_plan.md`. (`implementation_plan.md` calls this directory `memory/` — it was written before the repo existed. `docs/` is what we actually use.)

**What this is:** five small files that let an AI assistant pick up your project mid-build without you re-explaining it.

**Why you need it:** you have 12 phases, two people, and many separate assistant sessions. A fresh session knows nothing. It will re-suggest things you already built, contradict decisions you already made, and invent function names that don't match yours. With two of you running two separate sessions, that divergence doubles.

**Time cost:** ~5 minutes at the end of each phase.

---

## The five files

| File | Answers | Changes |
|------|---------|---------|
| `project_context.md` | *What are we building and with what?* | Almost never |
| `progress.md` | *What already exists?* | Every phase (append only) |
| `interfaces.md` | *What can I call, and what will it return?* | Before implementing anything shared |
| `decisions.md` | *Why is it this way and not the obvious other way?* | When a real choice is made |
| `state.json` | *Where are we right now?* | Every phase |

---

## The ritual — three steps, every phase

### 1. Start of phase — paste the Phase Prompt

Every phase in `implementation_plan.md` has a copy-paste **Phase Prompt** block. Paste it into your assistant. Its first instruction is always: *read the memory files and print a numbered summary of everything already implemented, before writing any code.*

**Do not skip the summary.** It is doing real work, not ceremony:
- Restating the files forces the model to actually condition on them rather than skim past them.
- It gives you a 10-second human check that the assistant is oriented. If the summary is wrong or thin, your memory files are wrong or thin — fix them before any code gets written on a bad foundation.
- It catches conflicts early. The prompt explicitly asks the assistant to stop if this phase contradicts something in memory.

### 2. During the phase — update `interfaces.md` first

The moment you know a function will be called by the *other* person, put its signature in `interfaces.md` before you implement it. They then write against the signature with a stub and neither of you blocks.

### 3. End of phase — 5 minutes, both of you

- Append your Phase N entry to `progress.md` (template is in that file)
- Flip statuses in `interfaces.md` (⬜ → ✅)
- Add any ADR to `decisions.md`
- Update `state.json`: `current_phase`, phase `status`, `implemented_features`, `known_issues`
- Commit with a message like `memory: close phase 4`

---

## Rules

1. **`progress.md` is append-only.** If something changed later, add a new entry saying so. Never rewrite history — the history is your report's methodology section.
2. **Never delete an ADR.** Supersede it with a new one and mark the old one superseded.
3. **If it isn't in `progress.md`, it doesn't exist.** An assistant reading memory will happily rebuild a module you forgot to log.
4. **Both people update memory.** Not just one. You each know things the other doesn't.
5. **Write the "known gaps" line honestly.** It's the highest-value line in a progress entry — it stops an assistant from assuming something works that doesn't.

---

## Quick digest command

When you want a compact paste-in summary, `scripts/memory_digest.py` [B, Phase 0] prints one:

```bash
python scripts/memory_digest.py
```

```
FINSIGHT — phase 5 in_progress | provider=gemini | 23 features across 12 files
DONE:    0 Foundations · 1 Database · 2 UI Shell · 3 Data Sourcing · 4 Extraction
CURRENT: 5 LLM Contract Rule Extraction  (A: schemas+extractor, B: llm_client)
NEXT:    6 Timeline & Reconciliation
OPEN:    #3 CUAD filter retains only 18% — top up from EDGAR
         #7 clause_locator fuzzy fallback untested on multi-page clauses
ADRs:    10 recorded, latest ADR-010 (CSV column mapping)
```

Useful when you want the assistant oriented fast without pasting four files. Use the full Phase Prompt when starting real work.

---

## When you skip this

Two things happen, both slowly. First, the assistant starts writing code that shadows code you already have — a second `parse_transactions` with different arguments, a third way of representing money. Second, you start re-litigating settled decisions, because nobody remembers *why* you chose Supabase over Neon, so you spend an evening comparing them again.

Neither is dramatic. Both cost you a week across a 12-phase project.
