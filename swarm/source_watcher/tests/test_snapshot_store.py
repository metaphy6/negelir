"""Tests for the append-only snapshot store."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm.source_watcher import snapshot_store as ss


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "history"


def test_first_store_creates_file(root: Path) -> None:
    snap = ss.store("mackolik", {"a": 1}, root=root)
    assert snap.path.exists()
    assert snap.path.parent == root / "mackolik"


def test_store_idempotent_for_identical_payload(root: Path) -> None:
    a = ss.store("nesine", {"x": 1}, root=root)
    b = ss.store("nesine", {"x": 1}, root=root)
    assert a.path == b.path
    assert a.sha256 == b.sha256
    assert len(ss.list_snapshots("nesine", root=root)) == 1


def test_store_creates_new_file_on_change(root: Path) -> None:
    ss.store("tff", {"v": 1}, root=root, now="2026-04-20T10-00-00Z")
    ss.store("tff", {"v": 2}, root=root, now="2026-04-20T10-00-01Z")
    snaps = ss.list_snapshots("tff", root=root)
    assert len(snaps) == 2


def test_latest_returns_most_recent(root: Path) -> None:
    ss.store("x", {"v": 1}, root=root, now="2026-01-01T00-00-00Z")
    ss.store("x", {"v": 2}, root=root, now="2026-01-01T00-00-01Z")
    ss.store("x", {"v": 3}, root=root, now="2026-01-01T00-00-02Z")
    latest = ss.latest("x", root=root)
    assert latest is not None
    assert latest.payload == {"v": 3}


def test_previous_returns_second_to_last(root: Path) -> None:
    ss.store("x", {"v": 1}, root=root, now="2026-01-01T00-00-00Z")
    ss.store("x", {"v": 2}, root=root, now="2026-01-01T00-00-01Z")
    prev = ss.previous("x", root=root)
    assert prev is not None
    assert prev.payload == {"v": 1}


def test_latest_and_previous_none_when_empty(root: Path) -> None:
    assert ss.latest("missing", root=root) is None
    assert ss.previous("missing", root=root) is None


def test_sha256_consistent_across_round_trip(root: Path) -> None:
    snap = ss.store("y", {"a": [1, 2, 3], "b": "hello"}, root=root)
    reloaded = ss.latest("y", root=root)
    assert reloaded is not None
    assert reloaded.sha256 == snap.sha256


def test_prune_keeps_only_n_newest(root: Path) -> None:
    for i in range(5):
        ss.store("z", {"v": i}, root=root, now=f"2026-01-01T00-00-0{i}Z")
    deleted = ss.prune("z", keep=2, root=root)
    assert len(deleted) == 3
    remaining = ss.list_snapshots("z", root=root)
    assert len(remaining) == 2
    # the survivors should be the two newest
    assert ss.latest("z", root=root).payload == {"v": 4}


def test_prune_no_op_when_under_keep(root: Path) -> None:
    ss.store("a", {"v": 1}, root=root)
    assert ss.prune("a", keep=10, root=root) == []


def test_unicode_payload_round_trips(root: Path) -> None:
    payload = {"team": "Beşiktaş", "city": "İstanbul"}
    ss.store("trtest", payload, root=root)
    loaded = ss.latest("trtest", root=root)
    assert loaded is not None
    assert loaded.payload == payload
