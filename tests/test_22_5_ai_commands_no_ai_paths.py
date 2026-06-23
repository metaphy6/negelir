"""Phase 22.5 proof test — ai_commands.py has no ai/ path references."""
from pathlib import Path


def test_22_5_ai_commands_no_ai_paths() -> None:
    """Verify ai_commands.py dispatcher has no ai/ path insertions."""
    ai_cmd_path = Path(__file__).parent.parent / "xops" / "makefile" / "ai_commands.py"
    content = ai_cmd_path.read_text(encoding="utf-8")
    
    # Should NOT have the old sys.path.insert for ai/
    assert 'sys.path.insert(0, str(REPO_ROOT / "ai"))' not in content, \
        "ai_commands.py must not add ai/ to sys.path"
    
    # Should still add REPO_ROOT to sys.path
    assert "sys.path.insert(0, str(REPO_ROOT))" in content, \
        "ai_commands.py must add REPO_ROOT to sys.path"
