#!/usr/bin/env python3
"""[B] Print a compact paste-in summary of the memory files. Phase 0.

    python scripts/memory_digest.py

Reads docs/state.json. Use this when you want an assistant oriented fast;
use the full Phase Prompt from docs/implementation_plan.md when starting
real work.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = PROJECT_ROOT / "docs" / "state.json"

LABEL_WIDTH = 9


def _line(label: str, text: str) -> str:
    return f"{label + ':':<{LABEL_WIDTH}}{text}"


def _continuation(text: str) -> str:
    return f"{'':<{LABEL_WIDTH}}{text}"


def build_digest(state: dict) -> str:
    phases = state.get("phases", [])
    by_number = {p["n"]: p for p in phases}
    current_n = state.get("current_phase", 0)
    current = by_number.get(current_n, {})

    features = state.get("implemented_features", [])
    file_count = len({f for feat in features for f in feat.get("files", [])})

    out = [
        f"{state.get('project', 'PROJECT').upper()} — "
        f"phase {current_n} {current.get('status', 'unknown')} | "
        f"provider={state.get('llm_provider', '?')} | "
        f"{len(features)} features across {file_count} files"
    ]

    done = [p for p in phases if p.get("status") == "done"]
    out.append(_line("DONE", " · ".join(f"{p['n']} {p['name']}" for p in done) or "nothing yet"))

    work = current.get("work", {})
    suffix = f"  (A: {work.get('A', '?')}, B: {work.get('B', '?')})" if work else ""
    out.append(_line("CURRENT", f"{current_n} {current.get('name', '?')}{suffix}"))

    nxt = by_number.get(current_n + 1)
    out.append(_line("NEXT", f"{nxt['n']} {nxt['name']}" if nxt else "— final phase"))

    issues = state.get("known_issues", [])
    if issues:
        out.append(_line("OPEN", f"#{issues[0]['id']} {issues[0]['text']}"))
        out.extend(_continuation(f"#{i['id']} {i['text']}") for i in issues[1:])
    else:
        out.append(_line("OPEN", "none recorded"))

    adrs = state.get("adrs", [])
    if adrs:
        latest = adrs[-1]
        out.append(_line("ADRs", f"{len(adrs)} recorded, latest {latest['id']} ({latest['title']})"))
    else:
        out.append(_line("ADRs", "none recorded"))

    return "\n".join(out)


def main() -> int:
    if not STATE_PATH.is_file():
        print(f"No state file at {STATE_PATH}", file=sys.stderr)
        return 1
    try:
        state = json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError as exc:
        print(f"{STATE_PATH} is not valid JSON: {exc}", file=sys.stderr)
        return 1
    print(build_digest(state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
