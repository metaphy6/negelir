"""Phase 22.5 proof test — Makefile has no PYTHONPATH=ai references."""
from pathlib import Path


def test_22_5_no_pythonpath_ai_in_makefile() -> None:
    """Verify Makefile has no PYTHONPATH=ai or ai/ test path references."""
    makefile = Path(__file__).parent.parent / "Makefile"
    assert makefile.exists(), f"Makefile not found"

    content = makefile.read_text(encoding="utf-8")
    
    # Check for old patterns
    assert "PYTHONPATH=ai " not in content, "Makefile must not have PYTHONPATH=ai"
    assert "PYTHONPATH: ai" not in content, "Makefile must not have PYTHONPATH: ai"
    assert "ai/tests/" not in content, "Makefile must not reference ai/tests/ directly"
    assert "python ai/" not in content, "Makefile must not have python ai/ references"
    
    # Verify test.adversarial is using new path
    if "test.adversarial" in content:
        # Extract the test line for test.adversarial
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if "test.adversarial:" in line:
                # Find the run command (next few lines)
                rest = '\n'.join(lines[i:i+3])
                assert "tests/test_adversarial_corpus.py" in rest or "pytest" not in rest, \
                    "test.adversarial must use tests/ path"
                break
