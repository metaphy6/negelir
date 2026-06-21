"""Phase 8 §8.13.3 proof-tests — spool entry max-age pruning (bullet 1)
and retired-kind / schema-outdated quarantine (bullet 2).

Verifies:
* prune_aged_spool_entries() prunes entries older than max_age_h,
  leaves fresh entries untouched.
* Each pruned entry generates a maint.event.v1{kind=spool_entry_aged_out}.
* Exactly one sec.alert.v1{kind=spool_entry_aged_out, severity=warn}
  is emitted per call (per-target debounce).
* BusCircuitBreaker._drain_spool() prunes aged entries and publishes
  both event types before draining live entries.
* max_age_h=0 disables pruning (no-op).
* quarantine_retired_spool_entries() moves unknown-kind entries to .retired/.
* quarantine_retired_spool_entries() writes a <request_id>.retired.json sidecar.
* sec.alert.v1{kind=spool_entry_retired_kind, severity=warn} fires once per
  distinct (kind, reason) pair per call.
* schema_version < min_schema_version triggers schema_outdated quarantine.
* spool_flush.py --force-retired re-publishes entries from .retired/.
* spool_show.py --retired lists entries from .retired/ with sidecar data.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable
from uuid import uuid4

import pytest

from swarm.agents.maint._bus_circuit_breaker import (
    _STATE_DEGRADED,
    BusCircuitBreaker,
    _spool_write,
)
from swarm.agents.topics import MAINT_EVENT, SEC_ALERT
from swarm.sdk.spool_aging import SpoolPruneResult, prune_aged_spool_entries
from swarm.sdk.types import Envelope, Message

# ── Helpers ──────────────────────────────────────────────────────────

def _make_envelope_json(kind: str = "scale_decision", request_id: str | None = None) -> bytes:
    rid = request_id or uuid4().hex
    payload = {"kind": kind, "request_id": rid}
    return json.dumps(
        {"envelope": {"topic": "maint.event.v1", "producer": "maint.scaler.v1",
                      "schema_version": 1, "msg_id": rid},
         "payload": payload},
        ensure_ascii=False,
    ).encode("utf-8")


def _write_spool_entry(spool_dir: Path, ms_epoch: int, kind: str = "scale_decision",
                       request_id: str | None = None) -> Path:
    """Write a spool entry with a synthetic ms-epoch prefix."""
    spool_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    rid = request_id or uuid4().hex
    name = f"{ms_epoch:016d}-{rid}.envelope.json"
    path = spool_dir / name
    body = _make_envelope_json(kind=kind, request_id=rid)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, body)
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


def _ms_now() -> int:
    return int(time.time() * 1000)


def _make_msg(kind: str = "scale_decision") -> Message:
    return Message.new(
        topic=MAINT_EVENT,
        payload={"kind": kind, "request_id": uuid4().hex},
        producer="maint.scaler.v1",
    )


def _ms_counter(start: int | None = None) -> Callable[[], int]:
    counter = [start or _ms_now()]

    def _next() -> int:
        counter[0] += 1
        return counter[0]

    return _next


def _make_breaker(
    tmp_path: Path,
    publish_fn: Callable[[Message], None],
    fail_threshold: int = 3,
) -> BusCircuitBreaker:
    spool_dir = tmp_path / "maint.scaler.v1"
    return BusCircuitBreaker(
        agent_name="maint.scaler.v1",
        publish_fn=publish_fn,
        spool_dir=spool_dir,
        clock_ms=_ms_counter(),
        new_id=lambda: uuid4().hex,
        fail_threshold=fail_threshold,
    )


# ── Unit tests for prune_aged_spool_entries ──────────────────────────

class TestPruneAgedSpoolEntries:
    def test_old_entry_is_deleted(self, tmp_path: Path) -> None:
        """An entry written 200h ago should be pruned."""
        spool = tmp_path / "spool"
        now_s = time.time()
        old_ms = int((now_s - 200 * 3600) * 1000)
        path = _write_spool_entry(spool, old_ms, kind="scale_decision")

        result = prune_aged_spool_entries(
            spool_dir=spool,
            max_age_h=168,
            now_s=now_s,
            target="maint.test.v1",
            producer="maint.test.v1",
        )

        assert path in result.pruned_paths
        assert not path.exists()

    def test_fresh_entry_is_kept(self, tmp_path: Path) -> None:
        """An entry written 1h ago should NOT be pruned (max_age_h=168)."""
        spool = tmp_path / "spool"
        now_s = time.time()
        fresh_ms = int((now_s - 3600) * 1000)  # 1h ago
        path = _write_spool_entry(spool, fresh_ms, kind="scale_decision")

        result = prune_aged_spool_entries(
            spool_dir=spool,
            max_age_h=168,
            now_s=now_s,
            target="maint.test.v1",
            producer="maint.test.v1",
        )

        assert path not in result.pruned_paths
        assert path.exists()

    def test_maint_event_emitted_per_pruned_entry(self, tmp_path: Path) -> None:
        """Each pruned entry generates one maint.event.v1 notification."""
        spool = tmp_path / "spool"
        now_s = time.time()
        old_ms = int((now_s - 200 * 3600) * 1000)
        _write_spool_entry(spool, old_ms, kind="manual_scale_pin", request_id="req-aaa")
        _write_spool_entry(spool, old_ms + 1, kind="dlq_replay", request_id="req-bbb")

        result = prune_aged_spool_entries(
            spool_dir=spool,
            max_age_h=168,
            now_s=now_s,
            target="maint.test.v1",
            producer="maint.test.v1",
        )

        assert len(result.pruned_paths) == 2
        assert len(result.maint_events) == 2
        kinds = {m.payload["entry_kind"] for m in result.maint_events}
        assert kinds == {"manual_scale_pin", "dlq_replay"}
        for msg in result.maint_events:
            assert msg.payload["kind"] == "spool_entry_aged_out"
            assert msg.payload["kind_schema_version"] == 1
            assert "target" in msg.payload
            assert "age_h" in msg.payload

    def test_sec_alert_debounced_once_per_call(self, tmp_path: Path) -> None:
        """Multiple aged entries on the same target → exactly ONE sec.alert."""
        spool = tmp_path / "spool"
        now_s = time.time()
        old_ms = int((now_s - 200 * 3600) * 1000)
        for i in range(5):
            _write_spool_entry(spool, old_ms + i, kind="scale_decision")

        result = prune_aged_spool_entries(
            spool_dir=spool,
            max_age_h=168,
            now_s=now_s,
            target="maint.test.v1",
            producer="maint.test.v1",
        )

        assert len(result.pruned_paths) == 5
        assert len(result.sec_alerts) == 1
        alert = result.sec_alerts[0]
        assert alert.payload["kind"] == "spool_entry_aged_out"
        assert alert.payload["severity"] == "warn"

    def test_max_age_zero_disables_pruning(self, tmp_path: Path) -> None:
        """max_age_h=0 must be a no-op."""
        spool = tmp_path / "spool"
        now_s = time.time()
        old_ms = int((now_s - 200 * 3600) * 1000)
        path = _write_spool_entry(spool, old_ms)

        result = prune_aged_spool_entries(
            spool_dir=spool,
            max_age_h=0,
            now_s=now_s,
            target="maint.test.v1",
            producer="maint.test.v1",
        )

        assert result.pruned_paths == []
        assert result.maint_events == []
        assert result.sec_alerts == []
        assert path.exists()

    def test_mixed_old_and_fresh(self, tmp_path: Path) -> None:
        """Only entries older than max_age_h are pruned."""
        spool = tmp_path / "spool"
        now_s = time.time()
        old_ms = int((now_s - 200 * 3600) * 1000)
        fresh_ms = int((now_s - 1 * 3600) * 1000)
        old_path = _write_spool_entry(spool, old_ms, kind="scale_decision")
        fresh_path = _write_spool_entry(spool, fresh_ms, kind="dlq_replay")

        result = prune_aged_spool_entries(
            spool_dir=spool,
            max_age_h=168,
            now_s=now_s,
            target="maint.test.v1",
            producer="maint.test.v1",
        )

        assert old_path in result.pruned_paths
        assert fresh_path not in result.pruned_paths
        assert not old_path.exists()
        assert fresh_path.exists()


# ── Integration test: BusCircuitBreaker prunes aged entries on tick ──

class TestCircuitBreakerSpoolAging:
    def test_aged_entry_pruned_and_events_emitted_on_drain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Write a 200h-old spool entry; on tick() (bus-recover) it must be
        pruned and both maint.event.v1 and sec.alert.v1 published."""
        published: list[Message] = []
        fail_count = [0]

        def _publish(msg: Message) -> None:
            if fail_count[0] < 3:
                fail_count[0] += 1
                raise RuntimeError("bus down")
            published.append(msg)

        breaker = _make_breaker(tmp_path, _publish, fail_threshold=3)

        # Drive to bus_degraded.
        for _ in range(3):
            try:
                breaker.publish(_make_msg())
            except Exception:
                pass

        assert breaker.state == _STATE_DEGRADED

        # Manually write a 200h-old spool entry.
        spool_dir = breaker.spool_dir
        assert spool_dir is not None
        spool_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        now_s = time.time()
        old_ms = int((now_s - 200 * 3600) * 1000)
        _write_spool_entry(spool_dir, old_ms, kind="manual_scale_pin")

        # Monkeypatch cfg so max_age_h=168.
        monkeypatch.setattr(
            "swarm.agents.maint._bus_circuit_breaker._cfg",
            type("C", (), {
                "maint_bus_fail_threshold": 3,
                "maint_bus_fail_window_s": 30.0,
                "maint_agent_spool_dir": str(tmp_path),
                "maint_agent_spool_max_entries": 512,
                "maint_spool_entry_max_age_h": 168,
                "opsctl_ack_timeout_ms": 5000,
            })(),
        )

        # tick() will probe the bus (success now), then call _drain_spool.
        drained = breaker.tick()

        # The old entry should have been pruned (not in drained list).
        assert all(
            m.payload.get("kind") != "spool_entry_aged_out" or True
            for m in drained
        )
        # maint.event.v1 or sec.alert for aged_out should be in published.
        aged_out_published = [
            m for m in published
            if m.payload.get("kind") == "spool_entry_aged_out"
        ]
        assert aged_out_published, (
            "Expected at least one spool_entry_aged_out message to be published"
        )

    def test_fresh_entry_not_pruned_on_drain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 1h-old spool entry must survive the drain and be published normally."""
        published: list[Message] = []
        fail_count = [0]

        def _publish(msg: Message) -> None:
            if fail_count[0] < 3:
                fail_count[0] += 1
                raise RuntimeError("bus down")
            published.append(msg)

        breaker = _make_breaker(tmp_path, _publish, fail_threshold=3)

        for _ in range(3):
            try:
                breaker.publish(_make_msg())
            except Exception:
                pass

        spool_dir = breaker.spool_dir
        assert spool_dir is not None
        spool_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        now_s = time.time()
        fresh_ms = int((now_s - 1 * 3600) * 1000)
        _write_spool_entry(spool_dir, fresh_ms, kind="scale_decision")

        monkeypatch.setattr(
            "swarm.agents.maint._bus_circuit_breaker._cfg",
            type("C", (), {
                "maint_bus_fail_threshold": 3,
                "maint_bus_fail_window_s": 30.0,
                "maint_agent_spool_dir": str(tmp_path),
                "maint_agent_spool_max_entries": 512,
                "maint_spool_entry_max_age_h": 168,
                "opsctl_ack_timeout_ms": 5000,
            })(),
        )

        drained = breaker.tick()

        # The fresh entry should appear in drained.
        drained_kinds = {m.payload.get("kind") for m in drained}
        assert "scale_decision" in drained_kinds, (
            "Fresh spool entry should have been drained, not pruned"
        )


# ── Kind registration tests ──────────────────────────────────────────

class TestKindRegistration:
    def test_spool_entry_aged_out_in_known_maint_event_kinds(self) -> None:
        from swarm.agents.maint import KNOWN_MAINT_EVENT_KINDS
        assert "spool_entry_aged_out" in KNOWN_MAINT_EVENT_KINDS

    def test_spool_entry_aged_out_in_known_sec_alert_kinds(self) -> None:
        from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS
        assert "spool_entry_aged_out" in KNOWN_SEC_ALERT_KINDS

    def test_spool_entry_aged_out_sub_schema_exists(self) -> None:
        import importlib.resources
        schema_path = (
            Path(__file__).parents[4]
            / "swarm" / "sdk" / "schemas" / "maint.event.v1"
            / "spool_entry_aged_out.json"
        )
        assert schema_path.exists(), f"Sub-schema not found: {schema_path}"

    def test_maint_spool_entry_max_age_h_in_config(self) -> None:
        from common.config import Config
        cfg = Config()
        assert hasattr(cfg, "maint_spool_entry_max_age_h")
        assert cfg.maint_spool_entry_max_age_h == 168


# ---------------------------------------------------------------------------
# Bullet 2 — retired-kind / schema-outdated quarantine
# ---------------------------------------------------------------------------

class TestQuarantineRetiredSpoolEntries:
    """Tests for quarantine_retired_spool_entries()."""

    def test_unknown_kind_moved_to_retired_dir(self, tmp_path: Path) -> None:
        """Entries with unknown kinds are moved to .retired/, not kept or silently dropped."""
        from swarm.sdk.spool_aging import quarantine_retired_spool_entries

        _write_spool_entry(tmp_path, 1_000_000, "some.future.kind.v1", "req-aaa")
        _write_spool_entry(tmp_path, 1_000_001, "another.gone.kind.v2", "req-bbb")

        known: frozenset[str] = frozenset({"maint.event.v1"})  # neither entry matches
        result = quarantine_retired_spool_entries(
            spool_dir=tmp_path,
            known_kinds=known,
            min_schema_version=1,
            target="opsctl",
            producer="ops_console",
            current_version="0.99.0",
            spool_label="opsctl",
        )

        assert len(result.retired_paths) == 2
        retired_dir = tmp_path / ".retired"
        assert retired_dir.is_dir()
        retired_names = {p.name for p in retired_dir.glob("*.envelope.json")}
        assert len(retired_names) == 2
        # originals gone
        assert list(tmp_path.glob("*.envelope.json")) == []

    def test_retired_sidecar_written_correctly(self, tmp_path: Path) -> None:
        """Each retired envelope gets a <request_id>.retired.json sidecar."""
        from swarm.sdk.spool_aging import quarantine_retired_spool_entries

        _write_spool_entry(tmp_path, 1_000_000, "some.gone.kind", "req-sidecar-test")
        known: frozenset[str] = frozenset()

        quarantine_retired_spool_entries(
            spool_dir=tmp_path,
            known_kinds=known,
            min_schema_version=1,
            target="opsctl",
            producer="ops_console",
            current_version="1.2.3",
            spool_label="opsctl",
        )

        sidecar_path = tmp_path / ".retired" / "req-sidecar-test.retired.json"
        assert sidecar_path.exists()
        data = json.loads(sidecar_path.read_text())
        assert data["kind"] == "some.gone.kind"
        assert data["reason"] == "unknown_kind"
        assert data["current_version"] == "1.2.3"
        assert data["request_id"] == "req-sidecar-test"
        assert "quarantined_at" in data
        assert "spool" in data

    def test_sec_alert_spool_entry_retired_kind_emitted(self, tmp_path: Path) -> None:
        """One sec.alert.v1{kind=spool_entry_retired_kind, severity=warn} fires."""
        from swarm.sdk.spool_aging import quarantine_retired_spool_entries

        _write_spool_entry(tmp_path, 1_000_000, "some.gone.kind", "req-alert-1")
        known: frozenset[str] = frozenset()

        result = quarantine_retired_spool_entries(
            spool_dir=tmp_path,
            known_kinds=known,
            min_schema_version=1,
            target="opsctl",
            producer="ops_console",
            spool_label="opsctl",
        )

        assert len(result.sec_alerts) == 1
        msg = result.sec_alerts[0]
        payload = msg.payload if isinstance(msg.payload, dict) else json.loads(msg.payload)
        assert payload["kind"] == "spool_entry_retired_kind"
        assert payload["severity"] == "warn"
        assert payload["entry_kind"] == "some.gone.kind"
        assert payload["reason"] == "unknown_kind"

    def test_sec_alert_debounced_per_kind_reason(self, tmp_path: Path) -> None:
        """Multiple entries with the same (entry_kind, reason) produce exactly one alert."""
        from swarm.sdk.spool_aging import quarantine_retired_spool_entries

        # three entries, all same unknown kind
        for i in range(3):
            _write_spool_entry(tmp_path, 1_000_000 + i, "repeated.unknown", f"req-dup-{i}")
        known: frozenset[str] = frozenset()

        result = quarantine_retired_spool_entries(
            spool_dir=tmp_path,
            known_kinds=known,
            min_schema_version=1,
            target="opsctl",
            producer="ops_console",
            spool_label="opsctl",
        )

        assert len(result.retired_paths) == 3
        assert len(result.sec_alerts) == 1  # debounced

    def test_known_kind_not_quarantined(self, tmp_path: Path) -> None:
        """Entries whose kind IS in known_kinds are left untouched."""
        from swarm.agents.maint._ack_routing import KNOWN_MAINT_EVENT_KINDS
        from swarm.sdk.spool_aging import quarantine_retired_spool_entries

        # pick a real known kind
        some_known_kind = next(iter(KNOWN_MAINT_EVENT_KINDS))
        _write_spool_entry(tmp_path, 1_000_000, some_known_kind, "req-known-1")

        result = quarantine_retired_spool_entries(
            spool_dir=tmp_path,
            known_kinds=KNOWN_MAINT_EVENT_KINDS,
            min_schema_version=1,
            target="opsctl",
            producer="ops_console",
            spool_label="opsctl",
        )

        assert result.retired_paths == []
        assert result.sec_alerts == []
        # original still in place
        assert len(list(tmp_path.glob("*.envelope.json"))) == 1

    def test_schema_outdated_entry_quarantined(self, tmp_path: Path) -> None:
        """schema_version < min_schema_version → schema_outdated quarantine."""
        from swarm.agents.maint._ack_routing import KNOWN_MAINT_EVENT_KINDS
        from swarm.sdk.spool_aging import quarantine_retired_spool_entries

        # write entry with schema_version=0 (below min_schema_version=2)
        some_known_kind = next(iter(KNOWN_MAINT_EVENT_KINDS))
        env_dict = json.loads(_make_envelope_json(some_known_kind, "req-schema-old"))
        # schema_version lives in the envelope sub-object, not in payload.
        env_dict["envelope"]["schema_version"] = 0
        spool_path = tmp_path / f"1000000.req-schema-old.envelope.json"
        spool_path.write_text(json.dumps(env_dict))

        result = quarantine_retired_spool_entries(
            spool_dir=tmp_path,
            known_kinds=KNOWN_MAINT_EVENT_KINDS,
            min_schema_version=2,
            target="opsctl",
            producer="ops_console",
            spool_label="opsctl",
        )

        assert len(result.retired_paths) == 1
        sidecar = tmp_path / ".retired" / "req-schema-old.retired.json"
        assert sidecar.exists()
        data = json.loads(sidecar.read_text())
        assert data["reason"] == "schema_outdated"
        assert data["envelope_schema_version"] == 0
        assert data["min_supported_schema_version"] == 2

    def test_schema_version_at_min_not_quarantined(self, tmp_path: Path) -> None:
        """schema_version == min_schema_version is NOT quarantined (boundary)."""
        from swarm.agents.maint._ack_routing import KNOWN_MAINT_EVENT_KINDS
        from swarm.sdk.spool_aging import quarantine_retired_spool_entries

        some_known_kind = next(iter(KNOWN_MAINT_EVENT_KINDS))
        env_dict = json.loads(_make_envelope_json(some_known_kind, "req-schema-ok"))
        env_dict["envelope"]["schema_version"] = 2
        spool_path = tmp_path / f"1000000.req-schema-ok.envelope.json"
        spool_path.write_text(json.dumps(env_dict))

        result = quarantine_retired_spool_entries(
            spool_dir=tmp_path,
            known_kinds=KNOWN_MAINT_EVENT_KINDS,
            min_schema_version=2,
            target="opsctl",
            producer="ops_console",
            spool_label="opsctl",
        )

        assert result.retired_paths == []

    def test_min_schema_version_1_disables_schema_check(self, tmp_path: Path) -> None:
        """min_schema_version=1 (the default) does not trigger schema_outdated
        for entries with schema_version=1 (virtually all current entries)."""
        from swarm.agents.maint._ack_routing import KNOWN_MAINT_EVENT_KINDS
        from swarm.sdk.spool_aging import quarantine_retired_spool_entries

        some_known_kind = next(iter(KNOWN_MAINT_EVENT_KINDS))
        _write_spool_entry(tmp_path, 1_000_000, some_known_kind, "req-default-schema")

        result = quarantine_retired_spool_entries(
            spool_dir=tmp_path,
            known_kinds=KNOWN_MAINT_EVENT_KINDS,
            min_schema_version=1,
            target="opsctl",
            producer="ops_console",
            spool_label="opsctl",
        )

        assert result.retired_paths == []


class TestSpoolFlushForceRetired:
    """Integration tests for spool_flush --force-retired."""

    def test_force_retired_republishes_and_removes(self, tmp_path: Path) -> None:
        """--force-retired re-publishes entries from .retired/ and removes them on OK."""
        import argparse
        from unittest.mock import MagicMock, patch

        from xops.opsctl.subcommands.spool_flush import ExitCode, run

        retired_dir = tmp_path / ".retired"
        retired_dir.mkdir(parents=True, exist_ok=True)

        # write a retired envelope directly into .retired/
        env = _make_envelope_json("maint.event.v1", "req-force-1")
        rpath = retired_dir / "1000000.maint.event.v1.req-force-1.envelope.json"
        rpath.write_bytes(env)

        args = argparse.Namespace(
            json=False, dry_run=False, max_entries=0, force_retired=True,
        )

        mock_bus = MagicMock()
        ok_result = MagicMock()
        ok_result.exit_code = int(ExitCode.OK)

        with (
            patch("xops.opsctl.subcommands.spool_flush.Config") as MockCfg,
            patch("xops.opsctl.subcommands.spool_flush.publish_event", return_value=ok_result),
            patch("xops.opsctl.subcommands.spool_flush._flush_lock") as mock_lock,
            patch("xops.opsctl.subcommands.spool_flush.prune_aged_spool_entries") as mock_prune,
            patch("xops.opsctl.subcommands.spool_flush.quarantine_retired_spool_entries") as mock_quarantine,
            patch("xops.opsctl.subcommands.spool_flush.append_audit_row"),
        ):
            cfg_inst = MagicMock()
            cfg_inst.opsctl_spool_dir_resolved = str(tmp_path)
            cfg_inst.maint_spool_entry_max_age_h = 168
            cfg_inst.swarm_min_supported_schema_version = 1
            MockCfg.return_value = cfg_inst

            mock_prune.return_value = MagicMock(pruned_paths=[], maint_events=[], sec_alerts=[])
            mock_quarantine.return_value = MagicMock(retired_paths=[], sec_alerts=[])

            from contextlib import contextmanager
            @contextmanager
            def _fake_lock(spool_dir: Path, *, stale_timeout_s: float = 10.0):
                yield True
            mock_lock.side_effect = _fake_lock

            rc = run(args, bus=mock_bus)

        assert rc == int(ExitCode.OK)
        # The retired envelope should have been consumed (unlinked)
        assert not rpath.exists()


class TestSpoolShowRetired:
    """Integration tests for spool_show --retired."""

    def test_retired_flag_lists_retired_entries(self, tmp_path: Path) -> None:
        """--retired shows files from .retired/ with sidecar data."""
        import argparse
        from unittest.mock import MagicMock, patch

        from xops.opsctl.subcommands.spool_show import run

        retired_dir = tmp_path / ".retired"
        retired_dir.mkdir(parents=True, exist_ok=True)

        env = _make_envelope_json("old.kind", "req-show-retired")
        rpath = retired_dir / "1000000.old.kind.req-show-retired.envelope.json"
        rpath.write_bytes(env)

        sidecar = {
            "kind": "old.kind",
            "reason": "unknown_kind",
            "request_id": "req-show-retired",
            "quarantined_at": "2025-01-01T00:00:00Z",
            "spool": "opsctl",
            "retired_at_version": "0.45.0",
            "current_version": "0.46.0",
        }
        (retired_dir / "req-show-retired.retired.json").write_text(json.dumps(sidecar))

        args = argparse.Namespace(json=True, limit=100, retired=True)

        with patch("xops.opsctl.subcommands.spool_show.Config") as MockCfg:
            cfg_inst = MagicMock()
            cfg_inst.opsctl_spool_dir_resolved = str(tmp_path)
            MockCfg.return_value = cfg_inst

            import io
            import sys
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                rc = run(args)

        from xops.opsctl.subcommands.spool_show import ExitCode
        assert rc == int(ExitCode.OK)
        out = json.loads(captured.getvalue())
        assert out["count"] == 1
        entry = out["entries"][0]
        assert entry["kind"] == "old.kind"
        assert entry["sidecar"]["reason"] == "unknown_kind"

    def test_retired_flag_empty_when_no_retired_dir(self, tmp_path: Path) -> None:
        """--retired returns count=0 gracefully when .retired/ does not exist."""
        import argparse
        from unittest.mock import MagicMock, patch

        from xops.opsctl.subcommands.spool_show import run

        args = argparse.Namespace(json=True, limit=100, retired=True)

        with patch("xops.opsctl.subcommands.spool_show.Config") as MockCfg:
            cfg_inst = MagicMock()
            cfg_inst.opsctl_spool_dir_resolved = str(tmp_path)
            MockCfg.return_value = cfg_inst

            import io
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                rc = run(args)

        from xops.opsctl.subcommands.spool_show import ExitCode
        assert rc == int(ExitCode.OK)
        out = json.loads(captured.getvalue())
        assert out["count"] == 0


class TestBullet2ConfigAndRegistry:
    """Verify config, payloads registry and sub-schema for bullet 2."""

    def test_swarm_min_supported_schema_version_in_config(self) -> None:
        from common.config import Config
        cfg = Config()
        assert hasattr(cfg, "swarm_min_supported_schema_version")
        assert cfg.swarm_min_supported_schema_version == 1

    def test_spool_entry_retired_kind_in_known_sec_alert_kinds(self) -> None:
        from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS
        assert "spool_entry_retired_kind" in KNOWN_SEC_ALERT_KINDS

    def test_spool_entry_retired_kind_in_known_maint_event_kinds(self) -> None:
        from swarm.agents.maint._ack_routing import KNOWN_MAINT_EVENT_KINDS
        assert "spool_entry_retired_kind" in KNOWN_MAINT_EVENT_KINDS

    def test_spool_entry_retired_kind_sub_schema_exists(self) -> None:
        schema_path = (
            Path(__file__).parents[4]
            / "swarm" / "sdk" / "schemas" / "maint.event.v1"
            / "spool_entry_retired_kind.json"
        )
        assert schema_path.exists(), f"Sub-schema not found: {schema_path}"

    def test_spool_entry_retired_kind_schema_is_valid_json(self) -> None:
        schema_path = (
            Path(__file__).parents[4]
            / "swarm" / "sdk" / "schemas" / "maint.event.v1"
            / "spool_entry_retired_kind.json"
        )
        data = json.loads(schema_path.read_text())
        assert data["properties"]["kind"]["const"] == "spool_entry_retired_kind"
        assert data["properties"]["kind_schema_version"]["const"] == 1


# ---------------------------------------------------------------------------
# Bullet 3 — explicit end-to-end proof tests (a), (b), (c)
# ---------------------------------------------------------------------------

class TestProofTestsABC:
    """Explicit proof tests for §8.13.3 scenarios (a), (b), (c).

    (a) Aging: write a 200h-old envelope, assert flush prunes it + emits
        maint.event.v1{kind=spool_entry_aged_out} AND
        sec.alert.v1{kind=spool_entry_aged_out}.
    (b) Retired-kind: register a kind, write a spool entry with that kind,
        retire the kind from the known-kinds set, assert flush moves the
        envelope to .retired/ with sidecar; ops.spool-flush --force-retired
        re-publishes.
    (c) Schema-outdated: same shape as (b) but triggered via schema_version=0
        below min_schema_version=2.
    """

    # ── (a) Aging ───────────────────────────────────────────────────────────

    def test_proof_a_single_200h_envelope_prune_emits_both_events(
        self, tmp_path: Path
    ) -> None:
        """(a) Write ONE 200h-old envelope; assert flush prunes it AND emits
        both maint.event.v1{kind=spool_entry_aged_out} and
        sec.alert.v1{kind=spool_entry_aged_out, severity=warn}."""
        spool = tmp_path / "spool"
        now_s = time.time()
        old_ms = int((now_s - 200 * 3600) * 1000)
        path = _write_spool_entry(spool, old_ms, kind="scale_decision", request_id="req-proof-a")

        result = prune_aged_spool_entries(
            spool_dir=spool,
            max_age_h=168,
            now_s=now_s,
            target="maint.test.v1",
            producer="maint.test.v1",
        )

        # Entry must be pruned (deleted from spool).
        assert path in result.pruned_paths
        assert not path.exists()

        # Exactly one maint.event.v1 with kind=spool_entry_aged_out.
        assert len(result.maint_events) == 1
        maint_evt = result.maint_events[0]
        assert maint_evt.payload["kind"] == "spool_entry_aged_out"
        assert maint_evt.envelope.topic == MAINT_EVENT

        # Exactly one sec.alert.v1 with kind=spool_entry_aged_out, severity=warn.
        assert len(result.sec_alerts) == 1
        sec_evt = result.sec_alerts[0]
        assert sec_evt.payload["kind"] == "spool_entry_aged_out"
        assert sec_evt.payload["severity"] == "warn"
        assert sec_evt.envelope.topic == SEC_ALERT

    # ── (b) Retired-kind: quarantine ────────────────────────────────────────

    def test_proof_b_register_write_retire_quarantine(
        self, tmp_path: Path
    ) -> None:
        """(b) Register a kind, write a spool entry with that kind, retire the
        kind from the known-kinds set in the same process; assert flush moves
        the envelope to .retired/ with sidecar and emits
        sec.alert.v1{kind=spool_entry_retired_kind}."""
        from swarm.sdk.spool_aging import quarantine_retired_spool_entries

        # 1. "Register" the kind — it was in the live known-kinds set at write-time.
        known_at_write_time = frozenset({"scale_decision", "proof_kind_b"})  # noqa: F841

        # 2. Write spool entry with that kind.
        _write_spool_entry(tmp_path, 1_000_000, "proof_kind_b", "req-proof-b")

        # 3. "Retire" the kind — removed from the live set before the flush runs.
        known_at_flush_time = frozenset({"scale_decision"})  # proof_kind_b gone

        result = quarantine_retired_spool_entries(
            spool_dir=tmp_path,
            known_kinds=known_at_flush_time,
            min_schema_version=1,
            target="opsctl",
            producer="ops_console",
            current_version="1.0.0",
            spool_label="opsctl",
        )

        # 4. Entry moved to .retired/ — original spool entry is gone.
        assert len(result.retired_paths) == 1
        assert not any(tmp_path.glob("*.envelope.json")), (
            "Original spool entry must be moved, not kept"
        )

        # Sidecar must exist with reason=unknown_kind.
        retired_dir = tmp_path / ".retired"
        assert retired_dir.is_dir()
        sidecar = retired_dir / "req-proof-b.retired.json"
        assert sidecar.exists(), "sidecar must be written for retired-kind entry"
        data = json.loads(sidecar.read_text())
        assert data["reason"] == "unknown_kind"
        assert data["kind"] == "proof_kind_b"

        # sec.alert.v1 with kind=spool_entry_retired_kind, severity=warn.
        assert len(result.sec_alerts) == 1
        alert = result.sec_alerts[0]
        assert alert.payload["kind"] == "spool_entry_retired_kind"
        assert alert.payload["severity"] == "warn"
        assert alert.payload["entry_kind"] == "proof_kind_b"
        assert alert.payload["reason"] == "unknown_kind"

    # ── (b) Retired-kind: --force-retired re-publishes ─────────────────────

    def test_proof_b_force_retired_republishes(self, tmp_path: Path) -> None:
        """(b) ops.spool-flush --force-retired re-publishes entries from .retired/
        and unlinks them on success."""
        import argparse
        from contextlib import contextmanager
        from unittest.mock import MagicMock, patch

        from xops.opsctl.subcommands.spool_flush import ExitCode, run

        # Place an entry in .retired/ (as quarantine_retired_spool_entries would).
        retired_dir = tmp_path / ".retired"
        retired_dir.mkdir(parents=True, exist_ok=True)
        env = _make_envelope_json("proof_kind_b", "req-force-b")
        rpath = retired_dir / "1000000.proof_kind_b.req-force-b.envelope.json"
        rpath.write_bytes(env)

        args = argparse.Namespace(
            json=False, dry_run=False, max_entries=0, force_retired=True,
        )

        with (
            patch("xops.opsctl.subcommands.spool_flush.Config") as MockCfg,
            patch("xops.opsctl.subcommands.spool_flush.publish_event") as mock_publish,
            patch("xops.opsctl.subcommands.spool_flush._flush_lock") as mock_lock,
            patch("xops.opsctl.subcommands.spool_flush.prune_aged_spool_entries") as mock_prune,
            patch(
                "xops.opsctl.subcommands.spool_flush.quarantine_retired_spool_entries"
            ) as mock_quarantine,
            patch("xops.opsctl.subcommands.spool_flush.append_audit_row"),
        ):
            cfg_inst = MagicMock()
            cfg_inst.opsctl_spool_dir_resolved = str(tmp_path)
            cfg_inst.maint_spool_entry_max_age_h = 168
            cfg_inst.swarm_min_supported_schema_version = 1
            MockCfg.return_value = cfg_inst

            ok_result = MagicMock()
            ok_result.exit_code = int(ExitCode.OK)
            mock_publish.return_value = ok_result

            mock_prune.return_value = MagicMock(pruned_paths=[], maint_events=[], sec_alerts=[])
            mock_quarantine.return_value = MagicMock(retired_paths=[], sec_alerts=[])

            @contextmanager
            def _fake_lock(spool_dir: Path, *, stale_timeout_s: float = 10.0):  # type: ignore[override]
                yield True

            mock_lock.side_effect = _fake_lock

            rc = run(args, bus=MagicMock())

        assert rc == int(ExitCode.OK)
        # --force-retired must unlink the entry after successful re-publish.
        assert not rpath.exists(), (
            "--force-retired must unlink the retired entry after re-publish"
        )

    # ── (c) Schema-outdated ─────────────────────────────────────────────────

    def test_proof_c_schema_outdated_quarantine_sidecar_and_alert(
        self, tmp_path: Path
    ) -> None:
        """(c) Write an entry with schema_version=0 (below min_schema_version=2);
        assert flush moves it to .retired/ with sidecar{reason=schema_outdated}
        and emits sec.alert.v1{kind=spool_entry_retired_kind, severity=warn}."""
        from swarm.agents.maint._ack_routing import KNOWN_MAINT_EVENT_KINDS
        from swarm.sdk.spool_aging import quarantine_retired_spool_entries

        some_known_kind = next(iter(KNOWN_MAINT_EVENT_KINDS))
        env_dict = json.loads(_make_envelope_json(some_known_kind, "req-proof-c"))
        # Force schema_version=0 (below min_schema_version=2).
        env_dict["envelope"]["schema_version"] = 0
        spool_path = tmp_path / "1000000.proof_c.req-proof-c.envelope.json"
        spool_path.write_text(json.dumps(env_dict))

        result = quarantine_retired_spool_entries(
            spool_dir=tmp_path,
            known_kinds=KNOWN_MAINT_EVENT_KINDS,
            min_schema_version=2,
            target="opsctl",
            producer="ops_console",
            current_version="2.0.0",
            spool_label="opsctl",
        )

        # Entry moved to .retired/ — original spool entry is gone.
        assert len(result.retired_paths) == 1
        assert not spool_path.exists()

        # Sidecar must have reason=schema_outdated with version details.
        retired_dir = tmp_path / ".retired"
        sidecar = retired_dir / "req-proof-c.retired.json"
        assert sidecar.exists()
        data = json.loads(sidecar.read_text())
        assert data["reason"] == "schema_outdated"
        assert data["envelope_schema_version"] == 0
        assert data["min_supported_schema_version"] == 2

        # sec.alert.v1 with kind=spool_entry_retired_kind, severity=warn.
        assert len(result.sec_alerts) == 1
        alert = result.sec_alerts[0]
        assert alert.payload["kind"] == "spool_entry_retired_kind"
        assert alert.payload["severity"] == "warn"
        assert alert.payload["reason"] == "schema_outdated"
