#!/usr/bin/env python3
"""Phase 13.11.7 — Confusable-character defense lint.

Refuses lexicon aliases that mix confusable characters from different scripts,
which could lead to unintended auto-merging of distinct entities.

Confusable pairs (per Unicode):
  * Cyrillic 'а' (U+0430) vs Latin 'a' (U+0061)
  * Greek 'Α' (U+0391) vs Latin 'A' (U+0041)
  * Cyrillic 'е' (U+0435) vs Latin 'e' (U+0065)
  * Cyrillic 'о' (U+043E) vs Latin 'o' (U+006F)
  * Other similar-looking characters across scripts

Per LEAGUE_CATALOG.md §2.2 and §13.11.7, aliases must not mix confusable
characters that could accidentally auto-merge distinct entities.

Exit codes:
    0   No confusable character mixing detected
    1   Confusable character mixing detected in aliases
    2   Schema validation or parse error
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


# Confusable character pairs: (script1_char, script2_char, description)
CONFUSABLE_PAIRS = [
    ('а', 'a', "Cyrillic 'а' (U+0430) vs Latin 'a' (U+0061)"),
    ('А', 'A', "Cyrillic 'А' (U+0410) vs Latin 'A' (U+0041)"),
    ('е', 'e', "Cyrillic 'е' (U+0435) vs Latin 'e' (U+0065)"),
    ('Е', 'E', "Cyrillic 'Е' (U+0415) vs Latin 'E' (U+0045)"),
    ('о', 'o', "Cyrillic 'о' (U+043E) vs Latin 'o' (U+006F)"),
    ('О', 'O', "Cyrillic 'О' (U+041E) vs Latin 'O' (U+004F)"),
    ('р', 'p', "Cyrillic 'р' (U+0440) vs Latin 'p' (U+0070)"),
    ('Р', 'P', "Cyrillic 'Р' (U+0420) vs Latin 'P' (U+0050)"),
    ('с', 'c', "Cyrillic 'с' (U+0441) vs Latin 'c' (U+0063)"),
    ('С', 'C', "Cyrillic 'С' (U+0421) vs Latin 'C' (U+0043)"),
    ('у', 'u', "Cyrillic 'у' (U+0443) vs Latin 'u' (U+0075)"),
    ('У', 'U', "Cyrillic 'У' (U+0423) vs Latin 'U' (U+0055)"),
    ('х', 'x', "Cyrillic 'х' (U+0445) vs Latin 'x' (U+0078)"),
    ('Х', 'X', "Cyrillic 'Х' (U+0425) vs Latin 'X' (U+0058)"),
    ('Α', 'A', "Greek 'Α' (U+0391) vs Latin 'A' (U+0041)"),
    ('Β', 'B', "Greek 'Β' (U+0392) vs Latin 'B' (U+0042)"),
    ('Ε', 'E', "Greek 'Ε' (U+0395) vs Latin 'E' (U+0045)"),
    ('Ζ', 'Z', "Greek 'Ζ' (U+0396) vs Latin 'Z' (U+0396)"),
    ('Η', 'H', "Greek 'Η' (U+0397) vs Latin 'H' (U+0048)"),
    ('Ι', 'I', "Greek 'Ι' (U+0399) vs Latin 'I' (U+0049)"),
    ('Κ', 'K', "Greek 'Κ' (U+039A) vs Latin 'K' (U+004B)"),
    ('Μ', 'M', "Greek 'Μ' (U+039C) vs Latin 'M' (U+004D)"),
    ('Ν', 'N', "Greek 'Ν' (U+039D) vs Latin 'N' (U+004E)"),
    ('Ο', 'O', "Greek 'Ο' (U+039F) vs Latin 'O' (U+004F)"),
    ('Ρ', 'P', "Greek 'Ρ' (U+03A1) vs Latin 'P' (U+0050)"),
    ('Τ', 'T', "Greek 'Τ' (U+03A4) vs Latin 'T' (U+0054)"),
    ('Υ', 'Y', "Greek 'Υ' (U+03A5) vs Latin 'Y' (U+0059)"),
    ('Χ', 'X', "Greek 'Χ' (U+03A7) vs Latin 'X' (U+0058)"),
]


def load_lexicon_file(path: Path) -> dict[str, Any] | None:
    """Load a lexicon YAML file and return its data, or None on error."""
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def has_confusable_mixing(text: str) -> tuple[bool, str]:
    """Check if text mixes confusable characters from different scripts.
    
    Returns: (has_mixing, description)
        has_mixing: True if the text contains confusable character mixing
        description: Explanation of the mixing if detected
    """
    for char1, char2, pair_desc in CONFUSABLE_PAIRS:
        # If the text contains both characters from the same confusable pair
        if char1 in text and char2 in text:
            return True, f"Mixes {pair_desc}"
    
    return False, ""


def check_no_confusable_aliases(lex_path: Path, entity_kind: str) -> tuple[bool, list[str]]:
    """Check that lexicon aliases don't mix confusable characters.
    
    Args:
        lex_path: Path to lexicon YAML file
        entity_kind: Human-readable kind (e.g., "competition", "team")
    
    Returns: (is_valid, errors)
        is_valid: True if no confusable mixing is detected
        errors: List of error messages if invalid
    """
    data = load_lexicon_file(lex_path)
    if not data:
        return False, [f"Invalid YAML or structure in {lex_path}"]
    
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        return False, [f"'entries' must be a list in {lex_path}"]
    
    errors = []
    
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        
        canonical_id = entry.get("canonical_id", "unknown")
        
        # Check all names
        names = entry.get("names", [])
        if isinstance(names, list):
            for i, name in enumerate(names):
                if isinstance(name, str):
                    has_mixing, desc = has_confusable_mixing(name)
                    if has_mixing:
                        errors.append(
                            f"Confusable characters in {entity_kind} '{canonical_id}' "
                            f"name[{i}] '{name}': {desc}. "
                            f"Lint refuses mixing of confusable characters per §13.11.7."
                        )
        
        # Check all aliases
        aliases = entry.get("aliases", [])
        if isinstance(aliases, list):
            for i, alias in enumerate(aliases):
                if isinstance(alias, str):
                    has_mixing, desc = has_confusable_mixing(alias)
                    if has_mixing:
                        errors.append(
                            f"Confusable characters in {entity_kind} '{canonical_id}' "
                            f"alias[{i}] '{alias}': {desc}. "
                            f"Lint refuses mixing of confusable characters per §13.11.7."
                        )
    
    return len(errors) == 0, errors


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Refuse confusable-character mixing in lexicon aliases (Phase 13.11.7)"
    )
    parser.add_argument(
        "lexicon_files",
        nargs="*",
        help="Lexicon YAML files to check"
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
        # Default: check all lexicon files
        lexicon_dir = args.repo_root / "ai" / "nlp" / "lexicon"
        files_to_check = [
            (f, "entity")
            for f in sorted(lexicon_dir.glob("*.tr.yaml"))
            if not f.name.startswith("_")
        ]
    
    all_errors = []
    for lex_file, entity_kind in files_to_check:
        if not lex_file.exists():
            continue
        
        is_valid, errors = check_no_confusable_aliases(lex_file, entity_kind)
        if not is_valid:
            all_errors.extend(errors)
    
    if all_errors:
        for err_msg in all_errors:
            print(f"ERROR: {err_msg}", file=sys.stderr)
        return 1
    
    print("OK: No confusable-character mixing detected in lexicon aliases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
