#!/usr/bin/env python3
"""Phase 22.5 k8s manifest linter — ensure no ai/ path references.

Scans all .yaml/.yml files under infra/k8s/ and rejects any that contain:
  - PYTHONPATH=ai (env vars)
  - python ai/ (python command references)  
  - /app/ai (volume mount paths)
  - ai/ (general string literal paths, CONSERVATIVE)

Exit codes:
  0: All manifests clean
  1: Lint failures found
"""

import os
import sys
from pathlib import Path
import re


def lint_k8s_manifests(repo_root: Path) -> list[tuple[Path, list[str]]]:
    """Scan k8s manifests for ai/ references.
    
    Returns list of (file_path, errors) tuples.
    """
    k8s_root = repo_root / "infra" / "k8s"
    if not k8s_root.exists():
        return []
    
    errors_by_file: list[tuple[Path, list[str]]] = []
    patterns = [
        (r"PYTHONPATH\s*=\s*ai\b", "PYTHONPATH=ai (should be PYTHONPATH=.)"),
        (r"python\s+ai/", "python ai/ command (should use root path)"),
        (r"/app/ai\b", "/app/ai volume mount (should be /app)"),
        (r"[\"']ai/", "ai/ path literal (should use root path)"),
    ]
    
    for yaml_file in k8s_root.rglob("*.ya?ml"):
        content = yaml_file.read_text(encoding="utf-8")
        file_errors = []
        
        for pattern, description in patterns:
            if re.search(pattern, content):
                file_errors.append(f"{yaml_file.relative_to(repo_root)}: {description}")
        
        if file_errors:
            errors_by_file.append((yaml_file, file_errors))
    
    return errors_by_file


def main() -> int:
    repo_root = Path(__file__).parent.parent.parent
    errors = lint_k8s_manifests(repo_root)
    
    if not errors:
        print("✔ k8s manifests clean — no ai/ path references found")
        return 0
    
    print("✗ k8s manifest lint failures:")
    for file_path, file_errors in errors:
        for error in file_errors:
            print(f"  {error}")
    
    return 1


if __name__ == "__main__":
    sys.exit(main())
