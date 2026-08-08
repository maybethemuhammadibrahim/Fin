#!/usr/bin/env python3
"""[A] Create every table against DATABASE_URL. Phase 1.

    python scripts/init_db.py            # create anything missing (idempotent)
    python scripts/init_db.py --drop     # drop everything first, then recreate
    python scripts/init_db.py --check    # connect and report, change nothing

No Alembic until Phase 9, so a schema change means `--drop`. It asks before
destroying anything that has rows in it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, inspect, select  # noqa: E402

from core.db import database  # noqa: E402
from core.db.models import ALL_MODELS  # noqa: E402


def _row_counts() -> dict[str, int]:
    """Row count per existing table. Missing tables are simply absent."""
    counts: dict[str, int] = {}
    existing = set(inspect(database.get_engine()).get_table_names())
    with database.session_scope() as session:
        for model in ALL_MODELS:
            name = model.__tablename__
            if name in existing:
                counts[name] = session.scalar(select(func.count()).select_from(model)) or 0
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Create FinSight's tables.")
    parser.add_argument("--drop", action="store_true", help="drop all tables first (destructive)")
    parser.add_argument("--check", action="store_true", help="report only; change nothing")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt for --drop")
    args = parser.parse_args()

    ok, message = database.check_connection()
    print(f"Database: {database.describe_backend()}")
    if not ok:
        print(f"  ✗ {message}", file=sys.stderr)
        print(
            "\nSet DATABASE_URL in .env to your Supabase URI, or leave it blank\n"
            "to use the offline SQLite fallback.",
            file=sys.stderr,
        )
        return 1
    print(f"  ✓ {message}")

    if args.check:
        counts = _row_counts()
        if not counts:
            print("\nNo tables yet. Run without --check to create them.")
            return 0
        print(f"\n{len(counts)} tables:")
        for name, count in counts.items():
            print(f"  {name:<22} {count:>8} rows")
        return 0

    if args.drop:
        existing = _row_counts()
        populated = {n: c for n, c in existing.items() if c}
        if populated and not args.yes:
            print("\n⚠  --drop will DELETE these rows permanently:")
            for name, count in populated.items():
                print(f"     {name:<22} {count:>8} rows")
            if input("\nType 'drop' to confirm: ").strip().lower() != "drop":
                print("Aborted. Nothing was changed.")
                return 1
        database.drop_all()
        print("\nDropped all tables.")

    before = set(inspect(database.get_engine()).get_table_names())
    database.init_db()
    after = set(inspect(database.get_engine()).get_table_names())

    created = sorted(after - before)
    print(f"\n{len(after)} tables present ({len(created)} created):")
    for model in ALL_MODELS:
        name = model.__tablename__
        mark = "+" if name in created else " "
        print(f"  {mark} {name}")

    missing = [m.__tablename__ for m in ALL_MODELS if m.__tablename__ not in after]
    if missing:
        print(f"\n✗ Expected tables missing: {', '.join(missing)}", file=sys.stderr)
        return 1

    print("\n✓ Schema is up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
