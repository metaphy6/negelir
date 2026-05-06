"""Phase 8 §8.13.2 — MaintStorageWarden proof tests."""
from __future__ import annotations

import os

import pytest

from common.config import cfg
from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS
from swarm.sdk.maint_storage import (
    MaintStorageWarden,
    assert_subdir_caps_within_global,
)


# ── Helpers ────────────────────────────────────────────────────────


def _write(path: str, n_bytes: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * n_bytes)


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


# ── Kind registration ─────────────────────────────────────────────


def test_pressure_kind_is_known() -> None:
    assert "maint_storage_pressure" in KNOWN_SEC_ALERT_KINDS


# ── Warden behavior ────────────────────────────────────────────────


def test_disabled_cap_is_noop(tmp_path) -> None:
    _write(str(tmp_path / "spool" / "x"), 5_000_000)
    w = MaintStorageWarden(root=str(tmp_path), cap_mb=0)
    d = w.check()
    assert d.alerts == []
    assert d.blocking is False
    assert d.cap_bytes == 0
    assert d.total_bytes == 5_000_000


def test_below_warn_emits_nothing(tmp_path) -> None:
    _write(str(tmp_path / "spool" / "x"), 1_000_000)  # 1MB
    w = MaintStorageWarden(root=str(tmp_path), cap_mb=10)  # cap=10MB → 10%
    d = w.check()
    assert d.alerts == []
    assert d.blocking is False


def test_warn_band_emits_warn_alert(tmp_path) -> None:
    # cap=10MB, write 8.5MB → 85%
    _write(str(tmp_path / "spool" / "x"), int(8.5 * 1024 * 1024))
    clock = _Clock()
    w = MaintStorageWarden(root=str(tmp_path), cap_mb=10, clock=clock)
    d = w.check()
    assert len(d.alerts) == 1
    p = d.alerts[0].payload
    assert p["kind"] == "maint_storage_pressure"
    assert p["severity"] == "warn"
    assert d.blocking is False


def test_warn_alert_is_debounced(tmp_path) -> None:
    _write(str(tmp_path / "spool" / "x"), int(8.5 * 1024 * 1024))
    clock = _Clock()
    w = MaintStorageWarden(root=str(tmp_path), cap_mb=10,
                           clock=clock, debounce_s=3600)
    a = w.check()
    clock.t += 1800  # 30min later
    b = w.check()
    clock.t += 1801  # past debounce
    c = w.check()
    assert len(a.alerts) == 1
    assert b.alerts == []
    assert len(c.alerts) == 1


def test_error_band_emits_error_and_blocks(tmp_path) -> None:
    _write(str(tmp_path / "spool" / "x"), int(11 * 1024 * 1024))  # >100%
    w = MaintStorageWarden(root=str(tmp_path), cap_mb=10)
    d = w.check()
    assert len(d.alerts) == 1
    assert d.alerts[0].payload["severity"] == "error"
    assert d.blocking is True
    assert w.is_blocking() is True


def test_hysteresis_release_band(tmp_path) -> None:
    # Cross 100%, drop to 75% (still blocking), drop to 65% (released).
    p = str(tmp_path / "spool" / "x")
    _write(p, int(11 * 1024 * 1024))
    w = MaintStorageWarden(root=str(tmp_path), cap_mb=10,
                           release_pct=70.0)
    d1 = w.check()
    assert d1.blocking is True

    _write(p, int(7.5 * 1024 * 1024))  # 75% — still blocking
    d2 = w.check()
    assert d2.blocking is True

    _write(p, int(6.5 * 1024 * 1024))  # 65% — released
    d3 = w.check()
    assert d3.blocking is False


def test_per_subdir_breakdown(tmp_path) -> None:
    _write(str(tmp_path / "spool_a" / "x"), 1024)
    _write(str(tmp_path / "spool_a" / "y"), 2048)
    _write(str(tmp_path / "spool_b" / "z"), 4096)
    _write(str(tmp_path / "topfile.bin"), 100)
    w = MaintStorageWarden(root=str(tmp_path), cap_mb=10)
    d = w.check()
    assert d.per_subdir_bytes["spool_a"] == 3072
    assert d.per_subdir_bytes["spool_b"] == 4096
    assert d.per_subdir_bytes["<root>"] == 100
    assert d.total_bytes == 7268


def test_missing_root_is_safe() -> None:
    w = MaintStorageWarden(root="/nonexistent/path/that/should/not/exist",
                           cap_mb=10)
    d = w.check()
    assert d.total_bytes == 0
    assert d.alerts == []
    assert d.blocking is False


def test_symlinks_are_not_followed(tmp_path) -> None:
    _write(str(tmp_path / "real" / "x"), 1024)
    os.symlink(str(tmp_path / "real"), str(tmp_path / "linked"))
    w = MaintStorageWarden(root=str(tmp_path), cap_mb=10)
    d = w.check()
    # Only 'real' is counted; 'linked' is a symlink and skipped.
    assert "real" in d.per_subdir_bytes
    assert d.per_subdir_bytes.get("linked", 0) == 0


def test_error_then_recovery_re_arms_warn(tmp_path) -> None:
    """After an error alert, dropping into the warn band re-emits
    one warn alert (operator visibility on recovery in progress)."""
    p = str(tmp_path / "spool" / "x")
    _write(p, int(11 * 1024 * 1024))  # error
    clock = _Clock()
    w = MaintStorageWarden(root=str(tmp_path), cap_mb=10,
                           clock=clock, debounce_s=60)
    a = w.check()
    assert a.alerts[0].payload["severity"] == "error"
    # Drop to 85% — warn band, should emit even though debounce
    # would have silenced a same-band repeat.
    _write(p, int(8.5 * 1024 * 1024))
    clock.t += 1
    b = w.check()
    assert len(b.alerts) == 1
    assert b.alerts[0].payload["severity"] == "warn"


# ── assert_subdir_caps_within_global ───────────────────────────────


def test_subdir_caps_audit_passes_when_within_global() -> None:
    assert_subdir_caps_within_global(
        {"opsctl_spool": 100, "agent_spool": 200, "audit": 50},
        global_cap_mb=512,
    )


def test_subdir_caps_audit_refuses_when_exceeds_global() -> None:
    with pytest.raises(RuntimeError, match="fail_safe_subdir_caps_exceed_global"):
        assert_subdir_caps_within_global(
            {"opsctl_spool": 400, "agent_spool": 400},
            global_cap_mb=512,
        )


def test_subdir_caps_audit_disabled_global_is_noop() -> None:
    # Even an absurd subdir cap is fine when the global is disabled.
    assert_subdir_caps_within_global(
        {"runaway": 1_000_000_000},
        global_cap_mb=0,
    )


def test_subdir_caps_audit_uses_cfg_when_global_omitted(monkeypatch) -> None:
    monkeypatch.setattr(cfg, "maint_storage_total_max_mb", 100, raising=False)
    with pytest.raises(RuntimeError, match="fail_safe_subdir_caps_exceed_global"):
        assert_subdir_caps_within_global({"x": 200})


# ── Constructor validation ────────────────────────────────────────


def test_invalid_pct_thresholds_rejected(tmp_path) -> None:
    with pytest.raises(ValueError):
        MaintStorageWarden(root=str(tmp_path), cap_mb=10,
                           warn_pct=120.0, error_pct=100.0)
    with pytest.raises(ValueError):
        MaintStorageWarden(root=str(tmp_path), cap_mb=10,
                           warn_pct=80.0, release_pct=90.0)


# ── Config validator ──────────────────────────────────────────────


def test_config_validator_accepts_zero() -> None:
    from common.config import Config
    issues = Config(maint_storage_total_max_mb=0).validate()
    assert not any("maint_storage_total_max_mb" in s for s in issues)


def test_config_validator_rejects_negative() -> None:
    from common.config import Config
    issues = Config(maint_storage_total_max_mb=-1).validate()
    assert any("maint_storage_total_max_mb" in s for s in issues)
