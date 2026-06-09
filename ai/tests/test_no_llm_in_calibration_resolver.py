"""Test that calibration profile resolution contains no LLM dependencies.

Per COMPETITIONS.md §4.1: profile resolution is deterministic, no LLM.
The resolution rule is hard-wired and unit-tested; LLM output is never consulted.
This test performs an AST scan to enforce that constraint.
"""

import ast
import pytest
from pathlib import Path


FORBIDDEN_IMPORTS = {
    "openai",
    "anthropic",
    "cohere",
    "together",
    "llm",
    "langchain",
    "llamaindex",
    "replicate",
    "huggingface_hub",
}


class TestNoLLMInCalibrationResolver:
    """AST scan: refuse LLM imports in _calibration.py."""

    @staticmethod
    def _scan_module_imports(module_path: Path) -> set[str]:
        """Extract all module imports from a Python file via AST."""
        with open(module_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split(".")[0]
                    imports.add(module_name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module_name = node.module.split(".")[0]
                    imports.add(module_name)

        return imports

    def test_calibration_module_has_no_llm_imports(self) -> None:
        """Calibration resolver module must not import any LLM package."""
        calibration_path = Path(__file__).parent.parent / "swarm" / "predictor" / "_calibration.py"
        assert calibration_path.exists(), f"{calibration_path} not found"

        imports = self._scan_module_imports(calibration_path)
        forbidden_found = imports & FORBIDDEN_IMPORTS

        assert (
            not forbidden_found
        ), (
            f"Forbidden LLM imports in {calibration_path}: {forbidden_found}. "
            "Profile resolution must be deterministic, not LLM-backed."
        )

    def test_calibration_module_only_uses_stdlib_and_dataclasses(self) -> None:
        """Verify minimal dependency footprint: stdlib + dataclasses only."""
        calibration_path = Path(__file__).parent.parent / "swarm" / "predictor" / "_calibration.py"
        imports = self._scan_module_imports(calibration_path)

        allowed_external = {"dataclasses"}  # if used; normally just stdlib
        stdlib_modules = {
            "typing", "dataclasses", "abc", "functools", "json", "re", "os", "sys"
        }
        allowed = stdlib_modules | allowed_external

        unexpected = imports - allowed
        assert (
            not unexpected
        ), (
            f"Unexpected imports in {calibration_path}: {unexpected}. "
            "Keep resolution rule minimal for clarity and testability."
        )
