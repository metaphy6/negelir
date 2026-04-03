"""
Negelir P2P — Unit tests (pytest)
Covers: message protocol, reputation tracker, node basics.
"""
import sys
import os
import json
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── P2P Message Protocol ──────────────────────────────────────────────────────

from protocol.messages import P2PMessage, MessageType


class TestP2PMessage:
    def test_message_creates_content_hash(self):
        msg = P2PMessage(
            message_type=MessageType.PING.value,
            sender_id="node_001",
            payload={"test": True},
        )
        assert len(msg.content_hash) == 64  # SHA-256 hex

    def test_same_payload_same_hash(self):
        ts = time.time()
        msg_a = P2PMessage(message_type=MessageType.PING.value, sender_id="node_a",
                           payload={"x": 1}, timestamp=ts)
        msg_b = P2PMessage(message_type=MessageType.PING.value, sender_id="node_a",
                           payload={"x": 1}, timestamp=ts)
        assert msg_a.content_hash == msg_b.content_hash

    def test_different_payload_different_hash(self):
        ts = time.time()
        msg_a = P2PMessage(message_type=MessageType.PING.value, sender_id="node_a",
                           payload={"x": 1}, timestamp=ts)
        msg_b = P2PMessage(message_type=MessageType.PING.value, sender_id="node_a",
                           payload={"x": 2}, timestamp=ts)
        assert msg_a.content_hash != msg_b.content_hash

    def test_serialise_to_bytes(self):
        msg = P2PMessage(
            message_type=MessageType.ANALYSIS.value,
            sender_id="node_001",
            payload={"match": "GS vs FB", "prediction": "H"},
        )
        data = msg.to_bytes()
        assert isinstance(data, bytes)
        parsed = json.loads(data.decode("utf-8"))
        assert parsed["sender_id"] == "node_001"
        assert parsed["message_type"] == "analysis"

    def test_round_trip_serialisation(self):
        msg = P2PMessage(
            schema_version="2.0",
            message_type=MessageType.OUTCOME_VALIDATION.value,
            sender_id="node_042",
            payload={"result": "H", "correct": True},
            ttl_hours=48,
        )
        data = msg.to_bytes()
        restored = P2PMessage.from_bytes(data)
        assert restored.sender_id == msg.sender_id
        assert restored.message_type == msg.message_type
        assert restored.payload == msg.payload
        assert restored.ttl_hours == msg.ttl_hours

    def test_message_type_enum_values(self):
        assert MessageType.ANALYSIS.value == "analysis"
        assert MessageType.PING.value == "ping"
        assert MessageType.PONG.value == "pong"
        assert MessageType.SCRAPE_DATA.value == "scrape_data"
        assert MessageType.PEER_DISCOVERY.value == "peer_discovery"
        assert MessageType.OUTCOME_VALIDATION.value == "outcome_validation"

    def test_schema_version_preserved(self):
        msg = P2PMessage(schema_version="2.0", message_type="ping",
                         sender_id="node_x", payload={})
        restored = P2PMessage.from_bytes(msg.to_bytes())
        assert restored.schema_version == "2.0"

    def test_default_ttl_is_seven_days(self):
        msg = P2PMessage()
        assert msg.ttl_hours == 168


# ── PeerNode ──────────────────────────────────────────────────────────────────

from node.peer import PeerNode, PeerAnalysis


class TestPeerNode:
    def test_node_initialises_with_id(self):
        node = PeerNode(node_id="test_node_1", port=9001)
        assert node.node_id == "test_node_1"

    def test_node_starts_with_empty_reputation_table(self):
        node = PeerNode(node_id="test_node_2", port=9002)
        assert isinstance(node.reputation_table, dict)
        assert len(node.reputation_table) == 0

    def test_node_starts_with_empty_analyses(self):
        node = PeerNode(node_id="test_node_3", port=9003)
        assert isinstance(node.analyses, dict)
        assert len(node.analyses) == 0

    def test_produce_analysis_stores_result(self):
        node = PeerNode(node_id="test_node_4", port=9004)
        analysis = node.produce_analysis("match_001", base_home_prob=0.55)
        assert "match_001" in node.analyses
        assert analysis.match_id == "match_001"
        assert analysis.node_id == "test_node_4"

    def test_analysis_probabilities_sum_to_one(self):
        node = PeerNode(node_id="test_node_5", port=9005)
        analysis = node.produce_analysis("match_002", base_home_prob=0.50)
        total = analysis.home_win_prob + analysis.draw_prob + analysis.away_win_prob
        assert abs(total - 1.0) < 0.01

    def test_analysis_probabilities_in_range(self):
        node = PeerNode(node_id="test_node_6", port=9006)
        analysis = node.produce_analysis("match_003", base_home_prob=0.60)
        assert 0.0 <= analysis.home_win_prob <= 1.0
        assert 0.0 <= analysis.draw_prob <= 1.0
        assert 0.0 <= analysis.away_win_prob <= 1.0

    def test_analysis_confidence_in_range(self):
        node = PeerNode(node_id="test_node_7", port=9007)
        analysis = node.produce_analysis("match_004", base_home_prob=0.70)
        assert 0.0 <= analysis.confidence <= 1.0

    def test_analysis_has_content_hash(self):
        node = PeerNode(node_id="test_node_8", port=9008)
        analysis = node.produce_analysis("match_005")
        assert len(analysis.content_hash) == 16

    def test_receive_peer_analysis_stores_it(self):
        node_a = PeerNode(node_id="node_a", port=9010)
        node_b = PeerNode(node_id="node_b", port=9011)
        analysis = node_a.produce_analysis("match_006", base_home_prob=0.55)
        node_b.receive_peer_analysis(analysis)
        assert "match_006" in node_b.peer_analyses
        assert len(node_b.peer_analyses["match_006"]) == 1

    def test_node_ignores_own_analysis(self):
        node = PeerNode(node_id="solo_node", port=9012)
        analysis = node.produce_analysis("match_007")
        # should not add own analysis to peer_analyses
        node.receive_peer_analysis(analysis)
        assert "match_007" not in node.peer_analyses

    def test_validate_outcome_updates_peer_reputation(self):
        node_a = PeerNode(node_id="node_aa", port=9020)
        node_b = PeerNode(node_id="node_bb", port=9021)
        # node_a produces, node_b receives and validates
        analysis = node_a.produce_analysis("match_010", base_home_prob=0.80)
        node_b.receive_peer_analysis(analysis)
        node_b.validate_outcome("match_010", actual_result="H")
        assert "node_aa" in node_b.reputation_table

    def test_ensemble_with_no_peers_returns_local(self):
        node = PeerNode(node_id="lone_node", port=9030)
        node.produce_analysis("match_020", base_home_prob=0.60)
        ensemble = node.compute_ensemble("match_020")
        assert ensemble is not None
        assert ensemble.match_id == "match_020"

    def test_ensemble_with_no_own_analysis_returns_none(self):
        node = PeerNode(node_id="blank_node", port=9031)
        result = node.compute_ensemble("nonexistent_match")
        assert result is None


# ── Reputation Tracker ────────────────────────────────────────────────────────

from reputation.tracker import compute_network_summary


class TestReputationTracker:
    def _make_nodes_with_history(self, count=5):
        """Create nodes that have validated peer predictions so reputation table is populated."""
        nodes = []
        for i in range(count):
            n = PeerNode(node_id=f"node_{i:03d}", port=9100 + i)
            nodes.append(n)

        # Cross-validate: each node sends analyses to every other node
        results = ["H", "D", "A", "H", "H", "D", "A", "H", "A", "H"]
        for j, match_id in enumerate(f"match_{k:03d}" for k in range(10)):
            # each node produces an analysis
            for n in nodes:
                n.produce_analysis(match_id, base_home_prob=0.55)
            # distribute to peers
            for n in nodes:
                for other in nodes:
                    if other.node_id != n.node_id:
                        analysis = other.analyses.get(match_id)
                        if analysis:
                            n.receive_peer_analysis(analysis)
            # validate
            for n in nodes:
                n.validate_outcome(match_id, actual_result=results[j % len(results)])

        return nodes

    def test_summary_node_count(self):
        nodes = self._make_nodes_with_history(5)
        summary = compute_network_summary(nodes)
        assert summary.total_nodes == 5

    def test_summary_avg_accuracy_in_range(self):
        nodes = self._make_nodes_with_history(4)
        summary = compute_network_summary(nodes)
        assert 0.0 <= summary.avg_accuracy <= 1.0

    def test_empty_network_summary(self):
        summary = compute_network_summary([])
        assert summary.total_nodes == 0
        assert summary.avg_accuracy == 0.0
