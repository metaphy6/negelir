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


# ── F7.8 / P7 — match.stored payload boundary ─────────────────────


def test_match_stored_payload_excludes_diff_fields() -> None:
    """F7.8 (P7): the ``match.stored`` topic carries an *event*
    receipt — record_id + change_kind + storage timing — and MUST
    NOT leak the field-level diff. The diff travels on the parallel
    ``freshness.events`` topic where freshness reactors expect it.

    Cross-emission of ``diff`` / ``previous_value`` / ``change_kind``
    fields beyond the documented MatchStored schema would: (a) break
    schema-contract subscribers that pin keys with ``additionalProperties=false``;
    (b) double the payload size for a topic many subscribers consume
    purely as a settlement trigger; (c) leak pre-redaction values
    to consumers without freshness-plane authorization.
    """
    from swarm.agents.payloads import NormalizedRecord
    from swarm.agents.storage import StorageAgent
    from swarm.agents.topics import MATCH_NORMALIZED, MATCH_STORED
    from swarm.sdk.types import Message

    agent = StorageAgent()
    rec_v1 = NormalizedRecord(
        record_type="match_detail",
        plane="live",
        source="mackolik",
        source_match_id="m-stored-bounds-1",
        stable_id="m-stored-bounds-1",
        extractor_version="test-1",
        payload={"home_score": 0, "away_score": 0, "league_id": "tr_super_lig"},
        captured_at="2025-01-01T00:00:00+00:00",
    )
    list(agent.handle(Message.new(MATCH_NORMALIZED, rec_v1.as_dict(), producer="test")))

    # Second upsert with diff-bearing changes.
    rec_v2 = NormalizedRecord(
        record_type="match_detail",
        plane="live",
        source="mackolik",
        source_match_id="m-stored-bounds-1",
        stable_id="m-stored-bounds-1",
        extractor_version="test-1",
        payload={"home_score": 1, "away_score": 0, "league_id": "tr_super_lig"},
        captured_at="2025-01-01T00:05:00+00:00",
    )
    out = list(agent.handle(Message.new(MATCH_NORMALIZED, rec_v2.as_dict(), producer="test")))

    stored_msgs = [m for m in out if m.envelope.topic == MATCH_STORED]
    assert stored_msgs, "expected a match.stored emission on diff-bearing upsert"
    payload = stored_msgs[0].payload
    forbidden = {"diff", "previous_value", "previous_payload", "before", "after"}
    leaks = forbidden & set(payload.keys())
    assert not leaks, (
        f"match.stored payload leaked diff-plane fields: {sorted(leaks)}. "
        "Diff data belongs on freshness.events (the authoritative diff topic); "
        "match.stored must stay a slim settlement receipt."
    )
    # Positive: the documented MatchStored fields ARE present.
    for key in ("record_id", "record_type", "plane", "source", "stable_id", "change_kind", "stored_at"):
        assert key in payload, f"match.stored payload missing required key: {key}"
