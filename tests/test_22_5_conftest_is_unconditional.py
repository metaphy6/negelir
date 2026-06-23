"""Phase 22.5 proof test — root conftest.py has no phase layout guards."""
from pathlib import Path


def test_22_5_conftest_is_unconditional() -> None:
    """Verify root conftest.py has no _phase22_layout checks."""
    conftest_path = Path(__file__).parent.parent / "conftest.py"
    content = conftest_path.read_text(encoding="utf-8")
    
    # Should NOT have the transitional check
    assert "_phase22_layout" not in content, \
        "conftest must not have _phase22_layout guard"
    
    # Should NOT have else branch for phase 18 layout
    assert "Phase 18:" not in content, \
        "conftest must not reference Phase 18 layout branch"
    
    # Should unconditionally add root to sys.path
    assert "sys.path.insert(0, _root_str)" in content, \
        "conftest must unconditionally insert root to sys.path"
    
    # pytest_configure should be unconditional
    lines = content.split('\n')
    in_pytest_configure = False
    has_if_phase22 = False
    for line in lines:
        if "def pytest_configure" in line:
            in_pytest_configure = True
        elif in_pytest_configure and "if _phase22_layout" in line:
            has_if_phase22 = True
            break
        elif in_pytest_configure and line.strip() and not line.startswith(" "):
            in_pytest_configure = False
    
    assert not has_if_phase22, \
        "pytest_configure must not have if _phase22_layout check"
