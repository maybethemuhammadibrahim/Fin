"""[B] The shapes every template renders. Phase 6 (FastAPI frontend).

This module is the whole point of the demo/live split. Both presenters —
`web.presenters.demo` and `web.presenters.live` — return these exact
dataclasses, so a template never asks *where* a figure came from. Adding a
field here means filling it in both presenters; that is deliberate friction,
because a field only one of them sets is a field the live page renders blank
without anyone noticing.

Three conventions carried over from `docs/interfaces.md`:

* Money arrives here **already formatted as a string** (``"6,480.00"``,
  negatives as ``"(480.00)"``). Templates do no arithmetic and no rounding —
  the same rule the LLM lives under, applied to Jinja.
* A value that legitimately does not exist is ``None``, never ``""`` and never
  ``0``. The ``dash`` filter turns ``None`` into an em dash at render time, so
  "we have no figure" and "the figure is zero" cannot look alike.
* A *block* that has no data at all is signalled by an empty list or a ``None``
  sub-model, and the template swaps in skeleton bars plus an `.absent` note
  saying which phase fills it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: The four Integrity Engine screens. In demo mode the user picks one from the
#: state bar; in live mode it is derived from what the database actually holds.
INTEGRITY_STATES = ("empty", "processing", "review", "clean")

#: Verdict flavours, which drive the tag styling. `kind` is one of these.
VERDICT_KINDS = ("confirmed", "waiting", "out")

#: How well the clause quote could be located in its PDF (ADR-005).
GROUND_KINDS = ("exact", "fuzzy", "none")

#: anomaly_type -> the phrase a non-accountant reads. The DB stores the first,
#: the user only ever sees the second.
TYPE_LABELS = {
    "ghost_invoice": "Never billed",
    "forgotten_raise": "Rise not applied",
    "zombie_discount": "Discount outlived its term",
    "short_change": "Paid short",
}

#: anomaly.status -> (verdict word, tag kind)
STATUS_LABELS = {
    "confirmed": ("Confirmed", "confirmed"),
    "unverified": ("Waiting", "waiting"),
    "needs_review": ("Needs you", "waiting"),
    "false_positive": ("Ruled out", "out"),
}

#: locate_method -> the badge and the sentence under the page preview. Kept
#: here rather than in a template so demo and live cannot word it differently.
GROUND_COPY = {
    "exact": (
        "Located exactly",
        "The model returned this sentence word for word; the highlight comes "
        "from searching the PDF for that text, so the box is measured rather "
        "than guessed.",
    ),
    "fuzzy": (
        "Located approximately",
        "The sentence was found with small differences — a line break inside a "
        "word. The highlight is close but may sit a line off.",
    ),
    "none": (
        "Not located",
        "This sentence could not be found anywhere in the PDF, so no highlight "
        "is drawn. The page is shown as it is and the quote is printed plainly. "
        "A highlight in the wrong place would be worse than none.",
    ),
}

#: Tag class per grounding outcome — exact reads as settled, fuzzy as hedged,
#: not-found as needing attention.
#:
#: These are deliberately *not* the verdict kinds (confirmed / waiting / out).
#: Grounding answers "was this quote found in the PDF?", which is a different
#: question from "is this finding real?", and the badge sits inches from a
#: verdict tag on the same screen. Borrowing the verdict classes drew "Located
#: approximately" in the identical grey as a ruled-out finding and "Not
#: located" in the identical accent as one awaiting review — two unrelated
#: facts wearing one uniform. app.css gives these three a dotted edge, so the
#: whole family reads as being about evidence rather than status.
GROUND_TAG_KIND = {"exact": "located", "fuzzy": "approx", "none": "unlocated"}


# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunOption:
    """One entry in the live-mode run picker."""

    id: int
    label: str
    selected: bool


@dataclass(frozen=True)
class Chrome:
    """Everything outside the two main panels: state bar, header, banner."""

    #: "demo" or "live" — the toggle this whole module exists to serve.
    data_mode: str
    page: str  # "integrity" | "decision"

    #: Which of the five mockup states the state bar shows as active. In live
    #: mode this is the derived Integrity state, and the buttons are inert.
    demo_state: str

    #: "demo_v1 · qwen2.5-3b base" — run label and model, or a dash apiece.
    run_label: str | None
    endpoint_label: str
    endpoint_online: bool
    #: The one-line explanation on the right of the state bar.
    state_note: str
    #: True paints the accent banner across the top: the model is unreachable
    #: but every stored figure still stands, because code computed it.
    is_offline: bool

    runs: list[RunOption] = field(default_factory=list)

    @property
    def is_demo(self) -> bool:
        return self.data_mode == "demo"


# ---------------------------------------------------------------------------
# Integrity Engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Card:
    """One of the four summary figures across the top."""

    label: str
    value: str | None
    sub: str | None = None
    accent: bool = False


@dataclass(frozen=True)
class PipelineDoc:
    """One uploaded document and how far through the pipeline it got."""

    name: str
    note: str | None
    status: str
    action: str
    #: Four stages: uploaded → text read → rules extracted → reconciled.
    #: 0 not started · 1 done · 2 in progress · 3 failed.
    stages: tuple[int, int, int, int]

    @property
    def needs_attention(self) -> bool:
        """A failure or a question for the user, which recolours the note."""
        return 3 in self.stages or self.status in {"Failed", "Needs you"}


@dataclass(frozen=True)
class ColumnMap:
    """One header of an uploaded CSV and the field it was mapped to."""

    source: str
    target: str | None
    ignored: bool = False


@dataclass(frozen=True)
class ClientConfirm:
    """One client the matcher found, awaiting a human yes."""

    name: str
    meta: str | None
    accent: bool = False
    action: str = "Keep separate"


@dataclass(frozen=True)
class Txn:
    """A line in the "what arrived" ledger."""

    label: str
    meta: str | None
    amount: str | None
    #: True for "no payment matched" rows, which are absence, not a figure.
    muted: bool = False


@dataclass(frozen=True)
class ToolCall:
    """One step of the verification agent's reasoning (Phase 8)."""

    call: str
    result: str


@dataclass(frozen=True)
class FindingRow:
    """One line of the findings table."""

    id: str
    client: str
    title: str
    sub: str | None
    due: str | None
    received: str | None
    gap: str | None
    verdict: str
    kind: str
    selected: bool = False
    #: anomaly_type, for grouping and for the filter chips.
    type_key: str = ""
    #: Everything about this row, lowercased, in one string. The client-side
    #: filter matches against this instead of walking the DOM for each row —
    #: one property read per row per keystroke rather than five.
    haystack: str = ""


@dataclass(frozen=True)
class FindingGroup:
    """Findings of one leak type, with their subtotal.

    Grouping is what makes a long list readable: four labelled runs with
    subtotals beat two hundred undifferentiated rows, and the subtotal answers
    "which kind of leak is costing me most?" without a chart.
    """

    key: str
    label: str
    count: int
    total: str | None
    rows: list[FindingRow]


@dataclass(frozen=True)
class SortOption:
    key: str
    label: str
    active: bool


@dataclass(frozen=True)
class FindingDetail:
    """The selected finding, blown out across the three lower panels."""

    client: str
    type_label: str
    period: str | None
    headline: str | None
    provenance: str | None
    calc: str | None

    # -- the contract side --
    clause: str | None
    clause_ref: str | None
    doc_meta: str | None
    ground: str  # one of GROUND_KINDS

    # -- the ledger side --
    txns: list[Txn]
    #: Everything that arrived for this client inside the matching window.
    #: `None` collapses the row, which is what the demo does — its ledger only
    #: ever lists the payments belonging to the billing in question, so the two
    #: totals would be the same number printed twice.
    window_total: str | None
    #: The part of that which reconciliation matched to *this* expected
    #: billing. On a client with several billings in one month the two differ,
    #: and showing only one of them is how a page ends up listing 16,000 of
    #: payments above a "Received 0.00".
    received_total: str | None
    due_total: str | None
    gap_total: str | None

    # -- the verification side --
    verdict: str
    kind: str
    tools: list[ToolCall]
    agent_prose: str | None
    needs_review: bool

    # -- the client strip --
    c_contracts: str | None
    c_received: str | None
    c_share: str | None
    c_gap: str | None

    @property
    def ground_tag(self) -> str:
        return GROUND_COPY[self.ground][0]

    @property
    def ground_note(self) -> str:
        return GROUND_COPY[self.ground][1]

    @property
    def ground_kind(self) -> str:
        return GROUND_TAG_KIND[self.ground]

    @property
    def highlighted(self) -> bool:
        """False means print the quote plainly — never highlight a guess."""
        return self.ground != "none"


@dataclass(frozen=True)
class CleanStat:
    label: str
    value: str | None


@dataclass(frozen=True)
class CleanRun:
    """The copy and figures for a run that found nothing."""

    run_label: str
    headline: str
    body: list[str]
    stats: list[CleanStat]


@dataclass(frozen=True)
class IntegrityView:
    """Everything the Integrity Engine page needs, in one object."""

    state: str  # one of INTEGRITY_STATES
    cards: list[Card] = field(default_factory=list)
    findings: list[FindingRow] = field(default_factory=list)
    #: The same rows, bucketed by leak type. The list pane renders these; the
    #: flat `findings` above is kept for counting and for the keyboard order.
    groups: list[FindingGroup] = field(default_factory=list)
    sorts: list[SortOption] = field(default_factory=list)
    selected: FindingDetail | None = None

    # processing state only
    pipeline: list[PipelineDoc] = field(default_factory=list)
    pipeline_headline: str | None = None
    pipeline_sub: str | None = None
    column_map: list[ColumnMap] = field(default_factory=list)
    column_map_file: str | None = None
    column_map_note: str | None = None
    clients: list[ClientConfirm] = field(default_factory=list)
    clients_headline: str | None = None

    clean: CleanRun | None = None

    #: Set when a block is empty for a structural reason rather than because
    #: the run is genuinely clean — "Phase 8 fills this in". Rendered in the
    #: `.absent` box beside skeletons instead of faking content.
    notices: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Decision Engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkRow:
    """One line of the "how this was worked out" ledger."""

    label: str
    src: str | None
    amount: str | None
    bold: bool = False
    final: bool = False
    accent: bool = False


@dataclass(frozen=True)
class Bar:
    """One month of the projection: `a` as things stand, `b` once collected."""

    a: str
    b: str


@dataclass(frozen=True)
class DecisionView:
    question: str
    suggestions: list[str]

    #: False when nothing has been asked yet, or when the analyser that would
    #: answer it does not exist yet. The page then shows the working it *can*
    #: compute and says plainly what is missing, rather than inventing a verdict.
    answered: bool
    verdict_word: str | None
    verdict_qual: str | None
    #: Pre-rendered HTML: the lead paragraph with its figures wrapped in <b>.
    #: Built by the presenter because the emphasis marks specific numbers.
    lead_html: str | None
    after: str | None

    bars: list[Bar] = field(default_factory=list)
    axis: list[str] = field(default_factory=list)
    working: list[WorkRow] = field(default_factory=list)
    caveat: str | None = None
    notices: dict[str, str] = field(default_factory=dict)
