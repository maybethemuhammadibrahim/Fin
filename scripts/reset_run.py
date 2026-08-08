#!/usr/bin/env python3
"""[A] Delete one run and everything scoped to it, leaving other runs intact.

    python scripts/reset_run.py --list        # show every run with its row counts
    python scripts/reset_run.py --run-id 3    # delete run 3 and its rows
    python scripts/reset_run.py --run-id 3 --yes

The plan lists this under Phase 1's User A tasks; the file's own docstring and
CLAUDE.md both said Phase 2. Built in Phase 1 because the cascade behaviour it
depends on is exactly what Phase 1 needs to prove.

Deletion relies on `ondelete="CASCADE"` declared in models.py, which SQLite only
honours because database.py turns on `PRAGMA foreign_keys`. Deleting the Run row
is therefore sufficient — but this script verifies the cascade actually emptied
everything rather than trusting it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from core.db import database  # noqa: E402
from core.db.models import (  # noqa: E402
    ActualTransaction,
    Anomaly,
    Client,
    Document,
    ExpectedTimeline,
    Run,
)

#: Run-scoped tables, i.e. everything carrying a run_id directly.
RUN_SCOPED = (Document, Client, ExpectedTimeline, ActualTransaction, Anomaly)


def _counts_for(session, run_id: int) -> dict[str, int]:
    return {
        model.__tablename__: session.scalar(
            select(func.count()).select_from(model).where(model.run_id == run_id)
        )
        or 0
        for model in RUN_SCOPED
    }


def _list_runs() -> int:
    with database.session_scope() as session:
        runs = session.scalars(select(Run).order_by(Run.id)).all()
        if not runs:
            print("No runs. Create one with queries.create_run(), or seed in Phase 2.")
            return 0
        print(f"{len(runs)} run(s):\n")
        for run in runs:
            counts = _counts_for(session, run.id)
            total = sum(counts.values())
            created = run.created_at.strftime("%Y-%m-%d %H:%M") if run.created_at else "?"
            print(f"  [{run.id}] {run.label}   {created}   model={run.model_name or '—'}")
            print(f"       {total} rows  ({', '.join(f'{k}={v}' for k, v in counts.items())})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete one run and its rows.")
    parser.add_argument("--run-id", type=int, help="the run to delete")
    parser.add_argument("--list", action="store_true", help="list runs and exit")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    ok, message = database.check_connection()
    if not ok:
        print(f"✗ {message}", file=sys.stderr)
        return 1

    if args.list or args.run_id is None:
        if args.run_id is None and not args.list:
            parser.print_help()
            print("\nNothing deleted — pass --run-id or --list.")
        return _list_runs()

    with database.session_scope() as session:
        run = session.get(Run, args.run_id)
        if run is None:
            print(f"✗ No run with id {args.run_id}.", file=sys.stderr)
            return 1

        counts = _counts_for(session, run.id)
        total = sum(counts.values())
        print(f"Run [{run.id}] {run.label!r} — {total} rows scoped to it:")
        for name, count in counts.items():
            print(f"  {name:<22} {count:>8}")

        if not args.yes:
            if input(f"\nType 'delete' to remove run {run.id}: ").strip().lower() != "delete":
                print("Aborted. Nothing was changed.")
                return 1

        session.delete(run)
        session.flush()

        leftover = {n: c for n, c in _counts_for(session, args.run_id).items() if c}
        if leftover:
            session.rollback()
            print(
                f"\n✗ Cascade left orphans: {leftover}. Rolled back — nothing deleted.\n"
                "  On SQLite this means PRAGMA foreign_keys was not applied.",
                file=sys.stderr,
            )
            return 1

    print(f"\n✓ Deleted run {args.run_id} and {total} rows. Other runs untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
