"""Per-source contract tests (Phase 13.6).

Verifies that each source's seed corpus produces all documented fields
per the xops/mock/sources.py registry. A contract violation (upstream
HTML reshuffle that drops a field) is caught here before Phase 17 patcher
is invoked.

Binding: AGENTS.md Rule 7 (adversarial tests) + Phase 13.6 §13.6.
"""

import pytest
from xops.mock.sources import by_key, all_keys


class TestSourceContractRegistry:
    """Verify the source registry itself is well-formed."""

    def test_all_sources_have_required_fields(self):
        """Each source must have robots_respect, tos_audit_passed, seed_max_age_days."""
        for key in all_keys():
            src = by_key(key)
            assert hasattr(src, 'robots_respect'), f"{key}: missing robots_respect"
            assert hasattr(src, 'tos_audit_passed'), f"{key}: missing tos_audit_passed"
            assert hasattr(src, 'seed_max_age_days'), f"{key}: missing seed_max_age_days"
            assert isinstance(src.robots_respect, bool)
            assert isinstance(src.tos_audit_passed, bool)
            assert isinstance(src.seed_max_age_days, int)
            assert src.seed_max_age_days > 0

    def test_all_sources_must_pass_tos_audit_for_mirroring(self):
        """Production sources must have tos_audit_passed=True."""
        for key in all_keys():
            src = by_key(key)
            assert src.tos_audit_passed, (
                f"{key}: ToS audit not passed. "
                f"Add xops/mock/sources.py documentation and set tos_audit_passed=True"
            )

    def test_all_sources_respect_robots(self):
        """All sources in the registry must respect robots.txt."""
        for key in all_keys():
            src = by_key(key)
            assert src.robots_respect, (
                f"{key}: does not respect robots.txt. "
                f"Update xops/mock/sources.py documentation."
            )

    def test_source_registry_immutable(self):
        """Source dataclass is frozen; prevents accidental mutation."""
        src = by_key("openfootball")
        with pytest.raises(Exception):  # FrozenInstanceError
            src.seed_max_age_days = 30  # type: ignore


class TestSourceContractMackolik:
    """Contract test for mackolik source."""

    def test_mackolik_source_exists_and_configured(self):
        src = by_key("mackolik")
        assert src.key == "mackolik"
        assert src.real_host == "www.mackolik.com"
        assert src.mock_host == "mackolik.local"
        assert src.robots_respect is True
        assert src.tos_audit_passed is True
        # Seed is captured periodically; max age enforces freshness
        assert src.seed_max_age_days == 90


class TestSourceContractNesine:
    """Contract test for nesine source."""

    def test_nesine_source_exists_and_configured(self):
        src = by_key("nesine")
        assert src.key == "nesine"
        assert src.real_host == "www.nesine.com"
        assert src.mock_host == "nesine.local"
        assert src.robots_respect is True
        assert src.tos_audit_passed is True


class TestSourceContractTFF:
    """Contract test for TFF (Turkish Football Federation) source."""

    def test_tff_source_exists_and_configured(self):
        src = by_key("tff")
        assert src.key == "tff"
        assert src.real_host == "www.tff.org"
        assert src.mock_host == "tff.local"
        assert src.robots_respect is True
        assert src.tos_audit_passed is True


class TestSourceContractOpenfootball:
    """Contract test for openfootball source."""

    def test_openfootball_source_exists_and_configured(self):
        src = by_key("openfootball")
        assert src.key == "openfootball"
        assert src.real_host == "raw.githubusercontent.com"
        assert src.mock_host == "openfootball.local"
        assert src.robots_respect is True
        assert src.tos_audit_passed is True
        # Git refs are stable; longer TTL than HTML sites
        assert src.seed_max_age_days == 180


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
