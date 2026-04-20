"""
Phase 1 follow-up regression tests.

Goal: prevent silent drift between the runtime configuration surface
(`ai/common/config.py`, `ai/common/league_config.py`) and the documentation
surface (`.env.example`).

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
ENV_EXAMPLE = REPO_ROOT / "xops" / "env" / ".env.example"
AI_CONFIG = REPO_ROOT / "ai" / "common" / "config.py"
GO_CONFIG = REPO_ROOT / "server" / "internal" / "config" / "config.go"
DEFAULTS_YAML = REPO_ROOT / "ai" / "common" / "defaults.yaml"

# Env vars listed in .env.example but intentionally not consumed by the
# Python config layer (Go server, docker-compose, optional features).
#
# NOTE: `test_every_documented_env_var_is_consumed` filters to NEGELIR_/SCRAPE_
# prefixes, so this allow-list is currently a documentation aid (no entry below
# matches those prefixes). Kept to make the Python/Go ownership boundary
# explicit; if a NEGELIR_* key ever needs to be Go-only, list it here too.
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
# Matches a `# shared` marker at end of an env-line, e.g.
#   POSTGRES_HOST=postgres        # shared
_SHARED_KEY_RE = re.compile(
    r"^([A-Z][A-Z0-9_]*)=[^\n]*#\s*shared\b", re.MULTILINE
)
# Matches `env:"FOO"` struct tags in the Go config file.
_GO_ENV_TAG_RE = re.compile(r'env:"([A-Z][A-Z0-9_]*)"')


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _env_example_keys() -> set[str]:
    return set(_ENV_KEY_RE.findall(_read(ENV_EXAMPLE)))


def _python_env_keys() -> set[str]:
    keys: set[str] = set()
    for path in (AI_CONFIG,):
        keys.update(_GETENV_RE.findall(_read(path)))
    return keys


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.is_file(), f".env.example missing at {ENV_EXAMPLE}"


def test_every_python_env_var_is_documented() -> None:
    """Every os.getenv("FOO") in config.py must appear in .env.example."""
    docs = _env_example_keys()
    code = _python_env_keys()
    undocumented = sorted((code - docs) - _DOCS_OPTIONAL_ENV_KEYS)
    assert not undocumented, (
        "These env vars are read by Python config but not documented in "
        f".env.example: {undocumented}"
    )


def test_every_documented_env_var_is_consumed() -> None:
    """Every NEGELIR_*/SCRAPE_* key in .env.example must be read somewhere."""
    docs = _env_example_keys()
    code = _python_env_keys()
    must_be_consumed = {
        k for k in docs
        if k.startswith(("NEGELIR_", "SCRAPE_"))
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


def test_p2p_module_removed() -> None:
    """Phase 0 swarm pivot: p2p/ directory must stay deleted."""
    assert not (REPO_ROOT / "p2p").exists(), (
        "p2p/ directory was removed in Phase 0 — do not re-introduce it. "
        "The swarm replacement lives under roadmap Phase 5+."
    )


def test_ai_config_strict_validate_raises_on_bad_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strict validation must raise on out-of-range values."""
    from common.config import Config

    monkeypatch.setenv("NEGELIR_TRAINING_TEST_SPLIT", "1.5")
    with pytest.raises(ValueError):
        Config().validate(strict=True)


def test_league_config_pickle_roundtrip() -> None:
    """LeagueConfig must survive pickle (model bundles ride with config)."""
    from common.league_config import get_league_config

    cfg = get_league_config("tr_super_lig")
    restored = pickle.loads(pickle.dumps(cfg))
    assert restored.league_id == cfg.league_id
    assert restored.xgb_weight == cfg.xgb_weight
    assert restored.dixon_coles_rho == cfg.dixon_coles_rho
    assert restored.derbies == cfg.derbies


def test_no_synthetic_imports_in_production_code() -> None:
    """Phase 2 gate: no production module may import the synthetic generator."""
    forbidden = re.compile(r"\bgenerate_synthetic_dataset\b")
    offenders: list[str] = []
    for module_root in ("ai",):
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


# ── Phase 1 additions ────────────────────────────────────────────────────


def _go_env_keys() -> set[str]:
    """Env keys bound by the Go server's config layer (Phase 1.2)."""
    if not GO_CONFIG.is_file():
        return set()
    return set(_GO_ENV_TAG_RE.findall(_read(GO_CONFIG)))


def _shared_marked_keys() -> set[str]:
    return set(_SHARED_KEY_RE.findall(_read(ENV_EXAMPLE)))


def test_strict_mode_rejects_unknown_negelir_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 1.1: NEGELIR_STRICT must surface unknown reserved-prefix keys."""
    from common.config import Config

    monkeypatch.setenv("NEGELIR_STRICT", "1")
    monkeypatch.setenv("NEGELIR_TOTALLY_BOGUS_OPTION", "boom")
    with pytest.raises(ValueError) as exc:
        Config().validate(strict=True)
    assert "NEGELIR_TOTALLY_BOGUS_OPTION" in str(exc.value)


def test_strict_mode_accepts_known_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strict mode must NOT trip on a legitimate, declared env key."""
    from common.config import Config

    monkeypatch.setenv("NEGELIR_STRICT", "1")
    monkeypatch.setenv("NEGELIR_TRAINING_TEST_SPLIT", "0.25")
    issues = Config().validate()  # explicit strict=False; env-strict still active
    # Only the unknown-key sweep should trigger; if any shows up we have a bug.
    stray = [i for i in issues if "unknown env key" in i]
    assert stray == [], f"strict mode tripped on declared key: {stray}"


def test_validate_rejects_bad_url_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 1.1: server_url must use http/https."""
    from common.config import Config

    monkeypatch.setenv("SERVER_URL", "ftp://nope")
    with pytest.raises(ValueError):
        Config().validate(strict=True)


def test_shared_env_keys_are_marked() -> None:
    """Phase 1.3: any key consumed by BOTH Python and Go must carry `# shared`."""
    py = _python_env_keys()
    go = _go_env_keys()
    docs = _env_example_keys()
    shared_marker = _shared_marked_keys()

    if not go:
        pytest.skip("Go config layer not present yet")

    overlap = (py & go) & docs
    unmarked = sorted(overlap - shared_marker)
    assert not unmarked, (
        "These env vars are read by BOTH Python and Go but lack a `# shared` "
        f"marker in .env.example: {unmarked}"
    )


def test_shared_marker_only_on_actually_shared_keys() -> None:
    """A `# shared` marker must correspond to a key both layers actually read."""
    py = _python_env_keys()
    go = _go_env_keys()
    if not go:
        pytest.skip("Go config layer not present yet")
    spurious = sorted(_shared_marked_keys() - (py & go))
    assert not spurious, (
        "These keys are marked `# shared` but are not actually consumed by both "
        f"Python and Go: {spurious}"
    )


# Tunables that are NOT defaults (operational toggles, dynamic JSON overrides,
# computed values) and so are intentionally absent from defaults.yaml even
# though they're documented in .env.example. Keep tight; add only with reason.
_DEFAULTS_YAML_OPTIONAL: frozenset[str] = frozenset({
    "NEGELIR_FEATURE_RANGES_JSON",  # default values are listed under feature_ranges:
})


def test_defaults_yaml_mentions_every_documented_tunable() -> None:
    """Phase 1.1 drift gate: every NEGELIR_*/SCRAPE_* env key documented in
    .env.example must appear somewhere in defaults.yaml (as a comment tag).
    Catches the silent drift the `[~]` deferral was hiding.
    """
    if not DEFAULTS_YAML.is_file():
        pytest.skip("defaults.yaml not present")
    yml_body = _read(DEFAULTS_YAML)
    # Loose match: any UPPER_SNAKE token (≥4 chars) anywhere in the file.
    yml_mentions = set(re.findall(r"\b([A-Z][A-Z0-9_]{3,})\b", yml_body))
    must = {
        k for k in _env_example_keys()
        if k.startswith(("NEGELIR_", "SCRAPE_"))
    }
    missing = sorted(must - yml_mentions - _DEFAULTS_YAML_OPTIONAL)
    assert not missing, (
        "defaults.yaml is out of sync with .env.example — these env keys are "
        "documented as tunables but never mentioned in defaults.yaml: "
        f"{missing}"
    )


def test_defaults_yaml_is_valid_yaml() -> None:
    """A regex-only drift check is fooled by a token that survives in a
    broken/merged comment line. Parse it for real to catch structural rot.
    """
    if not DEFAULTS_YAML.is_file():
        pytest.skip("defaults.yaml not present")
    yaml = pytest.importorskip("yaml")
    try:
        loaded = yaml.safe_load(_read(DEFAULTS_YAML))
    except yaml.YAMLError as exc:  # pragma: no cover - exercised on regression
        pytest.fail(f"defaults.yaml is not valid YAML: {exc}")
    assert isinstance(loaded, dict), "defaults.yaml top level must be a mapping"
    # Spot-check a few sections that landed in the Phase 1 audit so that a
    # future "merge into comment" defect can't slip past unnoticed.
    paths = loaded.get("paths") or {}
    assert "report_dir" in paths, (
        "paths.report_dir is missing — likely glued onto another comment line"
    )
    assert (loaded.get("operational") or {}).get("strict") is False, (
        "operational.strict default must be present and False"
    )


# Keys whose `os.getenv("X", "default")` fallback is allowed to differ from
# the value documented in `.env.example`. The canonical example is the host
# of a backing service: code defaults to "localhost" so a developer can run
# `python -m ...` without Docker, while `.env.example` defaults to the
# compose service name. Anything added here MUST have a one-line reason.
_VALUE_DRIFT_ALLOWED: dict[str, str] = {
    "POSTGRES_HOST": "container name vs host-dev fallback",
    "REDIS_HOST": "container name vs host-dev fallback",
    "SERVER_URL": "container hostname vs host-dev fallback",
    "POSTGRES_PASSWORD": ".env.example holds a placeholder; code default is empty",
    "NEGELIR_STRICT": "code treats empty == off; .env.example shows '0' as a hint",
}

# Capture `os.getenv("KEY", "literal default")` (only string-literal defaults).
_GETENV_DEFAULT_RE = re.compile(
    r"""os\.getenv\(\s*["']([A-Z][A-Z0-9_]*)["']\s*,\s*["']([^"']*)["']\s*\)"""
)


def test_python_defaults_match_env_example() -> None:
    """Phase 1 deep-audit gate: every `os.getenv("KEY", "default")` literal
    fallback in `ai/common/config.py` must equal the value documented in
    `.env.example`. Catches the silent value drift the key-only sync tests
    were blind to (e.g. SCRAPE_RATE_LIMIT_SECONDS=2 in env vs "5" in code).
    """
    py_text = _read(AI_CONFIG)
    env_text = _read(ENV_EXAMPLE)

    # Build map of KEY → documented value (strip trailing inline comment).
    env_vals: dict[str, str] = {}
    for line in env_text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2)
        # Strip an inline `# comment` only if preceded by whitespace, so
        # in-value `#` characters survive (rare but possible in user-agents).
        env_vals[key] = re.sub(r"\s+#.*$", "", raw).strip()

    drift: list[str] = []
    for key, py_default in _GETENV_DEFAULT_RE.findall(py_text):
        if key in _VALUE_DRIFT_ALLOWED:
            continue
        env_val = env_vals.get(key)
        if env_val is None:
            continue  # already covered by key-parity test
        if py_default != env_val:
            drift.append(f"{key}: PY={py_default!r}  ENV={env_val!r}")

    assert not drift, (
        "Default-value drift between ai/common/config.py and .env.example.\n"
        "Sync the two, or add the key to `_VALUE_DRIFT_ALLOWED` with a "
        "one-line reason if the divergence is deliberate.\n  - "
        + "\n  - ".join(sorted(drift))
    )
