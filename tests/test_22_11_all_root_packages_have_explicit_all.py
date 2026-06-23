"""Phase 22.11 — Proof test for __all__ declarations in root packages.

Verifies that every moved root-level package declares an explicit __all__
in its __init__.py, per Phase 18 §18.13 gate.
"""
from pathlib import Path
import ast


def test_22_11_all_root_packages_have_explicit_all() -> None:
    """Phase 22.11 bullet 4: Verify all root packages declare __all__.
    
    The Phase 18 §18.13 gate `test_components_declare_public_api_via_all`
    requires explicit __all__ in every root-level package's __init__.py.
    """
    # List of all moved root-level packages (post Phase 22.4)
    packages = [
        "scraper",
        "model", 
        "nlp",
        "pipeline",
        "qid",
        "tqu",
        "trc",
        "proofreader",
        "orchestrator",
        "backtest",
        "enrichment",
    ]
    
    # swarm is a merge (not a move), but should still have __all__
    packages.append("swarm")
    
    # common is a merge, should have __all__
    packages.append("common")
    
    missing_all = []
    
    for pkg_name in packages:
        init_path = Path(pkg_name) / "__init__.py"
        
        if not init_path.exists():
            raise AssertionError(f"Package {pkg_name} not found at {init_path}")
        
        content = init_path.read_text(encoding="utf-8")
        
        # Parse the file to check for __all__ assignment
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            raise AssertionError(f"{pkg_name}/__init__.py has syntax error: {e}")
        
        # Look for __all__ assignment at module level
        has_all = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        has_all = True
                        break
        
        if not has_all:
            missing_all.append(pkg_name)
    
    assert not missing_all, (
        f"Packages missing __all__ declaration: {missing_all}. "
        "Every root package must declare __all__ in __init__.py"
    )
