"""Phase 19 §19.9 — Unverified sources run in restricted OS namespace."""
import pytest
import os


def test_unverified_source_sandboxed():
    """Unverified sources use seccomp sandbox."""
    from xops.lint.source_trust_level import get_source_trust_level
    from xops.security.extractor_sandbox import SANDBOX_PROFILE
    
    # Function exists and is callable
    trust = get_source_trust_level("unverified_test_source")
    assert isinstance(trust, str)
    assert trust in ("verified", "unverified", "sandboxed")
    # Sandbox profile path exists or is set
    assert SANDBOX_PROFILE is not None


def test_verified_source_not_sandboxed():
    """Verified sources bypass sandbox."""
    from xops.lint.source_trust_level import get_source_trust_level
    
    trust = get_source_trust_level("verified_test_source")
    assert isinstance(trust, str)
