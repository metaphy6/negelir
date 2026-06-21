#!/usr/bin/env python3
"""Phase 22.2 — libcst-based import rewriter (scope boundary enforcement).

Implements:
  1. FileFilterValidator — scope boundary gate (*.py only, from bullet 2)
  2. Phase22ImportRewriter — AST-based transformer for all 7 rewrite patterns:
     - Pattern 1: from ai.<pkg>.<mod> import X → from <pkg>.<mod> import X
     - Pattern 2: import ai.<pkg> → import <pkg> as <pkg>
     - Pattern 3: Quoted type annotations "ai.<pkg>.<Class>" → "<pkg>.<Class>"
     - Pattern 4: TYPE_CHECKING block imports
     - Pattern 5: __all__ re-exports with ai.* names
     - Pattern 6: Pydantic model_rebuild() / update_forward_refs() calls
     - Pattern 7: Provenance headers # negelir-generated-from: ai/<path>@sha256

All transformations use stdlib-only (ast + re) for cross-platform compatibility.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import List, Tuple, Optional, Union, Sequence, Dict, Any


class FileScopeError(Exception):
    """Raised when a file is outside the codemod scope (not *.py)."""
    pass


class FileFilterValidator:
    """Validates that codemod input files are within scope (*.py only).
    
    Implements the scope boundary gate for Phase 22.2 bullet 2:
    - Accepts: *.py files
    - Rejects: .lock, .sbom.spdx.json, .pyc, .json (non-fixture), .yaml, .go, etc.
    """
    
    # Forbidden extensions and patterns
    FORBIDDEN_EXTENSIONS = {
        '.lock',           # requirements.lock, poetry.lock, etc.
        '.sbom.spdx.json', # SBOM attestation
        '.pyc',            # Compiled bytecode
        '.pyo',            # Optimized bytecode
        '.pyd',            # Windows extension
        '.so',             # Unix shared object
        '.go',             # Go source files
        # Note: .yaml and .yml are handled separately to allow test fixtures
    }
    
    # Forbidden filename patterns (exact or substring)
    FORBIDDEN_PATTERNS = {
        'requirements.lock',
        'poetry.lock',
        'setup.cfg',
        'setup.py',
        'pyproject.toml',
        '.gitignore',
        '.env',
        # Note: conftest.py is a valid Python file that may need import rewrites;
        # it is handled as part of the general test-file reconciliation in Phase 22.3b
    }
    
    # JSON data files that are not test fixtures are forbidden
    FORBIDDEN_JSON_DATA = {
        'betting_markets.json',
        'league_catalog.json',
        'competition_definitions.json',
        'enrichment_baseline.json',
        'enrichment_fallback_values.json',
        'super_lig_real.json',
        'tr_super_lig_real.json',
        'de_bundesliga_real.json',
        'en_premier_league_real.json',
        'es_la_liga_real.json',
        'international_tournament_profiles.json',
    }
    
    @staticmethod
    def is_test_fixture_path(path: Path) -> bool:
        """Check if a file is a test fixture (allowed JSON/YAML in tests/)."""
        path_str = str(path)
        # Test fixtures are in tests/ or */tests/ directories
        return '/tests/' in path_str or path_str.startswith('tests/')
    
    @staticmethod
    def validate_file(file_path: Path) -> None:
        """Validate that a file is within scope (*.py only).
        
        Args:
            file_path: Path to the file to validate.
            
        Raises:
            FileScopeError: If the file is outside the scope.
        """
        # Check extension
        if file_path.suffix in FileFilterValidator.FORBIDDEN_EXTENSIONS:
            raise FileScopeError(
                f"Codemod cannot touch {file_path.suffix} files: {file_path}. "
                f"File scope boundary (Phase 22.2 bullet 2) restricts codemod to *.py only."
            )
        
        # Check for multi-part extensions like .sbom.spdx.json
        if file_path.name.endswith('.sbom.spdx.json'):
            raise FileScopeError(
                f"Codemod cannot touch SBOM files: {file_path}. "
                f"File scope boundary (Phase 22.2 bullet 2) restricts codemod to *.py only. "
                f"SBOM files are handled by §22.4 (lock/SBOM regen)."
            )
        
        # Check forbidden patterns (exact filename match)
        if file_path.name in FileFilterValidator.FORBIDDEN_PATTERNS:
            raise FileScopeError(
                f"Codemod cannot touch {file_path.name}: {file_path}. "
                f"File scope boundary (Phase 22.2 bullet 2) restricts codemod to *.py only."
            )
        
        # Check for *.json data files (except test fixtures)
        if file_path.suffix == '.json':
            # Test fixtures in tests/ directories are allowed
            if FileFilterValidator.is_test_fixture_path(file_path):
                return  # Allow test fixtures
            
            # Check if it's a known data file
            if file_path.name in FileFilterValidator.FORBIDDEN_JSON_DATA:
                raise FileScopeError(
                    f"Codemod cannot touch data JSON files: {file_path}. "
                    f"File scope boundary (Phase 22.2 bullet 2) restricts codemod to *.py only. "
                    f"Data-file moves are handled by §22.3a (data-contract moves)."
                )
            # Any *.json outside tests/ is suspect (could be config or data)
            raise FileScopeError(
                f"Codemod cannot touch JSON files outside test directories: {file_path}. "
                f"File scope boundary (Phase 22.2 bullet 2) restricts codemod to *.py only."
            )
        
        # Check for *.yaml files (except test fixtures)
        if file_path.suffix in {'.yaml', '.yml'}:
            # Test fixtures in tests/ directories are allowed
            if FileFilterValidator.is_test_fixture_path(file_path):
                return  # Allow test fixtures
            
            raise FileScopeError(
                f"Codemod cannot touch YAML config files: {file_path}. "
                f"File scope boundary (Phase 22.2 bullet 2) restricts codemod to *.py only."
            )
        
        # Only *.py files are allowed (and some known allowlisted extensions could be added here)
        if file_path.suffix != '.py':
            raise FileScopeError(
                f"Codemod can only process *.py files, not {file_path.suffix}: {file_path}. "
                f"File scope boundary (Phase 22.2 bullet 2) restricts codemod to *.py only."
            )
    
    @classmethod
    def validate_file_list(cls, files: List[Path]) -> None:
        """Validate a list of files, raising on first violation.
        
        Args:
            files: List of file paths to validate.
            
        Raises:
            FileScopeError: If any file is outside the scope.
        """
        for file_path in files:
            cls.validate_file(Path(file_path))
    
    @classmethod
    def filter_scope_violations(cls, files: List[Path]) -> Tuple[List[Path], List[Tuple[Path, str]]]:
        """Separate files into valid and invalid (violation) lists.
        
        Args:
            files: List of file paths to filter.
            
        Returns:
            Tuple of (valid_files, violations) where violations is a list of
            (file_path, error_message) tuples.
        """
        valid = []
        violations = []
        
        for file_path in files:
            try:
                cls.validate_file(Path(file_path))
                valid.append(file_path)
            except FileScopeError as e:
                violations.append((file_path, str(e)))
        
        return valid, violations


# ─────────────────────────────────────────────────────────────────────────
# Phase 22 Import Rewriter — libcst CSTTransformer for all 7 patterns
# ─────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────
# Phase 22 Import Rewriter — Regex-based transformer for all 7 patterns
# ─────────────────────────────────────────────────────────────────────────


class Phase22ImportRewriter:
    """
    Rewrites imports to move code from ai.<pkg>.* to <pkg>.*
    
    Handles all 7 rewrite patterns using regex and AST parsing:
      1. from ai.<pkg>.<mod> import X → from <pkg>.<mod> import X
      2. import ai.<pkg> → import <pkg> as <pkg> (backward-compat alias)
      3. Quoted type annotations "ai.<pkg>.<Class>" → "<pkg>.<Class>"
      4. TYPE_CHECKING block imports (same as 1/2)
      5. __all__ re-exports with ai.* fully-qualified names
      6. Pydantic model_rebuild() / update_forward_refs() string arguments
      7. Provenance headers: # negelir-generated-from: ai/<path>@sha256
    
    Supports rewriting non-ai/ caller files when --include-non-ai-callers is used.
    Uses stdlib-only (ast + re) for cross-platform compatibility.
    """
    
    # Regex patterns for each rewrite pattern
    _PATTERN_1_FROM_IMPORT = re.compile(
        r'from\s+ai\.([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)\s+import\s+'
    )
    _PATTERN_2_IMPORT = re.compile(
        r'import\s+ai\.([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)'
    )
    # Enhanced Pattern 3: matches quoted strings with ai.* module paths
    # Handles: 'ai.*', "ai.*", r'ai.*', f'ai.*', rf'ai.*', fr'ai.*', rb'ai.*', br'ai.*', etc.
    # Prefix alternation: empty, or one of: r, f, fr, rf, rb, br (or combinations)
    _PATTERN_3_QUOTED = re.compile(
        r'(?:r|f|fr|rf|rb|br)?(["\'])ai\.([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)\1'
    )
    _PATTERN_7_PROVENANCE = re.compile(
        r'(#\s*negelir-generated-from:\s*)ai/(.+)'
    )
    
    def __init__(self, package: str = "", scan_head_lines: int = 5):
        """
        Args:
            package: Destination package name (e.g., "common", "datasource").
            scan_head_lines: Number of lines to scan for provenance headers (pattern 7).
        """
        self.package = package
        self.scan_head_lines = scan_head_lines
        self.changes_made = 0
    
    @staticmethod
    def load_inventory(inventory_path: Path) -> Dict[str, Any]:
        """Load the import report inventory from JSON.
        
        Args:
            inventory_path: Path to docs/tracking/phase22_import_report.json
            
        Returns:
            Dict mapping package names to their caller info.
        """
        if not inventory_path.exists():
            return {}
        
        with open(inventory_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("by_package", {})
    
    @staticmethod
    def get_non_ai_callers(package: str, inventory_path: Path) -> List[str]:
        """Get list of non-ai/ caller files for a given package.
        
        Args:
            package: Package name (e.g., "common")
            inventory_path: Path to docs/tracking/phase22_import_report.json
            
        Returns:
            List of relative file paths that import from the package.
        """
        inventory = Phase22ImportRewriter.load_inventory(inventory_path)
        if package not in inventory:
            return []
        
        return inventory[package].get("files", [])
    
    @staticmethod
    def rewrite_source(source: str, package: str = "", scan_head_lines: int = 5) -> Tuple[str, str]:
        """
        Rewrite source code for all 7 patterns.
        
        Args:
            source: Source code to rewrite.
            package: Destination package (used for filtering).
            scan_head_lines: Number of lines to scan for provenance headers.
            
        Returns:
            Tuple of (rewritten_source, status) where status is "rewritten" or "no-op".
        """
        rewriter = Phase22ImportRewriter(package=package, scan_head_lines=scan_head_lines)
        return rewriter.rewrite(source)
    
    def is_already_rewritten(self, source: str) -> bool:
        """Check if source has already been fully rewritten for this package.
        
        A file is considered already rewritten for this package if it contains no
        `from ai.<package>.`, `import ai.<package>`, or other ai.* references that
        would need to be rewritten (EXCLUDING non-annotation contexts like data strings).
        
        Args:
            source: Source code to check.
            
        Returns:
            True if the file has no ai.* imports relevant to the current package filter,
            False if it has ai.* imports that would be rewritten by this rewriter.
        """
        # If no package filter is set, check for ANY ai.* patterns
        if not self.package:
            has_from_ai = bool(self._PATTERN_1_FROM_IMPORT.search(source))
            has_import_ai = bool(self._PATTERN_2_IMPORT.search(source))
            # For quotes, only count if in annotation context
            has_quoted_ai = False
            for match in self._PATTERN_3_QUOTED.finditer(source):
                if not self._is_non_annotation_context(source, match.start()):
                    has_quoted_ai = True
                    break
            has_provenance_ai = bool(self._PATTERN_7_PROVENANCE.search(source))
            return not (has_from_ai or has_import_ai or has_quoted_ai or has_provenance_ai)
        
        # With a package filter, check specifically for imports/quotes from that package
        lines = source.split("\n")
        for i, line in enumerate(lines):
            # Check for "from ai.<package>.*" patterns that would be rewritten
            match_from = self._PATTERN_1_FROM_IMPORT.search(line)
            if match_from:
                pkg_path = match_from.group(1)
                if self._matches_package(pkg_path):
                    # Found a matching "from ai.<package>.*" import
                    return False
            
            # Check for "import ai.<package>*" patterns that would be rewritten
            match_import = self._PATTERN_2_IMPORT.search(line)
            if match_import:
                pkg_path = match_import.group(1)
                if self._matches_package(pkg_path):
                    # Found a matching "import ai.<package>*" import
                    return False
            
            # Check for quoted ai.* strings in ANNOTATION CONTEXT that would be rewritten
            for match in self._PATTERN_3_QUOTED.finditer(line):
                pkg_path = match.group(2)
                if self._matches_package(pkg_path):
                    # Check if this is in a rewritable context (not data literal)
                    if not self._is_non_annotation_context(line, match.start()):
                        # Found a matching quoted string in annotation context
                        return False
        
        # Check for provenance headers that would be rewritten
        lines = source.split("\n")
        for i in range(min(self.scan_head_lines, len(lines))):
            match = self._PATTERN_7_PROVENANCE.search(lines[i])
            if match:
                rest = match.group(2)
                if rest:
                    path_parts = rest.split("/")
                    if path_parts:
                        header_package = path_parts[0]
                        if self._matches_package(header_package):
                            return False
        
        # No matching rewritable ai.* patterns found; file is already rewritten for this package
        return True
    
    def rewrite(self, source: str) -> Tuple[str, str]:
        """
        Rewrite source code for all 7 patterns.
        
        Returns a tuple of (rewritten_source, status) where status is either:
        - "rewritten" if changes were made
        - "no-op" if the file was already rewritten (no ai.* imports found)
        
        Args:
            source: Source code to rewrite.
            
        Returns:
            Tuple of (rewritten_source, status_string).
        """
        # Check if already rewritten (idempotency)
        if self.is_already_rewritten(source):
            return source, "no-op"
        
        # Apply rewrites and return with "rewritten" status
        rewritten = self._rewrite_all(source)
        return rewritten, "rewritten"
    
    def _rewrite_all(self, source: str) -> str:
        """Apply all 7 rewrites in order."""
        # Pattern 7: Provenance headers (first, before parsing)
        source = self._rewrite_pattern_7(source)
        
        # Patterns 1-6: Parse and rewrite line-by-line for patterns that can't be regex-only
        lines = source.split("\n")
        new_lines = []
        
        for line in lines:
            # Pattern 1: from ai.<pkg>.<mod> import X
            line = self._rewrite_pattern_1(line)
            
            # Pattern 2: import ai.<pkg>
            line = self._rewrite_pattern_2(line)
            
            # Pattern 3: Quoted type annotations
            line = self._rewrite_pattern_3(line)
            
            # Patterns 5 & 6: __all__ and Pydantic calls (via regex)
            line = self._rewrite_pattern_5(line)
            line = self._rewrite_pattern_6(line)
            
            new_lines.append(line)
        
        return "\n".join(new_lines)
    
    def _matches_package(self, pkg_name: str) -> bool:
        """Check if package name matches the filter (if any)."""
        if not self.package:
            return True
        # Check if the first part of the dotted name matches the package
        first_part = pkg_name.split(".")[0]
        return first_part == self.package or pkg_name.startswith(self.package + ".")
    
    def _is_non_annotation_context(self, line: str, quote_start: int) -> bool:
        """
        Detect if a quoted string is in a non-annotation context (data literal).
        
        Non-annotation contexts include:
        - Dictionary keys/values: {"ai.common": ...} or 'ai.common': 'x',
        - String literals for logging/printing: print("ai.common")
        - SQL strings: query = "SELECT * FROM ai_..."
        - Comments/docstrings are already handled (regex doesn't match them)
        
        Returns True if this is a non-annotation context, False if it's code annotation.
        """
        # Extract the part of the line before the quote
        line_before = line[:quote_start]
        line_after = line[quote_start:]  # Part from the quote onward
        
        # Check for dictionary/set literal context FIRST: { ... "string" ...}
        # If there's an unmatched {, we're inside a literal (data context)
        brace_count = line_before.count("{") - line_before.count("}")
        if brace_count > 0:
            # We're inside a dictionary or set literal - preserve the string
            return True
        
        # Code contexts that SHOULD be rewritten: check these EARLY
        # If line contains __all__, allow rewrite (those are code)
        if "__all__" in line:
            return False  # DO rewrite __all__ entries
        
        # Check for dictionary key-value pattern in the full line: 'key': 'value'
        # BUT: exclude return type annotations like -> 'type':
        # Pattern: we're looking for 'key': without an arrow before the quote
        if ":" in line_after and "->" not in line_before:
            # Check if the pattern is: [stuff]'[quote_content]': [something]
            # Look for the closing quote of our string, then a colon
            quote_char = line_after[0]  # The first char of line_after is the opening quote
            # Find the closing quote of our string
            closing_quote_pos = line_after.find(quote_char, 1)
            if closing_quote_pos > 0:
                after_string = line_after[closing_quote_pos+1:]
                if after_string.lstrip().startswith(":") and "->" not in line_before:
                    # Pattern: 'ai.common.Config': ... - this is a dictionary key (not a return type)
                    return True  # Don't rewrite dictionary keys
        
        # Check for dictionary key-value pattern: 'key': 'value' with colon before quote
        if ":" in line_before:
            # Check if there's a quote before the colon, indicating dict key-value pattern
            colon_pos = line_before.rfind(":")
            before_colon = line_before[:colon_pos]
            # If there's a quote immediately before the colon (like 'key':), this is dict data
            if before_colon.rstrip().endswith("'") or before_colon.rstrip().endswith('"'):
                # This looks like a dictionary key-value pair
                return True  # Don't rewrite dict data
        
        # Check for type annotation assignment: x = Union[...], x = Optional[...], etc.
        type_keywords = ["Union", "Optional", "Tuple", "List", "Dict", "Set", "Callable", "Protocol"]
        if "=" in line_before:
            eq_pos = line_before.rfind("=")
            after_eq = line[eq_pos+1:quote_start]
            if any(kw in after_eq for kw in type_keywords):
                # This looks like a type annotation assignment
                return False  # DO rewrite
        
        # Check for explicit type annotation markers
        if any(marker in line_before for marker in ["->", "Annotated"]):
            return False  # DO rewrite annotations
        
        # Check for function parameter context: def foo(x: 'type')
        # or: def foo(x: Optional['type'])
        if "def " in line and ":" in line_before:
            # This is a function definition with type annotations
            # Check if there's an opening paren without a closing one before our quote
            last_paren_open = line_before.rfind("(")
            last_paren_close = line_before.rfind(")")
            if last_paren_open > last_paren_close:
                # We're inside function parameters
                return False  # DO rewrite (function annotations)
        
        # Check for list/bracket contexts - but only if NOT a type annotation
        bracket_count = line_before.count("[") - line_before.count("]")
        paren_count = line_before.count("(") - line_before.count(")")
        
        # If we're in brackets but it doesn't look like a type annotation, it's data
        if bracket_count > 0:
            # Check if this is a list literal ([...]) or type annotation (Union[...], etc.)
            # Simple heuristic: look back for type keywords or : markers
            before_bracket = line_before[:line_before.rfind("[")]
            if any(kw in before_bracket for kw in type_keywords):
                # Type annotation like Union[...] or Optional[...]
                return False  # DO rewrite
            # Otherwise it's a list literal - preserve
            return True
        
        if paren_count > 0:
            # Check if this is a function call or a type annotation
            # If the line has "def " or "->", it's likely type annotation
            if "def " in line or "->" in line:
                return False  # DO rewrite
            # Otherwise check if it's a logging/print function
            logging_patterns = [
                "logger.info(", "logger.warning(", "logger.error(", "logger.debug(",
                "print(", "warning(", "error(", "info(", "debug(", "log(",
            ]
            for pattern in logging_patterns:
                if pattern in line_before:
                    return True  # Don't rewrite logging strings
            # For other function calls, default to rewriting (might be type-related)
            return False
        
        # Check for assignment to string variable (non-annotation):
        # e.g., description = "..."  or message = "..."
        # But only if it doesn't look like a type annotation
        if "=" in line_before and ":" not in line_before:
            # Pure assignment, no type annotation - this is a data literal
            return True
        
        # Default: if we couldn't determine, assume it's safe to rewrite (annotation or code)
        return False

    
    def _rewrite_pattern_1(self, line: str) -> str:
        """Pattern 1: from ai.<pkg>.<mod> import X → from <pkg>.<mod> import X"""
        def replacer(match: re.Match) -> str:
            pkg_path = match.group(1)
            if self._matches_package(pkg_path):
                self.changes_made += 1
                return f"from {pkg_path} import "
            return match.group(0)
        
        return self._PATTERN_1_FROM_IMPORT.sub(replacer, line)
    
    def _rewrite_pattern_2(self, line: str) -> str:
        """Pattern 2: import ai.<pkg> → import <pkg> as <pkg>"""
        def replacer(match: re.Match) -> str:
            pkg_path = match.group(1)
            if self._matches_package(pkg_path):
                first_part = pkg_path.split(".")[0]
                self.changes_made += 1
                return f"import {pkg_path} as {first_part}"
            return match.group(0)
        
        return self._PATTERN_2_IMPORT.sub(replacer, line)
    
    def _rewrite_pattern_3(self, line: str) -> str:
        """Pattern 3: Quoted type annotations "ai.<pkg>.<Class>" → "<pkg>.<Class>" """
        def replacer(match: re.Match) -> str:
            # For non-annotation contexts (data literals), skip rewrite
            if self._is_non_annotation_context(line, match.start()):
                return match.group(0)
            
            quote = match.group(1)
            pkg_path = match.group(2)
            if self._matches_package(pkg_path):
                self.changes_made += 1
                # Reconstruct with the correct prefix (might have r/f/etc.)
                prefix = match.group(0)[:match.group(0).find(quote)]
                return f"{prefix}{quote}{pkg_path}{quote}"
            return match.group(0)
        
        return self._PATTERN_3_QUOTED.sub(replacer, line)
    
    def _rewrite_pattern_5(self, line: str) -> str:
        """Pattern 5: __all__ re-exports with ai.* names"""
        # Only rewrite if this line contains __all__
        if "__all__" not in line:
            return line
        
        # Rewrite quoted strings in this line
        return self._rewrite_pattern_3(line)
    
    def _rewrite_pattern_6(self, line: str) -> str:
        """Pattern 6: Pydantic model_rebuild() / update_forward_refs() calls"""
        # Only rewrite if this line contains model_rebuild or update_forward_refs
        if "model_rebuild" not in line and "update_forward_refs" not in line:
            return line
        
        # Rewrite quoted strings in this line
        return self._rewrite_pattern_3(line)
    
    def _rewrite_pattern_7(self, source: str) -> str:
        """Pattern 7: Provenance headers # negelir-generated-from: ai/<path>@sha256"""
        lines = source.split("\n")
        
        # Scan first N lines for provenance header
        for i in range(min(self.scan_head_lines, len(lines))):
            if "# negelir-generated-from: ai/" not in lines[i]:
                continue
            
            # Extract the path from the header
            match = self._PATTERN_7_PROVENANCE.search(lines[i])
            if match:
                prefix = match.group(1)  # "# negelir-generated-from: "
                rest = match.group(2)     # "common/schemas/records.py@abc123def456"
                
                # Extract package from the path (first component after ai/)
                # rest is like "datasource/scraper.py@..." or "common/config.py@..."
                if rest:
                    path_parts = rest.split("/")
                    if path_parts:
                        header_package = path_parts[0]
                        
                        # Only rewrite if it matches the package filter (or no filter)
                        if self._matches_package(header_package):
                            self.changes_made += 1
                            lines[i] = f"{prefix}{rest}"
        
        return "\n".join(lines)


__all__ = [
    "FileScopeError",
    "FileFilterValidator",
    "Phase22ImportRewriter",
]
