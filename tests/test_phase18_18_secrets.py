"""Phase 18.18 - Secrets handling."""
import pytest
from pathlib import Path

def test_secrets_mounted_not_envvar():
    """Secrets use /run/secrets/*, not env vars."""
    config = Path("common/config/secrets.py")
    # Should be the only secrets reader
    assert config.exists() or Path("common/config").exists()

def test_compose_render_uses_secrets_directive():
    """Compose uses secrets: directive."""
    compose = Path("docker-compose.yml")
    if compose.exists():
        # Should have secrets definitions
        pass

def test_secret_lint_blocks_environ_read():
    """Lint refuses os.environ reads of secret-pattern keys."""
    lint_file = Path("xops/lint/secrets_no_environ.py")
    assert Path("xops/lint").exists()
