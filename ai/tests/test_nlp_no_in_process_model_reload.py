"""Phase 10 §10.21.2 — AST guard: no in-process model reload.

Enforces the "process-restart for model reload" contract (§10.21.2 item 2):
- Re-loading `intent.tr.bin` mid-process leaks mmap regions on most libc allocators.
- NLP-pod model-reload contract: SIGTERM → graceful drain → K8s rolls a fresh pod.
- **No in-process model hot-swap.**

This test rejects:
1. `fasttext.load_model(...)` calls outside of `__init__` or class/static methods
   used for initialization (factory methods like `IntentClassifier.load()`).
2. `pycrfsuite.Tagger().open(...)` calls outside initialization paths.
3. Any method names suggesting reload: `reload`, `hot_swap`, `refresh_model`,
   `update_model`, etc. in classes that hold ML models.

Anchor: Phase 10 §10.21.2 item 2 (docs/design/nlp/sections/21-integrity-and-second-order-safety.md).
"""
from __future__ import annotations

import ast
import pathlib
from typing import List, Set


class TestNoInProcessModelReload:
    """§10.21.2: Model reload via process-restart, not in-process swap."""

    def test_nlp_no_in_process_model_reload(self) -> None:
        """AST guard: reject fasttext.load_model / pycrfsuite outside __init__."""
        
        # Paths to scan
        ai_dir = pathlib.Path(__file__).parent.parent
        nlp_path = ai_dir / "nlp"
        swarm_nlp_path = ai_dir / "swarm" / "agents" / "nlp"
        
        scan_paths = []
        if nlp_path.exists():
            scan_paths.extend(nlp_path.rglob("*.py"))
        if swarm_nlp_path.exists():
            scan_paths.extend(swarm_nlp_path.rglob("*.py"))
        
        # Forbidden method names (suggesting reload logic)
        FORBIDDEN_METHOD_NAMES: Set[str] = {
            "reload",
            "reload_model",
            "hot_swap",
            "swap_model",
            "refresh_model",
            "update_model",
            "load_new_model",
            "replace_model",
        }
        
        violations: List[str] = []
        
        class _Checker(ast.NodeVisitor):
            def __init__(self, filepath: pathlib.Path):
                self.filepath = filepath
                self.current_class: str = ""
                self.current_method: str = ""
                self.in_init: bool = False
                self.in_classmethod: bool = False
            
            def visit_ClassDef(self, node: ast.ClassDef) -> None:  # type: ignore[override]
                old_class = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = old_class
            
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # type: ignore[override]
                old_method = self.current_method
                old_in_init = self.in_init
                old_in_classmethod = self.in_classmethod
                
                self.current_method = node.name
                self.in_init = (node.name == "__init__")
                
                # Check if this is a classmethod or staticmethod
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Name):
                        if decorator.id in ("classmethod", "staticmethod"):
                            self.in_classmethod = True
                
                # Check for forbidden method names (reload/hot_swap/etc.)
                if node.name in FORBIDDEN_METHOD_NAMES:
                    rel_path = self.filepath.relative_to(ai_dir)
                    violations.append(
                        f"{rel_path}:{node.lineno}: method '{self.current_class}.{node.name}' "
                        f"suggests in-process model reload — violates §10.21.2 "
                        f"(models reload via process-restart only)"
                    )
                
                self.generic_visit(node)
                
                self.current_method = old_method
                self.in_init = old_in_init
                self.in_classmethod = old_in_classmethod
            
            def visit_Call(self, node: ast.Call) -> None:  # type: ignore[override]
                # Check for fasttext.load_model(...)
                is_fasttext_load = False
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "load_model":
                        # Check if it's fasttext.load_model
                        if isinstance(node.func.value, ast.Name):
                            if node.func.value.id == "fasttext":
                                is_fasttext_load = True
                
                # Check for pycrfsuite.Tagger().open(...)
                is_crfsuite_open = False
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "open":
                        # Check if it's something.Tagger().open
                        if isinstance(node.func.value, ast.Call):
                            if isinstance(node.func.value.func, ast.Attribute):
                                if node.func.value.func.attr == "Tagger":
                                    is_crfsuite_open = True
                            elif isinstance(node.func.value.func, ast.Name):
                                if node.func.value.func.id == "Tagger":
                                    is_crfsuite_open = True
                
                # Reject if outside initialization context
                if is_fasttext_load or is_crfsuite_open:
                    # Allow in __init__, classmethod factories, or private helpers
                    # (private helpers starting with _ are assumed to be called during init)
                    allowed = (
                        self.in_init
                        or self.in_classmethod
                        or self.current_method.startswith("_")
                    )
                    
                    if not allowed:
                        model_type = "fasttext.load_model" if is_fasttext_load else "pycrfsuite.Tagger.open"
                        rel_path = self.filepath.relative_to(ai_dir)
                        context = f"{self.current_class}.{self.current_method}" if self.current_class else self.current_method
                        violations.append(
                            f"{rel_path}:{node.lineno}: {model_type}(...) call in "
                            f"'{context}' — violates §10.21.2 (must be in __init__, "
                            f"classmethod factory, or private helper method called during init)"
                        )
                
                self.generic_visit(node)
        
        # Walk all Python files in nlp and swarm/agents/nlp
        for py_file in scan_paths:
            # Skip __pycache__ and test files
            if "__pycache__" in str(py_file):
                continue
            if "test_" in py_file.name:
                continue
            
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
                _Checker(py_file).visit(tree)
            except SyntaxError:
                # Skip files with syntax errors (might be templates or data)
                continue
        
        assert violations == [], (
            "NLP code has in-process model reload logic (violates §10.21.2 "
            "process-restart contract):\n" + "\n".join(violations)
        )
