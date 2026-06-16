"""Phase 18.7 ledger #28 proof test: legacy env vars are documented for alias window."""

from pathlib import Path


def test_legacy_env_vars_documented() -> None:
    """Legacy env vars (POSTGRES_*, REDIS_*, etc.) are documented in the alias window."""
    env_file = Path("/home/tech/code/negelir/xops/env/.env.example")
    assert env_file.exists()
    
    content = env_file.read_text()
    
    # Check that deprecation aliases are mentioned in the header
    assert "NEGELIR_<COMPONENT>_<KEY>" in content
    assert "Legacy (deprecated, 90-day alias window):" in content
    
    print("✓ Legacy env vars documented in alias window")


if __name__ == "__main__":
    test_legacy_env_vars_documented()
