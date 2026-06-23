"""Phase 22.13 — Verify no ai/ paths in docs with backticks."""
import re
from pathlib import Path


def test_22_13_no_ai_path_in_docs():
    """
    Verification: Zero backtick-enclosed `ai/` paths in docs/AGENTS.md/CLAUDE.md/.github/
    
    After Phase 22.12 ROADMAP sweep, no `ai/` references should remain in:
    - docs/**
    - AGENTS.md
    - CLAUDE.md
    - .github/**
    """
    repo_root = Path(__file__).parent.parent.parent
    
    # Files and directories to check
    check_paths = [
        repo_root / 'docs',
        repo_root / 'AGENTS.md',
        repo_root / 'CLAUDE.md',
        repo_root / '.github',
    ]
    
    # Regex pattern for backtick-enclosed ai/ paths
    # Matches `ai/...` patterns
    backtick_pattern = r'`ai/[^`]*`'
    
    violations = []
    
    for check_path in check_paths:
        if not check_path.exists():
            continue
        
        if check_path.is_file():
            files_to_check = [check_path]
        else:
            # Exclude certain dirs
            files_to_check = [
                f for f in check_path.rglob('*')
                if f.is_file() and (f.suffix in {'.md', '.py', '.yml', '.yaml', '.json'} or f.name in {'AGENTS.md', 'CLAUDE.md'})
            ]
        
        for file_path in files_to_check:
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            
            matches = re.findall(backtick_pattern, content)
            if matches:
                violations.append(
                    f"{file_path.relative_to(repo_root)}: {', '.join(set(matches))}"
                )
    
    assert not violations, (
        f"Found {len(violations)} backtick ai/ paths that should not exist:\n"
        + "\n".join(violations)
    )
