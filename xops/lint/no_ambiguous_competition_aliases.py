#!/usr/bin/env python3
"""Phase 13.11 — Competition/Team lexicon alias canonicalisation lint.

Refuses two competition or team records with the same alias resolving to
different canonical_id. This ensures that aliases are unambiguous shortcuts
that uniquely identify a single competition/team.

Per LEAGUE_CATALOG.md §2.2 and §13.11.2, ambiguous aliases are not allowed.

Exit codes:
    0   All aliases are canonical (no ambiguity)
    1   Ambiguous alias found (same alias in multiple canonical_ids)
    2   Schema validation or parse error
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


def load_lexicon_file(path: Path) -> dict[str, Any] | None:
    """Load a lexicon YAML file and return its data, or None on error."""
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def check_no_ambiguous_aliases(lex_path: Path, entity_kind: str) -> tuple[bool, list[str]]:
    """Check that no alias maps to multiple canonical_ids.
    
    Args:
        lex_path: Path to lexicon YAML file
        entity_kind: Human-readable kind (e.g. "competition", "team")
    
    Returns: (is_valid, errors)
        is_valid: True if all aliases are unambiguous
        errors: List of error messages if invalid
    """
    data = load_lexicon_file(lex_path)
    if not data:
        return False, [f"Invalid YAML or structure in {lex_path}"]
    
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        return False, [f"'entries' must be a list in {lex_path}"]
    
    # Map: alias → set of canonical_ids it appears in
    alias_to_canonical_ids: dict[str, set[str]] = {}
    
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        
        canonical_id = entry.get("canonical_id")
        if not canonical_id:
            continue
        
        # Check all names
        names = entry.get("names", [])
        if isinstance(names, list):
            for name in names:
                if isinstance(name, str):
                    normalized = name.lower().strip()
                    if normalized:
                        alias_to_canonical_ids.setdefault(normalized, set()).add(canonical_id)
        
        # Check all aliases
        aliases = entry.get("aliases", [])
        if isinstance(aliases, list):
            for alias in aliases:
                if isinstance(alias, str):
                    normalized = alias.lower().strip()
                    if normalized:
                        alias_to_canonical_ids.setdefault(normalized, set()).add(canonical_id)
    
    # Find ambiguous aliases
    errors = []
    for alias, canonical_ids in sorted(alias_to_canonical_ids.items()):
        if len(canonical_ids) > 1:
            canonical_ids_str = ", ".join(sorted(canonical_ids))
            errors.append(
                f"{entity_kind} alias '{alias}' is ambiguous: maps to {len(canonical_ids)} "
                f"canonical_ids ({canonical_ids_str}) in {lex_path}. "
                f"Lint refuses ambiguous shortcuts per §13.11.2."
            )
    
    return len(errors) == 0, errors


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Refuse ambiguous aliases in competition/team lexicons (Phase 13.11.2)"
    )
    parser.add_argument(
        "lexicon_files",
        nargs="*",
        help="Lexicon YAML files to check (default: competitions.tr.yaml and teams.tr.yaml)"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root path"
    )
    
    args = parser.parse_args(argv)
    
    if args.lexicon_files:
        files_to_check = [(Path(f), "entity") for f in args.lexicon_files]
    else:
        # Default: check competitions and teams lexicons
        lexicon_dir = args.repo_root / "ai" / "nlp" / "lexicon"
        files_to_check = [
            (lexicon_dir / "competitions.tr.yaml", "competition"),
            (lexicon_dir / "teams.tr.yaml", "team"),
        ]
    
    all_errors = []
    for lex_file, entity_kind in files_to_check:
        if not lex_file.exists():
            # Skip if file doesn't exist yet
            continue
        
        is_valid, errors = check_no_ambiguous_aliases(lex_file, entity_kind)
        if not is_valid:
            all_errors.extend(errors)
    
    if all_errors:
        for err_msg in all_errors:
            print(f"ERROR: {err_msg}", file=sys.stderr)
        return 1
    
    print(f"OK: No ambiguous aliases found in competition/team lexicons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
