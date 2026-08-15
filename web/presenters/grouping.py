"""[B] Sorting and grouping for the findings list. Phase 6.

Shared by both presenters on purpose. Grouping is presentation, not data, and
if demo and live each did their own the two lists would drift in order — which
is exactly the drift the identical-view-model rule exists to prevent.

Why grouping at all: the list has to stay readable at a few hundred rows. Four
labelled runs with a subtotal each let you answer "which kind of leak costs me
most?" by looking, and they give the eye somewhere to rest while scrolling.
Sorting inside a group is always by amount, because within one kind of problem
the only question is which one is biggest.
"""

from __future__ import annotations

from web.format import money
from web.viewmodels import TYPE_LABELS, FindingGroup, FindingRow, SortOption

#: Group order. Deliberately not alphabetical and not by size — it runs from
#: the most clear-cut leak to the most ambiguous, so the findings that are
#: easiest to act on are the ones you meet first.
TYPE_ORDER = ("ghost_invoice", "forgotten_raise", "zombie_discount", "short_change")

SORTS = (
    ("amount", "Amount"),
    ("client", "Client"),
    ("date", "Period"),
)
DEFAULT_SORT = "amount"


def sort_options(active: str) -> list[SortOption]:
    active = active if active in dict(SORTS) else DEFAULT_SORT
    return [SortOption(key=k, label=label, active=k == active) for k, label in SORTS]


def sort_key(sort: str):
    """A key function over (row, gap_value, client, period_sort_value) tuples.

    Rows carry their figures as formatted strings, so sorting has to happen on
    the raw values the caller still has. Callers pass a list of
    `(row, gap, client, period)` and get it back ordered.
    """
    if sort == "client":
        return lambda item: (item[2].lower(), -item[1])
    if sort == "date":
        # Newest first; rows with no period sort last rather than crashing on
        # a None comparison.
        return lambda item: (item[3] is None, item[3] and -item[3].toordinal(), -item[1])
    return lambda item: -item[1]


def build_groups(rows: list[FindingRow], gaps: dict[str, float]) -> list[FindingGroup]:
    """Bucket rows by leak type, in TYPE_ORDER, preserving the caller's order.

    `gaps` maps row id -> the raw gap, because the row itself only carries the
    formatted string and a subtotal cannot be summed from "(1,500.00)".
    """
    buckets: dict[str, list[FindingRow]] = {}
    for row in rows:
        buckets.setdefault(row.type_key, []).append(row)

    ordered = [k for k in TYPE_ORDER if k in buckets]
    ordered += [k for k in buckets if k not in TYPE_ORDER]  # unknown types last

    groups = []
    for key in ordered:
        members = buckets[key]
        total = sum(gaps.get(r.id, 0.0) for r in members)
        groups.append(
            FindingGroup(
                key=key,
                label=TYPE_LABELS.get(key, key.replace("_", " ").capitalize()),
                count=len(members),
                total=money(total) if total else None,
                rows=members,
            )
        )
    return groups


def haystack(*parts: str | None) -> str:
    """The one lowercased string the client-side filter matches against."""
    return " ".join(p for p in parts if p).lower()
