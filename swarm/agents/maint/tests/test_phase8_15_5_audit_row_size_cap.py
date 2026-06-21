"""Phase 8 §8.15.5 proof tests — maint_audit_log per-row size cap + per-kind details budget.

Covers the four DoD test groups from the §8.15.5 spec:

(a) Producer-side per-kind soft fence: MaintEvent._make() caps details kwarg.
(b) Trigger-backstop simulation: apply_row_cap() caps full payload dict.
(c) Sentinel round-trip: original bytes survive in the sidecar file.
(d) Adversarial / edge cases.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from swarm.sdk.maint_audit import (
    SENTINEL_KEY,
    apply_row_cap,
    build_sentinel,
    is_sentinel,
    truncate_oversize,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _big_dict(target_bytes: int) -> dict[str, Any]:
    """Return a dict whose JSON serialisation is >= target_bytes."""
    filler = "x" * target_bytes
    return {"data": filler}


def _serialised_size(d: dict[str, Any]) -> int:
    return len(json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8"))


# ─── (a) Producer-side per-kind soft fence ────────────────────────────────────


class TestProducerSideSoftFence:
    """MaintEvent._make() must cap the ``details`` kwarg when over budget."""

    def test_details_within_cap_returned_unchanged(self, tmp_path: Path) -> None:
        """Small details dict: no truncation, no sidecar."""
        from swarm.sdk.maint_audit import truncate_oversize

        details = {"event": "ok", "count": 1}
        result = truncate_oversize(
            details,
            kind="dlq_escalated",
            row_id="req-001",
            oversize_dir=tmp_path,
            cap_bytes=8192,
        )
        assert result is details, "Unchanged dict must be the same object"
        # No sidecar written.
        assert not list(tmp_path.glob("*.json"))

    def test_oversize_details_replaced_with_sentinel(self, tmp_path: Path) -> None:
        """details > cap_bytes → sentinel returned, sidecar written."""
        details = _big_dict(10_000)
        cap = 512

        result = truncate_oversize(
            details,
            kind="dlq_escalated",
            row_id="req-002",
            oversize_dir=tmp_path,
            cap_bytes=cap,
        )

        # Sentinel structure.
        assert is_sentinel(result)
        assert result[SENTINEL_KEY] is True
        assert result["_kind"] == "dlq_escalated"
        assert result["_original_size_bytes"] == _serialised_size(details)
        # _first_4kb is valid base64.
        decoded = base64.b64decode(result["_first_4kb"])
        assert len(decoded) <= 4096

        # Sidecar written and readable.
        sidecar = tmp_path / "req-002.json"
        assert sidecar.exists(), "Sidecar file must be written"
        recovered = json.loads(sidecar.read_bytes())
        assert recovered == details

    def test_sidecar_has_restricted_permissions(self, tmp_path: Path) -> None:
        """Sidecar file must have mode 0o600."""
        details = _big_dict(5_000)
        truncate_oversize(
            details,
            kind="schema_drift_detected",
            row_id="perm-test",
            oversize_dir=tmp_path,
            cap_bytes=100,
        )
        sidecar = tmp_path / "perm-test.json"
        assert sidecar.exists()
        mode = sidecar.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600 but got {oct(mode)}"

    def test_maint_event_make_applies_per_kind_cap(self, tmp_path: Path, monkeypatch) -> None:
        """MaintEvent._make() with oversized details → sentinel in returned dict."""
        # Monkeypatch cfg to use tmp_path for oversize_dir and a small per-kind cap.
        from common import config as _cfg_mod
        fake_cfg = MagicMock()
        fake_cfg.data_dir = str(tmp_path)
        kind_budgets = {"dlq_escalated": 256, "default": 128}
        fake_cfg.maint_audit_per_kind_details_max_bytes_parsed = kind_budgets

        monkeypatch.setattr(_cfg_mod, "cfg", fake_cfg)

        from swarm.sdk import payloads as _payloads
        import importlib
        importlib.reload(_payloads)

        from swarm.sdk.payloads import MaintEvent
        import time, datetime

        big_details = _big_dict(5_000)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

        result = MaintEvent.dlq_escalated(
            request_id="test-dlq-001",
            produced_at=now_iso,
            target="test_queue",
            client_id="test_client",
            details=big_details,
            _audit_row_id="test-dlq-001",
        )

        assert result["kind"] == "dlq_escalated"
        assert is_sentinel(result["details"]), "Over-budget details must be replaced with sentinel"
        sidecar = tmp_path / "maint" / "audit_oversize" / "test-dlq-001.json"
        assert sidecar.exists(), f"Sidecar must be at {sidecar}"
        recovered = json.loads(sidecar.read_bytes())
        assert recovered == big_details

        # Restore the module after reload.
        importlib.reload(_payloads)


# ─── (b) Trigger-backstop simulation ─────────────────────────────────────────


class TestApplyRowCap:
    """apply_row_cap() correctly truncates full payloads (trigger-backstop simulation)."""

    def test_within_cap_unchanged(self, tmp_path: Path) -> None:
        payload = {"kind": "scale_decision", "x": 1}
        result = apply_row_cap(
            payload,
            kind="scale_decision",
            row_id="r-001",
            oversize_dir=tmp_path,
            cap_bytes=2048,
        )
        assert result is payload

    def test_oversize_triggers_sentinel_and_alert(self, tmp_path: Path) -> None:
        """Oversized payload → sentinel returned, alert_fn called with expected kwargs."""
        payload = {"kind": "scale_decision", "data": "z" * 10_000}
        alert_calls: list[dict] = []

        def _alert(*, kind: str, original_size: int) -> None:
            alert_calls.append({"kind": kind, "original_size": original_size})

        result = apply_row_cap(
            payload,
            kind="scale_decision",
            row_id="r-002",
            oversize_dir=tmp_path,
            cap_bytes=512,
            alert_fn=_alert,
        )

        assert is_sentinel(result)
        assert result["_kind"] == "scale_decision"
        assert len(alert_calls) == 1
        assert alert_calls[0]["kind"] == "scale_decision"
        assert alert_calls[0]["original_size"] > 512

    def test_alert_fn_failure_does_not_raise(self, tmp_path: Path) -> None:
        """alert_fn that raises must not propagate the exception."""
        payload = {"data": "y" * 5_000}

        def _bad_alert(*, kind: str, original_size: int) -> None:
            raise RuntimeError("alert backend is down")

        # Must not raise.
        result = apply_row_cap(
            payload,
            kind="backup_dump_file_corrupted",
            row_id="r-003",
            oversize_dir=tmp_path,
            cap_bytes=100,
            alert_fn=_bad_alert,
        )
        assert is_sentinel(result)

    def test_no_alert_fn_succeeds(self, tmp_path: Path) -> None:
        payload = {"data": "a" * 5_000}
        result = apply_row_cap(
            payload,
            kind="dlq_escalated",
            row_id="r-004",
            oversize_dir=tmp_path,
            cap_bytes=100,
        )
        assert is_sentinel(result)


# ─── (c) Sentinel round-trip ─────────────────────────────────────────────────


class TestSentinelRoundTrip:
    """Sidecar contains the exact original bytes; sentinel metadata is correct."""

    def test_round_trip_10kb_details(self, tmp_path: Path) -> None:
        """Write a 10 KB details dict; sidecar round-trip gives back the original."""
        original = {f"key_{i}": "v" * 64 for i in range(80)}  # ~10 KB
        row_id = "rt-001"
        cap = 256

        sentinel = truncate_oversize(
            original,
            kind="dlq_escalated",
            row_id=row_id,
            oversize_dir=tmp_path,
            cap_bytes=cap,
        )

        assert is_sentinel(sentinel)
        sidecar = tmp_path / f"{row_id}.json"
        recovered = json.loads(sidecar.read_bytes())
        assert recovered == original, "Sidecar must contain the exact original dict"

    def test_sentinel_first_4kb_matches_serialisation(self, tmp_path: Path) -> None:
        """The _first_4kb field in the sentinel matches the first 4096 bytes of JSON."""
        original = {"data": "A" * 20_000}
        sentinel = truncate_oversize(
            original,
            kind="schema_drift_detected",
            row_id="rt-002",
            oversize_dir=tmp_path,
            cap_bytes=256,
        )
        raw = json.dumps(original, sort_keys=True, ensure_ascii=False).encode("utf-8")
        expected_b64 = base64.b64encode(raw[:4096]).decode("ascii")
        assert sentinel["_first_4kb"] == expected_b64

    def test_original_size_field_is_accurate(self, tmp_path: Path) -> None:
        original = {"text": "B" * 10_000}
        raw = json.dumps(original, sort_keys=True, ensure_ascii=False).encode("utf-8")
        sentinel = truncate_oversize(
            original,
            kind="backup_dump_file_corrupted",
            row_id="rt-003",
            oversize_dir=tmp_path,
            cap_bytes=256,
        )
        assert sentinel["_original_size_bytes"] == len(raw)


# ─── (d) Adversarial / edge cases ────────────────────────────────────────────


class TestAdversarialEdgeCases:
    """Edge-case and adversarial inputs."""

    def test_cap_bytes_zero_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="cap_bytes must be positive"):
            truncate_oversize({"x": 1}, kind="k", row_id="r", oversize_dir=tmp_path, cap_bytes=0)

    def test_cap_bytes_negative_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="cap_bytes must be positive"):
            truncate_oversize({"x": 1}, kind="k", row_id="r", oversize_dir=tmp_path, cap_bytes=-1)

    def test_apply_row_cap_zero_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="cap_bytes must be positive"):
            apply_row_cap({"x": 1}, kind="k", row_id="r", oversize_dir=tmp_path, cap_bytes=0)

    def test_empty_details_always_within_cap(self, tmp_path: Path) -> None:
        result = truncate_oversize({}, kind="k", row_id="r", oversize_dir=tmp_path, cap_bytes=1)
        # '{}' is 2 bytes — just over cap=1.
        assert is_sentinel(result)

    def test_sidecar_dir_created_if_absent(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "deeply" / "nested" / "dir"
        truncate_oversize(
            {"data": "z" * 5_000},
            kind="k",
            row_id="nested-r",
            oversize_dir=new_dir,
            cap_bytes=100,
        )
        assert (new_dir / "nested-r.json").exists()

    def test_is_sentinel_rejects_non_dict(self) -> None:
        assert not is_sentinel(None)
        assert not is_sentinel("string")
        assert not is_sentinel([1, 2])
        assert not is_sentinel(42)

    def test_is_sentinel_rejects_dict_without_key(self) -> None:
        assert not is_sentinel({"_truncated": False})
        assert not is_sentinel({"other": True})

    def test_audit_row_oversize_in_known_sec_alert_kinds(self) -> None:
        """KNOWN_SEC_ALERT_KINDS must contain 'audit_row_oversize' (§8.15.5)."""
        from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS
        assert "audit_row_oversize" in KNOWN_SEC_ALERT_KINDS

    def test_config_parsed_property_returns_dict(self) -> None:
        """Config.maint_audit_per_kind_details_max_bytes_parsed returns a dict."""
        from common.config import Config
        cfg = Config()
        parsed = cfg.maint_audit_per_kind_details_max_bytes_parsed
        assert isinstance(parsed, dict)
        assert "default" in parsed
        assert all(isinstance(v, int) and v > 0 for v in parsed.values())

    def test_config_validate_rejects_invalid_per_kind(self) -> None:
        """validate() must catch per-kind values that exceed row_max_bytes."""
        from common.config import Config
        import json
        too_big = json.dumps({"default": 99_999_999})
        cfg = Config(
            maint_audit_row_max_bytes=16384,
            maint_audit_per_kind_details_max_bytes=too_big,
        )
        issues = cfg.validate()
        assert any("maint_audit_per_kind_details_max_bytes" in issue for issue in issues), (
            f"Expected per-kind validation issue in: {issues}"
        )

    def test_config_validate_rejects_non_json(self) -> None:
        """validate() must catch non-JSON per-kind string."""
        from common.config import Config
        cfg = Config(
            maint_audit_per_kind_details_max_bytes="not json at all",
        )
        issues = cfg.validate()
        assert any("maint_audit_per_kind_details_max_bytes" in issue for issue in issues)
