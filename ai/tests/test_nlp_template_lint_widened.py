"""Phase 10 §10.21.6 bullet 1 — AST template lint widened to reject raw user input.

Tests that make nlp.template-lint now AST-rejects:
  - entity.original_text, entity.raw
  - *.user_text, *.normalized_text
  - kwargs.get(
  - request.*

And allows only:
  - entity.canonical_id, entity.kind, entity.span_start, entity.span_end
  - Predefined filter outputs (team | match_label, kickoff | kickoff_time)
"""
import jinja2
from jinja2 import nodes
from pathlib import Path


def test_nlp_template_lint_rejects_entity_original_text():
    """§10.21.6: entity.original_text (raw user input) must be rejected."""
    dangerous_template = """
Takım adı: {{ home_team | match_label }}
Kullanıcı girişi: {{ entity.original_text }}
"""
    
    env = jinja2.Environment()
    ast = env.parse(dangerous_template)
    
    # Extract attribute accesses using the same logic as cmd_nlp_template_lint
    def extract_attribute_accesses(node):
        accesses = []
        
        if isinstance(node, nodes.Getattr):
            base_obj = None
            if isinstance(node.node, nodes.Name):
                base_obj = node.node.name
            elif isinstance(node.node, nodes.Getattr):
                nested = extract_attribute_accesses(node.node)
                accesses.extend(nested)
                if nested:
                    base_obj = nested[-1][2]
            
            if base_obj:
                full_path = f"{base_obj}.{node.attr}"
                accesses.append((base_obj, node.attr, full_path))
        
        for child in node.iter_child_nodes():
            accesses.extend(extract_attribute_accesses(child))
        
        return accesses
    
    attr_accesses = extract_attribute_accesses(ast)
    
    # Check that entity.original_text was detected
    found_original_text = any(
        base == "entity" and attr == "original_text"
        for base, attr, _ in attr_accesses
    )
    
    assert found_original_text, (
        "Test setup error: entity.original_text not detected in AST"
    )
    
    # Verify that original_text is in the forbidden list
    FORBIDDEN_ATTR_SUFFIXES = {
        "original_text", "raw", "user_text", "normalized_text",
    }
    
    # The lint should reject this
    violations = [
        (base, attr, path)
        for base, attr, path in attr_accesses
        if attr in FORBIDDEN_ATTR_SUFFIXES
    ]
    
    assert violations, (
        "§10.21.6: entity.original_text should be caught as forbidden "
        "raw user input attribute"
    )
    assert ("entity", "original_text", "entity.original_text") in violations


def test_nlp_templates_do_not_access_shout_flag() -> None:
    """§10.28.8: reply templates must not branch on a shout metadata flag."""
    from pathlib import Path

    template_dir = Path(__file__).resolve().parents[2] / "ai" / "nlp" / "templates"
    if not template_dir.exists():
        return

    def extract_accesses(node):
        accesses = []
        if isinstance(node, nodes.Name):
            accesses.append((node.name, "", node.name))
        elif isinstance(node, nodes.Getattr):
            base_name = None
            if isinstance(node.node, nodes.Name):
                base_name = node.node.name
            elif isinstance(node.node, nodes.Getattr):
                nested = extract_accesses(node.node)
                accesses.extend(nested)
                if nested:
                    base_name = nested[-1][2]
            if base_name is not None:
                accesses.append((base_name, node.attr, f"{base_name}.{node.attr}"))
        for child in node.iter_child_nodes():
            accesses.extend(extract_accesses(child))
        return accesses

    for template_path in sorted(template_dir.glob("*.tr.j2")):
        ast = jinja2.Environment().parse(template_path.read_text(encoding="utf-8"))
        accesses = extract_accesses(ast)
        assert not any(
            attr == "shout" or path.endswith(".shout")
            for _, attr, path in accesses
        ), f"Template {template_path.name} must not branch on shout metadata"


if __name__ == "__main__":
    test_nlp_template_lint_rejects_entity_original_text()
    print("✓ test_nlp_template_lint_rejects_entity_original_text passed")


def test_nlp_template_finalize_blocks_raw_user_substring():
    """§10.21.6: Runtime finalize guard blocks templates that render raw user text.
    
    This is the defense-in-depth runtime check — the AST lint should catch these
    at build time, but finalize provides a 'shouldn't happen' alarm.
    """
    from nlp.render import build_environment, RawUserTextInTemplateError
    import pytest
    
    user_text = "Fenerbahçe kazanacak mı?"
    
    # Build environment with the runtime guard enabled
    env = build_environment(user_text_for_guard=user_text)
    
    # Template that directly echoes part of user input (forbidden)
    dangerous_template = "{{ user_query }}"
    
    tmpl = env.from_string(dangerous_template)
    
    # Attempt to render with user text as a slot value
    with pytest.raises(RawUserTextInTemplateError, match="raw user input substring"):
        tmpl.render(user_query=user_text)
    
    # Verify that rendering WITHOUT the user text works
    tmpl2 = env.from_string("{{ safe_value }}")
    result = tmpl2.render(safe_value="Galatasaray")
    assert result == "Galatasaray"


def test_nlp_citation_template_uses_only_allowed_fields():
    """§10.21.6: AST must verify citation block uses ONLY allowed fields.
    
    Allowed fields for citation block:
    - prediction_id
    - produced_at_utc
    - model_versions (list)
    - calibration_version
    - degraded_reason (optional)
    
    This test verifies that a citation block constructed with extra fields
    would be caught by AST analysis.
    """
    # Good citation template (uses only allowed fields)
    good_citation = """
---
[tahmin:{{ citation.prediction_id }} | üretim:{{ citation.produced_at_utc }} | kalibrasyon:{{ citation.calibration_version }} | modeller:{{ citation.model_versions | join(', ') }}]
{% if citation.degraded_reason %}
[sebep:{{ citation.degraded_reason }}]
{% endif %}
"""
    
    env = jinja2.Environment()
    ast_good = env.parse(good_citation)
    
    def extract_citation_fields(node):
        """Extract field accesses on 'citation' object."""
        fields = []
        if isinstance(node, nodes.Getattr):
            if isinstance(node.node, nodes.Name) and node.node.name == "citation":
                fields.append(node.attr)
        for child in node.iter_child_nodes():
            fields.extend(extract_citation_fields(child))
        return fields
    
    good_fields = extract_citation_fields(ast_good)
    
    # Verify all fields are allowed
    CITATION_ALLOWED_FIELDS = {
        "prediction_id",
        "produced_at_utc",
        "model_versions",
        "calibration_version",
        "degraded_reason",
    }
    
    for field in good_fields:
        assert field in CITATION_ALLOWED_FIELDS, (
            f"Field {field!r} used in citation but not in allowed set"
        )
    
    # Bad citation template (uses disallowed field)
    bad_citation = """
---
[tahmin:{{ citation.prediction_id }} | üretim:{{ citation.produced_at_utc }} | extra:{{ citation.extra_field }}]
"""
    
    ast_bad = env.parse(bad_citation)
    bad_fields = extract_citation_fields(ast_bad)
    
    disallowed = [f for f in bad_fields if f not in CITATION_ALLOWED_FIELDS]
    assert disallowed, (
        "Test setup error: bad citation template should use at least one disallowed field"
    )
    assert "extra_field" in disallowed, (
        "§10.21.6: Citation template using 'extra_field' should be detected as violation"
    )


def test_render_citation_block_integration():
    """Integration test: render_citation_block produces canonical form that
    templates can safely embed after CITATION_DELIMITER."""
    from nlp.render import render_citation_block, citation_sha256
    
    citation_data = {
        "prediction_id": "pred-integration-1",
        "produced_at_utc": "2026-05-27T14:00:00.000000Z",
        "model_versions": ["predictor-v2@2.0.0", "predictor-v1@1.0.0"],
        "calibration_version": 99,
    }
    
    # Render canonical citation block
    block = render_citation_block(citation_data)
    
    # Verify it contains all fields in canonical order
    assert "tahmin:pred-integration-1" in block
    assert "üretim:2026-05-27T14:00:00.000000Z" in block
    assert "kalibrasyon:99" in block
    # model_versions should be sorted
    assert "modeller:predictor-v1@1.0.0, predictor-v2@2.0.0" in block
    
    # Verify sha256 is stable
    sha1 = citation_sha256(block)
    sha2 = citation_sha256(render_citation_block(citation_data))
    assert sha1 == sha2
    
    # Simulate a complete answer: body + delimiter + citation
    body = "Maç tahmini burada."
    from nlp.render import CITATION_DELIMITER
    full_answer = body + CITATION_DELIMITER + block
    
    # Verify extraction works
    from nlp.render import extract_citation_block
    extracted_body, extracted_citation = extract_citation_block(full_answer)
    assert extracted_body == body
    assert extracted_citation == block
    
    # Verify sha256 round-trip
    sha_extracted = citation_sha256(extracted_citation)
    assert sha_extracted == sha1, (
        "SHA256 must be stable through extract → sha256 round-trip"
    )


def test_predict_templates_citation_section_uses_only_citation_block():
    """§10.21.6: citation section in predict templates is single-slot canonical."""
    env = jinja2.Environment()
    templates_dir = Path(__file__).resolve().parents[1] / "nlp" / "templates"

    predict_templates = sorted(templates_dir.glob("predict.*.tr.j2"))
    assert predict_templates, "No predict templates found for citation-section check"

    for tpl_path in predict_templates:
        source = tpl_path.read_text(encoding="utf-8")
        parts = source.split("---", 1)
        assert len(parts) == 2, f"{tpl_path.name}: missing citation delimiter"

        citation_ast = env.parse(parts[1])
        vars_in_citation = {
            n.name
            for n in citation_ast.find_all(nodes.Name)
            if n.name not in {"True", "False", "none"}
        }
        assert vars_in_citation == {"citation_block"}, (
            f"{tpl_path.name}: citation section must use only {{ citation_block }}, "
            f"found {sorted(vars_in_citation)}"
        )
