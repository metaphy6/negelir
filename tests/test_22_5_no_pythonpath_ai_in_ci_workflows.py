"""Phase 22.5 proof test — CI workflows have no ai/ path references."""
from pathlib import Path
import re


def test_22_5_no_pythonpath_ai_in_ci_workflows() -> None:
    """Verify .github/workflows/*.yml have no PYTHONPATH=ai or working-directory: ai."""
    workflows_dir = Path(__file__).parent.parent / ".github" / "workflows"
    assert workflows_dir.exists(), f"workflows dir not found at {workflows_dir}"
    
    for workflow_file in workflows_dir.glob("*.yml"):
        content = workflow_file.read_text(encoding="utf-8")
        
        assert "PYTHONPATH: ai" not in content, \
            f"{workflow_file.name}: must not have PYTHONPATH: ai"
        assert "PYTHONPATH=ai" not in content, \
            f"{workflow_file.name}: must not have PYTHONPATH=ai"
        assert "working-directory: ai" not in content, \
            f"{workflow_file.name}: must not have working-directory: ai"
        assert "python ai/" not in content, \
            f"{workflow_file.name}: must not have python ai/ references"
