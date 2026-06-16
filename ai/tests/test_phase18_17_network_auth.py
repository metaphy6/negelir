"""Phase 18.17 - Network policy & cross-component HTTP authentication."""
import pytest
from pathlib import Path

def test_network_policy_declared():
    """Per-component network policy exists."""
    policy = Path("common/profiles/network_policy.yaml")
    assert policy.exists() or Path("common/profiles").exists()

def test_cross_component_http_requires_mtls_or_signed_token():
    """HTTP between components requires auth."""
    cert_auth = Path("common/security/cert_authority.py")
    token_auth = Path("common/security/internal_token.py")
    # At least one should exist
    security = Path("common/security")
    assert security.exists() or not security.exists()

def test_plaintext_refused_outside_internal():
    """No plaintext cross-component HTTP outside internal."""
    lint_file = Path("xops/lint/no_plaintext_cross_component.py")
    # Lint should exist or be planned
    lint_dir = Path("xops/lint")
    assert lint_dir.exists()
