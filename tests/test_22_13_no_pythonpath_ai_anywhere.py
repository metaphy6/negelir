"""Phase 22.13 proof test — Comprehensive PYTHONPATH=ai scan across all config files."""
from pathlib import Path
import re


def test_22_13_no_pythonpath_ai_anywhere() -> None:
    """
    Verify zero PYTHONPATH=ai occurrences in:
    - Makefile
    - pyproject.toml
    - docker-compose*.yml files
    - .github/workflows/*.yml files
    
    After Phase 22 migration, all references must be PYTHONPATH=.
    """
    root = Path(__file__).parent.parent
    
    # 1. Check Makefile
    makefile = root / "Makefile"
    if makefile.exists():
        content = makefile.read_text(encoding="utf-8")
        assert "PYTHONPATH=ai" not in content, f"Makefile: found PYTHONPATH=ai"
        assert "PYTHONPATH: ai" not in content, f"Makefile: found PYTHONPATH: ai"
    
    # 2. Check pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text(encoding="utf-8")
        assert "PYTHONPATH=ai" not in content, f"pyproject.toml: found PYTHONPATH=ai"
    
    # 3. Check docker-compose files
    for compose_file in root.glob("docker-compose*.yml"):
        content = compose_file.read_text(encoding="utf-8")
        assert "PYTHONPATH=ai" not in content, \
            f"{compose_file.name}: found PYTHONPATH=ai"
        assert "PYTHONPATH: ai" not in content, \
            f"{compose_file.name}: found PYTHONPATH: ai"
        assert "python ai/" not in content, \
            f"{compose_file.name}: found python ai/ reference"
    
    # 4. Check .github/workflows
    workflows_dir = root / ".github" / "workflows"
    if workflows_dir.exists():
        for workflow_file in workflows_dir.glob("*.yml"):
            content = workflow_file.read_text(encoding="utf-8")
            assert "PYTHONPATH=ai" not in content, \
                f"{workflow_file.name}: found PYTHONPATH=ai"
            assert "PYTHONPATH: ai" not in content, \
                f"{workflow_file.name}: found PYTHONPATH: ai"
            assert "working-directory: ai" not in content, \
                f"{workflow_file.name}: found working-directory: ai"


if __name__ == "__main__":
    test_22_13_no_pythonpath_ai_anywhere()
    print("✓ No PYTHONPATH=ai occurrences found in any config files")
