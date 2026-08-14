"""[B] The mockup's own content, as view models. Phase 6.

Every string below is transcribed from the ``FINDINGS`` / ``PIPELINE`` /
``working`` arrays in the original single-file mockup. Nothing was invented and
nothing was improved; when the demo page and the mockup disagree, this file is
wrong.

It exists for two reasons. It is the reference render — the thing to diff
against when a template change is supposed to be invisible. And it is what the
app shows before a database has anything in it, so the shape of the product can
be discussed without a seeded run.

**It is never consulted in live mode.** There is no fallback path from
`live.py` into this module: a live page with missing data shows a skeleton and
says so. Borrowing a demo figure to fill a live gap would put an invented number
in front of a user, which is the one thing the whole architecture is arranged to
prevent.
"""

from __future__ import annotations

from web.viewmodels import (
    Bar,
    Card,
    CleanRun,
    CleanStat,
    ClientConfirm,
    ColumnMap,
    DecisionView,
    FindingDetail,
    FindingRow,
    IntegrityView,
    PipelineDoc,
    ToolCall,
    Txn,
    WorkRow,
)

# ---------------------------------------------------------------------------
# Source data — the mockup's arrays, unchanged
# ---------------------------------------------------------------------------

#: The one-line explanation in the right of the state bar, per state.
STATE_NOTES = {
    "empty": "First run · nothing uploaded",
    "processing": "Six documents read, one scan failed, two things need a person",
    "review": "Five findings · one waiting on a check · one ruled out",
    "clean": "A run that found nothing — the case that proves it discriminates",
    "offline": "The model endpoint is down; stored results still stand",
}

RUN_LABEL = "demo_v1 · qwen2.5-3b base"

_FINDINGS: list[dict] = [
    {
        "client": "Nexus Digital",
        "type": "Never billed",
        "period": "March 2026",
        "title": "Milestone 2 was delivered and never invoiced",
        "sub": "Website launch · due on delivery · clause 4.1",
        "due": "15,000.00",
        "received": "0.00",
        "gap": "(15,000.00)",
        "verdict": "Confirmed",
        "kind": "confirmed",
        "headline": "The contract billed 15,000 on delivery. Nothing was invoiced.",
        "provenance": "Statement of work signed 3 February 2026 · reconciled against statement_q1.csv",
        "calc": "due 15,000.00 · received 0.00 · not collected 15,000.00",
        "clause": "A milestone payment of $15,000 is due upon delivery of the final website.",
        "clause_ref": "clause 4.1",
        "doc_meta": "nexus_sow.pdf — page 2 — clause 4.1",
        "ground": "exact",
        "txns": [
            {
                "label": "No payment matched to this client in March",
                "meta": "statement_q1.csv · 41 rows scanned",
                "amount": "0.00",
                "muted": True,
            }
        ],
        "received_total": "0.00",
        "due_total": "15,000.00",
        "gap_total": "(15,000.00)",
        "tools": [
            ("read_contract_clause(ref=11)", "→ milestone 15,000 on delivery of final website"),
            ("search_bank_transactions(14000–16000, Feb–Apr)", "→ no payment in that range"),
            ("check_split_payments(client=2, target=15000)", "→ no combination sums to 15,000"),
        ],
        "agent_prose": (
            "Delivery is recorded, no payment of that size arrived in the window, and no "
            "set of smaller payments adds up to it. The invoice was never raised."
        ),
        "c_contracts": "1",
        "c_received": "31,000.00",
        "c_share": "24%",
        "c_gap": "(15,000.00)",
    },
    {
        "client": "Bloom Agency",
        "type": "Paid short",
        "period": "April 2026",
        "title": "Paid 8,500 against a 10,000 project fee",
        "sub": "Stage 1 · clause 3 · gap never chased",
        "due": "10,000.00",
        "received": "8,500.00",
        "gap": "(1,500.00)",
        "verdict": "Confirmed",
        "kind": "confirmed",
        "headline": "A 10,000 stage fee was settled at 8,500 and the balance was never chased.",
        "provenance": "Master services agreement signed 9 March 2026 · reconciled against statement_q2.csv",
        "calc": "due 10,000.00 · received 8,500.00 · not collected 1,500.00",
        "clause": (
            "Stage one shall be invoiced at ten thousand pounds (£10,000) on acceptance "
            "of the design pack."
        ),
        "clause_ref": "clause 3",
        "doc_meta": "bloom_msa.pdf — page 4 — clause 3",
        "ground": "none",
        "txns": [
            {
                "label": "Bank credit — BLOOM AGENCY LTD",
                "meta": "14 Apr · statement_q2.csv · row 18",
                "amount": "8,500.00",
                "muted": False,
            },
            {
                "label": "No further payments matched to this client in April",
                "meta": None,
                "amount": None,
                "muted": True,
            },
        ],
        "received_total": "8,500.00",
        "due_total": "10,000.00",
        "gap_total": "(1,500.00)",
        "tools": [
            ("search_invoices(client=3, Apr 2026)", "→ one invoice, 10,000.00"),
            ("check_split_payments(client=3, target=10000)", "→ no second payment found"),
            ("search_bank_transactions(1400–1600, Apr–Jun)", "→ nothing matching the balance"),
        ],
        "agent_prose": (
            "The invoice was for the full amount and only one payment arrived. The 1,500 "
            "was neither paid later nor credited back."
        ),
        "c_contracts": "2",
        "c_received": "20,500.00",
        "c_share": "16%",
        "c_gap": "(1,500.00)",
    },
    {
        "client": "Starter Labs",
        "type": "Discount outlived its term",
        "period": "May 2026",
        "title": "A three-month intro discount is still being applied",
        "sub": "Expired in April · clause 6.2 · recurring monthly",
        "due": "6,480.00",
        "received": "5,880.00",
        "gap": "(600.00)",
        "verdict": "Waiting",
        "kind": "waiting",
        "headline": "The intro discount ended in April. May was still billed at the discounted rate.",
        "provenance": "Retainer agreement signed 12 January 2025 · reconciled against statement_q2.csv",
        "calc": "6,480.00 less 10% = 5,832.00 billed · due 6,480.00 · not collected 600.00",
        "clause": "A 10% introductory discount applies for the first three months of the Term.",
        "clause_ref": "clause 6.2",
        "doc_meta": "starter_labs_2025.pdf — page 5 — clause 6.2",
        "ground": "fuzzy",
        "txns": [
            {
                "label": "Bank credit — STARTER LABS LTD",
                "meta": "09 May · statement_q2.csv · row 63",
                "amount": "5,880.00",
                "muted": False,
            },
            {
                "label": "No further payments matched to this client in May",
                "meta": None,
                "amount": None,
                "muted": True,
            },
        ],
        "received_total": "5,880.00",
        "due_total": "6,480.00",
        "gap_total": "(600.00)",
        "tools": [
            ("read_contract_clause(ref=7)", "→ 10% for the first three months of the Term"),
            ("search_invoices(client=1, May 2026)", "→ invoice not found in the uploaded set"),
            ("check_prior_month(client=1, 2026-04)", "→ 5,880.00, the same discounted amount"),
        ],
        "agent_prose": (
            "The clause is clear but the Term start date appears twice in this contract "
            "with different dates, so the check could not settle whether the discount "
            "expired in April or July. It has been left for you rather than guessed."
        ),
        "c_contracts": "2",
        "c_received": "39,600.00",
        "c_share": "31%",
        "c_gap": "(2,160.00)",
    },
    {
        "client": "Starter Labs",
        "type": "Rise not applied",
        "period": "January 2026",
        "title": "The 8% anniversary rise was never billed",
        "sub": "Anniversary 12 January · clause 5.1 · recurring monthly",
        "due": "6,480.00",
        "received": "6,000.00",
        "gap": "(480.00)",
        "verdict": "Confirmed",
        "kind": "confirmed",
        "headline": "The contract raised this fee to 6,480 on 12 January. You billed 6,000.",
        "provenance": "Retainer agreement signed 12 January 2025 · reconciled against statement_q1.csv",
        "calc": "6,000.00 × 1.08 = 6,480.00 · received 6,000.00 · not collected 480.00",
        "clause": "Fees shall increase by 8% on each anniversary of the Effective Date.",
        "clause_ref": "clause 5.1",
        "doc_meta": "starter_labs_2025.pdf — page 3 — clause 5.1",
        "ground": "exact",
        "txns": [
            {
                "label": "Bank credit — STARTER LABS LTD",
                "meta": "08 Jan · statement_q1.csv · row 41",
                "amount": "6,000.00",
                "muted": False,
            },
            {
                "label": "No further payments matched to this client in January",
                "meta": None,
                "amount": None,
                "muted": True,
            },
        ],
        "received_total": "6,000.00",
        "due_total": "6,480.00",
        "gap_total": "(480.00)",
        "tools": [
            ("read_contract_clause(ref=3)", "→ 8% after 12 months, from 12 Jan 2025"),
            ("check_split_payments(client=1, 2026-01)", "→ one payment only, no split found"),
            ("check_prior_month(client=1, 2025-12)", "→ 6,000.00, the pre-rise rate"),
        ],
        "agent_prose": (
            "The rise was due, December was billed at the old rate, and no second payment "
            "covers the difference. The shortfall is real rather than a payment split "
            "across two months."
        ),
        "c_contracts": "2",
        "c_received": "39,600.00",
        "c_share": "31%",
        "c_gap": "(2,160.00)",
    },
    {
        "client": "Bloom Agency",
        "type": "Never billed",
        "period": "June 2026",
        "title": "June retainer looked missing — the payment was under another name",
        "sub": "Found as BLOOM AGY LTD on 2 July · ruled out",
        "due": "2,000.00",
        "received": "2,000.00",
        "gap": "—",
        "verdict": "Ruled out",
        "kind": "out",
        "headline": "This one was a false alarm. The June retainer did arrive.",
        "provenance": "Master services agreement signed 9 March 2026 · reconciled against statement_q2.csv",
        "calc": "due 2,000.00 · received 2,000.00 · nothing outstanding",
        "clause": (
            "The monthly retainer of two thousand pounds (£2,000) is payable on the first "
            "business day of each month."
        ),
        "clause_ref": "clause 3.2",
        "doc_meta": "bloom_msa.pdf — page 4 — clause 3.2",
        "ground": "exact",
        "txns": [
            {
                "label": "Bank credit — BLOOM AGY LTD",
                "meta": "02 Jul · statement_q2.csv · row 91 · matched inside tolerance",
                "amount": "2,000.00",
                "muted": False,
            }
        ],
        "received_total": "2,000.00",
        "due_total": "2,000.00",
        "gap_total": "0.00",
        "tools": [
            ("search_bank_transactions(1900–2100, Jun–Jul)", '→ 2,000.00 on 2 July, "BLOOM AGY LTD"'),
            ("check_client_aliases(client=3)", "→ BLOOM AGY LTD is 0.91 similar to Bloom Agency"),
        ],
        "agent_prose": (
            "The payment arrived two days into July under an abbreviated name, which is "
            "why the month match missed it. Ruled out, and the alias has been remembered "
            "for next time."
        ),
        "c_contracts": "2",
        "c_received": "20,500.00",
        "c_share": "16%",
        "c_gap": "(1,500.00)",
    },
]

_PIPELINE: list[tuple[str, str, str, str, tuple[int, int, int, int]]] = [
    (
        "starter_labs_2025.pdf",
        "Two clauses located exactly, one approximately. Rules on file.",
        "Reconciled",
        "Open",
        (1, 1, 1, 1),
    ),
    (
        "bloom_msa.pdf",
        "Read, but no billing frequency found. Set it and this contract joins the comparison.",
        "Needs you",
        "Set frequency",
        (1, 1, 3, 0),
    ),
    (
        "nexus_sow.pdf",
        "No text layer — this is a scan. Queued for the next character-recognition batch.",
        "Reading",
        "Check status",
        (1, 2, 0, 0),
    ),
    (
        "scan_0417.pdf",
        "Character recognition returned nothing legible. Upload a clearer scan or type the figures in.",
        "Failed",
        "Replace file",
        (1, 3, 0, 0),
    ),
    (
        "statement_q1.csv",
        "55 rows read. 50 matched to a client, 5 name nobody we know.",
        "Needs you",
        "Place 5 payments",
        (1, 1, 1, 2),
    ),
    ("statement_q2.csv", "48 rows read and all matched.", "Reconciled", "Open", (1, 1, 1, 1)),
]

#: The demo's default selection — the 8% anniversary rise, which is the
#: clearest of the five to read cold.
DEFAULT_SELECTION = 3


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _detail(index: int) -> FindingDetail:
    f = _FINDINGS[index]
    return FindingDetail(
        client=f["client"],
        type_label=f["type"],
        period=f["period"],
        headline=f["headline"],
        provenance=f["provenance"],
        calc=f["calc"],
        clause=f["clause"],
        clause_ref=f["clause_ref"],
        doc_meta=f["doc_meta"],
        ground=f["ground"],
        txns=[Txn(t["label"], t["meta"], t["amount"], t["muted"]) for t in f["txns"]],
        # The mockup's ledger only ever lists the payments belonging to the
        # billing in question, so there is no second total to draw.
        window_total=None,
        received_total=f["received_total"],
        due_total=f["due_total"],
        gap_total=f["gap_total"],
        verdict=f["verdict"],
        kind=f["kind"],
        tools=[ToolCall(call, result) for call, result in f["tools"]],
        agent_prose=f["agent_prose"],
        needs_review=f["kind"] == "waiting",
        c_contracts=f["c_contracts"],
        c_received=f["c_received"],
        c_share=f["c_share"],
        c_gap=f["c_gap"],
    )


def selection_count() -> int:
    return len(_FINDINGS)


def integrity(state: str, selected: int = DEFAULT_SELECTION) -> IntegrityView:
    """The Integrity Engine in one of its four states, with demo content."""
    if state == "empty":
        return IntegrityView(state="empty")

    if state == "processing":
        return IntegrityView(
            state="processing",
            pipeline=[
                PipelineDoc(name=n, note=note, status=s, action=a, stages=st)
                for n, note, s, a, st in _PIPELINE
            ],
            pipeline_headline="Reading nine documents",
            pipeline_sub="Six done · two in progress · one needs you",
            column_map_file="statement_q1.csv",
            column_map=[
                ColumnMap("Txn Date", "Date of payment"),
                ColumnMap("Amt (GBP)", "Amount"),
                ColumnMap("Narrative", "Description"),
                ColumnMap("Balance", "Ignore this column", ignored=True),
            ],
            column_map_note=(
                "These headers match a mapping you confirmed on 2 July, so it has been "
                "filled in for you. Nothing is parsed until you accept it."
            ),
            clients_headline="Confirm the clients · 3 found in 5 contracts",
            clients=[
                ClientConfirm(
                    "Starter Labs", "2 contracts · statements also say STARTER LABS LTD, StarterLabs"
                ),
                ClientConfirm("Nexus Digital", "1 contract · 17 payments matched"),
                ClientConfirm("Bloom Agency", "2 contracts · 14 payments matched"),
                ClientConfirm(
                    "5 payments name nobody",
                    "They stay unassigned, and out of every figure, until you place them",
                    accent=True,
                    action="Place them",
                ),
            ],
        )

    if state == "clean":
        return IntegrityView(
            state="clean",
            cards=[
                Card("Not collected", "0.00"),
                Card("Findings", "0"),
                Card("Months checked", "18"),
                Card("Billings reconciled", "60 of 60"),
            ],
            clean=CleanRun(
                run_label="Clean run · fitzgerald_ltd",
                headline="Every billing matched. Nothing to collect.",
                body=[
                    "Eighteen months of retainers, two milestone payments and one price rise, "
                    "all present at the right amount in the right month. Two payments arrived "
                    "late and were matched inside the fifteen-day tolerance rather than flagged.",
                    "A run that finds nothing is a result, not a failure. If this tool flagged "
                    "something here, you would have no reason to trust it when it flags "
                    "something real.",
                ],
                stats=[
                    CleanStat("Clauses located", "14 exactly · 2 approximately · 0 not found"),
                    CleanStat("Matched inside tolerance", "2 payments, 3 and 5 days late"),
                    CleanStat("Unassigned payments", "None"),
                ],
            ),
        )

    # review (and offline, which is review plus the banner)
    selected = selected if 0 <= selected < len(_FINDINGS) else DEFAULT_SELECTION
    return IntegrityView(
        state="review",
        cards=[
            Card("Not collected", "16,980.00", "Confirmed findings only", accent=True),
            Card("Findings", "5", "3 confirmed · 1 waiting · 1 ruled out"),
            Card("Clients affected", "3 of 5", "Across 5 contracts on file"),
            Card("Clauses located", "11 of 13", "9 exactly · 2 approximately"),
        ],
        findings=[
            FindingRow(
                id=str(i),
                client=f["client"],
                title=f["title"],
                sub=f["sub"],
                due=f["due"],
                received=f["received"],
                gap=f["gap"],
                verdict=f["verdict"],
                kind=f["kind"],
                selected=i == selected,
            )
            for i, f in enumerate(_FINDINGS)
        ],
        selected=_detail(selected),
    )


def decision() -> DecisionView:
    """The Decision Engine's worked example."""
    return DecisionView(
        question="Can I afford a senior designer at 5,000 a month from September?",
        suggestions=[
            "Can I afford 3,000 a month more rent from July?",
            "Two contractors at 4,200 each?",
            "A 1,800 a month tool subscription?",
        ],
        answered=True,
        verdict_word="Yes",
        verdict_qual="18,915 a month left over — 17,500 if you recover nothing",
        lead_html=(
            "Your last six months averaged <b>22,500</b> a month after expenses. The three "
            "confirmed findings come to <b>16,980</b> a year, which is <b>1,415</b> a month "
            "once collected. A <b>5,000</b> hire leaves <b>18,915</b> against <b>17,500</b> today."
        ),
        after=(
            "Of the five findings, one is still waiting on a check and one was ruled out, so "
            "neither counts here. Confirming the waiting one would add another 50 a month."
        ),
        bars=[
            Bar(f"{v}%", f"{v + 5}%")
            for v in (58, 57, 59, 56, 60, 58, 61, 59, 57, 60, 62, 59)
        ],
        axis=["Sep", "Dec", "Mar", "Jun", "Aug"],
        working=[
            WorkRow("Average monthly revenue", "55 payments across six months", "41,300.00"),
            WorkRow("Average monthly expenses", "same period", "(18,800.00)", accent=True),
            WorkRow("Surplus today", None, "22,500.00", bold=True),
            WorkRow("Confirmed findings", "3 of 5 · see Findings", "16,980.00"),
            WorkRow("Spread across the year", "divided by 12", "1,415.00"),
            WorkRow("Surplus once collected", None, "23,915.00", bold=True),
            WorkRow("Cost of the hire", "taken from your question", "(5,000.00)", accent=True),
            WorkRow("Left over each month", None, "18,915.00", final=True),
        ],
        caveat=(
            "This answers questions about affording a recurring cost. It cannot yet answer "
            "questions about one client, a past period, or a change to your prices."
        ),
    )
