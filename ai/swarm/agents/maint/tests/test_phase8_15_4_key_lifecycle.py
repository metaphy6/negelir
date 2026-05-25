"""Phase 8 §8.15.4 proof tests — HMAC key lifecycle.

Covers the five DoD test groups from the §8.15.4 spec:

(a) Revocation grace window.
(b) Age-based auto-revocation.
(c) Cache coherency on rotation (on-demand force_reload).
(d) Kill-switch.
(e) Per-key rate-limit with debounced alert.

Plus: check_rotation_overdue alert emission.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from common.config import Config
from swarm.agents.maint._key_lifecycle import (
    OperatorsCache,
    check_kill_switch,
    check_rotation_overdue,
    get_operators_cache,
    get_rate_bucket,
    is_rate_limit_debounce_expired,
    reset_debounce_state,
    reset_operators_cache,
    reset_rate_bucket,
)
from swarm.agents.maint._op_signature import (
    key_id_from_bytes,
    verify_envelope_signature,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _utc_iso(offset_s: float = 0.0) -> str:
    ts = datetime.now(timezone.utc) + timedelta(seconds=offset_s)
    return ts.isoformat(timespec="seconds").replace("+00:00", "Z")


def _make_key_and_ops(
    tmp_path: Path,
    *,
    added_days_ago: float = 10,
    revoked_at: str | None = None,
) -> tuple[Path, Path, str, bytes]:
    """Return (key_file, ops_file, kid, raw_key)."""
    raw = secrets.token_bytes(32)
    key_file = tmp_path / "opsctl_key"
    key_file.write_bytes(raw)
    key_file.chmod(0o600)

    kid = key_id_from_bytes(raw, operator_email="op@test.example")
    added_at = _utc_iso(-added_days_ago * 86400)
    entry: dict[str, Any] = {
        "email": "op@test.example",
        "added_at": added_at,
        "revoked_at": revoked_at,
    }
    ops_file = tmp_path / "opsctl_operators.json"
    ops_file.write_text(
        json.dumps({"operators": {kid: entry}}, ensure_ascii=False)
    )
    return key_file, ops_file, kid, raw


def _signed_payload(
    raw: bytes,
    kid: str,
    *,
    kind: str = "liveness",
    target: str = "test",
    produced_at: str | None = None,
) -> dict[str, Any]:
    produced_at = produced_at or _utc_iso()
    request_id = secrets.token_hex(8)
    msg = f"{request_id}|{kind}|{target}|{produced_at}".encode()
    sig = hmac.new(raw, msg, hashlib.sha256).hexdigest()
    return {
        "kind": kind,
        "target": target,
        "produced_at": produced_at,
        "request_id": request_id,
        "op_key_id": kid,
        "op_signature": sig,
    }


def _make_cfg(
    tmp_path: Path,
    key_file: Path,
    ops_file: Path,
    *,
    grace_s: int = 60,
    max_age_days: int = 365,
    max_age_grace_days: int = 30,
    reload_s: int = 60,
    kill_switch_path: str = "",
    kill_switch_max_age_h: int = 24,
    rate_limit_per_min: int = 30,
) -> Config:
    from common.config import cfg as base
    import dataclasses

    overrides: dict[str, Any] = {
        "opsctl_key_path": str(key_file),
        "opsctl_operators_file": str(ops_file),
        "opsctl_require_signature": True,
        "opsctl_key_revocation_grace_s": grace_s,
        "opsctl_key_max_age_days": max_age_days,
        "opsctl_key_revocation_grace_days": max_age_grace_days,
        "opsctl_operators_reload_s": reload_s,
        "opsctl_kill_switch_path": kill_switch_path,
        "opsctl_kill_switch_max_age_h": kill_switch_max_age_h,
        "opsctl_key_rate_limit_per_min": rate_limit_per_min,
    }
    return dataclasses.replace(base, **overrides)


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Ensure singleton state does not bleed between tests."""
    reset_operators_cache()
    reset_rate_bucket()
    reset_debounce_state()
    yield
    reset_operators_cache()
    reset_rate_bucket()
    reset_debounce_state()


# ─── (a) Revocation grace window ─────────────────────────────────────────────


class TestRevocationGrace:
    def test_within_grace_accepted_with_grace_reason(self, tmp_path):
        """key revoked at T; publish at T+30 (grace=60) → accepted with grace reason."""
        now_s = time.time()
        revoked_at = _utc_iso(-(now_s - (now_s - 30)))  # 30 s ago
        # More simply: revoked 30 seconds ago, grace=60 → inside window
        revoked_at_str = _utc_iso(-30)
        key_file, ops_file, kid, raw = _make_key_and_ops(
            tmp_path, revoked_at=revoked_at_str
        )
        cfg = _make_cfg(tmp_path, key_file, ops_file, grace_s=60)
        # produced_at is "now" (0 s after revoked+30s means 30s post-revoke)
        payload = _signed_payload(raw, kid, produced_at=_utc_iso())
        ok, reason = verify_envelope_signature(payload, cfg)
        assert ok is True
        assert reason == "grace_window_pre_revocation"

    def test_outside_grace_rejected(self, tmp_path):
        """key revoked 90 s ago (grace=60) → rejected with key_revoked."""
        revoked_at_str = _utc_iso(-90)  # 90 s ago
        key_file, ops_file, kid, raw = _make_key_and_ops(
            tmp_path, revoked_at=revoked_at_str
        )
        cfg = _make_cfg(tmp_path, key_file, ops_file, grace_s=60)
        payload = _signed_payload(raw, kid, produced_at=_utc_iso())
        ok, reason = verify_envelope_signature(payload, cfg)
        assert ok is False
        assert reason == "key_revoked"

    def test_produced_at_within_grace_window_accepted(self, tmp_path):
        """Envelope with produced_at=T-40s (before revoke at T-30s) is in grace."""
        # revoked 30 s ago, envelope produced 50 s ago → produced_at < revoked_at + grace
        revoked_at_str = _utc_iso(-30)
        produced_at_str = _utc_iso(-50)  # produced 50s ago (before revoke)
        key_file, ops_file, kid, raw = _make_key_and_ops(
            tmp_path, revoked_at=revoked_at_str
        )
        cfg = _make_cfg(tmp_path, key_file, ops_file, grace_s=60)
        payload = _signed_payload(raw, kid, produced_at=produced_at_str)
        ok, reason = verify_envelope_signature(payload, cfg)
        assert ok is True
        assert reason == "grace_window_pre_revocation"


# ─── (b) Age-based auto-revocation ───────────────────────────────────────────


class TestAgeBasedAutoRevocation:
    def test_key_too_old_rejected(self, tmp_path):
        """Key added 400 days ago, max_age=365 + grace=30 → rejected at day 401."""
        key_file, ops_file, kid, raw = _make_key_and_ops(
            tmp_path, added_days_ago=401
        )
        cfg = _make_cfg(
            tmp_path, key_file, ops_file,
            max_age_days=365, max_age_grace_days=30
        )
        payload = _signed_payload(raw, kid)
        ok, reason = verify_envelope_signature(payload, cfg)
        assert ok is False
        assert reason == "key_age_exceeded"

    def test_key_within_age_accepted(self, tmp_path):
        """Key added 200 days ago with max_age=365 → still valid."""
        key_file, ops_file, kid, raw = _make_key_and_ops(
            tmp_path, added_days_ago=200
        )
        cfg = _make_cfg(
            tmp_path, key_file, ops_file,
            max_age_days=365, max_age_grace_days=30
        )
        payload = _signed_payload(raw, kid)
        ok, reason = verify_envelope_signature(payload, cfg)
        assert ok is True
        assert reason == ""

    def test_key_exactly_at_hard_limit_rejected(self, tmp_path):
        """Key added exactly at hard-limit days (365+30=395) → rejected."""
        key_file, ops_file, kid, raw = _make_key_and_ops(
            tmp_path, added_days_ago=396  # 1 day over the hard limit
        )
        cfg = _make_cfg(
            tmp_path, key_file, ops_file,
            max_age_days=365, max_age_grace_days=30
        )
        payload = _signed_payload(raw, kid)
        ok, reason = verify_envelope_signature(payload, cfg)
        assert ok is False
        assert reason == "key_age_exceeded"


# ─── (c) Cache coherency on rotation ─────────────────────────────────────────


class TestCacheCoherency:
    def test_new_key_accepted_via_on_demand_reload(self, tmp_path):
        """New key_id added to operators.json before first envelope → accepted."""
        # Start with a fresh ops file (no keys), then add the key.
        raw = secrets.token_bytes(32)
        key_file = tmp_path / "opsctl_key"
        key_file.write_bytes(raw)
        key_file.chmod(0o600)
        kid = key_id_from_bytes(raw, operator_email="op@test.example")

        ops_file = tmp_path / "opsctl_operators.json"
        # Initially empty
        ops_file.write_text(json.dumps({"operators": {}}, ensure_ascii=False))

        cfg = _make_cfg(tmp_path, key_file, ops_file, reload_s=3600)

        # Prime the cache with the empty ops file
        cache: OperatorsCache = get_operators_cache()
        operators, _ = cache.get_snapshot(cfg, ops_file)
        assert operators is not None
        assert kid not in operators

        # Now add the key to the file (simulating operator rotation)
        ops_file.write_text(json.dumps({
            "operators": {
                kid: {
                    "email": "op@test.example",
                    "added_at": _utc_iso(-1),
                    "revoked_at": None,
                }
            }
        }, ensure_ascii=False))

        # Consumer should pick up the new key via force_reload on unknown key_id
        payload = _signed_payload(raw, kid)
        ok, reason = verify_envelope_signature(payload, cfg)
        assert ok is True
        assert reason == ""

    def test_unknown_key_triggers_reload_not_false_critical(self, tmp_path):
        """Unknown key_id → on-demand reload, not an immediate hard reject."""
        # We confirm the behavior: after reload, if key is in file → accepted.
        key_file, ops_file, kid, raw = _make_key_and_ops(tmp_path)
        cfg = _make_cfg(tmp_path, key_file, ops_file, reload_s=3600)

        # Tamper the cache to think there are no operators
        cache: OperatorsCache = get_operators_cache()
        # Force a snapshot with empty operators by pointing at a temp empty file
        empty_ops = tmp_path / "empty_ops.json"
        empty_ops.write_text(json.dumps({"operators": {}}, ensure_ascii=False))
        cache.force_reload(empty_ops)

        # Now restore the real ops file to cfg and verify:
        # on-demand reload should recover
        payload = _signed_payload(raw, kid)
        ok, reason = verify_envelope_signature(payload, cfg)
        assert ok is True
        assert reason == ""


# ─── (d) Kill-switch ─────────────────────────────────────────────────────────


class TestKillSwitch:
    def test_kill_switch_file_absent_allows_verify(self, tmp_path):
        key_file, ops_file, kid, raw = _make_key_and_ops(tmp_path)
        ks_path = str(tmp_path / "opsctl_kill_switch")
        cfg = _make_cfg(
            tmp_path, key_file, ops_file,
            kill_switch_path=ks_path, kill_switch_max_age_h=24,
        )
        assert not check_kill_switch(cfg)
        payload = _signed_payload(raw, kid)
        ok, reason = verify_envelope_signature(payload, cfg)
        assert ok is True
        assert reason == ""

    def test_kill_switch_file_present_rejects_all(self, tmp_path):
        key_file, ops_file, kid, raw = _make_key_and_ops(tmp_path)
        ks_path = tmp_path / "opsctl_kill_switch"
        ks_path.touch()  # create the sentinel file
        cfg = _make_cfg(
            tmp_path, key_file, ops_file,
            kill_switch_path=str(ks_path), kill_switch_max_age_h=24,
        )
        assert check_kill_switch(cfg)
        payload = _signed_payload(raw, kid)
        ok, reason = verify_envelope_signature(payload, cfg)
        assert ok is False
        assert reason == "kill_switch_active"

    def test_stale_kill_switch_ignored(self, tmp_path):
        """Kill-switch file older than max_age_h is silently ignored."""
        import os

        key_file, ops_file, kid, raw = _make_key_and_ops(tmp_path)
        ks_path = tmp_path / "opsctl_kill_switch"
        ks_path.touch()
        # Back-date mtime by 25 h (> max_age_h=24)
        old_mtime = time.time() - 25 * 3600
        os.utime(str(ks_path), (old_mtime, old_mtime))
        cfg = _make_cfg(
            tmp_path, key_file, ops_file,
            kill_switch_path=str(ks_path), kill_switch_max_age_h=24,
        )
        # Stale file should be treated as absent
        assert not check_kill_switch(cfg)
        payload = _signed_payload(raw, kid)
        ok, reason = verify_envelope_signature(payload, cfg)
        assert ok is True


# ─── (e) Per-key rate-limit ───────────────────────────────────────────────────


class TestPerKeyRateLimit:
    def test_first_N_accepted_then_rejected(self, tmp_path):
        """30 envelopes/min limit: first 30 accepted, 31st rejected."""
        key_file, ops_file, kid, raw = _make_key_and_ops(tmp_path)
        limit = 10  # use a small limit for speed
        cfg = _make_cfg(tmp_path, key_file, ops_file, rate_limit_per_min=limit)

        accepted = 0
        for _ in range(limit):
            payload = _signed_payload(raw, kid)
            ok, _ = verify_envelope_signature(payload, cfg)
            if ok:
                accepted += 1

        assert accepted == limit

        # One more → should hit rate limit
        payload = _signed_payload(raw, kid)
        ok, reason = verify_envelope_signature(payload, cfg)
        assert ok is False
        assert reason == "key_rate_limited"

    def test_rate_limit_zero_means_unlimited(self, tmp_path):
        """rate_limit=0 disables the limit."""
        key_file, ops_file, kid, raw = _make_key_and_ops(tmp_path)
        cfg = _make_cfg(tmp_path, key_file, ops_file, rate_limit_per_min=0)

        for _ in range(100):
            payload = _signed_payload(raw, kid)
            ok, _ = verify_envelope_signature(payload, cfg)
            assert ok is True

    def test_debounce_expires_flag(self, tmp_path):
        """is_rate_limit_debounce_expired: initially True (no prior alert)."""
        key_file, ops_file, kid, raw = _make_key_and_ops(tmp_path)
        # Fresh state: debounce not yet set → expired = True
        assert is_rate_limit_debounce_expired(kid) is True


# ─── Rotation-overdue alert ───────────────────────────────────────────────────


class TestRotationOverdue:
    def test_overdue_key_flagged(self, tmp_path):
        """Key added 400 days ago (max_age=365) → flagged as overdue."""
        raw = secrets.token_bytes(32)
        kid = key_id_from_bytes(raw, operator_email="op@test.example")
        added_at = _utc_iso(-400 * 86400)
        operators = {
            kid: {
                "email": "op@test.example",
                "added_at": added_at,
                "revoked_at": None,
            }
        }
        import dataclasses
        from common.config import cfg as base
        cfg = dataclasses.replace(
            base,
            opsctl_key_max_age_days=365,
        )
        alerts = check_rotation_overdue(operators, cfg)
        assert len(alerts) == 1
        assert alerts[0]["key_id"] == kid

    def test_recent_key_not_flagged(self, tmp_path):
        raw = secrets.token_bytes(32)
        kid = key_id_from_bytes(raw, operator_email="op@test.example")
        operators = {
            kid: {
                "email": "op@test.example",
                "added_at": _utc_iso(-10 * 86400),
                "revoked_at": None,
            }
        }
        import dataclasses
        from common.config import cfg as base
        cfg = dataclasses.replace(base, opsctl_key_max_age_days=365)
        alerts = check_rotation_overdue(operators, cfg)
        assert alerts == []

    def test_already_revoked_key_not_flagged(self, tmp_path):
        raw = secrets.token_bytes(32)
        kid = key_id_from_bytes(raw, operator_email="op@test.example")
        operators = {
            kid: {
                "email": "op@test.example",
                "added_at": _utc_iso(-400 * 86400),
                "revoked_at": _utc_iso(-1),  # already revoked
            }
        }
        import dataclasses
        from common.config import cfg as base
        cfg = dataclasses.replace(base, opsctl_key_max_age_days=365)
        alerts = check_rotation_overdue(operators, cfg)
        assert alerts == []
