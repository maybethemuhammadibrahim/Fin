"""[B] Money, dates and missing values, formatted once. Phase 6.

Templates call none of this directly except through the Jinja filters
registered in `web.main`. The point is that a figure is turned into a string in
exactly one place, so the findings table and the drill-down cannot disagree
about how ``480`` should look.

House style, taken from the mockup:

* Money is grouped, always two decimals, no currency symbol: ``6,480.00``.
* A shortfall is written in accountancy parentheses: ``(480.00)``.
* Nothing at all is an em dash, never ``0.00`` — see `dash`.
"""

from __future__ import annotations

from datetime import date, datetime

DASH = "—"


def money(value: float | int | None, *, decimals: int = 2) -> str | None:
    """``6480.0`` -> ``"6,480.00"``. ``None`` stays ``None``.

    Passing ``None`` through rather than substituting zero is the whole
    contract: the caller decides whether absence means "nothing owed" or "we
    never found out", and only it knows which.
    """
    if value is None:
        return None
    return f"{float(value):,.{decimals}f}"


def gap(value: float | int | None) -> str | None:
    """A shortfall in accountancy parentheses: ``480.0`` -> ``"(480.00)"``.

    Zero is rendered as an em dash rather than ``(0.00)`` — a finding with no
    gap is a finding that was ruled out, and the table should read that way.
    """
    if value is None:
        return None
    if abs(float(value)) < 0.005:
        return DASH
    return f"({money(abs(value))})"


def pct(value: float | None, *, decimals: int = 0) -> str | None:
    """``0.31`` -> ``"31%"``. Expects a 0-1 fraction, not an already-scaled one."""
    if value is None:
        return None
    return f"{value * 100:.{decimals}f}%"


def dash(value: object) -> str:
    """Anything falsy-because-absent becomes an em dash.

    ``0`` and ``False`` are real answers and survive; only ``None`` and the
    empty string are treated as absence.
    """
    if value is None or value == "":
        return DASH
    return str(value)


def month_name(value: date | datetime | None) -> str | None:
    """``date(2026, 1, 8)`` -> ``"January 2026"``."""
    if value is None:
        return None
    return f"{value:%B %Y}"


def day_month(value: date | datetime | None) -> str | None:
    """``date(2026, 1, 8)`` -> ``"08 Jan"`` — the ledger's date column."""
    if value is None:
        return None
    return f"{value:%d %b}"


def plural(count: int, one: str, many: str | None = None) -> str:
    """``plural(1, "contract")`` -> ``"1 contract"``; ``2`` -> ``"2 contracts"``."""
    return f"{count} {one if count == 1 else (many or one + 's')}"
