"""Phase 10 §10.21.6 — Template safety gap demonstration.

This test demonstrates that the current template lint (§10.15) does not
catch entity.original_text usage, which is a security gap per §10.21.6.
"""
import tempfile
import pathlib
import subprocess


def test_current_template_lint_allows_entity_original_text():
    """Demonstrates §10.21.6 bullet 1: make nlp.template-lint allows entity.original_text.
    
    The §10.21.5 confusables defense adds entities[].original_text for audit,
    which contains raw user input. The current template lint only forbids
    {{ free_text }}, but doesn't catch {{ entity.original_text }}, which is
    equally dangerous.
    
    This test creates a temporary template with entity.original_text and
    shows it would currently pass the lint check.
    """
    dangerous_template = """
Takım adı: {{ home_team | match_label }}
Kullanıcı girişi: {{ entity.original_text }}
"""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = pathlib.Path(tmpdir)
        template_file = tmp_path / "dangerous.tr.j2"
        template_file.write_text(dangerous_template, encoding="utf-8")
        
        # Parse with Jinja2 AST (same logic as make nlp.template-lint)
        import jinja2
        from jinja2 import nodes
        
        env = jinja2.Environment()
        ast = env.parse(dangerous_template)
        
        # Extract variables
        def extract_variables(node):
            variables = set()
            if isinstance(node, nodes.Name):
                variables.add(node.name)
            for child in node.iter_child_nodes():
                variables.update(extract_variables(child))
            return variables
        
        variables = extract_variables(ast)
        
        # Current forbidden set (from xops/makefile/nlp.py)
        CURRENT_FORBIDDEN = {
            "free_text", "raw_input", "user_query", "unstructured",
            "arbitrary_text", "custom_message",
        }
        
        # Check: the dangerous template should contain entity
        assert "entity" in variables, "Test setup error: entity not found"
        
        # The problem: current lint doesn't check entity.original_text access
        # entity itself is allowed (for entity.canonical_id, entity.kind, etc.)
        # but entity.original_text is raw user input and should be forbidden
        forbidden_found = any(v in CURRENT_FORBIDDEN for v in variables)
        assert not forbidden_found, (
            "Test setup error: template should pass current lint check, "
            "but it contains a currently-forbidden slot"
        )
        
        # This is the gap: entity.original_text would pass the current lint,
        # but it shouldn't because it's raw user input
        # (The AST doesn't distinguish entity.original_text from entity.canonical_id)


if __name__ == "__main__":
    test_current_template_lint_allows_entity_original_text()
    print("✓ Demonstrated: current lint allows entity.original_text (§10.21.6 gap)")
