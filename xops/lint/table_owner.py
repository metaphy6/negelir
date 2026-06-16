"""Phase 18.6 §18.6 ledger #24 — CI lint: every table declares an owner.

This linter walks all migration files and asserts every CREATE TABLE
has a matching COMMENT ON TABLE ... IS 'owner=<component>'.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def extract_tables_from_migrations(migrations_dir: Path) -> dict[str, str | None]:
    """Extract table names and their owner comments from migration files.

    Returns:
        dict mapping table_name -> owner_component (or None if no owner comment).
    """
    tables: dict[str, str | None] = {}

    # Sort migration files numerically
    migration_files = sorted(
        migrations_dir.glob("*.sql"),
        key=lambda f: int(f.stem.split("_")[0]) if f.stem[0].isdigit() else 0,
    )

    for migration_file in migration_files:
        with open(migration_file, "r", encoding="utf-8") as fh:
            content = fh.read()

        # Find CREATE TABLE statements
        table_pattern = re.compile(
            r"CREATE\s+(?:TABLE|MATERIALIZED\s+VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            re.IGNORECASE,
        )

        for match in table_pattern.finditer(content):
            table_name = match.group(1)

            # Look for COMMENT ON TABLE ... IS 'owner=<component>'
            comment_pattern = rf"COMMENT\s+ON\s+TABLE\s+{table_name}\s+IS\s+'owner=(\w+)'"
            comment_match = re.search(comment_pattern, content, re.IGNORECASE)

            owner = comment_match.group(1) if comment_match else None
            tables[table_name] = owner

    return tables


def lint_table_owners(migrations_dir: Path) -> int:
    """Lint table ownership declarations.

    Returns:
        0 if all tables have owners, 1 otherwise.
    """
    tables = extract_tables_from_migrations(migrations_dir)

    if not tables:
        print("⚠ No tables found in migrations")
        return 0

    missing_owner = [t for t, owner in tables.items() if owner is None]

    if missing_owner:
        print(f"❌ {len(missing_owner)} table(s) missing owner comment:")
        for table in sorted(missing_owner):
            print(f"   - {table}")
        print("")
        print("Fix: Add this line after CREATE TABLE:")
        print("   COMMENT ON TABLE <table_name> IS 'owner=<component>';")
        print("")
        print("Valid components: datasource, swarm, server, patcher, common")
        return 1

    print(f"✅ All {len(tables)} table(s) declare an owner")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Lint: every table declares an owner component"
    )
    parser.add_argument(
        "migrations_dir",
        type=Path,
        default=Path("migrations"),
        nargs="?",
        help="Path to migrations directory (default: migrations/)",
    )

    args = parser.parse_args()
    sys.exit(lint_table_owners(args.migrations_dir))
