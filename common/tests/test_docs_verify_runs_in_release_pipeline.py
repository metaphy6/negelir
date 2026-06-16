"""Phase 18.8 — make docs.verify must run in the release pipeline."""

from pathlib import Path
import re


def test_docs_verify_target_exists_in_makefile() -> None:
    """The Makefile must define a docs.verify target."""
    repo_root = Path(__file__).resolve().parents[2]
    makefile = repo_root / "Makefile"
    
    content = makefile.read_text(encoding="utf-8")
    
    # Check for .PHONY: docs.verify and the target
    assert re.search(r"\.PHONY:\s+docs\.verify", content), "docs.verify not in .PHONY"
    assert re.search(r"^docs\.verify:", content, re.MULTILINE), "docs.verify target not defined"


def test_docs_verify_dispatcher_exists() -> None:
    """The xops/makefile/docs.py module must have cmd_verify."""
    repo_root = Path(__file__).resolve().parents[2]
    docs_py = repo_root / "xops" / "makefile" / "docs.py"
    
    assert docs_py.exists(), "xops/makefile/docs.py not found"
    
    content = docs_py.read_text(encoding="utf-8")
    assert "def cmd_verify" in content, "cmd_verify not found in docs.py"
    assert '"verify":' in content or "'verify':" in content, "verify not in COMMANDS dict"
