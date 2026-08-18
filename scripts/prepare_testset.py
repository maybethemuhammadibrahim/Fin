#!/usr/bin/env python3
"""[A] Prepare the sealed contracts for human review, then build eval_set.jsonl.

    python scripts/prepare_testset.py prepare    # draft answers + auto-checks (uses API)
    python scripts/prepare_testset.py finalize   # approved cards -> eval_set.jsonl
    python scripts/prepare_testset.py status     # how far through the review we are

Between the two, a human reviews the cards:

    streamlit run scripts/review_testset.py

---

## Why an excerpt and not the whole filing

The 30 sealed contracts total **9.4 million characters** — one of them
(`Chemtura_CORP_EX-99.1`) is 5.3 MB on its own, because an EDGAR exhibit can
carry a whole appendix set. Sending that to an API would exhaust the $5 cap on a
single document, and no human is going to read it either.

So each contract is reduced to a **focused excerpt**: the opening (parties and
dates) plus a window around the fee clause and around the escalation or discount
clause, located by the same `filter_contracts.score_contract` patterns that
sorted the corpus in the first place. Typically ~4 KB instead of ~40 KB.

This is not a shortcut, it is the same shape as the training data (~1 KB
documents, known issue #79's note about sequence length) and the same shape a
real extraction sees, because `prompts.extraction_user` already chunks long
documents. Measuring on excerpts and training on excerpts keeps the comparison
honest; measuring on excerpts while training on whole filings would not.

**The excerpt is what gets reviewed and what lands in `eval_set.jsonl`**, so a
human approves exactly the text the model will be scored on.

## The draft answers come from DeepSeek, and that is disclosed

`docs/implementation_plan.md` Phase 10 asks for pairs drafted by "the best
available model" and then human-verified. That is what this does — offline,
never in the runtime path, no vendor package added (hard rule 6).

**A drafted answer is a suggestion, not ground truth.** It becomes ground truth
only when a human approves the card. The report should say so plainly: the
held-out answers were drafted by a commercial model and human-verified, which is
standard practice and only dishonest if hidden.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_sourcing.filter_contracts import score_contract  # noqa: E402
from training.build_pairs import (  # noqa: E402
    BASETEN_MODEL,
    BASETEN_URL,
    INSTRUCTION,
    BudgetExhausted,
    Spend,
    _api_key,
    _numbers,
)

HELDOUT = ROOT / "data" / "corpus" / "heldout"
SEALED_JSON = HELDOUT / "SEALED.json"
PROPOSALS = HELDOUT / "proposals.json"
DECISIONS = HELDOUT / "decisions.json"
EVAL_SET = ROOT / "training" / "data" / "eval_set.jsonl"

HEAD_CHARS = 1200
WINDOW = 1400


# ---------------------------------------------------------------------------
# Excerpting
# ---------------------------------------------------------------------------


def _window_around(text: str, needle: str | None, size: int = WINDOW) -> str | None:
    """Locate a scored snippet in the ORIGINAL text and return a window around it.

    `score_contract` searches `_normalise()`d text — lowercased and
    whitespace-collapsed — so its snippets are never found verbatim in the raw
    document. A plain `text.find()` here silently returned None for 26 of the 30
    sealed contracts, which reduced every excerpt to its first 1200 characters
    and would have cut the fee clause out of the very thing being reviewed.

    So: rebuild the probe as a whitespace-tolerant, case-insensitive pattern.
    """
    if not needle:
        return None
    words = needle.strip().split()[:10]
    if len(words) < 3:
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    match = re.search(pattern, text, re.I)
    if match is None:  # shorter probe: the tail of a snippet is often cleaner
        words = needle.strip().split()[-10:]
        pattern = r"\s+".join(re.escape(w) for w in words)
        match = re.search(pattern, text, re.I)
    if match is None:
        return None
    start = max(0, match.start() - size // 3)
    return text[start : start + size]


def excerpt(path: Path) -> str:
    """Opening + the fee region + the escalation/discount region, de-duplicated."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    scored = score_contract(path)

    parts = [text[:HEAD_CHARS]]
    for snippet in (
        scored.concrete_recurring or scored.shape_recurring,
        scored.concrete_escalation or scored.shape_escalation,
    ):
        window = _window_around(text, snippet)
        if window and not any(window[:120] in existing for existing in parts):
            parts.append(window)

    joined = "\n\n[...]\n\n".join(p.strip() for p in parts if p and p.strip())
    return re.sub(r"\n{3,}", "\n\n", joined)


# ---------------------------------------------------------------------------
# Automatic checks — everything a machine can settle before a human looks
# ---------------------------------------------------------------------------

_INTEREST = re.compile(r"per annum|interest|late payment|overdue|past due", re.I)
_DISPUTE = re.compile(r"dispute|senior management|arbitrat|good faith|executive sponsor", re.I)
_REDACTED = re.compile(r"\[\s*\*+\s*\]|\*{3,}")


def appears_verbatim(quote: str, text: str) -> bool:
    """Is `quote` word-for-word in `text`, ignoring only whitespace and quote marks?

    A plain `quote in text` is too literal here and rejected good extractions.
    EDGAR exhibits are HTML converted to text, so a single sentence routinely
    carries newlines mid-clause and curly quotes; a model copying it faithfully
    still produces a string that fails `in`. Measured: it discarded GAMEZNFLIX,
    which states a $5,000 monthly fee AND a 10% anniversary increase — one of
    the best test cases in the corpus.

    Every word must still match, in order. This tolerates typography, not
    paraphrase, and it matches how `core/extraction/clause_locator.py` already
    behaves — Phase 7 hardened it to fold whitespace and typography for exactly
    this reason (#58/#59). Checking more strictly here than the product checks
    at runtime would measure the wrong thing.
    """
    if not quote or not quote.strip():
        return False

    def fold(s: str) -> str:
        s = s.replace("’", "'").replace("‘", "'")
        s = s.replace("“", '"').replace("”", '"')
        s = s.replace("–", "-").replace("—", "-").replace("\xa0", " ")
        return re.sub(r"\s+", " ", s).strip().lower()

    return fold(quote) in fold(text)


@dataclass
class Check:
    label: str
    passed: bool
    note: str = ""


@dataclass
class Proposal:
    filename: str
    excerpt: str
    rules: dict | None
    checks: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def failed_hard(self) -> bool:
        return self.rules is None or any(
            not c["passed"] and c["label"].startswith("!") for c in self.checks
        )

    @property
    def verdict(self) -> str:
        """`clean` | `needs_fix` | `unusable`.

        The first version of this was a two-way `auto_reject`, and it threw away
        good contracts because of bad *drafts*. Measured 2026-08-17: 22 of 30
        were binned, and among them Regal Entertainment and CBS Outdoor, whose
        excerpts plainly read "$6,000" and "$12,500" while the draft said there
        was no fee. Discarding a contract because a model misread it is the
        wrong way round — the whole premise of this product is that the machine
        reads these worse than a person does.

        `docs/implementation_plan.md` always said the human produces *"corrected
        pairs"*; keep-or-discard was an under-build. So a failed check now means
        "a human should look", and only a genuinely unusable document — no JSON
        at all, or no plausible recurring fee anywhere in the excerpt — is
        binned without being seen.
        """
        if self.rules is None:
            return "unusable"
        if not self.failed_hard:
            return "clean"
        return "needs_fix" if _has_correctable_fee(self.excerpt) else "unusable"


def _has_correctable_fee(text: str) -> bool:
    """Is there a recurring fee in this excerpt that a human could type in?

    If not, no amount of correcting will produce a usable answer and the card
    would only waste the reviewer's attention.
    """
    return bool(
        re.search(
            r"(?:monthly|quarterly|annual)\s+(?:base\s+)?(?:fee|retainer|compensation|salary)"
            r"[^.$]{0,60}\$\s?[\d,]+"
            r"|\$\s?[\d,]+(?:\.\d{2})?\s*(?:per|each)\s+(?:month|quarter|year)",
            re.sub(r"\s+", " ", text),
            re.I,
        )
    )


def _numeric_values(text: str) -> list[float]:
    """Every number in the text as a float — "$ 66,666.67" -> 66666.67.

    Tolerates the space EDGAR often leaves after a dollar sign, and the commas.
    """
    values: list[float] = []
    for raw in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        try:
            values.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return values


def run_checks(rules: dict, text: str) -> list[Check]:
    """Hard checks (prefixed `!`) auto-reject. Soft ones are warnings for the human."""
    checks: list[Check] = []
    numbers = _numbers(text)

    amount = rules.get("base_amount")
    # Compare NUMERICALLY, not as strings. `str(int(float(x)))` truncated
    # 66666.67 to "66666" and then failed to find it, rejecting Aureus Greenway
    # whose contract plainly reads "$ 66,666.67" — a false rejection that also
    # made the extraction look like it had done arithmetic when it had not.
    try:
        amount_ok = amount is not None and any(
            abs(float(amount) - value) < 0.01 for value in _numeric_values(text)
        )
    except (TypeError, ValueError):
        amount_ok = False
    checks.append(
        Check(
            "! the fee amount appears in the text",
            amount_ok,
            "no amount extracted" if amount is None else f"extracted {amount}",
        )
    )

    name = str(rules.get("client_name") or "").strip()
    checks.append(Check("the client name appears in the text", bool(name) and name[:18] in text))

    esc = rules.get("escalation")
    if isinstance(esc, dict):
        # Every field here is a MODEL's output and may be missing, null or the
        # wrong type. These checks exist to grade exactly that, so they must not
        # themselves crash on it — a malformed draft has to reach the card as a
        # failed check, not as a traceback that stops the whole run.
        quote = esc.get("clause_text") or ""
        pct = esc.get("percentage")
        checks.append(Check("! the quoted increase clause is verbatim", appears_verbatim(quote, text)))
        try:
            matches = pct is not None and f"{float(pct):g}" in _numbers(quote)
        except (TypeError, ValueError):
            matches = False
        checks.append(
            Check(
                "! the percentage matches its own quote",
                matches,
                "no percentage extracted" if pct is None else f"extracted {pct}%",
            )
        )
        checks.append(
            Check(
                "the quote is not a late-payment clause",
                not _INTEREST.search(quote),
                "mentions interest / per annum / overdue — known issue #34" if _INTEREST.search(quote) else "",
            )
        )
        checks.append(
            Check(
                "the quote is not a dispute-escalation clause",
                not _DISPUTE.search(quote),
                "mentions disputes / senior management — known issue #24" if _DISPUTE.search(quote) else "",
            )
        )

    for i, dis in enumerate(rules.get("discounts") or []):
        quote = (dis.get("clause_text") or "") if isinstance(dis, dict) else ""
        checks.append(Check(f"! discount {i + 1} quote is verbatim", appears_verbatim(quote, text)))

    for i, ms in enumerate(rules.get("milestones") or []):
        quote = (ms.get("clause_text") or "") if isinstance(ms, dict) else ""
        checks.append(Check(f"! milestone {i + 1} quote is verbatim", appears_verbatim(quote, text)))

    checks.append(
        Check(
            "no redacted figures in the excerpt",
            not _REDACTED.search(text),
            "contains [***] — known issue #25" if _REDACTED.search(text) else "",
        )
    )
    return checks


# ---------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------

DRAFT_SYSTEM = (
    "You extract financial rules from commercial contracts and return JSON only.\n"
    "Rules:\n"
    "1. Copy every clause_text VERBATIM from the contract. Never paraphrase, never "
    "add ellipses.\n"
    "2. An escalation is a rise in the RECURRING FEE the customer pays. Interest on "
    "late or overdue payments is NOT an escalation. Escalating a DISPUTE to senior "
    "management is NOT an escalation. Return null when there is none.\n"
    "3. Never invent a figure. If the contract does not state it, use null.\n"
    "4. billing_frequency is one of: monthly, quarterly, annual, one_time, unknown.\n"
    'Schema: {"client_name": str, "contract_start_date": "YYYY-MM-DD"|null, '
    '"contract_end_date": "YYYY-MM-DD"|null, "base_amount": number|null, '
    '"currency": str, "billing_frequency": str, "payment_terms": str|null, '
    '"escalation": {"percentage": number, "after_months": int, "clause_text": str}|null, '
    '"discounts": [{"percentage": number, "duration_months": int, "clause_text": str}], '
    '"milestones": [{"description": str, "amount": number, "due_condition": str|null, '
    '"clause_text": str}]}'
)


def draft(text: str, key: str, spend: Spend, tries: int = 3) -> dict | None:
    payload = {
        "model": BASETEN_MODEL,
        "messages": [
            {"role": "system", "content": DRAFT_SYSTEM},
            {"role": "user", "content": f"{INSTRUCTION}\n\n{text}"},
        ],
        "max_tokens": 3000,
        "temperature": 0.0,
        "reasoning_effort": "low",
    }
    request = urllib.request.Request(
        BASETEN_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(tries):
        try:
            body = json.loads(urllib.request.urlopen(request, timeout=240).read())
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode(errors="ignore")
            if exc.code in (402, 403) or "quota" in detail.lower() or "credit" in detail.lower():
                raise BudgetExhausted(f"HTTP {exc.code}: {detail}") from exc
            if exc.code == 429 and attempt < tries - 1:
                time.sleep(6 * (attempt + 1))
                continue
            return None
        except Exception:
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            return None

        usage = body.get("usage") or {}
        spend.calls += 1
        spend.prompt_tokens += usage.get("prompt_tokens", 0)
        spend.completion_tokens += usage.get("completion_tokens", 0)
        spend.reasoning_tokens += (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)

        content = (body.get("choices") or [{}])[0].get("message", {}).get("content")
        if not content:  # ran out of room mid-thought (#80)
            continue
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            continue
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_prepare(limit: int | None) -> int:
    if not SEALED_JSON.exists():
        print("! nothing sealed — run `python scripts/seal_testset.py` first")
        return 2
    key = _api_key()
    if not key:
        print("! no API key (BASETEN_API_KEY / DEEPSEEK_API) in the environment or .env")
        return 2

    manifest = json.loads(SEALED_JSON.read_text(encoding="utf-8"))
    names = [row["filename"] for row in manifest["contracts"]][: limit or None]

    spend = Spend()
    proposals: list[Proposal] = []
    for i, name in enumerate(names, 1):
        path = HELDOUT / name
        body = excerpt(path)
        print(f"  [{i:2}/{len(names)}] {name[:52]:52} {len(body):>6,} chars", flush=True)
        try:
            rules = draft(body, key, spend)
        except BudgetExhausted as exc:
            print(f"\n! THE API BUDGET IS EXHAUSTED — tell the user.\n  {exc}")
            print(f"  spend so far: {spend.line()}")
            break
        checks = [asdict(c) for c in run_checks(rules, body)] if rules else []
        proposals.append(
            Proposal(
                filename=name,
                excerpt=body,
                rules=rules,
                checks=checks,
                error=None if rules else "the model returned no usable JSON",
            )
        )
        time.sleep(1.5)

    PROPOSALS.write_text(
        json.dumps({"prepared": len(proposals), "proposals": [asdict(p) for p in proposals]}, indent=2),
        encoding="utf-8",
    )
    counts: dict[str, int] = {}
    for proposal in proposals:
        counts[proposal.verdict] = counts.get(proposal.verdict, 0) + 1
    print(f"\ndrafted {len(proposals)}")
    print(f"  clean      {counts.get('clean', 0):2}  every check passed — a quick yes/no")
    print(f"  needs_fix  {counts.get('needs_fix', 0):2}  a fee is there but the draft is wrong — correct it")
    print(f"  unusable   {counts.get('unusable', 0):2}  no recurring fee to find — you never see these")
    print(f"spend: {spend.line()}")
    print(f"written: {PROPOSALS.relative_to(ROOT)}")
    print("\nnow review them:  streamlit run scripts/review_testset.py")
    return 0


def read_decision(raw: object) -> tuple[str, dict | None]:
    """(verdict, corrected_rules). Accepts the old plain-string format too."""
    if isinstance(raw, str):
        return raw, None
    if isinstance(raw, dict):
        return str(raw.get("verdict", "drop")), raw.get("rules")
    return "drop", None


def cmd_status() -> int:
    if not PROPOSALS.exists():
        print("! nothing prepared yet — run `prepare` first")
        return 2
    proposals = [Proposal(**p) for p in json.loads(PROPOSALS.read_text(encoding="utf-8"))["proposals"]]
    decisions = json.loads(DECISIONS.read_text(encoding="utf-8")) if DECISIONS.exists() else {}
    verdicts = [read_decision(v)[0] for v in decisions.values()]
    corrected = sum(1 for v in decisions.values() if read_decision(v)[1])
    reviewable = [p for p in proposals if p.verdict != "unusable"]

    print(f"{len(proposals)} prepared, {len(proposals) - len(reviewable)} unusable (never shown)")
    print(f"reviewed: {len(decisions)} / {len(reviewable)}")
    print(f"  keep {verdicts.count('keep')}   discard {verdicts.count('drop')}   (of which corrected by hand: {corrected})")
    if verdicts.count("keep"):
        print(f"\nready to finalize {verdicts.count('keep')} into eval_set.jsonl")
    return 0


def cmd_finalize() -> int:
    if not (PROPOSALS.exists() and DECISIONS.exists()):
        print("! review the cards first: streamlit run scripts/review_testset.py")
        return 2
    proposals = {p["filename"]: p for p in json.loads(PROPOSALS.read_text(encoding="utf-8"))["proposals"]}
    decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))

    kept = []
    for name, raw in decisions.items():
        verdict, corrected = read_decision(raw)
        if verdict != "keep" or name not in proposals:
            continue
        row = dict(proposals[name])
        if corrected:  # a reviewed answer wins over the draft, always
            row["rules"] = corrected
        record = raw if isinstance(raw, dict) else {}
        rule_fixes = record.get("corrections") or []
        draft = proposals[name].get("rules")
        if rule_fixes:
            row["answer_source"] = "model_draft + rule_correction"
        elif corrected and corrected != draft:
            row["answer_source"] = "human_edit"
        else:
            row["answer_source"] = "model_draft"
        row["rule_corrections"] = rule_fixes
        kept.append(row)

    if not kept:
        print("! nothing approved — nothing to write")
        return 1

    EVAL_SET.parent.mkdir(parents=True, exist_ok=True)
    with EVAL_SET.open("w", encoding="utf-8") as handle:
        for row in kept:
            handle.write(
                json.dumps(
                    {
                        "instruction": INSTRUCTION,
                        "input": row["excerpt"],
                        "output": json.dumps(row["rules"], ensure_ascii=False),
                        "source": row["filename"],
                        # Provenance, stated exactly. "verified_by: human" was
                        # hardcoded and became a lie the moment
                        # scripts/autocorrect_testset.py repaired an answer by
                        # rule. The Phase 11 report has to be able to say how
                        # each answer was arrived at, so record it per row
                        # rather than asserting one story for all of them.
                        "approved_by": "human",
                        "answer_source": row.get("answer_source", "model_draft"),
                        "rule_corrections": row.get("rule_corrections") or [],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"wrote {len(kept)} human-verified pair(s) -> {EVAL_SET.relative_to(ROOT)}")
    print("This file is TRACKED IN GIT on purpose and must never be trained on.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("prepare", "status", "finalize"))
    parser.add_argument("--limit", type=int, default=None, help="prepare only the first N (cheap test)")
    args = parser.parse_args()
    if args.command == "prepare":
        return cmd_prepare(args.limit)
    if args.command == "status":
        return cmd_status()
    return cmd_finalize()


if __name__ == "__main__":
    raise SystemExit(main())
