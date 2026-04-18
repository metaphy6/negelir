"""
Phase 1 follow-up regression tests.

Goal: prevent silent drift between the runtime configuration surface
(`ai/common/config.py`, `p2p/config.py`, `ai/common/league_config.py`) and
the documentation surface (`.env.example`).

These tests do not require any external services. They run in any
environment where the source tree is checked out.
"""

from __future__ import annotations

import os
import pickle
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
AI_CONFIG = REPO_ROOT / "ai" / "common" / "config.py"
P2P_CONFIG = REPO_ROOT / "p2p" / "config.py"
# Some env vars are still read directly via os.getenv() at the call site
# (e.g. P2P simulation runner) instead of through a centralized dataclass.
# They are intentionally documented in .env.example, so include them in the scan.
_EXTRA_PYTHON_SCAN = (
    REPO_ROOT / "p2p" / "simulation" / "runner.py",
)

# Env vars listed in .env.example but intentionally not consumed by the
# Python config layer (Go server, docker-compose, optional features).
_PYTHON_UNUSED_ENV_KEYS = frozenset({
    # Go server-only knobs
    "DATABASE_URL",
    "REDIS_URL",
    "DB_MAX_CONNS",
    "DB_CONNECT_TIMEOUT_SEC",
    "DB_PING_TIMEOUT_SEC",
    "DB_RETRY_DELAY_SEC",
    "REDIS_RETRY_DELAY_SEC",
    "HTTP_READ_TIMEOUT_SEC",
    "HTTP_WRITE_TIMEOUT_SEC",
    "HTTP_SHUTDOWN_TIMEOUT_SEC",
    "CACHE_MATCHES_TTL_SEC",
    "CACHE_TEAMS_TTL_SEC",
    "SERVER_PORT",
})

# Env vars consumed by the Python layer but not surfaced in .env.example
# (e.g. only meaningful in CI or for ad-hoc overrides).
_DOCS_OPTIONAL_ENV_KEYS: frozenset[str] = frozenset()

_ENV_KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)
_GETENV_RE = re.compile(r"""os\.getenv\(\s*["']([A-Z][A-Z0-9_]*)["']""")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _env_example_keys() -> set[str]:
    return set(_ENV_KEY_RE.findall(_read(ENV_EXAMPLE)))


def _python_env_keys() -> set[str]:
    keys: set[str] = set()
    for path in (AI_CONFIG, P2P_CONFIG, *_EXTRA_PYTHON_SCAN):
        keys.update(_GETENV_RE.findall(_read(path)))
    return keys


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.is_file(), f".env.example missing at {ENV_EXAMPLE}"


def test_every_python_env_var_is_documented() -> None:
    """Every os.getenv("FOO") in config.py / p2p/config.py must appear in .env.example."""
    docs = _env_example_keys()
    code = _python_env_keys()
    undocumented = sorted((code - docs) - _DOCS_OPTIONAL_ENV_KEYS)
    assert not undocumented, (
        "These env vars are read by Python config but not documented in "
        f".env.example: {undocumented}"
    )


def test_every_documented_env_var_is_consumed() -> None:
    """Every NEGELIR_*/P2P_*/SCRAPE_* key in .env.example must be read somewhere."""
    docs = _env_example_keys()
    code = _python_env_keys()
    # Cross-language keys (POSTGRES_*, REDIS_*, AI_*, MACKOLIK_*, OPENFOOTBALL_*,
    # FOOTBALLDATA_*, BOOTSTRAP_*, DATA_DIR, MODEL_DIR) are consumed by Python
    # too, but the strict subset below MUST appear in code.
    must_be_consumed = {
        k for k in docs
        if k.startswith(("NEGELIR_", "P2P_", "SCRAPE_"))
    }
    orphans = sorted(must_be_consumed - code - _PYTHON_UNUSED_ENV_KEYS)
    assert not orphans, (
        "These env vars are documented in .env.example but never read by any "
        f"Python config: {orphans}"
    )


def test_ai_config_validate_passes_with_defaults() -> None:
    """`Config.validate()` must accept the shipped defaults with zero issues."""
    from common.config import Config

    issues = Config().validate()
    assert issues == [], f"Default Config has validation issues: {issues}"


def test_p2p_config_validate_passes_with_defaults() -> None:
    """`P2PConfig.validate()` must accept the shipped defaults with zero issues."""
    from p2p.config import P2PConfig

    issues = P2PConfig().validate()
    assert issues == [], f"Default P2PConfig has validation issues: {issues}"


def test_ai_config_strict_validate_raises_on_bad_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strict validation must raise on out-of-range values."""
    from common.config import Config

    monkeypatch.setenv("NEGELIR_TRAINING_TEST_SPLIT", "1.5")
    with pytest.raises(ValueError):
        Config().validate(strict=True)


def test_league_config_pickle_roundtrip() -> None:
    """LeagueConfig must survive pickle (P2P sim ships the model + config)."""
    from common.league_config import get_league_config

    cfg = get_league_config("tr_super_lig")
    restored = pickle.loads(pickle.dumps(cfg))
    assert restored.league_id == cfg.league_id
    assert restored.xgb_weight == cfg.xgb_weight
    assert restored.dixon_coles_rho == cfg.dixon_coles_rho
    assert restored.derbies == cfg.derbies


def test_p2p_config_pickle_roundtrip() -> None:
    """P2PConfig must survive pickle so it can ride along with peer state."""
    from p2p.config import P2PConfig

    cfg = P2PConfig()
    restored = pickle.loads(pickle.dumps(cfg))
    assert restored.tcp_port == cfg.tcp_port
    assert restored.message_ttl_hours == cfg.message_ttl_hours
    assert restored.sim_drop_rate == cfg.sim_drop_rate


def test_no_synthetic_imports_in_production_code() -> None:
    """Phase 2 gate: no production module may import the synthetic generator."""
    forbidden = re.compile(r"\bgenerate_synthetic_dataset\b")
    offenders: list[str] = []
    for module_root in ("ai", "p2p"):
        root = REPO_ROOT / module_root
        for py in root.rglob("*.py"):
            # Tests, fixtures and the test-data CLI are the allowed home.
            rel = py.relative_to(REPO_ROOT).as_posix()
            if "/tests/" in rel or rel.endswith("/tests"):
                continue
            text = py.read_text(encoding="utf-8", errors="ignore")
            if forbidden.search(text):
                offenders.append(rel)
    assert not offenders, (
        "generate_synthetic_dataset is referenced outside tests/: "
        f"{offenders}"
    )
