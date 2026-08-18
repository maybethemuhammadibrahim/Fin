"""[A+B] The review screen for the sealed test set. Phase 10, step 5.

    python scripts/prepare_testset.py prepare     # first — drafts the answers
    streamlit run scripts/review_testset.py       # then — this
    python scripts/prepare_testset.py finalize    # last — writes eval_set.jsonl

**This is the only task in Phase 10 that needs a human**, so the design goal is
to make it small: one card at a time, the extracted answer beside the sentence
it came from, the automatic checks already run, and a decision.

**You are not doing legal analysis.** Two questions per card:

1. Is this number in the highlighted sentence?
2. Is this sentence about the regular fee the customer pays — *not* interest on
   a late payment, *not* a complaints procedure?

Question 2 is the only one needing judgement, and it is exactly the trap known
issue #34 records: an "18% per annum" late-payment clause scored as a fee
escalation and was caught only by a human read.

**You can correct, not only approve.** Measured 2026-08-17, the drafting model
missed a fee that was plainly in the text on 22 of 30 contracts — Regal
Entertainment reads "$6,000" and the draft said there was none. Binning a real
contract because a model misread it is backwards, so a wrong draft now arrives
as an editable card. `docs/implementation_plan.md` always asked for *"corrected
pairs"*; approve-or-discard was an under-build.

**Discarding is still free and still encouraged.** A smaller clean set beats a
bigger dirty one, and an unsure discard costs nothing. The only way to damage
the eval set is to approve something you did not understand.

Decisions save after every click, so closing the tab loses nothing.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_testset import Proposal, read_decision, run_checks  # noqa: E402

HELDOUT = ROOT / "data" / "corpus" / "heldout"
PROPOSALS = HELDOUT / "proposals.json"
DECISIONS = HELDOUT / "decisions.json"

FREQUENCIES = ["monthly", "quarterly", "annual", "one_time", "unknown"]

st.set_page_config(page_title="FinSight — review the test set", layout="wide")


def load_proposals() -> list[dict]:
    if not PROPOSALS.exists():
        return []
    return json.loads(PROPOSALS.read_text(encoding="utf-8"))["proposals"]


def load_decisions() -> dict:
    if not DECISIONS.exists():
        return {}
    return json.loads(DECISIONS.read_text(encoding="utf-8"))


def save_decision(name: str, verdict: str, rules: dict | None = None) -> None:
    decisions = load_decisions()
    decisions[name] = {"verdict": verdict, "rules": rules}
    DECISIONS.write_text(json.dumps(decisions, indent=2), encoding="utf-8")


def highlight(text: str, quotes: list[str]) -> str:
    """The excerpt with every quoted clause marked.

    Falls back to a whitespace-tolerant match, because EDGAR text carries
    newlines mid-sentence and a faithfully-copied quote still fails `in`.
    When nothing matches, the text renders plain — which is itself the answer
    to question 1.
    """
    escaped = html.escape(text)
    for quote in quotes:
        if not quote:
            continue
        target = html.escape(quote)
        if target in escaped:
            escaped = escaped.replace(
                target, f'<mark style="background:#ffd54f;padding:2px 0">{target}</mark>', 1
            )
            continue
        words = [w for w in re.split(r"\s+", html.escape(quote).strip()) if w][:14]
        if len(words) >= 4:
            match = re.search(r"\s+".join(re.escape(w) for w in words), escaped)
            if match:
                escaped = (
                    escaped[: match.start()]
                    + f'<mark style="background:#ffe082;padding:2px 0">{match.group(0)}</mark>'
                    + escaped[match.end() :]
                )
    return escaped.replace("\n", "<br>")


def quotes_of(rules: dict | None) -> list[str]:
    if not rules:
        return []
    out: list[str] = []
    esc = rules.get("escalation")
    if isinstance(esc, dict) and esc.get("clause_text"):
        out.append(esc["clause_text"])
    for item in (rules.get("discounts") or []) + (rules.get("milestones") or []):
        if isinstance(item, dict) and item.get("clause_text"):
            out.append(item["clause_text"])
    return out


# ---------------------------------------------------------------------------

raw_proposals = load_proposals()
if not raw_proposals:
    st.error("Nothing prepared yet.")
    st.code("python scripts/prepare_testset.py prepare", language="bash")
    st.stop()

proposals = [Proposal(**p) for p in raw_proposals]
decisions = load_decisions()
reviewable = [p for p in proposals if p.verdict != "unusable"]
unusable = len(proposals) - len(reviewable)

st.title("Review the sealed test set")
st.caption(
    "These are the exam questions. Nothing here has ever been used for training — "
    "and nothing you approve ever will be."
)

kept = sum(1 for v in decisions.values() if read_decision(v)[0] == "keep")
done = sum(1 for p in reviewable if p.filename in decisions)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Sealed", len(proposals))
c2.metric("For you", len(reviewable))
c3.metric("Skipped", unusable, help="No recurring fee to find — you never need to see these")
c4.metric("Approved", kept)

if reviewable:
    st.progress(done / len(reviewable), text=f"{done} of {len(reviewable)} reviewed")

with st.expander("What am I actually deciding?  ← read this once", expanded=done == 0):
    st.markdown(
        """
**You are not doing legal analysis.** Two questions:

1. **Is the number in the highlighted sentence?**
2. **Is the highlighted sentence about the regular fee the customer pays?**
   Not interest on a late payment. Not a complaints procedure. Not a penalty.

**If a value is wrong, fix it.** The draft comes from a machine that misread
these contracts often — that is the whole reason this product exists. Correcting
one takes seconds and saves a real contract.

**If you are unsure, click Discard.** Throwing one away costs nothing. You cannot
damage this by being cautious — the only way to harm it is approving something
you did not understand.

There is a real example of question 2 in this pile: a clause reading
*"18% per annum"* which is a **late-payment penalty, not a fee increase.**
The computer cannot tell the difference. That is why you are here.
        """
    )

view = st.radio(
    "Show",
    ["To do", "Needs fixing", "All", "Done"],
    horizontal=True,
    label_visibility="collapsed",
)
if view == "To do":
    shown = [p for p in reviewable if p.filename not in decisions]
elif view == "Needs fixing":
    shown = [p for p in reviewable if p.verdict == "needs_fix" and p.filename not in decisions]
elif view == "Done":
    shown = [p for p in reviewable if p.filename in decisions]
else:
    shown = reviewable

if not shown:
    st.success("Nothing left in this view.")
    if kept:
        st.info("When you are done, write the exam paper:")
        st.code("python scripts/prepare_testset.py finalize", language="bash")
    st.stop()

proposal = shown[0]
name = proposal.filename
saved_verdict, saved_rules = read_decision(decisions.get(name)) if name in decisions else ("", None)
rules = dict(saved_rules or proposal.rules or {})

st.divider()
head1, head2 = st.columns([4, 1])
head1.subheader(name.rsplit("_EX", 1)[0].replace("_", " ").title())
head1.caption(name)
if proposal.verdict == "needs_fix":
    head2.warning("Needs a fix")
else:
    head2.success("Checks passed")

left, right = st.columns([3, 2])

with left:
    st.markdown("**The contract** — highlighted text is what the answer quotes")
    st.markdown(
        f'<div style="max-height:560px;overflow-y:auto;border:1px solid rgba(128,128,128,.35);'
        f'border-radius:8px;padding:14px;font-size:0.86rem;line-height:1.6;">'
        f"{highlight(proposal.excerpt, quotes_of(rules))}</div>",
        unsafe_allow_html=True,
    )

with right:
    st.markdown("**The answer** — edit anything that is wrong")

    rules["client_name"] = st.text_input("Client", value=str(rules.get("client_name") or ""), key=f"c{name}")

    amount_raw = st.text_input(
        "Fee amount (just the number)",
        value="" if rules.get("base_amount") is None else str(rules["base_amount"]),
        key=f"a{name}",
        help="Type it exactly as the contract states it. Leave blank if there is none.",
    )
    try:
        rules["base_amount"] = float(amount_raw.replace(",", "").replace("$", "").strip()) if amount_raw.strip() else None
    except ValueError:
        st.error("That is not a number")

    freq = str(rules.get("billing_frequency") or "unknown")
    rules["billing_frequency"] = st.selectbox(
        "How often", FREQUENCIES, index=FREQUENCIES.index(freq) if freq in FREQUENCIES else 4, key=f"f{name}"
    )
    rules["contract_start_date"] = (
        st.text_input("Starts (YYYY-MM-DD)", value=str(rules.get("contract_start_date") or ""), key=f"s{name}")
        or None
    )

    has_increase = st.checkbox(
        "This contract has a fee increase",
        value=isinstance(rules.get("escalation"), dict),
        key=f"he{name}",
        help="Only tick this for a rise in the regular fee — not late-payment interest.",
    )
    if has_increase:
        esc = rules.get("escalation") if isinstance(rules.get("escalation"), dict) else {}
        pct_raw = st.text_input(
            "Increase (%)", value="" if esc.get("percentage") is None else str(esc["percentage"]), key=f"p{name}"
        )
        quote = st.text_area(
            "The sentence it comes from (copy it exactly)",
            value=str(esc.get("clause_text") or ""),
            height=110,
            key=f"q{name}",
        )
        try:
            pct = float(pct_raw.strip()) if pct_raw.strip() else None
        except ValueError:
            pct = None
            st.error("That is not a number")
        rules["escalation"] = {
            "percentage": pct,
            "after_months": int(esc.get("after_months") or 12),
            "clause_text": quote,
        }
    else:
        rules["escalation"] = None

    rules.setdefault("currency", "USD")
    rules.setdefault("contract_end_date", None)
    rules.setdefault("payment_terms", None)
    rules.setdefault("discounts", [])
    rules.setdefault("milestones", [])

    st.markdown("**Checks on what you see now**")
    for check in run_checks(rules, proposal.excerpt):
        label = check.label.lstrip("! ").strip()
        note = f" — {check.note}" if check.note else ""
        st.markdown(("✅ " if check.passed else "⚠️ ") + label + note)

    if proposal.error:
        st.error(proposal.error)

st.divider()
b1, b2, b3, spacer = st.columns([1.2, 1, 1.4, 2.4])

if b1.button("✅  Approve", use_container_width=True, type="primary"):
    save_decision(name, "keep", rules)
    st.rerun()
if b2.button("🗑️  Discard", use_container_width=True):
    save_decision(name, "drop")
    st.rerun()
if b3.button("🤔  Not sure → discard", use_container_width=True):
    save_decision(name, "drop")
    st.rerun()

if saved_verdict:
    edited = " (with your corrections)" if saved_rules else ""
    st.caption(f"Currently marked **{saved_verdict}**{edited} — clicking again changes it.")
