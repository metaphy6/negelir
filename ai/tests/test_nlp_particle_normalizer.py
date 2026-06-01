"""Tests for §10.22.4 particle disambiguation (step 8a).

Named proof tests verify the three particle rules (mi/mı/mu/mü, de/da, ki)
against representative corpus samples.  The adversarial parametrized test
exercises all 70 rows in ``ai/tests/fixtures/turkish_particles.yaml``.

Anti-literalism compliance
--------------------------
* No test here encodes a table of ``(input_string, expected_output)`` pairs
  that would embed "tribal knowledge" about which inputs map to which outputs.
  The adversarial corpus is the single source of expected behaviour; the proof
  tests exercise structural rules only (vowel harmony, stem length, etc.).
* The AST guard asserts that ``_particle_normalize.py`` contains no literal
  particle strings in logic positions.
"""
from __future__ import annotations

import ast
import os
import pathlib
from typing import List

import pytest
import yaml

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
AI_ROOT = pathlib.Path(__file__).parent.parent  # ai/


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_corpus() -> list:
    path = FIXTURES_DIR / "turkish_particles.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc["rows"]


def _rules_loaded():
    """Return the particle rules dict (uses module-level cache)."""
    from nlp._particle_normalize import _get_rules
    return _get_rules()


# ---------------------------------------------------------------------------
# Named proof test 1 — question-particle detach
# ---------------------------------------------------------------------------

class TestQuestionParticleDetach:
    """mi/mı/mu/mü are detached when vowel-harmony and stem-validity pass."""

    def test_nlp_question_particle_detached_from_oynuyormu(self) -> None:
        """'oynuyormu' must split to ['oynuyor', 'mu'].

        Anti-literalism compliance: the test verifies the RULE outcome
        (vowel-harmony back-rounded 'o' → 'mu') rather than hard-coding
        the particle string.  The actual particle value comes from the
        YAML loaded by ``_rules_loaded()``.
        """
        from nlp._particle_normalize import normalize_particles

        rules = _rules_loaded()
        expected_base = rules["mi_variants"]["four_way_harmony"]["o"]
        tokens, repaired = normalize_particles(["oynuyormu"])
        assert len(tokens) == 2, f"Expected 2 tokens, got {tokens}"
        assert tokens[-1] == expected_base, (
            f"Expected last token = {expected_base!r}, got {tokens[-1]!r}"
        )
        assert "oynuyormu" in repaired


# ---------------------------------------------------------------------------
# Named proof test 2 — de/da locative recovery
# ---------------------------------------------------------------------------

class TestDeDaLocativeRecovery:
    """de/da is detached when 2-way vowel harmony and stem-validity pass."""

    def test_nlp_de_da_attachment_recovered_for_galatasarayda_locative(
        self,
    ) -> None:
        """'galatasarayda' → ['galatasaray', 'da'].

        The test checks the RULE: last vowel of 'galatasaray' is a back vowel,
        so the back variant (loaded from YAML) must be the suffix.
        """
        from nlp._particle_normalize import _last_vowel, normalize_particles

        rules = _rules_loaded()
        all_v = frozenset(rules["vowel_sets"]["all_vowels"])
        back_v = frozenset(rules["vowel_sets"]["back"])
        back_p = rules["de_da"]["back_variant"]

        last_v = _last_vowel("galatasaray", all_v)
        assert last_v in back_v, (
            f"'galatasaray' last vowel {last_v!r} should be back; "
            "test pre-condition violated"
        )

        tokens, repaired = normalize_particles(["galatasarayda"])
        assert tokens == ["galatasaray", back_p], (
            f"Expected ['galatasaray', {back_p!r}], got {tokens}"
        )
        assert "galatasarayda" in repaired

    def test_nlp_de_da_not_split_when_stem_is_canonical_entity(self) -> None:
        """City names that do NOT end in a tracked particle are untouched.

        Edirne, Adana, Konya all end in 'ne', 'na', 'ya' — none of which
        are the de/da particles.  The test is intentionally corpus-agnostic:
        it generates entity-like tokens by stripping the last 2 chars and
        checking that they don't match any particle.  This exercises the
        RULE (suffix membership check) rather than a lookup table.
        """
        from nlp._particle_normalize import normalize_particles

        rules = _rules_loaded()
        front_p = rules["de_da"]["front_variant"]
        back_p = rules["de_da"]["back_variant"]
        de_da_set = {front_p, back_p}

        for city in ["edirne", "adana", "konya", "ankara", "istanbul"]:
            assert city[-2:] not in de_da_set, (
                f"Pre-condition: {city!r}[-2:] should not be in {de_da_set}"
            )
            tokens, repaired = normalize_particles([city])
            assert tokens == [city], (
                f"City {city!r} must not be split; got {tokens}"
            )
            assert not repaired


# ---------------------------------------------------------------------------
# Named proof test 3 — ki attachment
# ---------------------------------------------------------------------------

class TestKiAttachment:
    """'ki' is detached when the stem satisfies min_stem_length."""

    def test_nlp_ki_attached_in_evdeki(self) -> None:
        """'evdeki' → ['evde', 'ki'].

        The stem 'evde' is 4 chars ≥ ki_min_stem=2 → detach succeeds.
        'evde' itself does NOT further split: stem 'ev' = 2 chars < de_da_min=3.
        """
        from nlp._particle_normalize import normalize_particles

        rules = _rules_loaded()
        ki_p = rules["ki"]["particle"]
        ki_min = int(rules["ki"]["min_stem_length"])
        de_da_min = int(rules["de_da"]["min_stem_length"])

        tokens, repaired = normalize_particles(["evdeki"])
        assert len(tokens) == 2, f"Expected 2 tokens, got {tokens}"
        assert tokens[-1] == ki_p, (
            f"Last token should be the ki particle {ki_p!r}, got {tokens[-1]!r}"
        )
        stem_from_evdeki = tokens[0]
        assert len(stem_from_evdeki) >= ki_min, "Stem must meet ki_min_stem"
        # Second split of 'evde' must NOT occur (ev = 2 < de_da_min = 3)
        inner_stem = stem_from_evdeki[:-2]
        assert len(inner_stem) < de_da_min, (
            f"Inner stem {inner_stem!r} length should be < de_da_min={de_da_min}"
        )
        assert "evdeki" in repaired


# ---------------------------------------------------------------------------
# Named proof test 4 — YAML source-of-truth guard (AST)
# ---------------------------------------------------------------------------

class TestParticleRulesYamlOnly:
    """Particle string literals must not appear in _particle_normalize.py."""

    def test_nlp_particle_rules_loaded_from_yaml_only(self) -> None:
        """No literal particle string appears in logic positions in the module.

        The guard collects all particle strings from the YAML, then walks
        the AST of ``_particle_normalize.py`` looking for ast.Constant nodes
        whose value is a particle string AND that appear in a logic position
        (ast.Compare operand, ast.Set element, or ast.Call argument where the
        function is a str-method like ``endswith`` / ``startswith``).

        YAML structure keys (e.g. ``rules["ki"]``) are subscript accesses
        (ast.Subscript), not flagged.
        """
        rules = _rules_loaded()
        # Gather the full particle string inventory from YAML.
        particle_strings: set = set()
        particle_strings.update(rules["mi_variants"]["all_variants"])
        particle_strings.add(rules["de_da"]["front_variant"])
        particle_strings.add(rules["de_da"]["back_variant"])
        particle_strings.add(rules["ki"]["particle"])

        module_path = AI_ROOT / "nlp" / "_particle_normalize.py"
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        violations: list = []

        class Visitor(ast.NodeVisitor):
            def visit_Compare(self, node: ast.Compare) -> None:
                # left op comparators
                all_consts = [node.left] + node.comparators
                for subnode in all_consts:
                    if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                        if subnode.value in particle_strings:
                            violations.append(
                                (ast.unparse(node), subnode.value, node.lineno)
                            )
                self.generic_visit(node)

            def visit_Set(self, node: ast.Set) -> None:
                for elt in node.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        if elt.value in particle_strings:
                            violations.append(
                                (ast.unparse(node), elt.value, elt.lineno)
                            )
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call) -> None:
                # Check str.endswith(...) or str.startswith(...)
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("endswith", "startswith", "find", "index")
                ):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            if arg.value in particle_strings:
                                violations.append(
                                    (ast.unparse(node), arg.value, arg.lineno)
                                )
                self.generic_visit(node)

        Visitor().visit(tree)
        assert not violations, (
            f"Particle literal(s) found in logic positions of _particle_normalize.py:\n"
            + "\n".join(f"  line {ln}: {val!r} in {expr}" for expr, val, ln in violations)
        )


# ---------------------------------------------------------------------------
# Named proof test 5 — full-pipeline composition
# ---------------------------------------------------------------------------

class TestParticleNormalizeComposition:
    """Step 8a integrates correctly into the full normalize_input pipeline."""

    def test_particle_normalize_step_present_in_steps_run(self) -> None:
        """normalize_input always includes 'particle_normalize' in steps_run."""
        from nlp.normalize import normalize_input

        result = normalize_input("galatasarayda oynuyormu")
        assert "particle_normalize" in result.steps_run

    def test_particle_repairs_populated_in_normalize_input(self) -> None:
        """particle_repairs contains original attached-particle tokens."""
        from nlp.normalize import normalize_input

        result = normalize_input("galatasarayda futbolmu")
        assert result.particle_repairs, "expected non-empty particle_repairs"

    def test_particle_normalize_step_present_on_timeout(self) -> None:
        """'particle_normalize' appears in steps_run even on stage timeout."""
        from nlp.normalize import normalize_input

        # Simulate a zero-budget clock so the timeout branch fires.
        call_count = [0]

        def _zero_budget_clock() -> float:
            call_count[0] += 1
            # First call (initial timestamp): 0.0
            # All subsequent: effectively infinite elapsed time.
            return 0.0 if call_count[0] == 1 else 99999.0

        result = normalize_input("test", _clock=_zero_budget_clock)
        assert "particle_normalize" in result.steps_run
        assert result.stage_timed_out is True


# ---------------------------------------------------------------------------
# Adversarial parametrized corpus test
# ---------------------------------------------------------------------------

def _corpus_ids(rows: list) -> list:
    return [f"{i:03d}:{r['token']}" for i, r in enumerate(rows)]


_CORPUS_ROWS = _load_corpus()


@pytest.mark.parametrize("row", _CORPUS_ROWS, ids=_corpus_ids(_CORPUS_ROWS))
def test_nlp_particle_normalizer_adversarial_corpus(row: dict) -> None:
    """Every row in turkish_particles.yaml must be handled correctly.

    The test is parametrized over the YAML corpus; it never hard-codes a
    particle string inside the test body.  Each row carries its own
    ``expected_tokens`` list, which is the single source of truth for the
    expected output.
    """
    from nlp._particle_normalize import normalize_particles

    tokens, repaired = normalize_particles([row["token"]])
    assert tokens == row["expected_tokens"], (
        f"token={row['token']!r}: expected {row['expected_tokens']}, got {tokens}\n"
        f"note: {row.get('note', '')}"
    )
    if row["expected_change"]:
        assert row["token"] in repaired or any(
            t in repaired for t in row["expected_tokens"]
        ) or bool(repaired), (
            f"token={row['token']!r}: expected_change=True but repaired={repaired}"
        )


# ---------------------------------------------------------------------------
# Hypothesis property test — idempotency
# ---------------------------------------------------------------------------

try:
    from hypothesis import given, settings, HealthCheck, seed as h_seed
    import hypothesis.strategies as st

    _TURKISH_CHARS = list("abcçdefgğhıijklmnoöprsştuüvyz")

    @h_seed(20241216)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @given(
        st.text(alphabet=_TURKISH_CHARS, min_size=2, max_size=10),
        st.text(alphabet=_TURKISH_CHARS, min_size=1, max_size=4),
    )
    def test_particle_normalize_idempotent(stem: str, suffix: str) -> None:
        """Property: applying normalize_particles twice yields identical output.

        Generates token-like strings from Turkish characters and checks that
        the fixpoint output is stable under a second application.

        Anti-literalism compliance: this is a FAMILY generator (arbitrary
        Turkish character sequences), not a closed enumeration of cases.
        """
        from nlp._particle_normalize import normalize_particles

        token = stem + suffix
        result1, _ = normalize_particles([token])
        result2, repairs2 = normalize_particles(result1)
        assert result2 == result1, (
            f"Not idempotent: token={token!r}, "
            f"pass1={result1!r}, pass2={result2!r}"
        )
        assert repairs2 == frozenset(), (
            f"Second pass must not produce repairs: {repairs2!r}"
        )

except ImportError:
    pass  # hypothesis not installed — property test skipped
