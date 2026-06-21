"""Phase 10 §10.21.6 bullet 2 — Runtime guard blocks raw user text in templates.

Tests the custom Jinja2 Environment.finalize callable that asserts no rendered
string slot equals the original qa.request.v1.text substring (length ≥ 6).
This is defense-in-depth: the AST lint should catch these cases at build time.
"""
import tempfile
from pathlib import Path

import pytest

from nlp.render import RawUserTextInTemplateError, build_environment


def test_nlp_template_finalize_blocks_raw_user_substring():
    """§10.21.6: finalize rejects render when slot contains user text."""
    # Setup: create a minimal template that renders a slot
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpl_path = Path(tmpdir) / "test.tr.j2"
        tmpl_path.write_text("Sonuç: {{ result }}")
        
        # User asks: "Galatasaray bugün ne zaman oynuyor?"
        user_text = "Galatasaray bugün ne zaman oynuyor?"
        
        # Guard enabled: build environment with user text
        env = build_environment(template_dir=tmpdir, user_text_for_guard=user_text)
        tmpl = env.get_template("test.tr.j2")
        
        # Case 1: Rendered slot contains the raw user input → blocked
        with pytest.raises(RawUserTextInTemplateError) as exc_info:
            tmpl.render(result=user_text)
        
        assert "raw user input substring" in str(exc_info.value).lower()
        assert exc_info.value.matched_substring == user_text[:100]
        assert exc_info.value.original_text == user_text[:100]
        
        # Case 2: Rendered slot contains a substring (≥ 6 chars) → blocked
        with pytest.raises(RawUserTextInTemplateError):
            tmpl.render(result="Galatasaray bugün")
        
        # Case 3: Rendered slot is safe (canonical entity) → allowed
        safe_result = tmpl.render(result="Galatasaray Spor Kulübü")
        assert "Galatasaray Spor Kulübü" in safe_result


def test_nlp_template_finalize_guard_disabled_when_no_user_text():
    """§10.21.6: guard is disabled when user_text_for_guard=None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpl_path = Path(tmpdir) / "test.tr.j2"
        tmpl_path.write_text("Sonuç: {{ result }}")
        
        # No user text provided → guard is off
        env = build_environment(template_dir=tmpdir, user_text_for_guard=None)
        tmpl = env.get_template("test.tr.j2")
        
        # Even raw user input passes (guard is disabled in test/dev mode)
        result = tmpl.render(result="Galatasaray bugün ne zaman oynuyor?")
        assert "Galatasaray bugün" in result


def test_nlp_template_finalize_guard_case_insensitive():
    """§10.21.6: guard checks case-insensitively to catch variants."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpl_path = Path(tmpdir) / "test.tr.j2"
        tmpl_path.write_text("Sonuç: {{ result }}")
        
        user_text = "Galatasaray maçı"
        env = build_environment(template_dir=tmpdir, user_text_for_guard=user_text)
        tmpl = env.get_template("test.tr.j2")
        
        # Upper/lowercase variants still blocked (note: Turkish İ/I handled by casefold)
        # Using correct Turkish characters: Maçı → MAÇI requires İ (capital I with dot)
        with pytest.raises(RawUserTextInTemplateError):
            tmpl.render(result="Galatasaray Maçı")  # exact match, different case
        
        with pytest.raises(RawUserTextInTemplateError):
            tmpl.render(result="galatasaray maçı")  # all lowercase


def test_nlp_template_finalize_guard_respects_min_length():
    """§10.21.6: guard only checks substrings ≥ cfg.nlp_template_finalize_min_user_text_len."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpl_path = Path(tmpdir) / "test.tr.j2"
        tmpl_path.write_text("Sonuç: {{ result }}")
        
        # User text shorter than min_len (default 6) → guard skips check
        short_user_text = "maç"
        env = build_environment(template_dir=tmpdir, user_text_for_guard=short_user_text)
        tmpl = env.get_template("test.tr.j2")
        
        # No exception even though result contains user text (too short to check)
        result = tmpl.render(result="maç sonucu")
        assert "maç" in result


def test_nlp_template_finalize_guard_ignores_non_strings():
    """§10.21.6: finalize guard only checks string values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpl_path = Path(tmpdir) / "test.tr.j2"
        tmpl_path.write_text("Skor: {{ home_score }} - {{ away_score }}")
        
        user_text = "Galatasaray bugün kaç kaç kazandı?"
        env = build_environment(template_dir=tmpdir, user_text_for_guard=user_text)
        tmpl = env.get_template("test.tr.j2")
        
        # Integer slots pass through without error
        result = tmpl.render(home_score=3, away_score=1)
        assert "3 - 1" in result


def test_nlp_template_finalize_exception_message_truncated():
    """§10.21.6: exception message truncates long strings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpl_path = Path(tmpdir) / "test.tr.j2"
        tmpl_path.write_text("{{ result }}")
        
        # Very long user text
        long_user_text = "Galatasaray " * 50  # 600+ chars
        env = build_environment(template_dir=tmpdir, user_text_for_guard=long_user_text)
        tmpl = env.get_template("test.tr.j2")
        
        with pytest.raises(RawUserTextInTemplateError) as exc_info:
            tmpl.render(result=long_user_text)
        
        # Exception truncates matched_substring and original_text to 100 chars
        assert len(exc_info.value.matched_substring) <= 100
        assert len(exc_info.value.original_text) <= 100


if __name__ == "__main__":
    test_nlp_template_finalize_blocks_raw_user_substring()
    print("✓ test_nlp_template_finalize_blocks_raw_user_substring passed")
    
    test_nlp_template_finalize_guard_disabled_when_no_user_text()
    print("✓ test_nlp_template_finalize_guard_disabled_when_no_user_text passed")
    
    test_nlp_template_finalize_guard_case_insensitive()
    print("✓ test_nlp_template_finalize_guard_case_insensitive passed")
    
    test_nlp_template_finalize_guard_respects_min_length()
    print("✓ test_nlp_template_finalize_guard_respects_min_length passed")
    
    test_nlp_template_finalize_guard_ignores_non_strings()
    print("✓ test_nlp_template_finalize_guard_ignores_non_strings passed")
    
    test_nlp_template_finalize_exception_message_truncated()
    print("✓ test_nlp_template_finalize_exception_message_truncated passed")
    
    print("\nAll §10.21.6 finalize guard tests passed!")
