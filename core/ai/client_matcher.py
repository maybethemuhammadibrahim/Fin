"""[A] Fuzzy grouping of client-name variants. Phase 5.

Upload four contracts and the model returns four `client_name` strings that a
human reads as three clients: "Starter Labs", "Starter Labs Inc." and
"StarterLabs" are one company with a comma problem. Group them, then **ask**
(`app/components/client_confirm.py`) — the confirmation step is the safety net,
because a wrong merge silently reconciles one client's invoices against
another's contract.

Pure: no DB, no network, no model.
"""

from __future__ import annotations

import re

from thefuzz import fuzz

DEFAULT_THRESHOLD = 85

#: Corporate suffixes and decoration that carry no identity. Stripped only for
#: COMPARISON — the canonical label shown to the user keeps whatever the
#: contract actually said.
_NOISE = re.compile(
    r"\b(?:inc|inc\.|incorporated|llc|l\.l\.c\.|ltd|ltd\.|limited|corp|corp\.|"
    r"corporation|co|co\.|company|plc|gmbh|s\.a\.|sa|pty|llp|lp|group|holdings|"
    r"the)\b",
    re.I,
)


def normalise(name: str) -> str:
    """Comparison key: suffixes, punctuation and spacing removed.

    "Starter Labs, Inc." and "StarterLabs" both become "starterlabs", which is
    the point — space removal is what catches the compound-word variant that
    token-based matching misses.
    """
    without_noise = _NOISE.sub(" ", name or "")
    return re.sub(r"[^a-z0-9]", "", without_noise.lower())


def similarity(left: str, right: str) -> int:
    """0-100. Compares normalised forms, so it is punctuation-blind."""
    a, b = normalise(left), normalise(right)
    if not a or not b:
        return 0
    if a == b:
        return 100
    return max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b))


def group_clients(names: list[str], threshold: int = DEFAULT_THRESHOLD) -> dict[str, list[str]]:
    """Group name variants. Returns {canonical name: [every variant seen]}.

    The canonical name is the **longest** variant in the group, because
    "Starter Labs, Inc." is the version a user recognises as the legal entity
    and "StarterLabs" is the version that looks like a typo. Order is stable:
    groups come out in first-seen order, and so do the variants inside them.
    """
    groups: dict[str, list[str]] = {}
    for name in names:
        if not name or not name.strip():
            continue
        cleaned = name.strip()
        for canonical, variants in groups.items():
            if any(similarity(cleaned, variant) >= threshold for variant in variants):
                if cleaned not in variants:
                    variants.append(cleaned)
                break
        else:
            groups[cleaned] = [cleaned]

    # Re-label each group with its longest member, keeping first-seen order.
    relabelled: dict[str, list[str]] = {}
    for variants in groups.values():
        relabelled[max(variants, key=len)] = variants
    return relabelled


def canonical_for(name: str, groups: dict[str, list[str]]) -> str:
    """Which group does this name belong to? Falls back to itself."""
    for canonical, variants in groups.items():
        if name in variants:
            return canonical
    return name
