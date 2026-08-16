"""[B] The button that turns contracts into findings. Phase 6.

Phases 2–5 gave this app read-only screens: uploads landed, text was extracted,
and everything past that point was seeded. This component is the first place a
user action **computes** something — it runs
`core/engine/pipeline.compute_run`, which rebuilds `expected_timeline` and
`anomalies` for the selected run from the contracts already in it.

Two deliberate limits, both stated on screen rather than hidden:

* **Extraction is a separate button.** Turning an uploaded contract into
  `contract_rules` needs the self-hosted model, and the endpoint is a notebook
  session that is usually not running (known issue #9). Reconciliation itself
  needs no model at all, so it must not be blocked behind one — a run whose
  contract rules are already stored reconciles with the GPU switched off.
* **Nothing here does arithmetic.** The panel renders what `compute_run`
  returned. Every figure was computed in `core/engine/`.

ADR-018: this is the `app/` half. `web/`'s equivalent buttons stay inert — it is
a read-only frontend, and the first write path added there must call
`web.cache.clear()`.
"""

from __future__ import annotations

import streamlit as st

from core.ai import endpoints
from core.ai.contract_extractor import extract_rules
from core.ai.schemas import DocBlock, ExtractedDoc
from core.db.queries import DocumentRow
from core.engine.pipeline import LocateSummary, RunSummary, compute_run, locate_run_clauses, persist_rules


def render_reconcile_panel(session, run_id: int, contract_count: int) -> bool:
    """The reconcile action. Returns True when rows were rewritten."""
    if contract_count == 0:
        st.info(
            "No contract rules in this run yet, so there is nothing to reconcile. "
            "Extract them from an uploaded contract below, or load a built "
            "scenario from the command line.",
            icon="📄",
        )
        st.code("python scripts/run_scenario.py realistic", language="bash")
        return False

    left, right = st.columns([3, 1])
    with left:
        st.markdown(
            f"**{contract_count} contract rule(s) on file.** Reconciliation rebuilds this "
            "run's expected billing timeline from them, compares it against the "
            "transactions on file and rewrites the findings. No model is called."
        )
    with right:
        pressed = st.button("Reconcile now", type="primary", use_container_width=True)

    if not pressed:
        return False

    with st.spinner("Generating the expected timeline and reconciling…"):
        summary = compute_run(session, run_id)
    with st.spinner("Placing each clause on its page…"):
        # Phase 7. Separate step, separate spinner: it opens documents rather
        # than doing arithmetic, and it is the slow half on a long contract.
        located = locate_run_clauses(session, run_id)

    _render_summary(summary)
    _render_locations(located)
    return True


def _render_summary(summary: RunSummary) -> None:
    st.success(summary.as_line(), icon="✅")

    columns = st.columns(4)
    columns[0].metric("Expected billings", f"{summary.timeline_rows:,}")
    columns[1].metric("Findings", f"{summary.anomalies:,}")
    columns[2].metric("Recoverable", f"${summary.total_gap:,.2f}")
    columns[3].metric("Payments matched", f"{summary.attributed:,}")

    if summary.by_type:
        st.caption(" · ".join(f"{kind.replace('_', ' ')}: {n}" for kind, n in sorted(summary.by_type.items())))

    # The honest residue. A run that hides these looks tidier and tells you less.
    if summary.unattributed:
        st.warning(
            f"{summary.unattributed} transaction(s) matched no client by name and were left "
            "out of reconciliation. Bank fees and interest belong here; a client payment "
            "does not — check the descriptions if a figure looks low.",
            icon="❓",
        )
    if summary.unmatched:
        st.caption(
            f"{summary.unmatched} payment(s) landed outside every billing window in this run."
        )
    for line in summary.skipped_contracts:
        st.warning(f"Not reconciled — {line}", icon="⚠️")
    for line in summary.unresolved_milestones:
        st.caption(f"Milestone not checked — {line}. No due date could be resolved from the clause.")


def _render_locations(located: LocateSummary) -> None:
    """What the clause locator managed to place, said plainly.

    "0 of 8 located" is a legitimate outcome — an ungrounded quote still shows
    its page without a highlight (ADR-005) — so this reports rather than warns.
    """
    st.caption(
        f"Evidence · {located.grounded} of {located.clauses} clauses placed on a page "
        f"({located.exact} exact, {located.fuzzy} approximate, {located.failed} not found)"
    )
    if located.typeset_documents:
        st.caption(
            f"{located.typeset_documents} document(s) had no PDF behind them and were typeset "
            "from their own extracted text so a page could be shown (ADR-021). The clause "
            "viewer says so on every such page."
        )
    for name in located.unrenderable:
        st.caption(f"No page to show for `{name}` — neither stored bytes nor extracted text.")


def render_extract_panel(session, run_id: int, documents: list[DocumentRow]) -> bool:
    """Run the Phase 5 extractor over contracts that have text but no rules yet.

    Returns True when at least one contract was written. Each call is one model
    round trip per contract chunk, and `llm_client` returns `None` rather than
    raising when the endpoint is down — so a dead notebook session produces a
    readable message here, not a stack trace (ADR-004).
    """
    candidates = [
        d
        for d in documents
        if d.category == "contract" and d.extraction_status == "complete" and _has_text(d)
    ]
    if not candidates:
        return False

    active = endpoints.active()
    st.caption(
        f"{len(candidates)} extracted contract(s) on file · endpoint: {active.label}"
        + ("" if active.configured else " — **no URL set**, so this will fail")
    )
    if not st.button(f"Extract contract rules from {len(candidates)} document(s)"):
        return False

    written = 0
    progress = st.progress(0.0, text="Reading contracts…")
    for index, document in enumerate(candidates, start=1):
        progress.progress(index / len(candidates), text=f"Extracting {document.filename}…")
        text = _text_of(document)
        doc = ExtractedDoc(
            doc_type="text",
            blocks=[DocBlock(page_number=1, text=text)],
            full_text=text,
            page_count=document.extracted_page_count or 1,
        )
        rules = extract_rules(doc)
        if rules is None:
            st.error(
                f"**{document.filename}** — the model returned nothing usable. "
                "The endpoint may be down; the Model endpoint page shows which host is active.",
                icon="🛑",
            )
            continue
        persist_rules(session, run_id, document.id, rules, document_text=text)
        written += 1
        st.markdown(f"✅ **{document.filename}** → {rules.client_name}")
    progress.empty()

    if written:
        st.success(f"{written} contract(s) written to `contract_rules`. Reconcile to see findings.")
    return bool(written)


def _has_text(document: DocumentRow) -> bool:
    return bool(_text_of(document))


def _text_of(document: DocumentRow) -> str:
    return getattr(document, "extracted_text", "") or ""
