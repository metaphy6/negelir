"""Phase 10 §10.21.2 — Jinja2 bytecode cache + AST guard: no from_string.

Enforces the "precompiled templates + no hot-path codegen" contract
(§10.21.2 item 4):
- Jinja2 Environment uses FileSystemBytecodeCache to cache compiled templates.
- AST guard rejects `Environment().from_string(...)` anywhere under `ai/nlp/render.py`
  (string-template compilation in hot path = unbounded codegen).

This test verifies:
1. `build_environment` creates bytecode cache files on first template render.
2. No `Environment().from_string(...)` calls in `ai/nlp/render.py` or related
   rendering code paths.

Anchor: Phase 10 §10.21.2 item 4 (docs/design/phase10/sections/21-integrity-and-second-order-safety.md).
"""
from __future__ import annotations

import ast
import pathlib
import tempfile
from typing import Set

from ai.common.config import cfg
from nlp.render import build_environment


class TestJinja2BytecodeCache:
    """§10.21.2: Jinja2 bytecode cache + no from_string codegen."""

    def test_nlp_jinja_bcc_used_creates_cache_files(self) -> None:
        """Bytecode cache creates .cache files on first template render."""
        # Use a temporary cache dir to avoid polluting the real cache
        with tempfile.TemporaryDirectory() as tmpdir:
            # Override config temporarily
            original_bcc_dir = cfg.nlp_jinja_bcc_dir
            cfg.nlp_jinja_bcc_dir = tmpdir
            
            try:
                # Build environment and render a simple template
                env = build_environment()
                
                # Render meta.unsupported (always present)
                tmpl = env.get_template("meta.unsupported.tr.j2")
                result = tmpl.render(suggestions=["test"])
                
                assert result  # non-empty render
                
                # Check that cache files were created
                cache_dir = pathlib.Path(tmpdir)
                cache_files = list(cache_dir.glob("__nlp_*.cache"))
                
                assert len(cache_files) > 0, (
                    f"Expected bytecode cache files in {tmpdir}, "
                    f"but found none. Cache should create __nlp_*.cache files."
                )
                
                # Verify the cache file pattern matches §10.21.2 spec
                for cache_file in cache_files:
                    assert cache_file.name.startswith("__nlp_"), (
                        f"Cache file {cache_file.name} does not match pattern __nlp_*.cache"
                    )
                    assert cache_file.name.endswith(".cache"), (
                        f"Cache file {cache_file.name} does not end with .cache"
                    )
            finally:
                cfg.nlp_jinja_bcc_dir = original_bcc_dir

    def test_nlp_no_string_template_compile_in_hot_path(self) -> None:
        """AST guard: reject Environment().from_string() in render.py."""
        # Path to scan
        ai_dir = pathlib.Path(__file__).parent.parent
        render_path = ai_dir / "nlp" / "render.py"
        
        assert render_path.exists(), f"render.py not found at {render_path}"
        
        # Parse the AST
        source = render_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(render_path))
        
        # Look for Environment().from_string(...) pattern
        violations: list[str] = []
        
        for node in ast.walk(tree):
            # Pattern: some_env.from_string(...)
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "from_string":
                        # Found a from_string call
                        lineno = node.lineno if hasattr(node, "lineno") else "?"
                        violations.append(
                            f"{render_path.name}:{lineno}: "
                            f"Environment().from_string(...) forbidden in hot path "
                            f"(§10.21.2: use FileSystemLoader + bytecode cache only)"
                        )
        
        assert not violations, (
            "§10.21.2 violation: Environment().from_string() found in render.py.\n"
            + "\n".join(violations)
            + "\n\nString-template compilation in hot path = unbounded codegen. "
            "Use FileSystemLoader + precompiled templates only."
        )

    def test_nlp_jinja_environment_has_auto_reload_false(self) -> None:
        """Verify auto_reload=False to prevent runtime recompilation."""
        env = build_environment()
        
        # Check that auto_reload is False
        # In Jinja2, auto_reload is accessed via env.auto_reload attribute
        assert hasattr(env, "auto_reload"), "Environment missing auto_reload attribute"
        assert env.auto_reload is False, (
            "§10.21.2 violation: Environment.auto_reload must be False. "
            "Runtime template recompilation is forbidden."
        )

    def test_nlp_jinja_environment_has_bytecode_cache(self) -> None:
        """Verify bytecode_cache is configured."""
        env = build_environment()
        
        # Check that bytecode_cache is set
        assert env.bytecode_cache is not None, (
            "§10.21.2 violation: Environment.bytecode_cache must be configured. "
            "FileSystemBytecodeCache is required."
        )
        
        # Verify it's the right type
        import jinja2.bccache
        assert isinstance(env.bytecode_cache, jinja2.bccache.FileSystemBytecodeCache), (
            f"§10.21.2 violation: bytecode_cache must be FileSystemBytecodeCache, "
            f"got {type(env.bytecode_cache).__name__}"
        )
