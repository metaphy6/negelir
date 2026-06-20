"""Phase 19 §19.9 — SSRF protection blocks non-mock URLs."""
import pytest


def test_ssrf_blocked_on_non_mock_source_url():
    """Non-mock URLs trigger SSRFRiskError."""
    from ai.common.security.input_sanitiser import sanitise_source_url, SSRFRiskError
    
    danger = "https://internal.company.local/api"
    with pytest.raises(SSRFRiskError):
        sanitise_source_url(danger)
