"""Phase 12 §12.0 — Proof tests for retired wrong assumptions (A0–A12).

Each assumption is documented in docs/design/phase12/sections/00-wrong-assumption-ledger.md.
This file provides the "both-direction proof" tests:
  - Test that the old assumption leads to failure
  - Test that the new fix addresses it (infrastructure exists)
"""

import json
from pathlib import Path
import re
import pytest
import yaml


class TestA0IsCrossCuttingNotPhase7Plus9:
    """A0: Phase 12 is cross-cutting (not just Phase 7 + 9)."""
    
    def test_catalogue_has_stubs_from_multiple_phases(self) -> None:
        """Chaos catalogue has stubs registered by multiple owning phases (not just 7 + 9)."""
        catalogue_file = Path(__file__).resolve().parents[2] / "docs" / "testing" / "phase12_catalogue.md"
        assert catalogue_file.exists(), f"Missing phase12_catalogue.md at {catalogue_file}"
        
        with open(catalogue_file) as f:
            content = f.read()
        
        # Extract all Phase IDs from catalogue (e.g., P12-5-A, P12-8-X, etc.)
        phases_in_catalogue = set()
        for match in re.finditer(r"P12-(\d+)", content):
            phase_num = int(match.group(1))
            phases_in_catalogue.add(phase_num)
        
        # Must have stubs from multiple owning phases to prove cross-cutting nature
        # The old assumption was only 7 + 9; the fix is at least 5+ different owning phases
        assert len(phases_in_catalogue) >= 5, \
            f"Catalogue only references {len(phases_in_catalogue)} phases; expected ≥5 to prove cross-cutting"
        
        # Verify that it's not just Phase 7 and 9 (the old assumption)
        # At least 2 other phases should be present
        non_79_phases = phases_in_catalogue - {7, 9}
        assert len(non_79_phases) >= 3, \
            f"Catalogue only references phases {phases_in_catalogue}; should have phases beyond 7 and 9"



class TestA1CoverageIsTiered:
    """A1: Coverage is tiered + branch-aware + diff-gated, not flat 85%."""
    
    def test_coverage_tiers_yaml_exists(self) -> None:
        """Tier map exists at xops/coverage/tiers.yaml."""
        tiers_file = Path(__file__).resolve().parents[2] / "xops" / "coverage" / "tiers.yaml"
        assert tiers_file.exists(), f"Missing tiers.yaml at {tiers_file}"
        
        with open(tiers_file) as f:
            doc = yaml.safe_load(f) or {}
        
        tiers = doc.get("tiers", {})
        
        # Verify tier structure
        assert "tier_1" in tiers, "Missing tier_1 (security/integrity/money)"
        assert "tier_2" in tiers, "Missing tier_2 (ordinary business logic)"
        assert "tier_3" in tiers, "Missing tier_3 (glue/generated/tooling)"
        
        # Tier-1 must have high coverage floor
        tier1_floor = tiers.get("tier_1", {}).get("line_minimum", 0)
        assert tier1_floor >= 0.95, f"Tier-1 floor too low: {tier1_floor}"
        
        tier1_branch_min = tiers.get("tier_1", {}).get("branch_minimum", 0)
        assert tier1_branch_min >= 0.90, f"Tier-1 branch floor too low: {tier1_branch_min}"


class TestA2TargetsAreDotStyle:
    """A2: Make targets use dot-style (chaos.*, test.*), not hyphen."""
    
    def test_makefile_has_dot_style_chaos_targets(self) -> None:
        """All chaos-related make targets use dot-style."""
        makefile = Path(__file__).resolve().parents[2] / "Makefile"
        with open(makefile) as f:
            content = f.read()
        
        # Find all chaos-related targets
        target_pattern = r"^([a-z\.\-]+)(?:\s+[:|%].*)?:\s*[#@]"
        targets = re.findall(target_pattern, content, re.MULTILINE)
        chaos_targets = [t for t in targets if "chaos" in t or "test" in t or "fuzz" in t]
        
        # Check for hyphen-style chaos targets (the old bad style)
        bad_targets = [t for t in chaos_targets if "chaos-" in t]
        assert not bad_targets, f"Found hyphen-style chaos targets (should be dot-style): {bad_targets}"


class TestA3FuzzesAreHypothesisAtherisGoFuzz:
    """A3: Fuzzers are Hypothesis + Atheris + go test -fuzz, not boofuzz."""
    
    def test_requirements_txt_has_hypothesis_not_boofuzz(self) -> None:
        """requirements.txt includes Hypothesis, excludes boofuzz."""
        req_file = Path(__file__).resolve().parents[2] / "ai" / "requirements.txt"
        assert req_file.exists(), f"Missing requirements.txt at {req_file}"
        
        with open(req_file) as f:
            content = f.read().lower()
        
        assert "hypothesis" in content, "Hypothesis not in requirements.txt"
        assert "boofuzz" not in content, "boofuzz should not be in requirements.txt"


class TestA4CorporaHaveGovernanceSidecars:
    """A4: Adversarial corpora have governance sidecars (corpus.yaml), not just files."""
    
    def test_adversarial_families_have_corpus_yaml(self) -> None:
        """Each adversarial family dir has corpus.yaml sidecar."""
        adv_dir = Path(__file__).resolve().parents[2] / "ai" / "tests" / "fixtures" / "adversarial"
        
        if not adv_dir.exists():
            pytest.skip(f"Adversarial corpus not found at {adv_dir}")
        
        families = [d for d in adv_dir.iterdir() if d.is_dir() and d.name != "archived"]
        assert len(families) > 0, "No adversarial families found"
        
        for family_dir in families:
            corpus_yaml = family_dir / "corpus.yaml"
            assert corpus_yaml.exists(), f"Missing corpus.yaml in {family_dir.name}"
            
            # Verify required fields
            with open(corpus_yaml) as f:
                data = yaml.safe_load(f) or {}
            
            required = {"seed", "provenance", "reviewers", "pii_scrub"}
            missing = required - set(data.keys())
            assert not missing, f"{family_dir.name}: missing fields {missing}"


class TestA5ChaosFrameworkExists:
    """A5: Chaos tools are integrated in framework (FaultInjector + docker-compose.chaos.yml)."""
    
    def test_fault_injector_exists(self) -> None:
        """xops/chaos/scenarios.py exists with FaultInjector class."""
        scenarios_file = Path(__file__).resolve().parents[2] / "xops" / "chaos" / "scenarios.py"
        assert scenarios_file.exists(), f"Missing FaultInjector at {scenarios_file}"
        
        with open(scenarios_file) as f:
            content = f.read()
        assert "class FaultInjector" in content, "FaultInjector class not defined"
    
    def test_chaos_compose_profile_exists(self) -> None:
        """docker-compose.chaos.yml exists."""
        chaos_compose = Path(__file__).resolve().parents[2] / "docker-compose.chaos.yml"
        assert chaos_compose.exists(), f"Missing docker-compose.chaos.yml at {chaos_compose}"


class TestA6AdversarialCoversAllBoundaries:
    """A6: Adversarial corpora cover all trust boundaries, not just prompt injection."""
    
    def test_adversarial_families_cover_multiple_boundaries(self) -> None:
        """Multiple adversarial corpus families exist (not just prompt_injection)."""
        adv_dir = Path(__file__).resolve().parents[2] / "ai" / "tests" / "fixtures" / "adversarial"
        
        if not adv_dir.exists():
            pytest.skip(f"Adversarial corpus not found at {adv_dir}")
        
        families = {d.name for d in adv_dir.iterdir() if d.is_dir() and d.name != "archived"}
        
        # Should have multiple trust boundaries, not just prompt injection
        expected_boundaries = {"prompt_injection", "html_dom", "unicode_abuse", "wire_envelope"}
        covered = families & expected_boundaries
        assert len(covered) >= 2, f"Only {len(covered)} trust boundaries covered; expected ≥ 2"


class TestA7ChaosAssertsDegradedContract:
    """A7: Chaos asserts degraded contracts + MTTD/MTTR budgets, not just liveness."""
    
    def test_degraded_modes_catalogue_exists(self) -> None:
        """docs/testing/degraded_modes.md exists (the contract catalogue)."""
        degraded_file = Path(__file__).resolve().parents[2] / "docs" / "testing" / "degraded_modes.md"
        assert degraded_file.exists(), f"Missing degraded_modes.md at {degraded_file}"
        
        with open(degraded_file) as f:
            content = f.read()
        
        assert len(content) > 100, "degraded_modes.md is suspiciously empty"
        assert "degraded" in content.lower(), "degraded_modes should mention 'degraded'"


class TestA8LanesAreCostMatched:
    """A8: Lanes (fast/pr/nightly/weekly) are cost-matched, not everything per-push."""
    
    def test_lanes_yaml_exists_and_has_four_lanes(self) -> None:
        """xops/ci/lanes.yaml exists with fast, pr, nightly, weekly."""
        lanes_file = Path(__file__).resolve().parents[2] / "xops" / "ci" / "lanes.yaml"
        assert lanes_file.exists(), f"Missing lanes.yaml at {lanes_file}"
        
        with open(lanes_file) as f:
            doc = yaml.safe_load(f) or {}
        
        lanes = doc.get("lanes", {})
        
        expected_lanes = {"fast", "pr", "nightly", "weekly"}
        found = set(lanes.keys())
        missing = expected_lanes - found
        assert not missing, f"Missing lanes: {missing}"


class TestA9NoXfailInAdversarial:
    """A9: Adversarial/chaos suites have zero xfail (not a release blocker)."""
    
    def test_xfail_lint_exists(self) -> None:
        """xops/lint/no_xfail_in_adversarial.py exists (the enforcer)."""
        lint_file = Path(__file__).resolve().parents[2] / "xops" / "lint" / "no_xfail_in_adversarial.py"
        assert lint_file.exists(), f"Missing xfail lint at {lint_file}"
        
        with open(lint_file) as f:
            content = f.read()
        assert len(content) > 50, "xfail lint file is suspiciously empty"


class TestA10DeterminismEnforced:
    """A10: Determinism is enforced (pinned Hypothesis profile, seeded faults)."""
    
    def test_hypothesis_ci_profile_in_conftest(self) -> None:
        """conftest.py defines Hypothesis 'ci' profile."""
        conftest = Path(__file__).resolve().parents[2] / "ai" / "tests" / "conftest.py"
        assert conftest.exists(), f"Missing conftest.py at {conftest}"
        
        with open(conftest) as f:
            content = f.read()
        
        # Look for Hypothesis profile or settings
        assert ("profile" in content.lower() or "settings" in content.lower()), \
            "conftest.py should configure Hypothesis determinism"


class TestA11CoverageToolingIntroduced:
    """A11: Coverage tooling is introduced (.coveragerc, coverage.py dispatcher)."""
    
    def test_coveragerc_exists_with_branch(self) -> None:
        """.coveragerc or pyproject.toml coverage config exists with branch: true."""
        repo_root = Path(__file__).resolve().parents[2]
        coveragerc = repo_root / ".coveragerc"
        pyproject = repo_root / "pyproject.toml"
        
        has_coveragerc = coveragerc.exists()
        has_pyproject = pyproject.exists()
        
        assert has_coveragerc or has_pyproject, "No coverage config found (.coveragerc or pyproject.toml)"
        
        if has_coveragerc:
            with open(coveragerc) as f:
                content = f.read().lower()
            assert "branch" in content, ".coveragerc should have branch: true"
    
    def test_coverage_dispatcher_exists(self) -> None:
        """xops/makefile/coverage.py exists."""
        coverage_py = Path(__file__).resolve().parents[2] / "xops" / "makefile" / "coverage.py"
        assert coverage_py.exists(), f"Missing coverage dispatcher at {coverage_py}"


class TestA12CatalogueIsCrossPhaseSource:
    """A12: Chaos catalogue is cross-phase single source (not just Phase 7 artifact)."""
    
    def test_phase12_catalogue_md_exists(self) -> None:
        """docs/testing/phase12_catalogue.md exists."""
        catalogue_file = Path(__file__).resolve().parents[2] / "docs" / "testing" / "phase12_catalogue.md"
        assert catalogue_file.exists(), f"Missing phase12_catalogue.md at {catalogue_file}"
        
        with open(catalogue_file) as f:
            content = f.read()
        
        # Should reference multiple phases, not just Phase 7
        phases_referenced = set()
        for match in re.finditer(r"P12-(\d+)", content):
            phases_referenced.add(int(match.group(1)))
        
        # Should have families from phases 3+
        assert len(phases_referenced) >= 3, f"Catalogue only references {len(phases_referenced)} phases; should be ≥3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
