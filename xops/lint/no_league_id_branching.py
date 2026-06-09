"""
Phase 13.1 — AST-scan linter: refuse hardcoded league_id branching.

Per Phase 13.1 bullet: "**AST-scan lint** (`xops/lint/no_league_id_branching.py`)
refuses any `if league_id == "..."`, `match league_id` literal, or hardcoded
league-string comparison anywhere under `ai/`, `swarm/`, or `server/`."

This linter enforces the league-isolation doctrine: every cross-league behaviour
is data in the catalog or a calibration profile, never a code branch.

Usage:
    python3 xops/lint/no_league_id_branching.py <file_or_dir>
    
Returns:
    Exit code 0 if no violations found, 1 if violations exist
"""

import ast
import sys
from pathlib import Path
from typing import List, Tuple

# Patterns we're looking for: hardcoded league_id values
# Examples: "super_lig", "tr_super_lig", "prem", "la_liga"
# Very simple heuristic: lowercase strings with underscores that look like league IDs
SUSPICIOUS_LEAGUE_PATTERNS = {
    "super_lig",
    "tr_super_lig",
    "prem",
    "la_liga",
    "serie_a",
    "bundesliga",
    "ligue_1",
    "eredivisie",
    "championship",
    "primeira_liga",
    "serie_a_br",
    "liga_mx",
    "mls",
    "k_league",
    "j_league",
    "a_league",
}


class LeagueIdBranchingVisitor(ast.NodeVisitor):
    """AST visitor that detects league_id hardcoding patterns."""
    
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.violations: List[Tuple[int, str]] = []
    
    def visit_Compare(self, node: ast.Compare) -> None:
        """Check for `league_id == "..."` patterns."""
        # Check left side: is it `league_id`?
        if self._is_league_id_ref(node.left):
            # Check comparators
            for comp in node.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    hardcoded_val = comp.value
                    if self._looks_like_league_id(hardcoded_val):
                        self.violations.append((
                            node.lineno,
                            f"Hardcoded league_id comparison: league_id == '{hardcoded_val}'"
                        ))
        
        # Also check right side (in case of reversed comparison)
        for comp in node.comparators:
            if self._is_league_id_ref(comp):
                if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                    hardcoded_val = node.left.value
                    if self._looks_like_league_id(hardcoded_val):
                        self.violations.append((
                            node.lineno,
                            f"Hardcoded league_id comparison: '{hardcoded_val}' == league_id"
                        ))
        
        self.generic_visit(node)
    
    def visit_Match(self, node: ast.Match) -> None:
        """Check for `match league_id:` patterns."""
        # Python 3.10+ match statement
        if hasattr(ast, 'Match'):  # Only available in 3.10+
            if self._is_league_id_ref(node.subject):
                self.violations.append((
                    node.lineno,
                    "Hardcoded league_id in match statement"
                ))
        
        self.generic_visit(node)
    
    def visit_If(self, node: ast.If) -> None:
        """Check for league_id hardcoding in if statements."""
        # Check the test expression for league_id comparisons
        if self._contains_league_id_hardcoding(node.test):
            self.violations.append((
                node.lineno,
                "Possible hardcoded league_id in if condition"
            ))
        
        self.generic_visit(node)
    
    def _is_league_id_ref(self, node: ast.expr) -> bool:
        """Check if node refers to league_id."""
        if isinstance(node, ast.Name):
            return node.id == "league_id"
        elif isinstance(node, ast.Attribute):
            # Also catch self.league_id, obj.league_id, etc.
            return node.attr == "league_id"
        return False
    
    def _looks_like_league_id(self, s: str) -> bool:
        """Check if string looks like a league_id constant."""
        # Known pattern: lowercase with underscores
        if not s or len(s) < 3:
            return False
        
        # Check against known leagues
        if s in SUSPICIOUS_LEAGUE_PATTERNS:
            return True
        
        # Also match the pattern: words connected by underscores, no spaces
        if "_" in s and s.islower() and s.replace("_", "").isalnum():
            # But not too generic (avoid false positives like "a_b")
            if len(s) > 5 or s.count("_") >= 1:
                return True
        
        return False
    
    def _contains_league_id_hardcoding(self, node: ast.expr) -> bool:
        """Recursively check if an expression contains league_id hardcoding."""
        if isinstance(node, ast.Compare):
            if self._is_league_id_ref(node.left):
                for comp in node.comparators:
                    if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                        if self._looks_like_league_id(comp.value):
                            return True
        
        # Check nested boolean operations
        if isinstance(node, ast.BoolOp):
            for value in node.values:
                if self._contains_league_id_hardcoding(value):
                    return True
        
        return False


def scan_file(filepath: Path) -> List[Tuple[int, str]]:
    """Scan a single Python file for league_id branching violations."""
    if not filepath.suffix == ".py":
        return []
    
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            source = fh.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
        return []
    
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        print(f"Syntax error in {filepath}: {e}", file=sys.stderr)
        return []
    
    visitor = LeagueIdBranchingVisitor(str(filepath))
    visitor.visit(tree)
    return visitor.violations


def scan_directory(dirpath: Path, patterns: List[str] | None = None) -> int:
    """Scan a directory for violations. Returns 0 if clean, 1 if violations found."""
    if patterns is None:
        patterns = ["ai", "swarm", "server"]
    
    all_violations = []
    
    for pattern in patterns:
        root = dirpath / pattern
        if not root.exists():
            continue
        
        for pyfile in root.rglob("*.py"):
            violations = scan_file(pyfile)
            if violations:
                for lineno, msg in violations:
                    all_violations.append((str(pyfile), lineno, msg))
    
    if all_violations:
        for filepath, lineno, msg in all_violations:
            print(f"{filepath}:{lineno}: {msg}")
        return 1
    
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        if target.is_dir():
            exit_code = scan_directory(target)
        else:
            violations = scan_file(target)
            if violations:
                for lineno, msg in violations:
                    print(f"{target}:{lineno}: {msg}")
                exit_code = 1
            else:
                exit_code = 0
    else:
        # Scan from current directory
        exit_code = scan_directory(Path.cwd())
    
    sys.exit(exit_code)
