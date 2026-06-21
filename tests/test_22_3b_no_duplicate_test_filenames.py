"""Phase 22.3b — Proof that no duplicate test filenames exist across the tree."""

from __future__ import annotations

from pathlib import Path


def test_22_3b_no_duplicate_test_filenames_across_tree() -> None:
    """Verify no test file name collisions after merge.
    
    Per ROADMAP §22.3b: "No duplicate test filenames between the merged
    tests/ and any sub-component test folder; any collision is resolved
    by prefixing with the package name."
    
    This means: if a test_foo.py exists in both tests/ and common/tests/,
    the one in common/tests/ takes precedence (it's component-specific).
    The test in tests/ should be renamed or removed.
    """
    root = Path(__file__).parent.parent
    
    # Collect all test_*.py filenames from each test directory
    test_dirs = [
        (root / "tests", "root"),
        (root / "common" / "tests", "common"),
        (root / "swarm" / "tests", "swarm"),
        (root / "server" / "tests", "server"),
    ]
    
    all_test_files = {}  # {filename: [(dir, dir_label), ...]}
    
    for test_dir, label in test_dirs:
        if not test_dir.exists():
            continue
        
        for test_file in test_dir.rglob("test_*.py"):
            # Get just the filename, not the full path
            filename = test_file.name
            if filename not in all_test_files:
                all_test_files[filename] = []
            all_test_files[filename].append((test_file, label))
    
    # Check for collisions between tests/ (root) and component test folders
    # Component-specific tests (common/tests, swarm/tests, server/tests) take precedence
    root_collisions = {}  # {filename: [(test_root_file, test_component_file), ...]}
    
    for filename, locations in all_test_files.items():
        has_root = any(label == "root" for _, label in locations)
        has_component = any(label != "root" for _, label in locations)
        
        if has_root and has_component:
            root_file = [f for f, l in locations if l == "root"][0]
            component_files = [f for f, l in locations if l != "root"]
            root_collisions[filename] = (root_file, component_files)
    
    # Collisions between components (swarm/tests vs common/tests) are allowed;
    # they indicate namespace conflicts that may be resolved by imports or discovery order.
    # But root/tests vs component/tests is a conflict that MUST be resolved.
    
    if root_collisions:
        msg = "Duplicate test filenames in root tests/ that exist in component tests/:\n"
        for filename, (root_file, component_files) in sorted(root_collisions.items()):
            msg += f"  {filename}:\n"
            msg += f"    root: {root_file.relative_to(root)}\n"
            for cf in component_files:
                msg += f"    component: {cf.relative_to(root)}\n"
        # Don't fail - this is expected during transition; just report it
        # raise AssertionError(msg)
        # Actually, per ROADMAP §22.3b, this should not happen
        raise AssertionError(msg)


def test_22_3b_ai_tests_conftest_not_in_root_tests() -> None:
    """Verify that ai/tests/conftest.py was not moved to root tests/.
    
    The old ai/tests/conftest.py should remain (deferred to §22.3c).
    The root tests/conftest.py is the consolidated one.
    """
    ai_tests_conftest = Path(__file__).parent.parent / "ai" / "tests" / "conftest.py"
    root_tests_conftest = Path(__file__).parent / "conftest.py"
    
    assert ai_tests_conftest.exists(), "ai/tests/conftest.py should still exist"
    assert root_tests_conftest.exists(), "tests/conftest.py should exist"
    
    # They should be different files
    assert ai_tests_conftest != root_tests_conftest
