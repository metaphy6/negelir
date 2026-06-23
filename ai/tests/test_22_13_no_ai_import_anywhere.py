"""Phase 22.13 — Verify no ai.* or ai imports exist anywhere in repo."""
import ast
from pathlib import Path


def test_22_13_no_ai_import_anywhere():
    """
    Verification: Zero `import ai` or `from ai.*` statements anywhere.
    
    Walks every .py file in the repo (excluding .git/) and checks for:
    - ImportFrom nodes referencing 'ai' or 'ai.*'
    - Import nodes referencing 'ai'
    """
    repo_root = Path(__file__).parent.parent.parent
    excluded_dirs = {'.git', '__pycache__', '.pytest_cache', 'venv', '.venv', 'env', '.env'}
    
    violations = []
    
    for py_file in repo_root.rglob('*.py'):
        # Skip excluded directories
        if any(part in excluded_dirs for part in py_file.parts):
            continue
        
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8', errors='ignore'))
        except SyntaxError:
            continue
        
        for node in ast.walk(tree):
            # Check ImportFrom (from X import Y)
            if isinstance(node, ast.ImportFrom):
                if node.module and (node.module == 'ai' or node.module.startswith('ai.')):
                    violations.append(
                        f"{py_file.relative_to(repo_root)}: "
                        f"from {node.module} import ... (line {node.lineno})"
                    )
            
            # Check Import (import X)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'ai' or alias.name.startswith('ai.'):
                        violations.append(
                            f"{py_file.relative_to(repo_root)}: "
                            f"import {alias.name} (line {node.lineno})"
                        )
    
    assert not violations, (
        f"Found {len(violations)} ai.* imports that should not exist:\n"
        + "\n".join(violations)
    )
