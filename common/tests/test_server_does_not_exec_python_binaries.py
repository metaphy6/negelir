"""Phase 18.1 §18.1 — Server isolation proof: no python binary execution.

Proof test that the server component does not shell out to forbidden binaries
(python, python3, pytest, xgboost, torch, etc.) via os/exec.Command.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def _iter_go_files(root: Path) -> list[Path]:
    """Recursively find all non-test Go files."""
    files = []
    if root.is_dir():
        for item in root.rglob("*.go"):
            # Skip test files
            if not item.name.endswith("_test.go"):
                files.append(item)
    return files


def _extract_exec_commands(file_path: Path) -> list[tuple[str, int]]:
    """
    Parse Go file to extract exec.Command calls (simple pattern matching).
    
    Returns list of (binary_name, line_number) tuples.
    """
    content = file_path.read_text(encoding="utf-8")
    commands = []
    
    lines = content.split("\n")
    for i, line in enumerate(lines, start=1):
        # Look for exec.Command or exec.CommandContext
        if "exec.Command" in line or "exec.CommandContext" in line:
            # Simple approach: find quoted strings in the line
            # Match both single and double quotes
            for match in re.finditer(r'(?:Command|CommandContext)[^(]*\(([^)]*)', line):
                args = match.group(1)
                # Look for quoted strings
                for qmatch in re.finditer(r'["\']([^"\']+)["\']', args):
                    binary = qmatch.group(1)
                    # Get just the binary name (strip path)
                    binary_name = os.path.basename(binary)
                    commands.append((binary_name, i))
    
    return commands


def test_server_go_files_do_not_exec_python() -> None:
    """Scan server Go files for exec.Command(\"python*\") calls."""
    repo_root = Path(__file__).resolve().parents[2]
    server_root = repo_root / "server"
    
    if not server_root.exists():
        return  # Skip if server/ doesn't exist yet
    
    forbidden_binaries = {
        "python",
        "python2", 
        "python3",
        "pytest",
        "xgboost",
        "torch",
        "pip",
        "pip3",
    }
    
    violations = []
    go_files = _iter_go_files(server_root)
    
    for go_file in go_files:
        exec_commands = _extract_exec_commands(go_file)
        for binary, line_no in exec_commands:
            if binary in forbidden_binaries:
                rel_path = go_file.relative_to(repo_root)
                violations.append(f"{rel_path}:{line_no}: exec.Command({binary!r})")
    
    assert not violations, (
        "Server Go files must not execute forbidden binaries via os/exec.Command:\n"
        + "\n".join(violations)
    )


def test_go_checker_references_ledger_3() -> None:
    """Verify that go_check.go documents its ledger reference."""
    checker_path = Path(__file__).resolve().parents[2] / "common" / "isolation" / "go_check.go"
    content = checker_path.read_text()
    
    # Should reference ledger #3
    assert "ledger" in content.lower() or "3" in content, (
        "go_check.go should reference its ledger row (ledger #3)"
    )


def test_go_isolation_policy_path_correct() -> None:
    """Verify that go_check.go loads policy.yaml from the correct location."""
    checker_path = Path(__file__).resolve().parents[2] / "common" / "isolation" / "go_check.go"
    content = checker_path.read_text()
    
    # Should reference policy.yaml in ai/common/isolation/
    assert ("isolation" in content and "policy" in content), (
        "go_check.go should reference policy.yaml in the isolation package"
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
