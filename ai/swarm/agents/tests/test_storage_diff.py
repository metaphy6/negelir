"""Pre-Phase-6 audit A5: diff fidelity on the freshness bus.

Earlier `_shallow_diff` truncated to a counter once >16 fields
changed, which dropped semantic keys (e.g. `league_id`) that the
freshness reactors rely on for plane-bounded routing. We now keep
the full diff on the bus and only truncate when projecting to
low-cardinality telemetry sinks.
"""
from __future__ import annotations

from swarm.agents.storage import _shallow_diff, summarize_diff_for_telemetry


def test_shallow_diff_keeps_all_fields_even_when_large() -> None:
    before = {f"f{i}": i for i in range(50)}
    after = {f"f{i}": i + 1 for i in range(50)}
    diff = _shallow_diff(before, after)
    assert "_truncated" not in diff
    assert len(diff) == 50
    # Every key must round-trip with [before, after] tuples.
    assert diff["f0"] == [0, 1]
    assert diff["f49"] == [49, 50]


def test_shallow_diff_keeps_routing_keys() -> None:
    """The reactor at reactor.py L295/L383 inspects ev.diff for
    `league_id`; that must survive even when many other fields move."""
    before = {f"f{i}": i for i in range(30)}
    before["league_id"] = "tr_super_lig"
    after = {f"f{i}": i + 1 for i in range(30)}
    after["league_id"] = "en_premier"
    diff = _shallow_diff(before, after)
    assert "league_id" in diff
    assert diff["league_id"] == ["tr_super_lig", "en_premier"]


def test_summarize_diff_for_telemetry_truncates_above_threshold() -> None:
    big = {f"f{i}": [i, i + 1] for i in range(20)}
    summary = summarize_diff_for_telemetry(big, max_fields=16)
    assert summary == {"_truncated": True, "n_changed": 20}


def test_summarize_diff_for_telemetry_passes_small_diffs_through() -> None:
    small = {"a": [1, 2], "b": [3, 4]}
    summary = summarize_diff_for_telemetry(small, max_fields=16)
    assert summary == {"a": [1, 2], "b": [3, 4]}
