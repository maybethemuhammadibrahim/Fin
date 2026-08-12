"""[B] pandas CSV parsing against a human-confirmed column mapping. Phase 4.

`sniff_columns()` returns the same `ColumnProposal` shape ADR-010 describes as
"LLM-proposed" — but Phase 4 runs before `core/ai/llm_client.py` exists at all
(Phase 5 stands up the self-hosted endpoint, ADR-012; until then `COLAB_TUNNEL_URL`
is unset by design, known_issue #9). So this proposes a mapping with a deterministic
header-name heuristic (`thefuzz` against a small synonym vocabulary) instead of a
model call. The human-confirmation step in `app/components/column_mapper.py` is
identical either way — it doesn't know or care where the proposal came from — so
Phase 5 can swap this function's body for a real LLM call with zero changes to the
UI or to `ColumnProposal` itself.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

import pandas as pd
from thefuzz import fuzz

from core.ai.schemas import ColumnProposal, TransactionRow

#: The three fields every downstream consumer (reconciliation, the agent's
#: search tools) needs out of an actuals CSV, regardless of the source bank's
#: own column names.
REQUIRED_FIELDS = ("date", "amount", "description")

_FIELD_SYNONYMS: dict[str, list[str]] = {
    "date": ["date", "txn date", "transaction date", "posted date", "trans date", "value date", "posting date"],
    "amount": ["amount", "amt", "value", "transaction amount", "net amount", "debit", "credit"],
    "description": ["description", "desc", "memo", "narrative", "details", "payee", "reference", "particulars"],
}

_MATCH_THRESHOLD = 55  # thefuzz score below which a field is left unmapped


def _read_sample(file_path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    df = pd.read_csv(file_path, nrows=5, dtype=str, keep_default_na=False)
    columns = [str(c) for c in df.columns]
    return columns, df.to_dict(orient="records")


def header_signature(columns: list[str]) -> str:
    """Stable id for a header layout, independent of column order noise from
    re-exports — sorted, not positional, so two banks that reorder the same
    fields still share a cached mapping (ADR-010)."""
    normalised = "|".join(sorted(c.strip().lower() for c in columns))
    return hashlib.sha256(normalised.encode()).hexdigest()


def sniff_columns(file_path: str | Path) -> ColumnProposal:
    """Best-effort {field: column} guess from header names alone. Never raises;
    a field that matches nothing is simply absent from `mapping`, and
    column_mapper.py's dropdowns default to unmapped rather than guessing wrong
    silently."""
    columns, sample_rows = _read_sample(file_path)

    mapping: dict[str, str] = {}
    for field, synonyms in _FIELD_SYNONYMS.items():
        best_col, best_score = None, 0
        for col in columns:
            score = max(fuzz.token_sort_ratio(col.strip().lower(), syn) for syn in synonyms)
            if score > best_score:
                best_col, best_score = col, score
        if best_score >= _MATCH_THRESHOLD:
            mapping[field] = best_col

    return ColumnProposal(mapping=mapping, header_signature=header_signature(columns), sample_rows=sample_rows)


def _clean_amount(raw: object) -> float | None:
    """"$6,000.00" / "6000" / "(1,500)" -> 6000.0 / -1500.0. None on garbage."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = re.sub(r"[^\d.\-]", "", text)
    if not text or text in ("-", "."):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return -abs(value) if negative else value


def _parse_dates(raw: pd.Series) -> pd.Series:
    """Dayfirst detection: try month-first (US bank export default), and only
    fall back to dayfirst if that leaves too many rows unparsed — e.g.
    "31/01/2025" is unambiguous and forces dayfirst on its own."""
    parsed = pd.to_datetime(raw, errors="coerce", dayfirst=False)
    if parsed.isna().mean() > 0.2:
        parsed = pd.to_datetime(raw, errors="coerce", dayfirst=True)
    return parsed


def parse_transactions(file_path: str | Path, mapping: dict[str, str]) -> list[TransactionRow]:
    """Apply a confirmed {field: column} mapping and return clean rows. A row
    whose date or amount can't be read is dropped rather than guessed — the
    caller sees a row count that may be smaller than the CSV's, never a
    fabricated one."""
    date_col, amount_col = mapping.get("date"), mapping.get("amount")
    if not date_col or not amount_col:
        return []

    df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
    if date_col not in df.columns or amount_col not in df.columns:
        return []

    dates = _parse_dates(df[date_col])
    desc_col = mapping.get("description")

    rows: list[TransactionRow] = []
    for i in range(len(df)):
        d = dates.iloc[i]
        amount = _clean_amount(df[amount_col].iloc[i])
        if pd.isna(d) or amount is None:
            continue
        description = str(df[desc_col].iloc[i]).strip() if desc_col and desc_col in df.columns else None
        rows.append(
            TransactionRow(
                transaction_date=date(d.year, d.month, d.day),
                amount=amount,
                description=description or None,
                source_type=None,
            )
        )
    return rows
