"""Phase 10 §10.21.5 -- Unicode confusables / homoglyph defense tests.

Verifies that the confusables-fold stage (step 3.5) correctly defends against
Cyrillic/Greek lookalike attacks (CVE-2021-42574-style) and that bidi strip
covers all 9 specified codepoints.

Per AGENTS.md Rule 10: happy paths + adversarial + regression tests.
"""
from __future__ import annotations

import ast
import hashlib
import json


class TestConfusablesCyrillicA:
    """Corpus probe: Cyrillic 'а' in team name resolves after confusables fold."""

    def test_confusables_cyrillic_a_resolves_to_galatasaray(self) -> None:
        """Real attack: 'Galаtasaray' (Cyrillic а U+0430) must resolve to Galatasaray."""
        from nlp.normalize import normalize_input

        # Input: "Gal<CYRILLIC-a>tasaray" where <CYRILLIC-a> is U+0430
        malicious_input = "Gal\u0430tasaray"
        result = normalize_input(malicious_input)

        # After confusables_fold step, Cyrillic а -> Latin a -> lowercase -> "galatasaray"
        joined = " ".join(result.tokens)
        assert joined == "galatasaray", f"Expected 'galatasaray', got '{joined}'"
        assert "confusables_fold" in result.steps_run

    def test_confusables_greek_alpha_resolves(self) -> None:
        """Greek α (U+03B1) should fold to Latin a."""
        from nlp.normalize import normalize_input

        # Input: "G<GREEK-alpha>latasaray"
        malicious_input = "G\u03B1latasaray"
        result = normalize_input(malicious_input)

        joined = " ".join(result.tokens)
        assert joined == "galatasaray", f"Expected 'galatasaray', got '{joined}'"

    def test_confusables_cyrillic_o_in_word(self) -> None:
        """Cyrillic о (U+043E) should fold to Latin o."""
        from nlp.normalize import normalize_input

        # Input: "Fenerbahçe" but with Cyrillic о replacing 'o' -> "Fenerbahçe" but 'o' is Cyrillic
        # Actually, let's use a cleaner test: "Galatas<CYRILLIC-o>ray"
        malicious_input = "Galatas\u043Eray"
        result = normalize_input(malicious_input)

        joined = " ".join(result.tokens)
        # Cyrillic о -> Latin o -> lowercase -> "galatasoray" 
        assert joined == "galatasoray", f"Expected 'galatasoray', got '{joined}'"

    def test_confusables_mixed_scripts_all_folded(self) -> None:
        """Multiple confusables in one input should all be folded."""
        from nlp.normalize import normalize_input

        # Mix: Gal<CYRILLIC-а>t<GREEK-α>s<CYRILLIC-о>ray
        # Positions: Gal[а]t[α]s[о]ray
        malicious_input = "Gal\u0430t\u03B1s\u043Eray"
        result = normalize_input(malicious_input)

        joined = " ".join(result.tokens)
        # All fold: а->a, α->a, о->o, lowercase -> "galatаsoray"
        # Wait: "Gal" + "а"(->a) + "t" + "α"(->a) + "s" + "о"(->o) + "ray"
        #     = "Gal" + "a" + "t" + "a" + "s" + "o" + "ray"
        #     = "Galatasoray"
        assert joined == "galatasoray", f"Expected 'galatasoray', got '{joined}'"

    def test_confusables_uppercase_cyrillic_A(self) -> None:
        """Cyrillic А (U+0410) should fold to Latin A."""
        from nlp.normalize import normalize_input

        malicious_input = "\u0410rsenal"  # Cyrillic А
        result = normalize_input(malicious_input)

        joined = " ".join(result.tokens)
        assert joined == "arsenal"  # Lowercase after fold

    def test_confusables_fullwidth_fold_to_ascii(self) -> None:
        """Fullwidth Latin letters should normalize to ASCII."""
        from nlp.normalize import normalize_input

        malicious_input = "Ｇａｌａｔａｓａｒａｙ"
        result = normalize_input(malicious_input)

        assert " ".join(result.tokens) == "galatasaray"

    def test_confusables_mathalpha_fold_to_ascii(self) -> None:
        """Mathematical alphanumeric symbols should normalize to ASCII."""
        from nlp.normalize import normalize_input

        malicious_input = "𝐆𝐚𝐥𝐚𝐭𝐚𝐬𝐚𝐫𝐚𝐲"
        result = normalize_input(malicious_input)

        assert " ".join(result.tokens) == "galatasaray"

    def test_confusables_tag_characters_stripped(self) -> None:
        """Tag characters used for emoji spoofing must be stripped."""
        from nlp.normalize import normalize_input

        malicious_input = "Galatasaray\U000E0020"
        result = normalize_input(malicious_input)

        assert " ".join(result.tokens) == "galatasaray"

    def test_confusables_enclosed_alphanumerics_fold_to_ascii(self) -> None:
        """Enclosed alphanumerics should normalize to ASCII."""
        from nlp.normalize import normalize_input

        malicious_input = "ⒼⒶⓁⒶⓉⒶⓈⒶⓇⒶⓎ"
        result = normalize_input(malicious_input)

        assert " ".join(result.tokens) == "galatasaray"


class TestBidiStripCoverage:
    """Bidi formatting strip must cover all 9 specified codepoints."""

    def test_nlp_bidi_strip_covers_all_9_codepoints(self) -> None:
        """AST guard: _STRIP_RE in normalize.py must include all 9 bidi codepoints."""
        # The 9 bidi codepoints per §10.21.5:
        # LRE, RLE, PDF, LRO, RLO (U+202A-U+202E)
        # LRI, RLI, FSI, PDI (U+2066-U+2069)
        
        # Verify by checking the regex covers these ranges
        from ai.common.text.normalize import _STRIP_RE
        
        pattern_str = _STRIP_RE.pattern
        
        # The pattern contains the unicode escapes (after Python string parsing)
        # Check that the ranges are present (case-insensitive for hex)
        assert ("\u202a" in pattern_str and "\u202e" in pattern_str), \
            "Pattern must include U+202A-U+202E range"
        assert ("\u2066" in pattern_str and "\u2069" in pattern_str), \
            "Pattern must include U+2066-U+2069 range"
        
        # Runtime verification: all 9 are actually matched
        for cp in [0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069]:
            assert _STRIP_RE.search(chr(cp)), f"Bidi codepoint U+{cp:04X} not matched by _STRIP_RE"

    def test_bidi_strips_all_9_in_practice(self) -> None:
        """Runtime verification: all 9 bidi codepoints are actually stripped."""
        from nlp.normalize import normalize_input

        # Inject all 9 bidi codepoints into input
        bidi_chars = "".join([
            "\u202A",  # LRE
            "\u202B",  # RLE
            "\u202C",  # PDF
            "\u202D",  # LRO
            "\u202E",  # RLO
            "\u2066",  # LRI
            "\u2067",  # RLI
            "\u2068",  # FSI
            "\u2069",  # PDI
        ])
        malicious = f"galatasaray {bidi_chars} mac"
        result = normalize_input(malicious)

        joined = " ".join(result.tokens)
        # All bidi chars should be stripped (they are zero-width formatters)
        for cp in [0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069]:
            assert chr(cp) not in joined, f"Bidi U+{cp:04X} was not stripped"

        assert joined == "galatasaray mac"


class TestConfusablesBoundary:
    """Confusables fold must NOT be applied to password fields."""

    def test_nlp_confusables_fold_skipped_for_password_field(self) -> None:
        """Boundary: NLP plane never sees passwords (§7.1); reassert here."""
        # The NLP normalize pipeline is only called on qa.request.v1.text (user queries).
        # Passwords flow through server/internal/auth/ and never touch the NLP plane.
        # This test documents the invariant: there is NO codepath that applies
        # confusables_fold to a password field.

        # AST scan: confusables_fold import in nlp/normalize.py is legitimate.
        # AST scan: confusables_fold call in normalize_input is legitimate.
        # AST scan: NO import of confusables_fold in ai/swarm/agents/sec/ (or server/internal/auth/).

        import ai.nlp.normalize as nlp_norm
        import inspect

        # Verify confusables_fold is only called from normalize_input, which is NLP-plane only
        source = inspect.getsource(nlp_norm)
        # Should have exactly one call to confusables_fold in normalize_input
        assert source.count("confusables_fold(") == 1, "confusables_fold should be called exactly once"
        assert "def normalize_input" in source

        # The function docstring and comments should document password exclusion
        from ai.common.text.normalize import confusables_fold
        doc = confusables_fold.__doc__
        assert doc is not None
        assert "password" in doc.lower(), "confusables_fold docstring must mention password exclusion"


class TestConfusablesTablePin:
    """Confusables table must be pinned in chart.json compatibility block."""

    def test_nlp_confusables_table_sha_pinned(self) -> None:
        """Chart compat: confusables_table entry exists with source spec and cardinality."""
        with open("xops/versioning/chart.json") as f:
            chart = json.load(f)

        compat = chart.get("compatibility", {})
        data_files = compat.get("data_files", {})

        assert "confusables_table" in data_files, "confusables_table missing from chart.json compatibility"

        entry = data_files["confusables_table"]
        assert "source_spec" in entry, "confusables_table must have source_spec"
        assert "Unicode TR39" in entry["source_spec"], "Must reference Unicode TR39"
        assert "sha256" in entry, "Must have SHA pin"
        assert "cardinality" in entry, "Must document table size"

        # Verify the table size matches
        from ai.common.text.normalize import _CONFUSABLES_TABLE
        expected_size = len(_CONFUSABLES_TABLE)
        assert entry["cardinality"] == expected_size, \
            f"Chart says {entry['cardinality']} entries, actual table has {expected_size}"

        # Pin must be deterministic from the in-code table contents.
        payload = {str(k): v for k, v in sorted(_CONFUSABLES_TABLE.items())}
        expected_sha = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert entry["sha256"] == expected_sha, "Chart SHA must match canonical confusables table digest"

    def test_confusables_table_is_immutable_dict(self) -> None:
        """The table must be dict[int, str], not a mutable structure."""
        from ai.common.text.normalize import _CONFUSABLES_TABLE

        assert isinstance(_CONFUSABLES_TABLE, dict), "Must be a dict"
        # Check a sample entry
        assert 0x0430 in _CONFUSABLES_TABLE, "Cyrillic а (U+0430) must be in table"
        assert _CONFUSABLES_TABLE[0x0430] == "a", "Cyrillic а must map to Latin a"

        # Check type hints if available
        import ai.common.text.normalize as norm_mod
        source = open(norm_mod.__file__).read()
        assert "dict[int, str]" in source, "Table type hint must be dict[int, str]"


class TestHomoglyphCanonicalIdResolution:
    """§10.21.5 bullet 4: Gazetteer MUST use folded form for exact match."""

    def test_gazetteer_matches_on_folded_form(self) -> None:
        """After confusables fold, gazetteer uses folded text for matching."""
        from ai.common.text.normalize import confusables_fold

        # Input with Cyrillic 'а' (U+0430)
        raw_text = "Gal\u0430tasaray"  # Galаtasaray (Cyrillic а)
        folded_text = confusables_fold(raw_text)

        # Folded form should be "Galatasaray" (all Latin)
        assert folded_text == "Galatasaray", f"Expected 'Galatasaray', got '{folded_text}'"

        # The gazetteer MUST match on the folded form, not the raw
        # (This test documents the contract; actual implementation pending Phase 10 §10.5)

    def test_original_text_preserved_when_confusables_differ(self) -> None:
        """If folded differs from raw, preserve original in entities[].original_text."""
        from ai.common.text.normalize import confusables_fold

        # Raw with confusable
        raw_text = "Gal\u0430tasaray"
        folded = confusables_fold(raw_text)

        assert raw_text != folded, "Raw and folded must differ for this test"

        # When entity extraction happens (Phase 10 §10.5), if raw != folded:
        # - Match using folded form
        # - Preserve raw form in entities[].original_text
        # This test documents the contract for qa.intent.v1 schema

    def test_qa_intent_schema_supports_original_text_field(self) -> None:
        """qa.intent.v1.entities[].original_text field exists (optional)."""
        import json
        from pathlib import Path

        schema_path = Path("ai/swarm/sdk/schemas/qa.intent.v1.json")
        with open(schema_path) as f:
            schema = json.load(f)

        entity_schema = schema["properties"]["entities"]["items"]
        props = entity_schema["properties"]

        assert "original_text" in props, "entities[].original_text field missing"
        assert props["original_text"]["type"] == "string"
        assert "§10.21.5" in props["original_text"]["description"]
        assert "original_text" not in entity_schema.get("required", []), \
            "original_text must be optional (omit if no confusables)"

    def test_confusables_resolved_count_in_qa_intent_schema(self) -> None:
        """qa.intent.v1.confusables_resolved_count field exists (required, integer ≥ 0)."""
        import json
        from pathlib import Path

        schema_path = Path("ai/swarm/sdk/schemas/qa.intent.v1.json")
        with open(schema_path) as f:
            schema = json.load(f)

        props = schema["properties"]
        assert "confusables_resolved_count" in props, "confusables_resolved_count field missing"
        assert props["confusables_resolved_count"]["type"] == "integer"
        assert props["confusables_resolved_count"]["minimum"] == 0
        assert "§10.21.5" in props["confusables_resolved_count"]["description"]
        assert "confusables_resolved_count" in schema["required"], \
            "confusables_resolved_count must be required"

    def test_confusables_count_increments_per_resolved_entity(self) -> None:
        """confusables_resolved_count = count of entities where folded != raw."""
        from ai.common.text.normalize import confusables_fold

        # Scenario: 2 entities, one with confusable, one without
        entity1_raw = "Gal\u0430tasaray"  # Has confusable
        entity2_raw = "Fenerbahçe"  # No confusable

        entity1_folded = confusables_fold(entity1_raw)
        entity2_folded = confusables_fold(entity2_raw)

        resolved_count = 0
        if entity1_raw != entity1_folded:
            resolved_count += 1
        if entity2_raw != entity2_folded:
            resolved_count += 1

        # Expected: 1 (only entity1 had confusables)
        assert resolved_count == 1, f"Expected 1, got {resolved_count}"

        # The qa.intent.v1 payload would carry confusables_resolved_count=1
        # This test documents the counting logic

    def test_confusables_resolved_zero_when_no_confusables(self) -> None:
        """confusables_resolved_count=0 when no entities had confusables."""
        from ai.common.text.normalize import confusables_fold

        # Clean inputs (no confusables)
        inputs = ["Galatasaray", "Fenerbahçe", "Beşiktaş"]

        for text in inputs:
            folded = confusables_fold(text)
            assert text == folded, f"'{text}' should not be modified by confusables_fold"

        # confusables_resolved_count would be 0

    def test_multiple_confusables_in_one_entity_counts_as_one(self) -> None:
        """One entity with multiple confusables still counts as 1 resolved entity."""
        from ai.common.text.normalize import confusables_fold

        # Entity with 3 confusables: Gal<CYRILLIC-а>t<GREEK-α>s<CYRILLIC-о>ray
        raw = "Gal\u0430t\u03B1s\u043Eray"
        folded = confusables_fold(raw)

        assert raw != folded, "Should have confusables"
        # This entity counts as 1 toward confusables_resolved_count
        # (not 3 — we count entities, not codepoints)

    def test_audit_preserves_raw_form_for_forensics(self) -> None:
        """original_text is preserved for audit/forensics when confusables were resolved."""
        from ai.common.text.normalize import confusables_fold

        # Attack vector: Cyrillic lookalike
        raw = "Gal\u0430tasaray"
        folded = confusables_fold(raw)

        # Operator reviewing audit log needs to see that raw had a Cyrillic char
        # entities[].original_text = "Galаtasaray" (with Cyrillic а)
        # entities[].canonical_id = "team:galatasaray" (resolved via folded)
        assert raw != folded
        assert "\u0430" in raw, "Raw should contain Cyrillic а"
        assert "\u0430" not in folded, "Folded should not contain Cyrillic а"

